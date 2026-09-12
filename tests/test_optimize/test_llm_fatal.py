"""LLM 硬失败 fail-fast 测试（无需真实 API）。

回归防护：鉴权失效/余额不足这类确定性错误应立即中止并冒泡清晰原因，而不是逐批吞掉、
刷屏几十条相同 ERROR 后硬撑到下一步。
"""

import pytest

from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg
from videocaptioner.core.optimize import optimize as opt_mod
from videocaptioner.core.optimize.optimize import (
    LLMFatalError,
    SubtitleOptimizer,
    _is_fatal_llm_error,
)


class _FakeLLMError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class TestFatalClassifier:
    def test_status_code_402(self):
        assert _is_fatal_llm_error(_FakeLLMError("boom", 402))

    def test_status_code_401(self):
        assert _is_fatal_llm_error(_FakeLLMError("boom", 401))

    def test_message_balance(self):
        assert _is_fatal_llm_error(
            _FakeLLMError("Error code: 402 - your account balance is insufficient")
        )

    def test_message_invalid_key(self):
        assert _is_fatal_llm_error(_FakeLLMError("Invalid API key provided"))

    def test_transient_not_fatal(self):
        assert not _is_fatal_llm_error(_FakeLLMError("Connection reset by peer"))
        assert not _is_fatal_llm_error(_FakeLLMError("timeout", 500))


class TestOptimizeFailFast:
    def _data(self) -> ASRData:
        return ASRData(
            [ASRDataSeg(f"line number {i}", i * 1000, i * 1000 + 900) for i in range(12)]
        )

    def test_fatal_aborts_immediately(self, monkeypatch):
        calls = {"n": 0}

        def boom(*args, **kwargs):
            calls["n"] += 1
            raise _FakeLLMError(
                "Error code: 402 - your account balance is insufficient", 402
            )

        monkeypatch.setattr(opt_mod, "call_llm", boom)
        optimizer = SubtitleOptimizer(
            thread_num=2, batch_num=5, model="m", custom_prompt=""
        )
        try:
            with pytest.raises(LLMFatalError):
                optimizer.optimize_subtitle(self._data())
        finally:
            optimizer.stop()
        # 12 段 / batch 5 = 3 批；fail-fast 应远少于"每批 3 步 × 3 批"的重试放大
        assert calls["n"] <= 3

    def test_transient_keeps_original(self, monkeypatch):
        def flaky(*args, **kwargs):
            raise _FakeLLMError("temporary network error")

        monkeypatch.setattr(opt_mod, "call_llm", flaky)
        optimizer = SubtitleOptimizer(
            thread_num=2, batch_num=5, model="m", custom_prompt=""
        )
        try:
            result = optimizer.optimize_subtitle(self._data())
        finally:
            optimizer.stop()
        # 非硬失败：不中止，保留原文
        assert len(result.segments) == 12
        assert result.segments[0].text == "line number 0"
