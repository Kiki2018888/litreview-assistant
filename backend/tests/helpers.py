"""测试辅助：Kimi / AsyncOpenAI mock 工具."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, Iterator, Optional
from unittest.mock import MagicMock, patch

from backend.models.tables import Paper


class AsyncStreamIterator:
    """模拟 OpenAI 流式响应（可被 await create(stream=True) 后 async for）."""

    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = list(chunks)
        self._index = 0

    def __aiter__(self) -> AsyncStreamIterator:
        return self

    async def __anext__(self) -> Any:
        if self._index >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk


def make_stream_chunk(text: str, *, finish: bool = False) -> MagicMock:
    """构造单个 SSE chunk."""
    choice = MagicMock()
    choice.index = 0
    choice.delta = MagicMock()
    choice.delta.content = text
    choice.finish_reason = "stop" if finish else None
    chunk = MagicMock()
    chunk.choices = [choice]
    return chunk


def make_chat_completion(content: str) -> MagicMock:
    """构造非流式 chat completion 响应."""
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = content
    return mock_resp


def make_mock_openai_client(
    *,
    chat_return: Optional[MagicMock] = None,
    stream_chunks: Optional[list[MagicMock]] = None,
) -> MagicMock:
    """构造 Mock AsyncOpenAI 实例."""

    async def _create(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("stream"):
            return AsyncStreamIterator(stream_chunks or [])
        return chat_return

    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = _create
    return mock_client


def make_kimi_client_instance(
    *,
    chat_return: Optional[MagicMock] = None,
    stream_chunks: Optional[list[MagicMock]] = None,
) -> MagicMock:
    """构造 Mock KimiClient（含 _client 属性）."""
    instance = MagicMock()
    instance._client = make_mock_openai_client(
        chat_return=chat_return,
        stream_chunks=stream_chunks,
    )
    return instance


@contextmanager
def patch_upload_session_flush() -> Iterator[None]:
    """上传流程在 flush 前尚未写入 file_path，测试侧补占位路径."""
    from sqlalchemy.orm import Session

    original_flush = Session.flush

    def _flush_with_placeholder(self, objects=None):
        for obj in list(self.new):
            if isinstance(obj, Paper) and not obj.file_path:
                obj.file_path = f"/fake/papers/{uuid.uuid4()}.pdf"
        return original_flush(self, objects)

    with patch.object(Session, "flush", _flush_with_placeholder):
        yield


async def run_sync_to_thread(fn, *args, **kwargs):
    """替代 asyncio.to_thread，测试内同步执行."""
    return fn(*args, **kwargs)
