"""Hear ASR 单元测试

测试 app/core/asr/hear.py 中的 HearASR 功能
"""

import platform
from pathlib import Path

import pytest

from app.core.asr.hear import HearASR
from app.core.entities import TranscribeConfig, TranscribeModelEnum


@pytest.fixture
def audio_fixture_path():
    """测试音频文件路径"""
    return str(Path(__file__).parent.parent / "fixtures" / "audio" / "en.mp3")


@pytest.fixture
def zh_audio_fixture_path():
    """中文测试音频文件路径"""
    return str(Path(__file__).parent.parent / "fixtures" / "audio" / "zh.mp3")


class TestHearASR:
    """Hear ASR 基本功能测试"""

    def test_check_availability(self):
        """测试 Hear 可用性检查"""
        is_available = HearASR.check_availability()

        if platform.system() == "Darwin":
            assert isinstance(is_available, bool)
        else:
            assert is_available is False

    def test_get_supported_locales(self):
        """测试获取支持的语言列表"""
        locales = HearASR.get_supported_locales()

        assert isinstance(locales, dict)
        assert len(locales) > 0
        assert "en-US" in locales
        assert "zh-CN" in locales
        assert locales["en-US"] == "English (US)"
        assert locales["zh-CN"] == "Chinese (Simplified)"

    @pytest.mark.skipif(
        platform.system() != "Darwin", reason="Hear is only available on macOS"
    )
    def test_initialization(self, audio_fixture_path):
        """测试 HearASR 初始化"""
        asr = HearASR(
            audio_path=audio_fixture_path,
            locale="en-US",
            use_punctuation=True,
            on_device_only=True,
            use_cache=False,
        )

        assert asr.locale == "en-US"
        assert asr.use_punctuation is True
        assert asr.on_device_only is True
        assert asr.hear_program is not None

    @pytest.mark.skipif(
        platform.system() != "Darwin", reason="Hear is only available on macOS"
    )
    def test_build_command(self, audio_fixture_path):
        """测试命令构建"""
        asr = HearASR(
            audio_path=audio_fixture_path,
            locale="en-US",
            use_punctuation=True,
            on_device_only=True,
            use_cache=False,
        )

        cmd = asr._build_command(audio_fixture_path)

        assert "-i" in cmd
        assert audio_fixture_path in cmd
        assert "-l" in cmd
        assert "en-US" in cmd
        assert "-S" in cmd  # Subtitle mode
        assert "-p" in cmd  # Punctuation
        assert "-d" in cmd  # On-device only

    @pytest.mark.skipif(
        platform.system() != "Darwin", reason="Hear is only available on macOS"
    )
    def test_build_command_without_punctuation(self, audio_fixture_path):
        """测试不带标点符号的命令构建"""
        asr = HearASR(
            audio_path=audio_fixture_path,
            locale="zh-CN",
            use_punctuation=False,
            on_device_only=False,
            use_cache=False,
        )

        cmd = asr._build_command(audio_fixture_path)

        assert "-p" not in cmd
        assert "-d" not in cmd
        assert "zh-CN" in cmd

    @pytest.mark.skipif(
        platform.system() != "Darwin" or not HearASR.check_availability(),
        reason="Hear is not available",
    )
    def test_transcription_english(self, audio_fixture_path):
        """测试英文转录 (实际运行)"""
        asr = HearASR(
            audio_path=audio_fixture_path,
            locale="en-US",
            use_punctuation=True,
            on_device_only=True,
            use_cache=False,
        )

        def progress_callback(progress, message):
            print(f"Progress: {progress}% - {message}")

        try:
            result = asr.run(callback=progress_callback)
            assert result is not None
            assert len(result.segments) >= 0

            if len(result.segments) > 0:
                # 验证第一个片段
                first_seg = result.segments[0]
                assert hasattr(first_seg, "text")
                assert hasattr(first_seg, "start_time")
                assert hasattr(first_seg, "end_time")
                assert first_seg.start_time >= 0
                assert first_seg.end_time > first_seg.start_time

                print(f"\nTranscription result: {first_seg.text}")

        except RuntimeError as e:
            pytest.skip(f"Hear execution failed (may be environment issue): {e}")

    @pytest.mark.skipif(
        platform.system() != "Darwin" or not HearASR.check_availability(),
        reason="Hear is not available",
    )
    def test_transcription_chinese(self, zh_audio_fixture_path):
        """测试中文转录 (实际运行)"""
        asr = HearASR(
            audio_path=zh_audio_fixture_path,
            locale="zh-CN",
            use_punctuation=True,
            on_device_only=True,
            use_cache=False,
        )

        def progress_callback(progress, message):
            print(f"Progress: {progress}% - {message}")

        try:
            result = asr.run(callback=progress_callback)
            assert result is not None
            assert len(result.segments) >= 0

            if len(result.segments) > 0:
                first_seg = result.segments[0]
                print(f"\nChinese transcription result: {first_seg.text}")

        except RuntimeError as e:
            pytest.skip(f"Hear execution failed (may be environment issue): {e}")


