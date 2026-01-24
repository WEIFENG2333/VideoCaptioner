"""LLM 连接测试工具"""

from typing import Literal, Optional

import openai

from app.core.llm.client import normalize_base_url


def check_llm_connection(
    base_url: str, api_key: str, model: str
) -> tuple[Literal[True], Optional[str]] | tuple[Literal[False], Optional[str]]:
    """测试 LLM API 连接

    使用指定的API设置与LLM进行对话测试。

    参数:
        base_url: API 基础 URL
        api_key: API 密钥
        model: 模型名称

    返回:
        (是否成功, 错误信息或AI助手的回复)
    """
    try:
        # 创建OpenAI客户端并发送请求到API
        base_url = normalize_base_url(base_url)
        api_key = api_key.strip()
        response = openai.OpenAI(
            base_url=base_url, api_key=api_key, timeout=60
        ).chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": 'Just respond with "Hello"!'},
            ],
            timeout=30,
        )
        return True, response.choices[0].message.content
    except openai.APIConnectionError:
        return False, "API Connection Error. Please check your network or VPN."
    except openai.RateLimitError as e:
        return False, "Rate Limit Error: " + str(e)
    except openai.AuthenticationError:
        return False, "Authentication Error. Please check your API key."
    except openai.NotFoundError:
        return False, "URL Not Found Error. Please check your Base URL."
    except openai.OpenAIError as e:
        return False, "OpenAI Error: " + str(e)
    except Exception as e:
        return False, str(e)


def get_available_models(base_url: str, api_key: str) -> list[str]:
    """获取可用的模型列表

    参数:
        base_url: API 基础 URL
        api_key: API 密钥

    返回:
        模型ID列表，按优先级排序
    """
    try:
        base_url = normalize_base_url(base_url)
        # 创建OpenAI客户端并获取模型列表
        models = openai.OpenAI(
            base_url=base_url, api_key=api_key, timeout=5
        ).models.list()

        # 去除非文本模型
        non_text_models = (
            "tts",
            "transcribe",
            "realtime",
            "embedding",
            "vision",
            "audio",
            "search",
            "text-",
            "image",
            "audio",
            "whisper",
            "gpt-3.5",
            "gpt-4-",
        )
        models = [
            model
            for model in models
            if not any(keyword in model.id.lower() for keyword in non_text_models)
        ]

        # 根据不同模型设置权重进行排序
        def get_model_weight(model_name: str) -> int:
            model_name = model_name.lower()
            if model_name.startswith(("gpt-5", "claude-4", "gemini-2", "gemini-3")):
                return 10
            elif model_name.startswith(("gpt-4")):
                return 5
            elif model_name.startswith(("deepseek", "glm", "qwen", "doubao")):
                return 3
            return 0

        sorted_models = sorted(
            [model.id for model in models], key=lambda x: (-get_model_weight(x), x)
        )
        return sorted_models
    except Exception:
        return []
