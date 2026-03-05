from __future__ import annotations

import gc
import os
import tempfile
from typing import Any, Callable, Optional, Union

from openai import APIConnectionError, OpenAI

from app.core.llm.client import normalize_base_url
from app.core.utils.logger import setup_logger

from .asr_data import ASRDataSeg
from .base import BaseASR

logger = setup_logger("qwen_asr")

_QWEN_LANGUAGE_MAP = {
    "zh": "Chinese",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "yue": "Cantonese",
}


class QwenASR(BaseASR):
    """Qwen-ASR implementation based on qwen-asr python package."""

    def __init__(
        self,
        audio_input: Union[str, bytes],
        model_name: str,
        aligner_model_name: str = "Qwen/Qwen3-ForcedAligner-0.6B",
        backend: str = "transformers",
        language: str = "",
        api_base: str = "",
        api_key: str = "",
        prompt: str = "",
        need_word_time_stamp: bool = True,
        max_new_tokens: int = 1024,
        timestamp_mode: str = "forced_aligner_word",
        compute_dtype: str = "bfloat16",
        language_mode: str = "auto",
        force_language: str = "",
        timestamp_rounding: str = "round",
        use_cache: bool = False,
    ):
        super().__init__(audio_input, use_cache, need_word_time_stamp)
        self.model_name = model_name.strip()
        self.aligner_model_name = aligner_model_name.strip()
        self.backend = backend.strip() or "transformers"
        self.language = language.strip()
        self.api_base = api_base.strip()
        self.api_key = api_key.strip()
        self.prompt = prompt.strip()
        self.need_word_time_stamp = need_word_time_stamp
        self.max_new_tokens = max_new_tokens
        self.timestamp_mode = timestamp_mode.strip() or "forced_aligner_word"
        self.compute_dtype = compute_dtype.strip() or "bfloat16"
        self.language_mode = language_mode.strip() or "auto"
        self.force_language = force_language.strip()
        self.timestamp_rounding = timestamp_rounding.strip() or "round"

        if not self.model_name:
            raise ValueError("Qwen ASR model name must be set")

    def _get_key(self) -> str:
        return (
            f"{self.crc32_hex}-{self.model_name}-{self.backend}-"
            f"{self.language}-{self.need_word_time_stamp}-{self.max_new_tokens}-"
            f"{self.api_base}-{self.prompt}-{self.timestamp_mode}-"
            f"{self.compute_dtype}-{self.language_mode}-{self.force_language}-"
            f"{self.timestamp_rounding}"
        )

    def _run(
        self, callback: Optional[Callable[[int, str], None]] = None, **kwargs: Any
    ) -> dict:
        if self.backend == "vllm":
            return self._run_vllm(callback)
        return self._run_transformers(callback)

    def _run_vllm(
        self, callback: Optional[Callable[[int, str], None]] = None
    ) -> dict:
        base_url = normalize_base_url(self.api_base)
        if not base_url or not self.api_key:
            raise RuntimeError(
                "Qwen ASR(vllm) 需要配置 API Base URL 和 API Key（OpenAI 兼容）"
            )

        if callback:
            callback(30, "Qwen-ASR(vllm) 推理中")

        client = OpenAI(base_url=base_url, api_key=self.api_key)
        api_kwargs: dict[str, Any] = {
            "model": self.model_name,
            "response_format": "verbose_json",
            "file": ("audio.mp3", self.file_binary or b"", "audio/mp3"),
            "timestamp_granularities": ["word", "segment"],
        }
        if self.language:
            api_kwargs["language"] = self.language
        if self.prompt:
            api_kwargs["prompt"] = self.prompt

        try:
            completion = client.audio.transcriptions.create(**api_kwargs)
        except APIConnectionError as e:
            raise RuntimeError(
                f"Qwen ASR(vllm) 连接失败：{base_url}。请先启动服务并确认端口可访问。"
            ) from e
        if isinstance(completion, str):
            raise RuntimeError(
                "Qwen ASR(vllm) 返回异常，请检查 OpenAI 兼容 API 地址与模型配置"
            )

        if callback:
            callback(95, "Qwen-ASR(vllm) 结果整理中")

        return completion.to_dict()

    def _run_transformers(
        self, callback: Optional[Callable[[int, str], None]] = None
    ) -> dict:
        language = self._resolve_qwen_language()
        use_forced_aligner = self._need_forced_aligner()

        if callback:
            callback(30, "Qwen-ASR 推理中")

        result: Any
        resources_to_release: list[Any] = []
        try:
            # qwen-asr>=0.0.6 API
            from qwen_asr import Qwen3ASRModel
        except Exception as import_error:
            try:
                # qwen-asr early API fallback
                from qwen_asr import Qwen3ASR
                from qwen_asr.models.qwen3_asr import Qwen3ASRConfig
                from qwen_asr.models.qwen3_asr_toolkit import Qwen3ASRToolkit
            except Exception:
                raise RuntimeError(
                    "Qwen ASR(transformers) 依赖加载失败，请检查 qwen-asr/torch 环境与版本兼容"
                ) from import_error

            config = Qwen3ASRConfig(
                model_name_or_path=self.model_name,
                llm_backend=self.backend,
                max_new_tokens=self.max_new_tokens,
            )
            model = Qwen3ASR(config=config)
            resources_to_release.append(model)
            toolkit = None
            if use_forced_aligner:
                toolkit = Qwen3ASRToolkit.forced_aligner(self.aligner_model_name)
                resources_to_release.append(toolkit)
            try:
                result = model.transcribe(
                    self.file_binary,
                    language=language,
                    toolkit=toolkit,
                )
            except Exception as old_api_error:
                raise RuntimeError(
                    f"Qwen ASR(transformers) 推理失败：{old_api_error}"
                ) from old_api_error
            finally:
                self._release_resources(resources_to_release)
        else:
            audio_input_for_qwen, temp_audio_path = self._prepare_audio_input_for_qwen()
            try:
                model_load_kwargs: dict[str, Any] = {}
                try:
                    import torch

                    if torch.cuda.is_available():
                        model_load_kwargs["device_map"] = "cuda:0"
                        dtype_map = {
                            "float16": torch.float16,
                            "bfloat16": torch.bfloat16,
                            "float32": torch.float32,
                        }
                        model_load_kwargs["torch_dtype"] = dtype_map.get(
                            self.compute_dtype, torch.bfloat16
                        )
                        logger.info("Qwen ASR using CUDA device: cuda:0")
                except Exception:
                    pass

                model = Qwen3ASRModel.from_pretrained(
                    self.model_name,
                    forced_aligner=(self.aligner_model_name if use_forced_aligner else None),
                    max_new_tokens=self.max_new_tokens,
                    **model_load_kwargs,
                )
                resources_to_release.append(model)
                results = model.transcribe(
                    audio_input_for_qwen,
                    language=language,
                    return_time_stamps=use_forced_aligner,
                )
                result = (
                    results[0] if isinstance(results, list) and results else results
                )
            except Exception as inference_error:
                err_text = str(inference_error)
                if (
                    use_forced_aligner
                    and (
                        "Qwen3-ForcedAligner" in err_text
                        or "Repository Not Found" in err_text
                        or "401" in err_text
                    )
                ):
                    fallback_aligner = "Qwen/Qwen3-ForcedAligner-0.6B"
                    if self.aligner_model_name != fallback_aligner:
                        logger.warning(
                            "Qwen aligner `%s` unavailable, fallback to `%s`",
                            self.aligner_model_name,
                            fallback_aligner,
                        )
                        try:
                            model = Qwen3ASRModel.from_pretrained(
                                self.model_name,
                                forced_aligner=fallback_aligner,
                                max_new_tokens=self.max_new_tokens,
                            )
                            resources_to_release.append(model)
                            results = model.transcribe(
                                audio_input_for_qwen,
                                language=language,
                                return_time_stamps=True,
                            )
                            result = (
                                results[0]
                                if isinstance(results, list) and results
                                else results
                            )
                            return self._normalize_result(result)
                        except Exception:
                            pass
                    raise RuntimeError(
                        "Qwen ASR(transformers) 对齐器模型不可用：请把 Aligner 改为 "
                        "`Qwen/Qwen3-ForcedAligner-0.6B`，或关闭“词级时间戳”。"
                    ) from inference_error
                raise RuntimeError(
                    f"Qwen ASR(transformers) 推理失败：{inference_error}"
                ) from inference_error
            finally:
                if temp_audio_path:
                    try:
                        os.remove(temp_audio_path)
                    except OSError:
                        pass
                self._release_resources(resources_to_release)

        if callback:
            callback(95, "Qwen-ASR 结果整理中")

        normalized = self._normalize_result(result)
        if normalized:
            return normalized

        raise TypeError("Qwen ASR returned unsupported result type")

    def _normalize_result(self, result: Any) -> dict:
        if isinstance(result, dict):
            return result

        if hasattr(result, "model_dump"):
            dumped = result.model_dump()
            if isinstance(dumped, dict):
                return dumped

        if hasattr(result, "__dict__"):
            normalized: dict[str, Any] = dict(result.__dict__)
            time_stamps = normalized.get("time_stamps")
            if time_stamps is not None:
                items = getattr(time_stamps, "items", time_stamps)
                converted = []
                for item in items or []:
                    if isinstance(item, dict):
                        text = item.get("text", "")
                        start_value = item.get("start_time", item.get("start", 0))
                        end_value = item.get("end_time", item.get("end", start_value))
                    else:
                        text = getattr(item, "text", "")
                        start_value = getattr(
                            item, "start_time", getattr(item, "start", 0)
                        )
                        end_value = getattr(
                            item,
                            "end_time",
                            getattr(item, "end", start_value),
                        )

                    try:
                        start_time = float(start_value)
                        end_time = float(end_value)
                    except (TypeError, ValueError):
                        continue

                    converted.append(
                        {
                            "text": text,
                            "word": text,
                            "start": start_time,
                            "end": end_time,
                            "start_time": start_time,
                            "end_time": end_time,
                        }
                    )
                normalized["time_stamps"] = converted
                normalized["words"] = converted
            return normalized

        return {}

    def _prepare_audio_input_for_qwen(self) -> tuple[Union[str, bytes], Optional[str]]:
        if isinstance(self.audio_input, str) and os.path.exists(self.audio_input):
            return self.audio_input, None

        if not self.file_binary:
            raise RuntimeError("Qwen ASR(transformers) 音频输入为空")

        with tempfile.NamedTemporaryFile(
            suffix=".wav", delete=False
        ) as temp_audio_file:
            temp_audio_file.write(self.file_binary)
            return temp_audio_file.name, temp_audio_file.name

    def _release_resources(self, resources: list[Any]) -> None:
        for resource in list(resources):
            self._release_single_resource(resource)
        resources.clear()
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:
            pass

    def _release_single_resource(self, resource: Any) -> None:
        try:
            # qwen-asr wrapper objects keep heavy references in these fields.
            for field in ("model", "forced_aligner", "processor", "sampling_params"):
                if hasattr(resource, field):
                    inner = getattr(resource, field)
                    self._release_torch_object(inner)
                    try:
                        setattr(resource, field, None)
                    except Exception:
                        pass
            self._release_torch_object(resource)
        except Exception:
            pass

    def _release_torch_object(self, obj: Any) -> None:
        if obj is None:
            return
        try:
            # Move modules to CPU before dropping refs to encourage CUDA allocator release.
            to_fn = getattr(obj, "to", None)
            if callable(to_fn):
                try:
                    to_fn("cpu")
                except Exception:
                    pass
        except Exception:
            pass

    def _make_segments(self, resp_data: dict) -> list[ASRDataSeg]:
        words = resp_data.get("words") or []
        if self._need_forced_aligner() and words:
            segments: list[ASRDataSeg] = []
            for word in words:
                if not isinstance(word, dict):
                    continue
                token_text = (word.get("word") or word.get("text") or "").strip()
                if not token_text:
                    continue
                start = word.get("start", word.get("start_time", 0))
                end = word.get("end", word.get("end_time", start))
                try:
                    start_ms = self._to_ms(start)
                    end_ms = self._to_ms(end)
                except (TypeError, ValueError):
                    continue
                segments.append(
                    ASRDataSeg(
                        text=token_text,
                        start_time=start_ms,
                        end_time=end_ms,
                    )
                )
            if segments:
                if self._needs_synthetic_timeline(segments):
                    logger.warning(
                        "Qwen ASR words timestamps are degenerate (all zero), fallback to synthetic timeline"
                    )
                    return self._synthesize_timeline(segments)
                return self._repair_partial_zero_timestamps(segments)

        api_segments = resp_data.get("segments") or []
        if api_segments:
            segments: list[ASRDataSeg] = []
            for seg in api_segments:
                if not isinstance(seg, dict):
                    continue
                seg_text = (seg.get("text") or "").strip()
                start = seg.get("start", 0)
                end = seg.get("end", start)
                try:
                    start_ms = self._to_ms(start)
                    end_ms = self._to_ms(end)
                except (TypeError, ValueError):
                    continue
                segments.append(
                    ASRDataSeg(
                        text=seg_text,
                        start_time=start_ms,
                        end_time=end_ms,
                    )
                )
            if segments:
                if self._needs_synthetic_timeline(segments):
                    logger.warning(
                        "Qwen ASR segment timestamps are degenerate (all zero), fallback to synthetic timeline"
                    )
                    return self._synthesize_timeline(segments)
                return self._repair_partial_zero_timestamps(segments)

        time_stamps = resp_data.get("time_stamps") or resp_data.get("timestamps") or []
        text = (resp_data.get("text") or "").strip()

        if self._need_forced_aligner() and time_stamps:
            segments: list[ASRDataSeg] = []
            for item in time_stamps:
                if not isinstance(item, dict):
                    continue

                token_text = (
                    item.get("text")
                    or item.get("word")
                    or item.get("token")
                    or ""
                ).strip()
                if not token_text:
                    continue

                start = item.get("start_time", item.get("start", 0))
                end = item.get("end_time", item.get("end", start))
                try:
                    start_ms = self._to_ms(start)
                    end_ms = self._to_ms(end)
                except (TypeError, ValueError):
                    continue

                segments.append(
                    ASRDataSeg(
                        text=token_text,
                        start_time=start_ms,
                        end_time=end_ms,
                    )
                )

            if segments:
                if self._needs_synthetic_timeline(segments):
                    logger.warning(
                        "Qwen ASR time_stamps are degenerate (all zero), fallback to synthetic timeline"
                    )
                    return self._synthesize_timeline(segments)
                return self._repair_partial_zero_timestamps(segments)

        if text:
            max_end_ms = 0
            for item in time_stamps:
                if not isinstance(item, dict):
                    continue
                end = item.get("end_time", item.get("end", 0))
                try:
                    max_end_ms = max(max_end_ms, self._to_ms(end))
                except (TypeError, ValueError):
                    continue

            if max_end_ms <= 0:
                max_end_ms = int(max(self.audio_duration, 0.1) * 1000)

            return [ASRDataSeg(text=text, start_time=0, end_time=max_end_ms)]

        logger.warning("Qwen ASR returned empty result")
        return [
            ASRDataSeg(
                text="",
                start_time=0,
                end_time=int(max(self.audio_duration, 0.1) * 1000),
            )
        ]

    def _resolve_qwen_language(self) -> Optional[str]:
        if self.language_mode != "force":
            return None
        preferred_language = self.force_language or self.language
        if not preferred_language:
            return None
        mapped = _QWEN_LANGUAGE_MAP.get(preferred_language)
        if mapped is None:
            logger.warning(
                "Qwen ASR force language mode is enabled but `%s` is unsupported, fallback to auto",
                preferred_language,
            )
        return mapped

    def _need_forced_aligner(self) -> bool:
        return self.need_word_time_stamp and self.timestamp_mode == "forced_aligner_word"

    def _to_ms(self, value: Any) -> int:
        ms = float(value) * 1000.0
        if self.timestamp_rounding == "floor":
            return int(ms)
        return int(round(ms))

    def _needs_synthetic_timeline(self, segments: list[ASRDataSeg]) -> bool:
        if not segments:
            return False

        zero_pair_count = sum(
            1 for seg in segments if seg.start_time == 0 and seg.end_time == 0
        )
        zero_pair_ratio = zero_pair_count / len(segments)
        max_end = max(seg.end_time for seg in segments)

        return zero_pair_ratio >= 0.9 or max_end <= 0

    def _synthesize_timeline(self, segments: list[ASRDataSeg]) -> list[ASRDataSeg]:
        if not segments:
            return []

        total_ms = int(max(self.audio_duration, 0.1) * 1000)
        total_ms = max(total_ms, len(segments))

        rebuilt: list[ASRDataSeg] = []
        for idx, seg in enumerate(segments):
            start = int(idx * total_ms / len(segments))
            end = int((idx + 1) * total_ms / len(segments))
            if end <= start:
                end = start + 1
            rebuilt.append(
                ASRDataSeg(
                    text=seg.text,
                    start_time=start,
                    end_time=end,
                )
            )

        return rebuilt

    def _repair_partial_zero_timestamps(
        self, segments: list[ASRDataSeg]
    ) -> list[ASRDataSeg]:
        if not segments:
            return []

        zero_pair_indexes = [
            idx
            for idx, seg in enumerate(segments)
            if seg.start_time == 0 and seg.end_time == 0
        ]
        if not zero_pair_indexes:
            return segments

        max_end = max(seg.end_time for seg in segments)
        if max_end <= 0:
            return segments

        rebuilt = [
            ASRDataSeg(
                text=seg.text,
                start_time=seg.start_time,
                end_time=seg.end_time,
                translated_text=seg.translated_text,
            )
            for seg in segments
        ]
        synthetic = self._synthesize_timeline(segments)

        for idx in zero_pair_indexes:
            rebuilt[idx].start_time = synthetic[idx].start_time
            rebuilt[idx].end_time = synthetic[idx].end_time

        logger.warning(
            "Qwen ASR repaired %d zero-pair timestamps with synthetic positions",
            len(zero_pair_indexes),
        )
        return rebuilt
