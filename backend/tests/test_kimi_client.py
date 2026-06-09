"""KimiClient 单元测试 —— mock AsyncOpenAI 调用与重试逻辑."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from backend.services.kimi_client import _format_error
from backend.tests.helpers import (
    AsyncStreamIterator,
    make_chat_completion,
    make_mock_openai_client,
    make_stream_chunk,
)


def _make_mock_openai(chat_return=None):
    """构造一个完整的 Mock AsyncOpenAI 实例（非流式）."""
    return make_mock_openai_client(chat_return=chat_return)


def _make_ok_response(content="Mock AI response"):
    """构造成功的 chat completion 响应."""
    return make_chat_completion(content)


def _make_stream_chunks(texts: list[str]):
    """构造流式响应 chunks."""
    return [make_stream_chunk(text, finish=(i == len(texts) - 1)) for i, text in enumerate(texts)]


class TestKimiClientChat:
    """非流式 chat() 测试."""

    def test_chat_success(self):
        mock_openai = _make_mock_openai(chat_return=_make_ok_response("Hello from Kimi"))
        with patch("backend.services.kimi_client._get_api_key", return_value="sk-test"):
            with patch("backend.services.kimi_client._ensure_settings_row", return_value=None):
                with patch("backend.services.kimi_client.AsyncOpenAI", return_value=mock_openai):
                    from backend.services.kimi_client import KimiClient

                    client = KimiClient()
                    reply = asyncio.run(client.chat([{"role": "user", "content": "Hello"}]))
                    assert "Hello from Kimi" in reply

    def test_chat_with_system_message(self):
        mock_openai = _make_mock_openai(chat_return=_make_ok_response("System-aware response"))
        with patch("backend.services.kimi_client._get_api_key", return_value="sk-test"):
            with patch("backend.services.kimi_client._ensure_settings_row", return_value=None):
                with patch("backend.services.kimi_client.AsyncOpenAI", return_value=mock_openai):
                    from backend.services.kimi_client import KimiClient

                    client = KimiClient()
                    reply = asyncio.run(client.chat([
                        {"role": "system", "content": "You are helpful."},
                        {"role": "user", "content": "Hi"},
                    ]))
                    assert isinstance(reply, str)
                    assert len(reply) > 0

    def test_chat_empty_response(self):
        """API 返回空 content."""
        mock_openai = _make_mock_openai(chat_return=_make_ok_response(""))
        with patch("backend.services.kimi_client._get_api_key", return_value="sk-test"):
            with patch("backend.services.kimi_client._ensure_settings_row", return_value=None):
                with patch("backend.services.kimi_client.AsyncOpenAI", return_value=mock_openai):
                    from backend.services.kimi_client import KimiClient

                    client = KimiClient()
                    reply = asyncio.run(client.chat([{"role": "user", "content": "?"}]))
                    assert reply == ""


class TestKimiClientRetry:
    """重试逻辑测试."""

    def test_retry_succeeds_after_failure(self):
        """第 1 次失败，第 2 次成功."""
        call_count = [0]

        async def _maybe_fail(*args, **kwargs):
            if kwargs.get("stream"):
                return AsyncStreamIterator([])
            call_count[0] += 1
            if call_count[0] < 2:
                raise ConnectionError("Temporary failure")
            return _make_ok_response("Recovered")

        mock_openai = MagicMock()
        mock_openai.chat = MagicMock()
        mock_openai.chat.completions = MagicMock()
        mock_openai.chat.completions.create = _maybe_fail

        with patch("backend.services.kimi_client._get_api_key", return_value="sk-test"):
            with patch("backend.services.kimi_client._ensure_settings_row", return_value=None):
                with patch("backend.services.kimi_client.AsyncOpenAI", return_value=mock_openai):
                    with patch("asyncio.sleep", return_value=None):
                        from backend.services.kimi_client import KimiClient

                        client = KimiClient()
                        reply = asyncio.run(client.chat([{"role": "user", "content": "Hello"}]))
                        assert reply == "Recovered"
                        assert call_count[0] == 2

    def test_retry_exhausted_raises(self):
        """全部重试失败 → RuntimeError."""
        async def _always_fail(*args, **kwargs):
            if kwargs.get("stream"):
                return AsyncStreamIterator([])
            raise ConnectionError("Always down")

        mock_openai = MagicMock()
        mock_openai.chat = MagicMock()
        mock_openai.chat.completions = MagicMock()
        mock_openai.chat.completions.create = _always_fail

        with patch("backend.services.kimi_client._get_api_key", return_value="sk-test"):
            with patch("backend.services.kimi_client._ensure_settings_row", return_value=None):
                with patch("backend.services.kimi_client.AsyncOpenAI", return_value=mock_openai):
                    with patch("asyncio.sleep", return_value=None):
                        from backend.services.kimi_client import KimiClient

                        client = KimiClient()
                        with pytest.raises(RuntimeError, match="已重试"):
                            asyncio.run(client.chat([{"role": "user", "content": "Hello"}]))

    def test_chat_stream_retry_exhausted(self):
        """流式重试耗尽."""
        async def _stream_fail(*args, **kwargs):
            if kwargs.get("stream"):
                raise TimeoutError("Stream timeout")
            return _make_ok_response("")

        mock_openai = MagicMock()
        mock_openai.chat = MagicMock()
        mock_openai.chat.completions = MagicMock()
        mock_openai.chat.completions.create = _stream_fail

        with patch("backend.services.kimi_client._get_api_key", return_value="sk-test"):
            with patch("backend.services.kimi_client._ensure_settings_row", return_value=None):
                with patch("backend.services.kimi_client.AsyncOpenAI", return_value=mock_openai):
                    with patch("asyncio.sleep", return_value=None):
                        from backend.services.kimi_client import KimiClient

                        client = KimiClient()
                        with pytest.raises(RuntimeError, match="已重试"):

                            async def _consume():
                                async for _ in client.chat_stream([{"role": "user", "content": "Hi"}]):
                                    pass

                            asyncio.run(_consume())


class TestKimiClientStream:
    """SSE 流式 chat_stream() 测试."""

    def test_chat_stream_yields_chunks(self):
        chunks = _make_stream_chunks(["Hello ", "from ", "Kimi"])
        mock_openai = make_mock_openai_client(stream_chunks=chunks)

        with patch("backend.services.kimi_client._get_api_key", return_value="sk-test"):
            with patch("backend.services.kimi_client._ensure_settings_row", return_value=None):
                with patch("backend.services.kimi_client.AsyncOpenAI", return_value=mock_openai):
                    from backend.services.kimi_client import KimiClient

                    client = KimiClient()

                    async def _collect():
                        collected = []
                        async for c in client.chat_stream([{"role": "user", "content": "Tell"}]):
                            collected.append(c)
                        return collected

                    result = asyncio.run(_collect())
                    assert len(result) == 3
                    assert "Hello" in result[0]
                    assert "Kimi" in result[2]


class TestFormatError:
    """_format_error 错误格式化测试."""

    def test_401_unauthorized(self):
        msg = _format_error(Exception("401 Unauthorized - Incorrect API key provided"))
        assert "API Key 无效" in msg

    def test_429_rate_limit(self):
        msg = _format_error(Exception("429 Too Many Requests"))
        assert "过于频繁" in msg

    def test_503_service_unavailable(self):
        msg = _format_error(Exception("503 Service Unavailable"))
        assert "暂时不可用" in msg

    def test_timeout(self):
        msg = _format_error(Exception("Connection timed out after 30 seconds"))
        assert "超时" in msg

    def test_generic_error(self):
        msg = _format_error(Exception("Some random error"))
        assert "API 调用异常" in msg

    def test_none_error(self):
        msg = _format_error(None)
        assert "未知错误" in msg


class TestApiKeyIntegration:
    """API Key 解密集成测试."""

    def test_get_api_key_delegates_to_secrets(self):
        """_get_api_key 委托 secrets._get_decrypted_api_key."""
        with patch("backend.services.secrets._get_decrypted_api_key", return_value="sk-decrypted"):
            from backend.services.kimi_client import _get_api_key

            key = _get_api_key()
            assert key == "sk-decrypted"

    def test_get_api_key_raises_when_none(self):
        """无 API Key 时抛出 ValueError."""
        with patch("backend.services.secrets._get_decrypted_api_key", return_value=None):
            from backend.services.kimi_client import _get_api_key

            with pytest.raises(ValueError, match="API Key 未配置"):
                _get_api_key()
