"""TTS 核心功能测试"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
import requests

from app.core.tts import (
    BaseTTS,
    OpenAIFmTTS,
    OpenAITTS,
    SiliconFlowTTS,
    TTSConfig,
    TTSData,
    TTSDataSeg,
    TTSStatus,
)


class TestTTSConfig:
    """测试 TTSConfig 配置类"""

    def test_default_config(self):
        """测试默认配置"""
        config = TTSConfig(
            model="FunAudioLLM/CosyVoice2-0.5B",
            api_key="test-key",
            base_url="https://api.siliconflow.cn/v1",
        )
        assert config.model == "FunAudioLLM/CosyVoice2-0.5B"
        assert config.base_url == "https://api.siliconflow.cn/v1"
        assert config.response_format == "mp3"
        assert config.sample_rate == 32000
        assert config.speed == 1.0
        assert config.gain == 0
        assert config.cache_ttl == 86400 * 2  # 2天
        assert config.timeout == 60

    def test_custom_config(self):
        """测试自定义配置"""
        config = TTSConfig(
            model="custom-model",
            api_key="test-key",
            base_url="https://test.api",
            voice="female",
            speed=1.5,
            cache_ttl=86400 * 7,  # 7天
        )
        assert config.model == "custom-model"
        assert config.api_key == "test-key"
        assert config.base_url == "https://test.api"
        assert config.voice == "female"
        assert config.speed == 1.5
        assert config.cache_ttl == 86400 * 7


class TestTTSData:
    """测试 TTSData 数据类"""

    def test_create_tts_data_seg(self):
        """测试创建 TTSDataSeg"""
        seg = TTSDataSeg(
            text="你好世界",
            audio_path="/path/to/audio.mp3",
            start_time=0.0,
            end_time=2.5,
            audio_duration=2.5,
            voice="female",
        )
        assert seg.text == "你好世界"
        assert seg.audio_path == "/path/to/audio.mp3"
        assert seg.start_time == 0.0
        assert seg.end_time == 2.5
        assert seg.audio_duration == 2.5
        assert seg.voice == "female"

    def test_create_tts_data_from_segments(self):
        """测试从 segments 创建 TTSData"""
        segments = [
            TTSDataSeg(text="第一段", audio_path="/audio1.mp3"),
            TTSDataSeg(text="第二段", audio_path="/audio2.mp3"),
        ]
        data = TTSData(segments=segments)
        assert len(data) == 2
        assert data.segments[0].text == "第一段"
        assert data.segments[1].text == "第二段"

    def test_from_texts(self):
        """测试从文本列表创建 TTSData"""
        texts = ["文本1", "文本2", "文本3"]
        data = TTSData.from_texts(texts)
        assert len(data) == 3
        assert data.segments[0].text == "文本1"
        assert data.segments[1].text == "文本2"
        assert data.segments[2].text == "文本3"

    def test_filter_empty_segments(self):
        """测试过滤空文本段"""
        segments = [
            TTSDataSeg(text="有效文本", audio_path="/audio1.mp3"),
            TTSDataSeg(text="", audio_path="/audio2.mp3"),
            TTSDataSeg(text="  ", audio_path="/audio3.mp3"),
            TTSDataSeg(text="另一个有效文本", audio_path="/audio4.mp3"),
        ]
        data = TTSData(segments=segments)
        assert len(data) == 2
        assert data.segments[0].text == "有效文本"
        assert data.segments[1].text == "另一个有效文本"


class TestTTSStatus:
    """测试 TTSStatus 状态枚举"""

    def test_status_properties(self):
        """测试状态属性"""
        status = TTSStatus.SYNTHESIZING
        assert status.message == "synthesizing"
        assert status.progress == 30

    def test_callback_tuple(self):
        """测试回调元组"""
        status = TTSStatus.COMPLETED
        assert status.callback_tuple() == (100, "completed")

    def test_with_progress(self):
        """测试自定义进度"""
        status = TTSStatus.SYNTHESIZING
        assert status.with_progress(50) == (50, "synthesizing")

    def test_all_statuses(self):
        """测试所有状态"""
        assert TTSStatus.INITIALIZING.progress == 0
        assert TTSStatus.PREPARING.progress == 10
        assert TTSStatus.SYNTHESIZING.progress == 30
        assert TTSStatus.PROCESSING.progress == 50
        assert TTSStatus.SAVING.progress == 70
        assert TTSStatus.FINALIZING.progress == 90
        assert TTSStatus.COMPLETED.progress == 100


class MockTTS(BaseTTS):
    """用于测试的 Mock TTS 实现"""

    def __init__(self, config: TTSConfig):
        super().__init__(config)
        self.synthesize_calls = []

    def _synthesize(self, segment: TTSDataSeg, output_path: str) -> None:
        self.synthesize_calls.append((segment.text, output_path))
        # 创建虚拟音频文件
        Path(output_path).write_text(f"mock audio: {segment.text}")
        # 更新 segment
        segment.audio_path = output_path
        segment.audio_duration = 1.0
        segment.voice = self.config.voice


class TestBaseTTS:
    """测试 BaseTTS 基类"""

    def test_generate_cache_key(self):
        """测试缓存键生成"""
        config = TTSConfig(
            model="test-model",
            api_key="test-key",
            base_url="https://test.api",
            voice="female",
            speed=1.5,
        )
        tts = MockTTS(config)
        seg1 = TTSDataSeg(text="测试文本")
        seg2 = TTSDataSeg(text="测试文本")
        seg3 = TTSDataSeg(text="不同文本")

        key1 = tts._generate_cache_key_for_segment(seg1)
        key2 = tts._generate_cache_key_for_segment(seg2)
        key3 = tts._generate_cache_key_for_segment(seg3)

        # 相同文本应生成相同的键
        assert key1 == key2
        # 不同文本应生成不同的键
        assert key1 != key3

    def test_generate_filename(self):
        """测试文件名生成"""
        config = TTSConfig(
            model="test-model",
            api_key="test-key",
            base_url="https://test.api",
            response_format="mp3",
        )
        tts = MockTTS(config)
        filename = tts._generate_filename("测试文本", 5)

        assert filename.startswith("tts_0005_")
        assert filename.endswith(".mp3")
        assert len(filename.split("_")[2].split(".")[0]) == 8  # 8位哈希

    def test_synthesize_single(self):
        """测试单条语音合成"""
        config = TTSConfig(
            model="test-model", api_key="test-key", base_url="https://test.api"
        )
        tts = MockTTS(config)

        with tempfile.TemporaryDirectory() as tmpdir:
            tts_data = TTSData.from_texts(["你好"])
            result = tts.synthesize(tts_data, tmpdir)

            assert len(result) == 1
            seg = result.segments[0]
            assert seg.text == "你好"
            assert seg.audio_path
            assert seg.audio_duration == 1.0
            assert Path(seg.audio_path).exists()

    def test_synthesize_batch(self):
        """测试批量合成"""
        config = TTSConfig(
            model="test-model", api_key="test-key", base_url="https://test.api"
        )
        tts = MockTTS(config)
        texts = ["第一句", "第二句", "第三句"]

        with tempfile.TemporaryDirectory() as tmpdir:
            tts_data = TTSData.from_texts(texts)
            result = tts.synthesize(tts_data, tmpdir)

            assert len(result) == 3
            # 验证每个片段
            for i, seg in enumerate(result.segments):
                assert seg.text == texts[i]
                assert seg.audio_path
                assert Path(seg.audio_path).exists()

            # 检查文件是否创建
            files = list(Path(tmpdir).glob("*.mp3"))
            assert len(files) == 3

    def test_batch_with_callback(self):
        """测试批量合成带回调"""
        config = TTSConfig(
            model="test-model", api_key="test-key", base_url="https://test.api"
        )
        tts = MockTTS(config)
        texts = ["文本1", "文本2"]

        callback_calls = []

        def callback(progress: int, message: str):
            callback_calls.append((progress, message))

        with tempfile.TemporaryDirectory() as tmpdir:
            tts_data = TTSData.from_texts(texts)
            tts.synthesize(tts_data, tmpdir, callback=callback)

            # 应该有进度回调
            assert len(callback_calls) > 0
            # 最后一次应该是完成
            assert callback_calls[-1] == (100, "completed")

    def test_cache_parameter(self):
        """测试 use_cache 参数"""
        config_no_cache = TTSConfig(
            model="test-model",
            api_key="test-key",
            base_url="https://test.api",
            use_cache=False,
        )
        config_with_cache = TTSConfig(
            model="test-model",
            api_key="test-key",
            base_url="https://test.api",
            use_cache=True,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            # 测试 use_cache=False
            tts1 = MockTTS(config_no_cache)
            tts_data1 = TTSData.from_texts(["测试1"])
            result1 = tts1.synthesize(tts_data1, tmpdir)
            assert len(result1) == 1
            assert result1.segments[0].text == "测试1"
            assert Path(result1.segments[0].audio_path).exists()

            # 测试 use_cache=True
            tts2 = MockTTS(config_with_cache)
            tts_data2 = TTSData.from_texts(["测试2"])
            result2 = tts2.synthesize(tts_data2, tmpdir)
            assert len(result2) == 1
            assert result2.segments[0].text == "测试2"
            assert Path(result2.segments[0].audio_path).exists()

            # 验证两次都调用了 _synthesize（因为文本不同）
            assert len(tts1.synthesize_calls) == 1
            assert len(tts2.synthesize_calls) == 1


class TestSiliconFlowTTS:
    """测试 SiliconFlowTTS 实现"""

    def test_init_without_api_key(self):
        """测试没有 API key 的初始化"""
        config = TTSConfig(model="test-model", api_key="", base_url="https://test.api")
        with pytest.raises(ValueError, match="API key is required"):
            SiliconFlowTTS(config)

    @patch("app.core.tts.siliconflow.requests.post")
    def test_synthesize_success(self, mock_post):
        """测试成功合成"""
        config = TTSConfig(
            model="test-model",
            api_key="test-key",
            base_url="https://api.siliconflow.cn/v1",
        )
        tts = SiliconFlowTTS(config)

        # 模拟 API 响应
        mock_response = Mock()
        mock_response.content = b"fake audio data"
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test.mp3"
            segment = TTSDataSeg(text="测试文本")
            tts._synthesize(segment, str(output_path))

            # 检查 API 调用
            assert mock_post.called
            call_args = mock_post.call_args
            assert "audio/speech" in call_args[0][0]
            assert call_args[1]["headers"]["Authorization"] == "Bearer test-key"
            assert call_args[1]["json"]["input"] == "测试文本"
            assert call_args[1]["json"]["model"] == "test-model"

            # 检查结果
            assert segment.text == "测试文本"
            assert segment.audio_path == str(output_path)
            assert output_path.exists()
            assert output_path.read_bytes() == b"fake audio data"

    @patch("app.core.tts.siliconflow.requests.post")
    def test_synthesize_with_optional_params(self, mock_post):
        """测试带可选参数的合成"""
        config = TTSConfig(
            model="test-model",
            api_key="test-key",
            base_url="https://api.siliconflow.cn/v1",
            voice="female",
            stream=True,
        )
        tts = SiliconFlowTTS(config)

        mock_response = Mock()
        mock_response.content = b"audio"
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test.mp3"
            segment = TTSDataSeg(text="测试")
            tts._synthesize(segment, str(output_path))

            # 检查可选参数是否传递
            call_json = mock_post.call_args[1]["json"]
            assert call_json["voice"] == "female"
            assert call_json["stream"] is True


class TestOpenAITTS:
    """测试 OpenAITTS 实现"""

    def test_init_without_api_key(self):
        """测试没有 API key 的初始化"""
        config = TTSConfig(model="test-model", api_key="", base_url="https://test.api")
        with pytest.raises(ValueError, match="API key is required"):
            OpenAITTS(config)

    @patch("app.core.tts.openai_tts.OpenAI")
    def test_synthesize_success(self, mock_openai_class):
        """测试成功合成"""
        config = TTSConfig(
            model="tts-1",
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            voice="alloy",
        )

        # 模拟 OpenAI 客户端
        mock_client = Mock()
        mock_response = Mock()
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_response.stream_to_file = Mock()

        mock_client.audio.speech.with_streaming_response.create.return_value = (
            mock_response
        )
        mock_openai_class.return_value = mock_client

        tts = OpenAITTS(config)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test.mp3"
            segment = TTSDataSeg(text="测试文本")
            tts._synthesize(segment, str(output_path))

            # 检查 OpenAI 客户端初始化
            mock_openai_class.assert_called_once_with(
                api_key="test-key",
                base_url="https://api.openai.com/v1",
            )

            # 检查 API 调用
            mock_client.audio.speech.with_streaming_response.create.assert_called_once_with(
                model="tts-1",
                voice="alloy",
                input="测试文本",
                response_format="mp3",
                speed=1.0,
            )

            # 检查流式写入文件
            mock_response.stream_to_file.assert_called_once_with(str(output_path))

            # 检查结果
            assert segment.text == "测试文本"
            assert segment.audio_path == str(output_path)
            assert segment.voice == "alloy"

    @patch("app.core.tts.openai_tts.OpenAI")
    def test_synthesize_with_custom_voice(self, mock_openai_class):
        """测试使用自定义音色"""
        config = TTSConfig(
            model="FunAudioLLM/CosyVoice2-0.5B",
            api_key="test-key",
            base_url="https://api.siliconflow.cn/v1",
            voice="FunAudioLLM/CosyVoice2-0.5B:alex",
            speed=1.2,
        )

        mock_client = Mock()
        mock_response = Mock()
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_response.stream_to_file = Mock()

        mock_client.audio.speech.with_streaming_response.create.return_value = (
            mock_response
        )
        mock_openai_class.return_value = mock_client

        tts = OpenAITTS(config)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test.mp3"
            segment = TTSDataSeg(text="你好")
            tts._synthesize(segment, str(output_path))

            # 检查自定义参数
            call_kwargs = (
                mock_client.audio.speech.with_streaming_response.create.call_args[1]
            )
            assert call_kwargs["model"] == "FunAudioLLM/CosyVoice2-0.5B"
            assert call_kwargs["voice"] == "FunAudioLLM/CosyVoice2-0.5B:alex"
            assert call_kwargs["speed"] == 1.2

    @patch("app.core.tts.openai_tts.OpenAI")
    def test_default_voice(self, mock_openai_class):
        """测试默认音色"""
        config = TTSConfig(
            model="tts-1",
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            voice=None,  # 没有指定音色
        )

        mock_client = Mock()
        mock_response = Mock()
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_response.stream_to_file = Mock()

        mock_client.audio.speech.with_streaming_response.create.return_value = (
            mock_response
        )
        mock_openai_class.return_value = mock_client

        tts = OpenAITTS(config)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test.mp3"
            segment = TTSDataSeg(text="测试")
            tts._synthesize(segment, str(output_path))

            # 应该使用默认音色 "alloy"
            call_kwargs = (
                mock_client.audio.speech.with_streaming_response.create.call_args[1]
            )
            assert call_kwargs["voice"] == "alloy"


# ============================================================================
# OpenAI.fm 测试已禁用 - 外部API不可用
# ============================================================================
'''
class TestOpenAIFmTTS:
    """测试 OpenAI.fm TTS 实现"""

    def test_api_url_constant(self):
        """测试 API URL 常量"""
        assert OpenAIFmTTS.API_URL == "https://www.openai.fm/api/generate"

    def test_available_voices(self):
        """测试获取可用音色列表"""
        voices = OpenAIFmTTS.get_available_voices()
        assert isinstance(voices, list)
        assert len(voices) > 0
        assert "fable" in voices
        assert "alloy" in voices
        assert "echo" in voices

    def test_prompt_templates(self):
        """测试获取提示词模板"""
        templates = OpenAIFmTTS.get_prompt_templates()
        assert isinstance(templates, dict)
        assert "natural" in templates
        assert "professional" in templates
        assert "friendly" in templates

    def test_default_voice(self):
        """测试默认音色"""
        config = TTSConfig(
            model="openai-fm",
            api_key="not-required",
            base_url="https://www.openai.fm/api",
        )
        tts = OpenAIFmTTS(config)
        assert tts.config.voice == "fable"

    def test_custom_voice(self):
        """测试自定义音色"""
        config = TTSConfig(
            model="openai-fm",
            api_key="not-required",
            base_url="https://www.openai.fm/api",
            voice="echo",
        )
        tts = OpenAIFmTTS(config)
        assert tts.config.voice == "echo"

    @patch("app.core.tts.openai_fm.requests.get")
    def test_synthesize_success(self, mock_get):
        """测试语音合成成功"""
        config = TTSConfig(
            model="openai-fm",
            api_key="not-required",
            base_url="https://www.openai.fm/api",
            voice="fable",
        )
        tts = OpenAIFmTTS(config)

        # 模拟 HTTP 响应
        mock_response = Mock()
        mock_response.content = b"fake audio data"
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test.mp3"
            segment = TTSDataSeg(text="你好，世界！")
            tts._synthesize(segment, str(output_path))

            # 验证请求参数
            mock_get.assert_called_once()
            call_args = mock_get.call_args

            # 验证 URL
            assert call_args[0][0] == OpenAIFmTTS.API_URL

            # 验证请求参数
            params = call_args[1]["params"]
            assert params["input"] == "你好，世界！"
            assert params["voice"] == "fable"
            assert "prompt" in params

            # 验证文件生成
            assert output_path.exists()
            assert output_path.read_bytes() == b"fake audio data"

            # 验证返回结果
            assert segment.text == "你好，世界！"
            assert segment.audio_path == str(output_path)
            assert segment.voice == "fable"

    @patch("app.core.tts.openai_fm.requests.get")
    def test_synthesize_with_different_voices(self, mock_get):
        """测试不同音色的合成"""
        voices = ["alloy", "echo", "nova", "shimmer"]

        mock_response = Mock()
        mock_response.content = b"audio data"
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        for voice in voices:
            config = TTSConfig(
                model="openai-fm",
                api_key="not-required",
                base_url="https://www.openai.fm/api",
                voice=voice,
            )
            tts = OpenAIFmTTS(config)

            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = Path(tmpdir) / f"test_{voice}.mp3"
                segment = TTSDataSeg(text="测试")
                tts._synthesize(segment, str(output_path))

                # 验证使用了正确的音色
                params = mock_get.call_args[1]["params"]
                assert params["voice"] == voice
                assert segment.voice == voice

    @patch("app.core.tts.openai_fm.requests.get")
    def test_synthesize_with_long_text(self, mock_get):
        """测试长文本合成"""
        config = TTSConfig(
            model="openai-fm",
            api_key="not-required",
            base_url="https://www.openai.fm/api",
        )
        tts = OpenAIFmTTS(config)

        mock_response = Mock()
        mock_response.content = b"long audio data"
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        long_text = "这是一段很长的测试文本。" * 20

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test_long.mp3"
            segment = TTSDataSeg(text=long_text)
            tts._synthesize(segment, str(output_path))

            # 验证文本传递正确
            params = mock_get.call_args[1]["params"]
            assert params["input"] == long_text
            assert segment.text == long_text

    @patch("app.core.tts.openai_fm.requests.get")
    def test_synthesize_timeout(self, mock_get):
        """测试超时配置"""
        config = TTSConfig(
            model="openai-fm",
            api_key="not-required",
            base_url="https://www.openai.fm/api",
            timeout=30,
        )
        tts = OpenAIFmTTS(config)

        mock_response = Mock()
        mock_response.content = b"audio"
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test.mp3"
            segment = TTSDataSeg(text="测试")
            tts._synthesize(segment, str(output_path))

            # 验证超时参数
            assert mock_get.call_args[1]["timeout"] == 30

    @patch("app.core.tts.openai_fm.requests.get")
    def test_synthesize_api_error(self, mock_get):
        """测试 API 错误处理"""
        config = TTSConfig(
            model="openai-fm",
            api_key="not-required",
            base_url="https://www.openai.fm/api",
        )
        tts = OpenAIFmTTS(config)

        # 模拟 HTTP 错误
        mock_get.side_effect = requests.exceptions.HTTPError("API Error")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test.mp3"
            segment = TTSDataSeg(text="测试")

            # 应该抛出异常
            with pytest.raises(requests.exceptions.HTTPError):
                tts._synthesize(segment, str(output_path))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
'''