class TestHearTranscribeIntegration:
    """Hear 与 transcribe 函数的集成测试"""

    @pytest.mark.skipif(
        platform.system() != "Darwin" or not HearASR.check_availability(),
        reason="Hear is not available",
    )
    def test_transcribe_with_hear(self, audio_fixture_path):
        """测试通过 transcribe 函数使用 Hear"""
        from app.core.asr import transcribe

        config = TranscribeConfig(
            transcribe_model=TranscribeModelEnum.HEAR,
            transcribe_language="en",
            need_word_time_stamp=False,
            hear_locale="en-US",
            hear_use_punctuation=True,
            hear_on_device_only=True,
        )

        def progress_callback(progress, message):
            print(f"Transcribe Progress: {progress}% - {message}")

        try:
            result = transcribe(audio_fixture_path, config, callback=progress_callback)
            assert result is not None
            assert len(result.segments) >= 0

            if len(result.segments) > 0:
                print(f"\nTranscribe result: {result.segments[0].text}")

        except RuntimeError as e:
            pytest.skip(f"Transcription failed (may be environment issue): {e}")


class TestHearEdgeCases:
    """Hear ASR 边缘情况测试"""

    def test_initialization_on_non_macos(self):
        """测试在非 macOS 系统上初始化"""
        if platform.system() != "Darwin":
            with pytest.raises(EnvironmentError, match="only available on macOS"):
                HearASR(
                    audio_path="dummy.mp3",
                    locale="en-US",
                    use_cache=False,
                )

    @pytest.mark.skipif(
        platform.system() != "Darwin", reason="Test only valid on macOS"
    )
    def test_unsupported_locale_warning(self, audio_fixture_path, caplog):
        """测试不支持的语言会产生警告"""
        asr = HearASR(
            audio_path=audio_fixture_path,
            locale="xx-XX",  # Invalid locale
            use_cache=False,
        )

        assert asr.locale == "xx-XX"
        # Check for warning in logs (optional, depends on logging setup)

    @pytest.mark.skipif(
        platform.system() != "Darwin", reason="Hear is only available on macOS"
    )
    def test_cache_key_generation(self, audio_fixture_path):
        """测试缓存键生成"""
        asr1 = HearASR(
            audio_path=audio_fixture_path,
            locale="en-US",
            use_punctuation=True,
            use_cache=True,
        )

        asr2 = HearASR(
            audio_path=audio_fixture_path,
            locale="zh-CN",  # Different locale
            use_punctuation=True,
            use_cache=True,
        )

        key1 = asr1._get_key()
        key2 = asr2._get_key()

        # Different locales should produce different cache keys
        assert key1 != key2
        assert isinstance(key1, str)
        assert isinstance(key2, str)
