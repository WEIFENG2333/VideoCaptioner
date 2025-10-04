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
    TTSBatchResult,
    TTSConfig,
    TTSData,
    TTSStatus,
)


class TestTTSConfig:
    """测试 TTSConfig 配置类"""

    def test_default_config(self):
        """测试默认配置"""
        config = TTSConfig()
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
            voice="female",
            speed=1.5,
            cache_ttl=86400 * 7,  # 7天
        )
        assert config.model == "custom-model"
        assert config.api_key == "test-key"
        assert config.voice == "female"
        assert config.speed == 1.5
        assert config.cache_ttl == 86400 * 7


class TestTTSData:
    """测试 TTSData 数据类"""

    def test_create_tts_data(self):
        """测试创建 TTSData"""
        data = TTSData(
            text="你好世界",
            audio_path="/path/to/audio.mp3",
            start_time=0.0,
            end_time=2.5,
            audio_duration=2.5,
            model="test-model",
            voice="female",
        )
        assert data.text == "你好世界"
        assert data.audio_path == "/path/to/audio.mp3"
        assert data.start_time == 0.0
        assert data.end_time == 2.5
        assert data.audio_duration == 2.5
        assert data.model == "test-model"
        assert data.voice == "female"

    def test_to_dict(self):
        """测试转换为字典"""
        data = TTSData(
            text="测试",
            audio_path="/test.mp3",
            start_time=0.0,
            end_time=1.5,
            audio_duration=1.5,
        )
        result = data.to_dict()
        assert result == {
            "text": "测试",
            "audio_path": "/test.mp3",
            "start_time": 0.0,
            "end_time": 1.5,
            "audio_duration": 1.5,
            "model": "",
            "voice": None,
        }


class TestTTSBatchResult:
    """测试 TTSBatchResult 批量结果类"""

    def test_initial_state(self):
        """测试初始状态"""
        result = TTSBatchResult()
        assert len(result.items) == 0

    def test_add_items(self):
        """测试添加项目"""
        result = TTSBatchResult()
        data1 = TTSData(text="测试1", audio_path="/test1.mp3")
        data2 = TTSData(text="测试2", audio_path="/test2.mp3")

        result.items.append(data1)
        result.items.append(data2)

        assert len(result.items) == 2
        assert result.items[0] == data1
        assert result.items[1] == data2

    def test_to_dict(self):
        """测试转换为字典"""
        result = TTSBatchResult()
        result.items.append(TTSData(text="成功", audio_path="/success.mp3"))
        result.items.append(TTSData(text="失败", audio_path=""))

        result_dict = result.to_dict()
        assert "items" in result_dict
        assert len(result_dict["items"]) == 2


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

    def _synthesize(self, text: str, output_path: str) -> TTSData:
        self.synthesize_calls.append((text, output_path))
        # 创建虚拟音频文件
        Path(output_path).write_text(f"mock audio: {text}")
        return TTSData(
            text=text,
            audio_path=output_path,
            audio_duration=1.0,
            model=self.config.model,
            voice=self.config.voice,
        )


