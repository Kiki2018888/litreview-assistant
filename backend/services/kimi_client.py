"""Kimi API 客户端.

封装 OpenAI 兼容的 Kimi API 调用，支持：
- 普通 chat 请求与 SSE 流式请求
- 自动重试（指数退避）
- API Key / endpoint 从 settings 表动态读取（多 Provider）
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
    DEFAULT_TEMPERATURE,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    RETRY_BASE_DELAY,
)
from backend.services.api_provider import (
    ResolvedApiConfig,
    load_runtime_config_from_db,
)
from backend.services.db import SessionLocal

logger = logging.getLogger(__name__)


def _ensure_settings_row() -> None:
    """确保 settings 表有默认行（id=1），用于存储配置."""
    db = SessionLocal()
    try:
        from sqlalchemy import text

        from backend.config import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE
        from backend.services.api_provider import (
            DEFAULT_DEEPSEEK_BASE_URL,
            PROVIDER_DEEPSEEK,
            default_model_for_provider,
        )

        row = db.execute(text("SELECT 1 FROM settings WHERE id = 1")).fetchone()
        if row is None:
            db.execute(
                text(
                    "INSERT INTO settings "
                    "(id, api_provider, api_base_url, default_model, temperature, max_tokens, theme) "
                    "VALUES (1, :provider, :base_url, :model, :temp, :tokens, :theme)"
                ),
                {
                    "provider": PROVIDER_DEEPSEEK,
                    "base_url": DEFAULT_DEEPSEEK_BASE_URL,
                    "model": default_model_for_provider(PROVIDER_DEEPSEEK),
                    "temp": DEFAULT_TEMPERATURE,
                    "tokens": DEFAULT_MAX_TOKENS,
                    "theme": "system",
                },
            )
            db.commit()
    finally:
        db.close()


class KimiClient:
    """Kimi API 异步客户端（多 Provider endpoint）."""

    def __init__(self) -> None:
        """初始化客户端，从 settings 表读取 Key 与 endpoint."""
        _ensure_settings_row()
        self._config: ResolvedApiConfig = load_runtime_config_from_db()
        self._client = AsyncOpenAI(
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            timeout=float(REQUEST_TIMEOUT),
            max_retries=0,
        )
        self._model = self._config.model

    async def chat(
        self,
        messages: list[ChatCompletionMessageParam],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """发送非流式 chat 请求，返回完整回复文本."""
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
                if is_retryable_error(exc) and attempt < MAX_RETRIES:
                    delay = retry_after_seconds(exc, RETRY_BASE_DELAY * (2 ** attempt))
                    logger.warning(
                        "Kimi API 请求失败(可重试) (尝试 %d/%d)，%0.1fs 后重试: %s",
                        attempt + 1, MAX_RETRIES + 1, delay, exc,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "Kimi API 请求失败（不可重试或已耗尽重试）: %s", exc
                    )
                    break

        raise RuntimeError(
            f"Kimi API 调用失败（已重试 {MAX_RETRIES} 次或遇不可重试错误）。"
            f"最后错误: {_format_error(last_error)}"
        )

    async def chat_json(
        self,
        messages: list[ChatCompletionMessageParam],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        extra_body: Optional[dict] = None,
    ) -> tuple[str, str | None, dict]:
        """发送非流式 chat 请求（JSON Mode），返回 (content, finish_reason, usage_dict).

        用于 structure extraction 等需要 json_object response_format 的场景。
        """
        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self._client.chat.completions.create(
                    model=model or self._model,
                    messages=messages,
                    temperature=temperature if temperature is not None else DEFAULT_TEMPERATURE,
                    max_tokens=max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS,
                    response_format={"type": "json_object"},
                    extra_body=extra_body or {},
                )
                choice = response.choices[0]
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                }
                return (
                    choice.message.content or "",
                    choice.finish_reason,
                    usage,
                )

            except Exception as exc:
                last_error = exc
                if is_retryable_error(exc) and attempt < MAX_RETRIES:
                    delay = retry_after_seconds(exc, RETRY_BASE_DELAY * (2 ** attempt))
                    logger.warning(
                        "Kimi API JSON 请求失败(可重试) (尝试 %d/%d)，%0.1fs 后重试: %s",
                        attempt + 1, MAX_RETRIES + 1, delay, exc,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "Kimi API JSON 请求失败（不可重试或已耗尽重试）: %s", exc
                    )
                    break

        raise RuntimeError(
            f"Kimi API JSON 调用失败（已重试 {MAX_RETRIES} 次或遇不可重试错误）。"
            f"最后错误: {_format_error(last_error)}"
        )

    async def chat_stream(
        self,
        messages: list[ChatCompletionMessageParam],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """发送 SSE 流式 chat 请求，逐块 yield 文本."""
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

                return

            except Exception as exc:
                last_error = exc
                if is_retryable_error(exc) and attempt < MAX_RETRIES:
                    delay = retry_after_seconds(exc, RETRY_BASE_DELAY * (2 ** attempt))
                    logger.warning(
                        "Kimi SSE 流式请求失败(可重试) (尝试 %d/%d)，%0.1fs 后重试: %s",
                        attempt + 1, MAX_RETRIES + 1, delay, exc,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "Kimi SSE 流式请求失败（不可重试或已耗尽重试）: %s", exc
                    )
                    break

        raise RuntimeError(
            f"Kimi SSE 流式调用失败（已重试 {MAX_RETRIES} 次或遇不可重试错误）。"
            f"最后错误: {_format_error(last_error)}"
        )


_MAX_BACKOFF_SECONDS = 30.0


def is_retryable_error(exc: Exception) -> bool:
    """区分"可重试错误"（限流/超时/连接/5xx）与"真失败"（认证/请求格式错误）。

    - 可重试：RateLimit(429)、Timeout、Connection、5xx。
    - 不可重试：400/401/403/404/422。
    - 未知异常：保守按可重试处理。
    """
    import openai

    if isinstance(exc, (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError)):
        return True
    status = getattr(exc, "status_code", None)
    if status is None:
        resp = getattr(exc, "response", None)
        status = getattr(resp, "status_code", None)
    if status is not None:
        if status == 429 or status >= 500:
            return True
        if status in (400, 401, 403, 404, 422):
            return False
    return True


def retry_after_seconds(exc: Exception, fallback: float) -> float:
    """优先读取响应头 Retry-After（限流场景），否则用退避 fallback；上限 30s。"""
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            ra = resp.headers.get("retry-after")
        except Exception:
            ra = None
        if ra:
            try:
                return min(float(ra), _MAX_BACKOFF_SECONDS)
            except (TypeError, ValueError):
                pass
    return min(fallback, _MAX_BACKOFF_SECONDS)


def _format_error(exc: Optional[Exception]) -> str:
    """将异常格式化为用户友好的错误信息."""
    if exc is None:
        return "未知错误"

    msg = str(exc)

    if "401" in msg or "Unauthorized" in msg or "Incorrect API key" in msg:
        return "API Key 无效或 endpoint 不匹配，请检查设置页面的 Provider 与 API Key 类型。"
    if "403" in msg and "Coding" in msg:
        return "Kimi For Coding Key 不支持当前应用客户端，请改用 Moonshot 平台 API Key。"
    if "429" in msg or "Rate limit" in msg:
        return "API 请求过于频繁，请稍后重试。"
    if "503" in msg or "Service Unavailable" in msg:
        return "Kimi 服务暂时不可用，请稍后重试。"
    if "timeout" in msg.lower() or "timed out" in msg.lower():
        return f"请求超时（{REQUEST_TIMEOUT} 秒），请检查网络连接或增大超时设置。"

    return f"API 调用异常: {msg}"


_client_singleton: Optional[KimiClient] = None


def reset_kimi_client() -> None:
    """设置变更后重置客户端单例."""
    global _client_singleton
    _client_singleton = None


def _get_client() -> KimiClient:
    """获取客户端单例（懒初始化）."""
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = KimiClient()
    return _client_singleton


def get_model_name() -> str:
    """获取当前配置的模型名称（用于耗时预估等）."""
    return _get_client()._model


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
    "chat_json",
    "chat_stream",
    "get_model_name",
    "reset_kimi_client",
]
