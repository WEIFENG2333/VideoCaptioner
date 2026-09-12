"""Alibaba Cloud Bailian FunAudio-ASR HTTP client.

This module intentionally uses plain HTTP requests instead of the DashScope SDK.
The recorded-file API accepts HTTP(S) URLs or temporary ``oss://`` URLs, so local
files are first uploaded through the official DashScope upload-policy endpoint.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any, Literal, Optional, TypedDict, cast

import requests

from videocaptioner.core.utils.logger import setup_logger

from .asr_data import ASRDataSeg
from .base import BaseASR

logger = setup_logger("fun_asr")

DEFAULT_FUN_ASR_API_BASE = "https://dashscope.aliyuncs.com"
DEFAULT_FUN_ASR_MODEL = "fun-asr"
SUPPORTED_LANGUAGE_HINTS = {
    "zh",
    "en",
    "ja",
    "ko",
    "vi",
    "th",
    "id",
    "ms",
    "tl",
    "hi",
    "ar",
    "fr",
    "de",
    "es",
    "pt",
    "ru",
    "it",
    "nl",
    "sv",
    "da",
    "fi",
    "no",
    "el",
    "pl",
    "cs",
    "hu",
    "ro",
    "bg",
    "hr",
    "sk",
}


class FunASRUploadPolicy(TypedDict):
    policy: str
    signature: str
    upload_dir: str
    upload_host: str
    oss_access_key_id: str
    x_oss_object_acl: str
    x_oss_forbid_overwrite: str
    expire_in_seconds: int
    max_file_size_mb: int


class FunASRSubmitInput(TypedDict):
    file_urls: list[str]


class FunASRSubmitParameters(TypedDict, total=False):
    channel_id: list[int]
    language_hints: list[str]
    diarization_enabled: bool
    speaker_count: int
    vocabulary_id: str
    special_word_filter: str


class FunASRSubmitRequest(TypedDict):
    model: str
    input: FunASRSubmitInput
    parameters: FunASRSubmitParameters


class FunASRTaskOutput(TypedDict, total=False):
    task_id: str
    task_status: str


class FunASRSubmitResponse(TypedDict):
    output: FunASRTaskOutput
    request_id: str


class FunASRTaskResult(TypedDict, total=False):
    subtask_status: str
    file_url: str
    transcription_url: str
    code: str
    message: str


class FunASRQueryOutput(FunASRTaskOutput, total=False):
    results: list[FunASRTaskResult]
    task_metrics: dict[str, int]


class FunASRQueryResponse(TypedDict):
    output: FunASRQueryOutput
    request_id: str


class FunASRWord(TypedDict, total=False):
    begin_time: int
    end_time: int
    text: str
    punctuation: str


class FunASRSentence(TypedDict, total=False):
    begin_time: int
    end_time: int
    text: str
    sentence_id: int
    speaker_id: int
    words: list[FunASRWord]


class FunASRTranscript(TypedDict, total=False):
    channel_id: int
    content_duration_in_milliseconds: int
    text: str
    sentences: list[FunASRSentence]


class FunASRTranscriptionResult(TypedDict, total=False):
    file_url: str
    properties: dict[str, Any]
    transcripts: list[FunASRTranscript]


class BailianFunASR(BaseASR):
    """ASR implementation for Alibaba Cloud Bailian FunAudio-ASR."""

    def __init__(
        self,
        audio_input: Optional[str | bytes] = None,
        use_cache: bool = False,
        need_word_time_stamp: bool = False,
        api_key: str = "",
        api_base: str = DEFAULT_FUN_ASR_API_BASE,
        model: str = DEFAULT_FUN_ASR_MODEL,
        language: str = "",
        poll_interval: float = 2.0,
        timeout: int = 1800,
    ):
        self.api_key = (api_key or os.getenv("DASHSCOPE_API_KEY", "")).strip()
        self.api_base = (api_base or DEFAULT_FUN_ASR_API_BASE).rstrip("/")
        self.model = model or DEFAULT_FUN_ASR_MODEL
        self.language = language or ""
        self.need_word_time_stamp = need_word_time_stamp
        self.poll_interval = poll_interval
        self.timeout = timeout
        self._source_path = audio_input if isinstance(audio_input, str) else None
        super().__init__(audio_input, use_cache, need_word_time_stamp)

    def _get_key(self) -> str:
        return f"{self.crc32_hex}:{self.model}:{self.language}:{self.need_word_time_stamp}"

    def _run(self, callback=None) -> FunASRTranscriptionResult:
        if not self.api_key:
            raise ValueError("百炼 ASR API Key 未配置，请先在设置页或环境变量中填写。")

        if callback:
            callback(5, "上传音频")
        audio_url = self._upload_input()

        if callback:
            callback(20, "提交转录任务")
        task_id = self._submit_task(audio_url)

        if callback:
            callback(30, "等待转录结果")
        transcription_url = self._wait_for_task(task_id, callback)

        if callback:
            callback(95, "下载转录结果")
        result = self._download_transcription(transcription_url)

        if callback:
            callback(100, "转录完成")
        return result

    def _headers(self, *, json_content: bool = True) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if json_content:
            headers["Content-Type"] = "application/json"
        return headers

    def _request_json(
        self,
        method: Literal["GET", "POST"],
        url: str,
        *,
        expected_status: tuple[int, ...] = (200,),
        **kwargs,
    ) -> dict[str, Any]:
        response = requests.request(method, url, timeout=60, **kwargs)
        if response.status_code not in expected_status:
            raise RuntimeError(self._format_http_error(response))
        try:
            return cast(dict[str, Any], response.json())
        except ValueError as exc:
            raise RuntimeError(f"百炼接口返回了非 JSON 响应: {response.text[:200]}") from exc

    def _format_http_error(self, response: requests.Response) -> str:
        try:
            payload = response.json()
            message = payload.get("message") or payload.get("code") or response.text
        except ValueError:
            message = response.text
        return f"百炼 ASR 请求失败 ({response.status_code}): {message}"

    def _get_upload_policy(self) -> FunASRUploadPolicy:
        url = f"{self.api_base}/api/v1/uploads"
        payload = self._request_json(
            "GET",
            url,
            headers=self._headers(),
            params={"action": "getPolicy", "model": self.model},
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("百炼上传凭证响应缺少 data 字段")
        return cast(FunASRUploadPolicy, data)

    def _upload_input(self) -> str:
        policy = self._get_upload_policy()
        if self._source_path:
            path = Path(self._source_path)
            return self._upload_file(policy, path.name, path.read_bytes())

        suffix = ".mp3"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(self.file_binary or b"")
            tmp_path = Path(tmp.name)
        try:
            return self._upload_file(policy, f"{self.crc32_hex}{suffix}", tmp_path.read_bytes())
        finally:
            tmp_path.unlink(missing_ok=True)

    def _upload_file(self, policy: FunASRUploadPolicy, file_name: str, data: bytes) -> str:
        key = f"{policy['upload_dir']}/{file_name}"
        files = {
            "OSSAccessKeyId": (None, policy["oss_access_key_id"]),
            "Signature": (None, policy["signature"]),
            "policy": (None, policy["policy"]),
            "x-oss-object-acl": (None, policy["x_oss_object_acl"]),
            "x-oss-forbid-overwrite": (None, policy["x_oss_forbid_overwrite"]),
            "key": (None, key),
            "success_action_status": (None, "200"),
            "file": (file_name, data),
        }
        response = requests.post(policy["upload_host"], files=files, timeout=120)
        if response.status_code != 200:
            raise RuntimeError(self._format_http_error(response))
        return f"oss://{key}"

    def _submit_task(self, audio_url: str) -> str:
        url = f"{self.api_base}/api/v1/services/audio/asr/transcription"
        parameters: FunASRSubmitParameters = {"channel_id": [0]}
        language_hint = self._language_hint()
        if language_hint:
            parameters["language_hints"] = [language_hint]
        body: FunASRSubmitRequest = {
            "model": self.model,
            "input": {"file_urls": [audio_url]},
            "parameters": parameters,
        }
        headers = self._headers()
        headers["X-DashScope-Async"] = "enable"
        headers["X-DashScope-OssResourceResolve"] = "enable"
        payload = cast(
            FunASRSubmitResponse,
            self._request_json("POST", url, headers=headers, json=body),
        )
        task_id = payload.get("output", {}).get("task_id")
        if not task_id:
            raise RuntimeError(f"百炼 ASR 提交任务失败: {payload}")
        return task_id

    def _language_hint(self) -> str:
        language = self.language.strip().lower()
        if language in SUPPORTED_LANGUAGE_HINTS:
            return language
        if language:
            logger.info("Fun-ASR does not support language hint '%s', using auto detection", language)
        return ""

    def _wait_for_task(self, task_id: str, callback=None) -> str:
        deadline = time.time() + self.timeout
        url = f"{self.api_base}/api/v1/tasks/{task_id}"
        last_status = ""
        while time.time() < deadline:
            payload = cast(
                FunASRQueryResponse,
                self._request_json("GET", url, headers=self._headers(json_content=False)),
            )
            output = payload.get("output", {})
            status = output.get("task_status", "")
            if status != last_status:
                logger.info("Fun-ASR task %s status: %s", task_id, status)
                last_status = status
            if status == "SUCCEEDED":
                return self._pick_transcription_url(output)
            if status in {"FAILED", "CANCELED", "UNKNOWN"}:
                raise RuntimeError(self._format_task_failure(output))
            if callback:
                callback(50, f"任务状态：{status or '处理中'}")
            time.sleep(self.poll_interval)
        raise TimeoutError("百炼 ASR 等待结果超时")

    def _pick_transcription_url(self, output: FunASRQueryOutput) -> str:
        for result in output.get("results", []) or []:
            if result.get("subtask_status") == "SUCCEEDED" and result.get("transcription_url"):
                return result["transcription_url"]
        raise RuntimeError(self._format_task_failure(output))

    def _format_task_failure(self, output: FunASRQueryOutput) -> str:
        for result in output.get("results", []) or []:
            code = result.get("code", "")
            message = result.get("message", "")
            if code or message:
                return f"百炼 ASR 子任务失败: {code} {message}".strip()
        return f"百炼 ASR 任务失败: {output.get('task_status', 'UNKNOWN')}"

    def _download_transcription(self, transcription_url: str) -> FunASRTranscriptionResult:
        payload = self._request_json(
            "GET",
            transcription_url,
            expected_status=(200,),
        )
        return cast(FunASRTranscriptionResult, payload)

    def _make_segments(self, resp_data: FunASRTranscriptionResult) -> list[ASRDataSeg]:
        segments: list[ASRDataSeg] = []
        for transcript in resp_data.get("transcripts", []) or []:
            sentences = transcript.get("sentences", []) or []
            if self.need_word_time_stamp:
                segments.extend(self._word_segments(sentences))
            else:
                segments.extend(self._sentence_segments(sentences))
        return segments

    def _sentence_segments(self, sentences: list[FunASRSentence]) -> list[ASRDataSeg]:
        segments: list[ASRDataSeg] = []
        for sentence in sentences:
            text = (sentence.get("text") or "").strip()
            if not text:
                continue
            start = int(sentence.get("begin_time") or 0)
            end = int(sentence.get("end_time") or start)
            segments.append(ASRDataSeg(text=text, start_time=start, end_time=end))
        return segments

    def _word_segments(self, sentences: list[FunASRSentence]) -> list[ASRDataSeg]:
        segments: list[ASRDataSeg] = []
        for sentence in sentences:
            words = sentence.get("words") or []
            if not words:
                text = (sentence.get("text") or "").strip()
                if text:
                    segments.append(
                        ASRDataSeg(
                            text=text,
                            start_time=int(sentence.get("begin_time") or 0),
                            end_time=int(sentence.get("end_time") or 0),
                        )
                    )
                continue
            for word in words:
                text = f"{word.get('text', '')}{word.get('punctuation', '')}".strip()
                if not text:
                    continue
                start = int(word.get("begin_time") or 0)
                end = int(word.get("end_time") or start)
                segments.append(ASRDataSeg(text=text, start_time=start, end_time=end))
        return segments

