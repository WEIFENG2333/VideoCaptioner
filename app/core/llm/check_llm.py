"""LLM 连接测试工具"""

from typing import Literal, Optional

import openai

from app.core.llm.client import normalize_base_url


def is_insufficient_quota_error(error: openai.OpenAIError) -> bool:
    """Check whether an OpenAI error indicates insufficient balance/quota."""
    message = str(error).lower()
    return (
        "insufficient_user_quota" in message
        or ("insufficient" in message and "quota" in message)
        or "balance is insufficient" in message
    )


def format_llm_error(error: openai.OpenAIError) -> str:
    """Format OpenAI-compatible errors into user-friendly messages."""
    message = str(error)
    return "LLM Error: " + message


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
        if is_insufficient_quota_error(e):
            return True, "已忽略余额/额度提示，可继续使用该接口。"
        return False, format_llm_error(e)
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
            "image",
            "audio",
            "whisper",
        )
        models = [
            model
            for model in models
            if not any(keyword in model.id.lower() for keyword in non_text_models)
        ]

        # 根据不同模型设置权重进行排序
        def get_model_weight(model_name: str) -> int:
            model_name = model_name.lower()
            if model_name.startswith(("gpt-5", "claude-4", "gemini-2")):
                return 10
            elif model_name.startswith(("gpt-4")):
                return 5
            elif model_name.startswith(("deepseek", "glm", "qwen")):
                return 3
            return 0

        sorted_models = sorted(
            [model.id for model in models], key=lambda x: (-get_model_weight(x), x)
        )
        return sorted_models
    except Exception:
        return []
