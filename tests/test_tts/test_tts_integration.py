"""TTS 集成测试 - 真实 API 调用

运行前需要设置环境变量（在 .env 文件中）:
    OPENAI_TTS_BASE_URL=https://api.siliconflow.cn/v1
    OPENAI_TTS_API_KEY=your-api-key-here
    OPENAI_TTS_MODEL=FunAudioLLM/CosyVoice2-0.5B
    OPENAI_TTS_VOICE=FunAudioLLM/CosyVoice2-0.5B:alex

    OPENAI_API_BASE_URL=https://api.openai.com/v1
    OPENAI_API_KEY=your-api-key-here
    OPENAI_TTS_MODEL_NAME=tts-1

运行方式:
    pytest tests/test_tts/test_tts_integration.py -v
    pytest tests/test_tts/test_tts_integration.py -v -k "test_siliconflow_single"
"""

import os
import tempfile
from pathlib import Path

import pytest
from dotenv import load_dotenv

from app.core.tts import OpenAIFmTTS, OpenAITTS, SiliconFlowTTS, TTSConfig, TTSData

# 加载环境变量
load_dotenv(Path(__file__).parent.parent / ".env")

# SiliconFlow TTS 环境变量配置
SILICONFLOW_BASE_URL = os.getenv("OPENAI_TTS_BASE_URL", "https://api.siliconflow.cn/v1")
SILICONFLOW_API_KEY = os.getenv("OPENAI_TTS_API_KEY", "")
SILICONFLOW_MODEL = os.getenv("OPENAI_TTS_MODEL", "FunAudioLLM/CosyVoice2-0.5B")
SILICONFLOW_VOICE = os.getenv("OPENAI_TTS_VOICE", "FunAudioLLM/CosyVoice2-0.5B:alex")

# SiliconFlow TTS 跳过标记
skip_siliconflow = pytest.mark.skipif(
    not SILICONFLOW_BASE_URL
    or not SILICONFLOW_API_KEY
    or not SILICONFLOW_MODEL
    or not SILICONFLOW_VOICE,
    reason="SiliconFlow 未启用或缺少 API Key (设置 OPENAI_TTS_BASE_URL 和 OPENAI_TTS_API_KEY)",
)


@pytest.fixture
def siliconflow_config():
    """创建 SiliconFlow TTS 配置"""
    return TTSConfig(
        base_url=SILICONFLOW_BASE_URL,
        api_key=SILICONFLOW_API_KEY,
        model=SILICONFLOW_MODEL,
        voice=SILICONFLOW_VOICE,
        timeout=60,
    )


# OpenAI TTS 环境变量配置
OPENAI_BASE_URL = os.getenv("OPENAI_TTS_BASE_URL", "https://api.openai.com/v1")
OPENAI_API_KEY = os.getenv("OPENAI_TTS_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_TTS_MODEL", "tts-1")
OPENAI_VOICE = os.getenv("OPENAI_TTS_VOICE", "alloy")

# OpenAI TTS 跳过标记
skip_openai = pytest.mark.skipif(
    not OPENAI_BASE_URL or not OPENAI_API_KEY or not OPENAI_MODEL or not OPENAI_VOICE,
    reason="OpenAI 未启用或缺少 API Key (设置 OPENAI_API_BASE_URL 和 OPENAI_API_KEY)",
)


@pytest.fixture
def openai_config():
    """创建 OpenAI TTS 配置"""
    return TTSConfig(
        base_url=OPENAI_BASE_URL,
        api_key=OPENAI_API_KEY,
        model=OPENAI_MODEL,
        voice=OPENAI_VOICE,
        timeout=60,
    )


@skip_siliconflow
class TestSiliconFlowIntegration:
    """SiliconFlow TTS 真实 API 集成测试"""

    def test_siliconflow_single_synthesis(self, siliconflow_config):
        """测试 SiliconFlow 单条语音合成 - 真实 API 调用"""
        tts = SiliconFlowTTS(siliconflow_config)

        with tempfile.TemporaryDirectory() as tmpdir:
            tts_data = TTSData.from_texts(["你好，欢迎使用 SiliconFlow TTS 服务。"])
            result = tts.synthesize(tts_data, tmpdir)

            # 验证返回数据
            assert len(result) == 1
            seg = result.segments[0]
            assert seg.text == "你好，欢迎使用 SiliconFlow TTS 服务。"
            assert seg.audio_path
            assert Path(seg.audio_path).exists(), "音频文件未生成"
            assert Path(seg.audio_path).stat().st_size > 0, "音频文件为空"

    def test_siliconflow_batch_synthesis(self, siliconflow_config):
        """测试 SiliconFlow 批量语音合成"""
        tts = SiliconFlowTTS(siliconflow_config)

        texts = [
            "第一段文本",
            "第二段文本",
            "第三段文本",
        ]

        callback_calls = []

        def callback(progress: int, message: str):
            callback_calls.append((progress, message))

        with tempfile.TemporaryDirectory() as tmpdir:
            tts_data = TTSData.from_texts(texts)
            result = tts.synthesize(tts_data, tmpdir, callback=callback)

            # 验证批量结果
            assert len(result) == 3

            # 验证文件生成
            files = list(Path(tmpdir).glob("*.mp3"))
            assert len(files) == 3, f"应生成3个音频文件，实际生成{len(files)}个"

            # 验证每个文件都不为空
            for file in files:
                assert file.stat().st_size > 0, f"文件 {file.name} 为空"

            # 应该有进度回调
            assert len(callback_calls) > 0, "没有收到进度回调"

            # 最后一次应该是完成（100%）
            assert callback_calls[-1][0] == 100, "最后进度应为100%"


