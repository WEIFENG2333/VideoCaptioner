"""End-to-end subtitle dubbing pipeline.

文件落盘分两类：

- 原始 TTS 分段是跨任务缓存：按（文本 + 全部影响发音的配置）内容寻址，
  存全局 CACHE_PATH/tts_segments，配置一变 hash 即变，不会复用到旧音频。
- 变速拟合分段与 report.json 是本次任务的中间产物：进调用方传入的
  work_dir（任务目录），随任务目录一起清理。
"""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Literal, Optional

from videocaptioner.config import CACHE_PATH
from videocaptioner.core.application import output_paths
from videocaptioner.core.speech import (
    SpeechProviderConfig,
    SynthesisRequest,
    create_speech_synthesizer,
)

from .audio import change_tempo, create_timeline_audio, get_audio_duration_ms, mux_dubbed_audio
from .models import DubbingConfig, DubbingResult, DubbingSegment, SpeakerProfile
from .rewriter import rewrite_segments_if_needed
from .subtitle_parser import load_dubbing_segments

ProgressCallback = Callable[[int, str], None]

# Edge 是免费 TTS，并发不暴露给用户、程序内部固定，避免免费接口被高并发限流。
EDGE_TTS_WORKERS = 5

TTS_SEGMENT_CACHE_DIR = CACHE_PATH / "tts_segments"


