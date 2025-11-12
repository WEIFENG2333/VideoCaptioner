"""Whisper API 连接测试工具"""

from typing import Literal, Optional

import openai

from app.config import ASSETS_PATH
from app.core.llm.client import normalize_base_url

# 测试音频文件路径
TEST_AUDIO_PATH = ASSETS_PATH / "en.mp3"


def check_whisper_connection(
    base_url: str, api_key: str, model: str
) -> tuple[Literal[True], Optional[str]] | tuple[Literal[False], Optional[str]]:
    """
    测试 Whisper API 连接

    使用测试音频文件进行转录测试，并返回转录结果文本。

    参数:
        base_url: API 基础 URL
        api_key: API 密钥
        model: 模型名称

    返回:
        (是否成功, 转录结果文本或错误信息)
    """
    try:
        # 检查测试音频文件是否存在
        if not TEST_AUDIO_PATH.exists():
            return False, f"Test audio file not found: {TEST_AUDIO_PATH}"

        # 创建 OpenAI 客户端
        base_url = normalize_base_url(base_url)
        api_key = api_key.strip()
        client = openai.OpenAI(base_url=base_url, api_key=api_key, timeout=60)

        # 读取音频文件
        with open(TEST_AUDIO_PATH, "rb") as audio_file:
            # 调用 Whisper API 进行转录
            response = client.audio.transcriptions.create(
                model=model,
                file=audio_file,
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"],
                timeout=30,
            )

        # 返回成功结果和转录文本
        if isinstance(response, str):
            raise ValueError(
                "WhisperAPI returned type error, please check your base URL."
            )
        else:
            resp = f"{response.text}"
            return True, resp

    except openai.APIConnectionError:
        return False, "API Connection Error. Please check your network or VPN."
    except openai.RateLimitError as e:
        return False, "Rate Limit Error: " + str(e)
    except openai.AuthenticationError:
        return False, "Authentication Error. Please check your API key."
    except openai.NotFoundError:
        return False, "URL Not Found Error. Please check your Base URL."
    except openai.BadRequestError as e:
        return False, "Bad Request Error: " + str(e)
    except openai.OpenAIError as e:
        return False, "OpenAI Error: " + str(e)
    except FileNotFoundError:
        return False, f"Test audio file not found: {TEST_AUDIO_PATH}"
    except Exception as e:
        return False, str(e)