@skip_openai
class TestOpenAITTSIntegration:
    """OpenAI TTS 真实 API 集成测试"""

    def test_openai_single_synthesis(self, openai_config):
        """测试 OpenAI TTS 单条语音合成 - 真实 API 调用"""
        tts = OpenAITTS(openai_config)

        with tempfile.TemporaryDirectory() as tmpdir:
            tts_data = TTSData.from_texts(["你好，欢迎使用 OpenAI TTS 服务。"])
            result = tts.synthesize(tts_data, tmpdir)

            # 验证返回数据
            assert len(result) == 1
            seg = result.segments[0]
            assert seg.text == "你好，欢迎使用 OpenAI TTS 服务。"
            assert seg.audio_path
            assert Path(seg.audio_path).exists(), "音频文件未生成"
            assert Path(seg.audio_path).stat().st_size > 0, "音频文件为空"

    def test_openai_batch_synthesis(self, openai_config):
        """测试 OpenAI TTS 批量语音合成"""
        tts = OpenAITTS(openai_config)

        texts = [
            "第一段文本",
            "第二段文本",
            "第三段文本",
        ]

        callback_calls = []

        def callback(progress: int, message: str):
            callback_calls.append((progress, message))

        with tempfile.TemporaryDirectory() as tmpdir:
            tts_data = TTSData.from_texts(texts)
            result = tts.synthesize(tts_data, tmpdir, callback=callback)

            # 验证批量结果
            assert len(result) == 3

            # 验证文件生成
            files = list(Path(tmpdir).glob("*.mp3"))
            assert len(files) == 3, f"应生成3个音频文件，实际生成{len(files)}个"

            # 验证每个文件都不为空
            for file in files:
                assert file.stat().st_size > 0, f"文件 {file.name} 为空"

            # 应该有进度回调
            assert len(callback_calls) > 0, "没有收到进度回调"

            # 最后一次应该是完成（100%）
            assert callback_calls[-1][0] == 100, "最后进度应为100%"


# ============================================================================
# OpenAI.fm 集成测试已禁用 - 外部API不可用
# ============================================================================
'''
class TestOpenAIFmIntegration:
    """OpenAI.fm TTS 真实 API 集成测试（免费服务）"""

    def test_openai_fm_single_synthesis(self):
        """测试 OpenAI.fm 单条语音合成 - 真实 API 调用"""
        config = TTSConfig(
            model="openai-fm",
            api_key="not-required",
            base_url="https://www.openai.fm/api",
            voice="fable",
        )
        tts = OpenAIFmTTS(config)

        with tempfile.TemporaryDirectory() as tmpdir:
            tts_data = TTSData.from_texts(["你好，欢迎使用 OpenAI.fm TTS 服务。"])
            result = tts.synthesize(tts_data, tmpdir)

            # 验证返回数据
            assert len(result) == 1
            seg = result.segments[0]
            assert seg.text == "你好，欢迎使用 OpenAI.fm TTS 服务。"
            assert seg.audio_path
            assert Path(seg.audio_path).exists(), "音频文件未生成"
            assert Path(seg.audio_path).stat().st_size > 0, "音频文件为空"

    def test_openai_fm_batch_synthesis(self):
        """测试 OpenAI.fm 批量语音合成"""
        config = TTSConfig(
            model="openai-fm",
            api_key="not-required",
            base_url="https://www.openai.fm/api",
            voice="fable",
        )
        tts = OpenAIFmTTS(config)

        texts = [
            "第一段文本",
            "第二段文本",
            "第三段文本",
        ]

        callback_calls = []

        def callback(progress: int, message: str):
            callback_calls.append((progress, message))

        with tempfile.TemporaryDirectory() as tmpdir:
            tts_data = TTSData.from_texts(texts)
            result = tts.synthesize(tts_data, tmpdir, callback=callback)

            # 验证批量结果
            assert len(result) == 3

            # 验证文件生成
            files = list(Path(tmpdir).glob("*.mp3"))
            assert len(files) == 3, f"应生成3个音频文件，实际生成{len(files)}个"

            # 验证每个文件都不为空
            for file in files:
                assert file.stat().st_size > 0, f"文件 {file.name} 为空"

            # 应该有进度回调
            assert len(callback_calls) > 0, "没有收到进度回调"

            # 最后一次应该是完成（100%）
            assert callback_calls[-1][0] == 100, "最后进度应为100%"


'''
if __name__ == "__main__":
    # 运行集成测试
    pytest.main([__file__, "-v", "-s"])