class DubbingPipeline:
    """Create a dubbed audio track, optionally muxed into a video."""

    def __init__(self, config: DubbingConfig):
        self.config = config
        speech_config = SpeechProviderConfig(
            provider=config.provider,
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.model,
            default_voice=config.voice,
            response_format=self._provider_response_format(config),
            sample_rate=config.sample_rate,
            speed=config.speed,
            gain=config.gain,
            timeout=config.timeout,
            style_prompt=config.style_prompt,
        )
        self.synthesizer = create_speech_synthesizer(speech_config)

    def run(
        self,
        subtitle_path: str,
        output_audio_path: str,
        *,
        work_dir: str,
        video_path: Optional[str] = None,
        output_video_path: Optional[str] = None,
        text_track: str = "auto",
        callback: Optional[ProgressCallback] = None,
    ) -> DubbingResult:
        cb = callback or (lambda _progress, _message: None)
        out_audio = Path(output_audio_path)
        out_audio.parent.mkdir(parents=True, exist_ok=True)
        work = Path(work_dir)
        work.mkdir(parents=True, exist_ok=True)

        cb(2, "loading subtitles")
        segments = load_dubbing_segments(subtitle_path, text_track=text_track)
        if not segments:
            raise ValueError("No subtitle lines found for dubbing")
        self._apply_speakers(segments)

        cb(8, "rewriting long lines")
        rewrite_segments_if_needed(segments, self.config)

        warnings: list[str] = []
        timeline_items: list[tuple[str, int]] = []
        total = len(segments)
        configured_workers = (
            EDGE_TTS_WORKERS if self.config.provider == "edge" else self.config.tts_workers
        )
        workers = max(1, min(configured_workers, total))
        completed = 0
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_pos = {
                executor.submit(self._process_segment, segment, work): pos
                for pos, segment in enumerate(segments)
            }
            ordered: list[DubbingSegment | None] = [None] * total
            for future in as_completed(future_to_pos):
                pos = future_to_pos[future]
                segment = future.result()
                ordered[pos] = segment
                completed += 1
                cb(10 + int(completed / total * 75), f"synthesizing {completed}/{total}")

        segments = [seg for seg in ordered if seg is not None]
        for segment in segments:
            timeline_items.append((segment.fitted_path, segment.start_ms))
            overflow_ms = segment.start_ms + segment.fitted_duration_ms - segment.end_ms
            if overflow_ms > 80:
                warning = f"segment {segment.index} exceeds target by {overflow_ms} ms"
                segment.warning = warning
                warnings.append(warning)

        duration_ms = max(
            max(seg.end_ms for seg in segments),
            max(seg.start_ms + seg.fitted_duration_ms for seg in segments),
        )
        cb(88, "assembling audio")
        create_timeline_audio(
            timeline_items,
            str(out_audio),
            duration_ms,
            volume=self.config.dubbed_audio_volume,
        )

        out_video: Optional[Path] = None
        if video_path:
            if not output_video_path:
                output_video_path = str(
                    output_paths.product_path(video_path, output_paths.TAG_DUBBED)
                )
            cb(94, "muxing video")
            mux_dubbed_audio(
                video_path,
                str(out_audio),
                output_video_path,
                mix_original_audio=self.config.mix_original_audio,
                original_audio_volume=self.config.original_audio_volume,
                dubbed_audio_volume=1.0,
            )
            out_video = Path(output_video_path)

        report_path = work / output_paths.DUBBING_REPORT_FILE
        self._write_report(report_path, segments, warnings)
        cb(100, "completed")
        return DubbingResult(
            audio_path=out_audio,
            video_path=out_video,
            segments=segments,
            duration_ms=duration_ms,
            warnings=warnings,
            report_path=report_path,
        )

    def _apply_speakers(self, segments: list[DubbingSegment]) -> None:
        default_profile = self.config.speaker_profiles.get("default")
        for segment in segments:
            profile = self.config.speaker_profiles.get(segment.speaker) or default_profile
            if profile:
                self._apply_profile(segment, profile)
            if not segment.voice:
                segment.voice = self.config.voice or None
            if not segment.style_prompt:
                segment.style_prompt = self.config.style_prompt or None

    @staticmethod
    def _apply_profile(segment: DubbingSegment, profile: SpeakerProfile) -> None:
        if profile.voice:
            segment.voice = profile.voice
        if profile.clone_audio_path:
            segment.clone_audio_path = profile.clone_audio_path
        if profile.clone_audio_text:
            segment.clone_audio_text = profile.clone_audio_text
        if profile.style_prompt:
            segment.style_prompt = profile.style_prompt

    def _fit_segment(self, segment: DubbingSegment, work_dir: Path) -> str:
        source = segment.synthesized_path
        if self.config.fit_mode == "none" or not segment.target_duration_ms:
            return source
        target_ms = max(100, segment.target_duration_ms - self.config.target_padding_ms)
        synth_ms = segment.synthesized_duration_ms
        if synth_ms <= target_ms:
            # 短于目标：默认放慢拉伸到原时长（factor<1 → atempo 拉长），下限 min_speed。
            if not self.config.stretch_to_fit:
                segment.speed_factor = 1.0
                return source
            factor = max(synth_ms / target_ms, self.config.min_speed)
            if factor >= 0.999:  # 已基本贴合，无需处理
                segment.speed_factor = 1.0
                return source
            segment.speed_factor = factor
            out_path = work_dir / f"{segment.index:04d}_fit.wav"
            change_tempo(source, str(out_path), factor)
            return str(out_path)
        # 长于目标：加速压缩，上限 max_speed。
        factor = min(synth_ms / target_ms, self.config.max_speed)
        segment.speed_factor = factor
        out_path = work_dir / f"{segment.index:04d}_fit.wav"
        change_tempo(source, str(out_path), factor)
        return str(out_path)

    def _raw_segment_path(self, segment: DubbingSegment, work: Path) -> Path:
        """原始 TTS 分段路径：开缓存走全局内容寻址，关缓存进任务目录。"""
        ext = self._provider_extension()
        if self.config.use_cache:
            TTS_SEGMENT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            return TTS_SEGMENT_CACHE_DIR / f"{self._segment_hash(segment)}.{ext}"
        return work / f"{segment.index:04d}_raw.{ext}"

    def _process_segment(self, segment: DubbingSegment, work: Path) -> DubbingSegment:
        raw_path = self._raw_segment_path(segment, work)
        reusable_raw = self.config.use_cache and self._valid_audio_path(raw_path)
        if reusable_raw:
            segment.synthesized_path = str(raw_path)
            segment.synthesized_duration_ms = get_audio_duration_ms(segment.synthesized_path)
            if self._needs_duration_retry(segment, segment.synthesized_duration_ms):
                raw_path.unlink(missing_ok=True)
                reusable_raw = False
        if not reusable_raw:
            segment.synthesized_path = self._synthesize_with_duration_retry(segment, raw_path)
        segment.synthesized_duration_ms = get_audio_duration_ms(segment.synthesized_path)
        segment.fitted_path = self._fit_segment(segment, work)
        segment.fitted_duration_ms = get_audio_duration_ms(segment.fitted_path)
        return segment

    def _synthesize_with_duration_retry(self, segment: DubbingSegment, raw_path: Path) -> str:
        last_path = ""
        original_style = segment.style_prompt
        for attempt in range(3):
            raw_path.unlink(missing_ok=True)
            style_prompt = original_style
            if attempt == 1 and original_style:
                style_prompt = "自然、清晰地朗读。"
            elif attempt == 2:
                style_prompt = None
            result = self.synthesizer.synthesize(
                SynthesisRequest(
                    text=segment.text_for_tts,
                    output_path=str(raw_path),
                    voice=segment.voice,
                    style_prompt=style_prompt,
                    clone_audio_path=segment.clone_audio_path,
                    clone_audio_text=segment.clone_audio_text,
                )
            )
            last_path = result.output_path
            duration_ms = get_audio_duration_ms(last_path)
            if not self._needs_duration_retry(segment, duration_ms):
                return last_path
        return last_path

    def _needs_duration_retry(self, segment: DubbingSegment, duration_ms: int) -> bool:
        if self.config.fit_mode != "tempo" or not segment.target_duration_ms:
            return False
        target_ms = max(100, segment.target_duration_ms - self.config.target_padding_ms)
        if duration_ms <= target_ms * self.config.max_speed:
            return False
        # Very short subtitles occasionally produce pathological long TTS output.
        return len(segment.text_for_tts.strip()) <= 40

    def _provider_extension(self) -> str:
        if self.config.provider == "gemini":
            return "wav"
        if self.config.provider == "edge":
            return "mp3"
        return self.config.response_format

    @staticmethod
    def _provider_response_format(
        config: DubbingConfig,
    ) -> Literal["mp3", "opus", "aac", "flac", "wav", "pcm"]:
        if config.provider == "gemini":
            return "wav"
        if config.provider == "edge":
            return "mp3"
        return config.response_format

    def _segment_hash(self, segment: DubbingSegment) -> str:
        """缓存键：必须覆盖所有影响发音的输入。

        漏掉任何一项（曾漏过 speed/gain）都会让用户改完配置仍命中
        旧音频；新增会影响合成结果的配置字段时这里必须同步。
        """
        raw = "|".join(
            [
                segment.text_for_tts,
                segment.voice or "",
                segment.style_prompt or "",
                segment.clone_audio_path or "",
                segment.clone_audio_text or "",
                str(self.config.provider),
                self.config.model,
                str(self.config.speed),
                str(self.config.gain),
                str(self.config.sample_rate),
                self.config.response_format,
            ]
        )
        return hashlib.md5(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _valid_audio_path(path: Path) -> bool:
        if not path.exists() or path.stat().st_size <= 0:
            return False
        try:
            get_audio_duration_ms(str(path))
            return True
        except Exception:
            return False

    @staticmethod
    def _write_report(path: Path, segments: list[DubbingSegment], warnings: list[str]) -> None:
        report = {
            "warnings": warnings,
            "segments": [
                {
                    "index": seg.index,
                    "speaker": seg.speaker,
                    "start_ms": seg.start_ms,
                    "end_ms": seg.end_ms,
                    "text": seg.text,
                    "rewritten_text": seg.rewritten_text,
                    "voice": seg.voice,
                    "synthesized_duration_ms": seg.synthesized_duration_ms,
                    "fitted_duration_ms": seg.fitted_duration_ms,
                    "speed_factor": round(seg.speed_factor, 4),
                    "warning": seg.warning,
                }
                for seg in segments
            ],
        }
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