class TestBaseTTS:
    """测试 BaseTTS 基类"""

    def test_generate_cache_key(self):
        """测试缓存键生成"""
        config = TTSConfig(model="test-model", voice="female", speed=1.5)
        tts = MockTTS(config)
        key1 = tts._generate_cache_key("测试文本")
        key2 = tts._generate_cache_key("测试文本")
        key3 = tts._generate_cache_key("不同文本")

        # 相同文本应生成相同的键
        assert key1 == key2
        # 不同文本应生成不同的键
        assert key1 != key3

    def test_generate_filename(self):
        """测试文件名生成"""
        config = TTSConfig(response_format="mp3")
        tts = MockTTS(config)
        filename = tts._generate_filename("测试文本", 5)

        assert filename.startswith("tts_0005_")
        assert filename.endswith(".mp3")
        assert len(filename.split("_")[2].split(".")[0]) == 8  # 8位哈希

    def test_synthesize_single(self):
        """测试单条语音合成"""
        config = TTSConfig()
        tts = MockTTS(config)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test.mp3"
            result = tts.synthesize("你好", str(output_path))

            assert result.text == "你好"
            assert result.audio_path == str(output_path)
            assert result.audio_duration == 1.0
            assert output_path.exists()

    def test_synthesize_batch(self):
        """测试批量合成"""
        config = TTSConfig()
        tts = MockTTS(config)
        texts = ["第一句", "第二句", "第三句"]

        with tempfile.TemporaryDirectory() as tmpdir:
            result = tts.synthesize_batch(texts, tmpdir)

            assert len(result.items) == 3
            # 验证成功数量
            success_count = sum(1 for item in result.items if item.audio_path)
            assert success_count == 3

            # 检查文件是否创建
            files = list(Path(tmpdir).glob("*.mp3"))
            assert len(files) == 3

    def test_batch_with_callback(self):
        """测试批量合成带回调"""
        config = TTSConfig()
        tts = MockTTS(config)
        texts = ["文本1", "文本2"]

        callback_calls = []

        def callback(progress: int, message: str):
            callback_calls.append((progress, message))

        with tempfile.TemporaryDirectory() as tmpdir:
            tts.synthesize_batch(texts, tmpdir, callback=callback)

            # 应该有进度回调
            assert len(callback_calls) > 0
            # 最后一次应该是完成
            assert callback_calls[-1] == (100, "completed")

    def test_cache_parameter(self):
        """测试 use_cache 参数"""
        config = TTSConfig()
        tts = MockTTS(config)

        with tempfile.TemporaryDirectory() as tmpdir:
            # 测试 use_cache=False（默认）
            output1 = Path(tmpdir) / "test1.mp3"
            result1 = tts.synthesize("测试1", str(output1), use_cache=False)
            assert result1.text == "测试1"
            assert output1.exists()

            # 测试 use_cache=True
            output2 = Path(tmpdir) / "test2.mp3"
            result2 = tts.synthesize("测试2", str(output2), use_cache=True)
            assert result2.text == "测试2"
            assert output2.exists()

            # 验证两次都调用了 _synthesize（因为文本不同）
            assert len(tts.synthesize_calls) == 2


