"""Kimi API 客户端.

封装 OpenAI 兼容的 Kimi API 调用，支持：
- 普通 chat 请求与 SSE 流式请求
- 自动重试（指数退避）
- API Key 从 settings 表读取，不硬编码
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Optional

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from backend.config import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    KIMI_BASE_URL,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    RETRY_BASE_DELAY,
)
from backend.services.db import SessionLocal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# API Key 获取
# ---------------------------------------------------------------------------


def _get_api_key() -> str:
    """从 settings 表读取 API Key（解密后的明文）.

    委托 M6 settings 模块的 Fernet 解密逻辑读取并解密 API Key。
    如果 settings 表中没有 API Key 或解密失败，抛出友好提示。

    Returns:
        解密后的 API Key 字符串。

    Raises:
        ValueError: API Key 未配置（提示用户前往设置页配置）。
    """
    try:
        from backend.services.secrets import _get_decrypted_api_key

        plain = _get_decrypted_api_key()
        if plain:
            return plain
        raise ValueError(
            "API Key 未配置。请前往「设置」页面输入 Kimi API Key，"
            "API Key 将加密存储在本地数据库中。"
        )
    except ImportError as exc:
        raise RuntimeError(
            f"无法加载设置模块，请确认应用已正确初始化: {exc}"
        ) from exc


def _ensure_settings_row() -> None:
    """确保 settings 表有默认行（id=1），用于存储配置."""
    db = SessionLocal()
    try:
        from sqlalchemy import text
        row = db.execute(text("SELECT 1 FROM settings WHERE id = 1")).fetchone()
        if row is None:
            db.execute(text(
                "INSERT INTO settings (id, default_model, temperature, max_tokens, theme) "
                "VALUES (1, :model, :temp, :tokens, :theme)"
            ), {
                "model": DEFAULT_MODEL,
                "temp": DEFAULT_TEMPERATURE,
                "tokens": DEFAULT_MAX_TOKENS,
                "theme": "system",
            })
            db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# KimiClient
# ---------------------------------------------------------------------------


class KimiClient:
    """Kimi API 异步客户端.

    用法::

        client = KimiClient()
        # 普通请求
        reply = await client.chat([{"role": "user", "content": "Hello"}])
        # 流式请求
        async for chunk in client.chat_stream([{"role": "user", "content": "Hello"}]):
            print(chunk, end="")
    """

    def __init__(self) -> None:
        """初始化客户端，从 settings 表读取 API Key."""
        _ensure_settings_row()

        api_key = _get_api_key()

        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=KIMI_BASE_URL,
            timeout=float(REQUEST_TIMEOUT),
            max_retries=0,  # 我们自己控制重试
        )
        self._model = DEFAULT_MODEL

    # ------------------------------------------------------------------
    # 普通请求
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[ChatCompletionMessageParam],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """发送非流式 chat 请求，返回完整回复文本.

        Args:
            messages: OpenAI 格式的消息列表。
            model: 模型名，默认使用 config.DEFAULT_MODEL。
            temperature: 采样温度，默认使用 config.DEFAULT_TEMPERATURE。
            max_tokens: 最大输出 token，默认使用 config.DEFAULT_MAX_TOKENS。

        Returns:
            AI 回复的完整文本。

        Raises:
            RuntimeError: 所有重试均失败。
        """
        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self._client.chat.completions.create(
                    model=model or self._model,
                    messages=messages,
                    temperature=temperature if temperature is not None else DEFAULT_TEMPERATURE,
                    max_tokens=max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS,
                )
                return response.choices[0].message.content or ""

            except Exception as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "Kimi API 请求失败 (尝试 %d/%d)，%0.1fs 后重试: %s",
                        attempt + 1, MAX_RETRIES + 1, delay, exc,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "Kimi API 请求失败，已用尽全部 %d 次重试", MAX_RETRIES + 1
                    )

        raise RuntimeError(
            f"Kimi API 调用失败，已重试 {MAX_RETRIES} 次。"
            f"最后错误: {_format_error(last_error)}"
        )

    # ------------------------------------------------------------------
    # SSE 流式请求
    # ------------------------------------------------------------------

    async def chat_stream(
        self,
        messages: list[ChatCompletionMessageParam],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """发送 SSE 流式 chat 请求，逐块 yield 文本.

        Args:
            messages: OpenAI 格式的消息列表。
            model: 模型名，默认使用 config.DEFAULT_MODEL。
            temperature: 采样温度。
            max_tokens: 最大输出 token。

        Yields:
            str: 每块增量文本内容。

        Raises:
            RuntimeError: 所有重试均失败。
        """
        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                stream = await self._client.chat.completions.create(
                    model=model or self._model,
                    messages=messages,
                    temperature=temperature if temperature is not None else DEFAULT_TEMPERATURE,
                    max_tokens=max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS,
                    stream=True,
                )

                async for chunk in stream:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield delta.content

                return  # 流式请求成功，退出重试循环

            except Exception as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "Kimi SSE 流式请求失败 (尝试 %d/%d)，%0.1fs 后重试: %s",
                        attempt + 1, MAX_RETRIES + 1, delay, exc,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "Kimi SSE 流式请求失败，已用尽全部 %d 次重试", MAX_RETRIES + 1
                    )

        raise RuntimeError(
            f"Kimi SSE 流式调用失败，已重试 {MAX_RETRIES} 次。"
            f"最后错误: {_format_error(last_error)}"
        )


# ---------------------------------------------------------------------------
# 错误格式化
# ---------------------------------------------------------------------------


def _format_error(exc: Optional[Exception]) -> str:
    """将异常格式化为用户友好的错误信息."""
    if exc is None:
        return "未知错误"

    msg = str(exc)

    # OpenAI API 返回的标准错误格式
    if "401" in msg or "Unauthorized" in msg or "Incorrect API key" in msg:
        return "API Key 无效或已过期，请检查设置页面的 API Key 是否正确。"
    if "429" in msg or "Rate limit" in msg:
        return "API 请求过于频繁，请稍后重试。"
    if "503" in msg or "Service Unavailable" in msg:
        return "Kimi 服务暂时不可用，请稍后重试。"
    if "timeout" in msg.lower() or "timed out" in msg.lower():
        return f"请求超时（{REQUEST_TIMEOUT} 秒），请检查网络连接或增大超时设置。"

    return f"API 调用异常: {msg}"


# ---------------------------------------------------------------------------
# 模块级便捷函数（兼容快速调用）
# ---------------------------------------------------------------------------


_client_singleton: Optional[KimiClient] = None


def _get_client() -> KimiClient:
    """获取客户端单例（懒初始化）."""
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = KimiClient()
    return _client_singleton


async def chat(
    messages: list[ChatCompletionMessageParam],
    **kwargs: object,
) -> str:
    """便捷函数：非流式 chat 请求."""
    return await _get_client().chat(messages, **kwargs)  # type: ignore[arg-type]


async def chat_stream(
    messages: list[ChatCompletionMessageParam],
    **kwargs: object,
) -> AsyncGenerator[str, None]:
    """便捷函数：SSE 流式 chat 请求."""
    async for chunk in _get_client().chat_stream(messages, **kwargs):  # type: ignore[arg-type]
        yield chunk


__all__ = [
    "KimiClient",
    "chat",
    "chat_stream",
]