class TestSiliconFlowTTS:
    """测试 SiliconFlowTTS 实现"""

    def test_init_without_api_key(self):
        """测试没有 API key 的初始化"""
        config = TTSConfig(api_key="")
        with pytest.raises(ValueError, match="API key is required"):
            SiliconFlowTTS(config)

    @patch("app.core.tts.siliconflow.requests.post")
    def test_synthesize_success(self, mock_post):
        """测试成功合成"""
        config = TTSConfig(
            api_key="test-key",
            model="test-model",
        )
        tts = SiliconFlowTTS(config)

        # 模拟 API 响应
        mock_response = Mock()
        mock_response.content = b"fake audio data"
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test.mp3"
            result = tts._synthesize("测试文本", str(output_path))

            # 检查 API 调用
            assert mock_post.called
            call_args = mock_post.call_args
            assert "audio/speech" in call_args[0][0]
            assert call_args[1]["headers"]["Authorization"] == "Bearer test-key"
            assert call_args[1]["json"]["input"] == "测试文本"
            assert call_args[1]["json"]["model"] == "test-model"

            # 检查结果
            assert result.text == "测试文本"
            assert result.audio_path == str(output_path)
            assert output_path.exists()
            assert output_path.read_bytes() == b"fake audio data"

    @patch("app.core.tts.siliconflow.requests.post")
    def test_synthesize_with_optional_params(self, mock_post):
        """测试带可选参数的合成"""
        config = TTSConfig(
            api_key="test-key",
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
            tts._synthesize("测试", str(output_path))

            # 检查可选参数是否传递
            call_json = mock_post.call_args[1]["json"]
            assert call_json["voice"] == "female"
            assert call_json["stream"] is True


class TestOpenAITTS:
    """测试 OpenAITTS 实现"""

    def test_init_without_api_key(self):
        """测试没有 API key 的初始化"""
        config = TTSConfig(api_key="")
        with pytest.raises(ValueError, match="API key is required"):
            OpenAITTS(config)

    @patch("app.core.tts.openai_tts.OpenAI")
    def test_synthesize_success(self, mock_openai_class):
        """测试成功合成"""
        config = TTSConfig(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="tts-1",
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
            result = tts._synthesize("测试文本", str(output_path))

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
            assert result.text == "测试文本"
            assert result.audio_path == str(output_path)
            assert result.model == "tts-1"
            assert result.voice == "alloy"

    @patch("app.core.tts.openai_tts.OpenAI")
    def test_synthesize_with_custom_voice(self, mock_openai_class):
        """测试使用自定义音色"""
        config = TTSConfig(
            api_key="test-key",
            base_url="https://api.siliconflow.cn/v1",
            model="FunAudioLLM/CosyVoice2-0.5B",
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
            tts._synthesize("你好", str(output_path))

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
            api_key="test-key",
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
            tts._synthesize("测试", str(output_path))

            # 应该使用默认音色 "alloy"
            call_kwargs = (
                mock_client.audio.speech.with_streaming_response.create.call_args[1]
            )
            assert call_kwargs["voice"] == "alloy"


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
        config = TTSConfig()
        tts = OpenAIFmTTS(config)
        assert tts.config.voice == "fable"

    def test_custom_voice(self):
        """测试自定义音色"""
        config = TTSConfig(
            voice="echo",
        )
        tts = OpenAIFmTTS(config)
        assert tts.config.voice == "echo"

    @patch("app.core.tts.openai_fm.requests.get")
    def test_synthesize_success(self, mock_get):
        """测试语音合成成功"""
        config = TTSConfig(
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
            result = tts._synthesize("你好，世界！", str(output_path))

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
            assert result.text == "你好，世界！"
            assert result.audio_path == str(output_path)
            assert result.model == "openai-fm"
            assert result.voice == "fable"

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
                voice=voice,
            )
            tts = OpenAIFmTTS(config)

            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = Path(tmpdir) / f"test_{voice}.mp3"
                result = tts._synthesize("测试", str(output_path))

                # 验证使用了正确的音色
                params = mock_get.call_args[1]["params"]
                assert params["voice"] == voice
                assert result.voice == voice

    @patch("app.core.tts.openai_fm.requests.get")
    def test_synthesize_with_long_text(self, mock_get):
        """测试长文本合成"""
        config = TTSConfig()
        tts = OpenAIFmTTS(config)

        mock_response = Mock()
        mock_response.content = b"long audio data"
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        long_text = "这是一段很长的测试文本。" * 20

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test_long.mp3"
            result = tts._synthesize(long_text, str(output_path))

            # 验证文本传递正确
            params = mock_get.call_args[1]["params"]
            assert params["input"] == long_text
            assert result.text == long_text

    @patch("app.core.tts.openai_fm.requests.get")
    def test_synthesize_timeout(self, mock_get):
        """测试超时配置"""
        config = TTSConfig(
            timeout=30,
        )
        tts = OpenAIFmTTS(config)

        mock_response = Mock()
        mock_response.content = b"audio"
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test.mp3"
            tts._synthesize("测试", str(output_path))

            # 验证超时参数
            assert mock_get.call_args[1]["timeout"] == 30

    @patch("app.core.tts.openai_fm.requests.get")
    def test_synthesize_api_error(self, mock_get):
        """测试 API 错误处理"""
        config = TTSConfig()
        tts = OpenAIFmTTS(config)

        # 模拟 HTTP 错误
        mock_get.side_effect = requests.exceptions.HTTPError("API Error")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test.mp3"

            # 应该抛出异常
            with pytest.raises(requests.exceptions.HTTPError):
                tts._synthesize("测试", str(output_path))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
