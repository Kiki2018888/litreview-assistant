"""pytest 配置与共享 fixtures.

核心策略:
- 内存 SQLite 隔离测试
- monkeypatch 替换 db.engine / SessionLocal
- FTS5 虚拟表与触发器完整创建
- Mock Kimi API 避免外部调用
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from backend.models.tables import Base

# ---------------------------------------------------------------------------
# Session 级测试引擎 (一次性创建)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _test_engine():
    """创建内存 SQLite 引擎，建所有表 + FTS5.

    StaticPool 确保 :memory: 数据库连接复用，否则每次从连接池获取新连接
    会得到全新的空数据库，导致表不存在错误。
    """
    from sqlalchemy.pool import StaticPool

    engine = sa.create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _record):  # noqa: ARG001
        c = dbapi_conn.cursor()
        c.execute("PRAGMA foreign_keys=ON")
        c.close()

    Base.metadata.create_all(bind=engine)

    # FTS5 虚拟表 + 同步触发器
    _fts5_sql = [
        """CREATE VIRTUAL TABLE papers_fts USING fts5(
            title, authors, journal, keywords, background, methods, conclusion
        )""",
        """CREATE TRIGGER papers_ai AFTER INSERT ON papers BEGIN
            INSERT INTO papers_fts(rowid, title, authors, journal, keywords, background, methods, conclusion)
            VALUES (new.rowid, COALESCE(new.title,''), COALESCE(new.authors,''),
                    COALESCE(new.journal,''), '', '', '', '');
        END""",
        """CREATE TRIGGER papers_au AFTER UPDATE ON papers BEGIN
            UPDATE papers_fts SET title=COALESCE(new.title,''), authors=COALESCE(new.authors,''),
            journal=COALESCE(new.journal,'') WHERE rowid=old.rowid;
        END""",
        """CREATE TRIGGER papers_ad AFTER DELETE ON papers BEGIN
            DELETE FROM papers_fts WHERE rowid=old.rowid;
        END""",
        """CREATE TRIGGER extracted_data_ai AFTER INSERT ON extracted_data BEGIN
            UPDATE papers_fts SET keywords=COALESCE(new.keywords,''), background=COALESCE(new.background,''),
            methods=COALESCE(new.methods,''), conclusion=COALESCE(new.conclusion,'')
            WHERE rowid=(SELECT rowid FROM papers WHERE id=new.paper_id);
        END""",
        """CREATE TRIGGER extracted_data_au AFTER UPDATE ON extracted_data BEGIN
            UPDATE papers_fts SET keywords=COALESCE(new.keywords,''), background=COALESCE(new.background,''),
            methods=COALESCE(new.methods,''), conclusion=COALESCE(new.conclusion,'')
            WHERE rowid=(SELECT rowid FROM papers WHERE id=new.paper_id);
        END""",
        """CREATE TRIGGER extracted_data_ad AFTER DELETE ON extracted_data BEGIN
            UPDATE papers_fts SET keywords='', background='', methods='', conclusion=''
            WHERE rowid=(SELECT rowid FROM papers WHERE id=old.paper_id);
        END""",
    ]
    with engine.connect() as conn:
        for stmt in _fts5_sql:
            conn.execute(text(stmt))
        conn.commit()

    return engine


@pytest.fixture(scope="session")
def _TestSession(_test_engine):
    """Session 级 sessionmaker."""
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(autocommit=False, autoflush=False, bind=_test_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _patch_db(monkeypatch, _test_engine, _TestSession):
    """每个测试自动替换 db 模块的 engine 和 SessionLocal.

    关键时序：本 fixture 在 client fixture 之前执行（client 显式依赖它），
    保证 monkeypatch 生效后 API 模块才被 import，从而各模块的
    `from backend.services.db import SessionLocal` 本地绑定直接拿到
    _TestSession，无需逐个修补 8 个 API 模块。
    同时设置 dependency_overrides[get_db] 作为双保险。
    """
    # 1. 替换 db 模块自身的 engine / SessionLocal
    monkeypatch.setattr("backend.services.db.engine", _test_engine)
    monkeypatch.setattr("backend.services.db.SessionLocal", _TestSession)

    # 2. 覆盖 FastAPI 依赖注入 —— 用于 Depends(get_db) 的路由
    from backend.services.db import get_db as _get_db
    from backend.main import app

    def _override_get_db():
        db = _TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[_get_db] = _override_get_db

    yield

    # 测试结束：清理 dependency_overrides，避免跨测试污染
    app.dependency_overrides.pop(_get_db, None)


# ---------------------------------------------------------------------------
# 函数级 fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session(_TestSession):
    """每个测试独立 session，结束时回滚."""
    db = _TestSession()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def client(_patch_db) -> TestClient:
    """FastAPI TestClient.

    显式依赖 _patch_db：确保 monkeypatch + dependency_overrides
    在 app 及其路由模块 import 之前生效。
    """
    from backend.main import app

    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Mock fixtures ── Kimi API
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_kimi_chat():
    """Mock AsyncOpenAI.chat.completions.create (非流式).

    Usage:
        def test_xxx(mock_kimi_chat):
            # mock_kimi_chat 返回 "Mock reply"
            ...
    """
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Mock AI response"

    async def _create(*args, **kwargs):  # noqa: ARG001
        return mock_response

    with patch(
        "openai.resources.chat.completions.Completions.create",
        side_effect=_create,
    ):
        yield


@pytest.fixture
def mock_kimi_stream():
    """Mock AsyncOpenAI.chat.completions.create (流式 SSE).

    Yields chunks: ["Hello ", "world", ""]
    """
    chunks_data = ["Hello ", "from ", "Kimi"]

    async def _chunk_gen():
        for i, text in enumerate(chunks_data):
            choice = MagicMock()
            choice.index = 0
            choice.delta.content = text
            choice.finish_reason = "stop" if i == len(chunks_data) - 1 else None
            chunk = MagicMock()
            chunk.choices = [choice]
            yield chunk

    async def _create(*args, **kwargs):  # noqa: ARG001
        return _chunk_gen()

    with patch(
        "openai.resources.chat.completions.Completions.create",
        side_effect=_create,
    ):
        yield


# ---------------------------------------------------------------------------
# Mock fixtures ── PDF Parser
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_parse_pdf():
    """Mock pdf_parser.parse_pdf 返回模拟解析结果."""
    from backend.services.pdf_parser import PageInfo, PaperMetadata, ParsedPDF

    fake = ParsedPDF(
        file_path="/fake/test.pdf",
        page_count=3,
        pages=[
            PageInfo(page_number=1, text_content="Page one content. " * 10, char_count=180, is_scanned=False),
            PageInfo(page_number=2, text_content="Page two content. " * 10, char_count=180, is_scanned=False),
            PageInfo(page_number=3, text_content="Page three content. " * 10, char_count=180, is_scanned=False),
        ],
        total_chars=540,
        is_scanned=False,
        metadata=PaperMetadata(
            title="Test Paper Title",
            authors=["Author One", "Author Two"],
            year=2024,
            journal="Journal of Testing",
        ),
        parser_used="pdfplumber",
    )

    with patch("backend.services.pdf_parser.parse_pdf", return_value=fake):
        yield fake


@pytest.fixture
def mock_scanned_pdf():
    """Mock parse_pdf 返回扫描版 PDF."""
    from backend.services.pdf_parser import PageInfo, PaperMetadata, ParsedPDF

    fake = ParsedPDF(
        file_path="/fake/scanned.pdf",
        page_count=2,
        pages=[
            PageInfo(page_number=1, text_content="", char_count=0, is_scanned=True),
            PageInfo(page_number=2, text_content="few chars", char_count=9, is_scanned=True),
        ],
        total_chars=9,
        is_scanned=True,
        metadata=PaperMetadata(title=None, authors=None, year=None, journal=None),
        parser_used="pymupdf",
    )
    with patch("backend.services.pdf_parser.parse_pdf", return_value=fake):
        yield fake


# ---------------------------------------------------------------------------
# 测试数据工厂
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_paper(db_session):
    """在 DB 中创建一篇测试文献."""
    from backend.models.tables import Paper

    pid = str(uuid.uuid4())
    paper = Paper(
        id=pid,
        file_path=f"/fake/papers/{pid}.pdf",
        file_size=10240,
        page_count=3,
        title="Sample Paper",
        authors=["John Doe"],
        year=2023,
        journal="Nature",
        doi="10.1234/test.1",
        status="pending",
        is_scanned=False,
    )
    db_session.add(paper)
    db_session.commit()
    db_session.refresh(paper)
    return paper


@pytest.fixture(autouse=True)
def _ensure_default_project(db_session):
    """每个测试确保存在默认「未分类」项目."""
    from backend.services.project_service import get_default_project

    get_default_project(db_session)
    db_session.commit()


@pytest.fixture
def sample_project(db_session):
    """在 DB 中创建一个测试项目."""
    from backend.models.tables import Project

    pid = str(uuid.uuid4())
    project = Project(
        id=pid,
        name="Test Project",
        description="Project for testing",
        paper_count=0,
        is_default=False,
    )
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)
    return project


@pytest.fixture
def sample_batch(sample_project):
    """向后兼容：sample_batch 指向 sample_project."""
    return sample_project


@pytest.fixture
def sample_extracted_paper(db_session):
    """创建一篇带提取数据的文献."""
    import datetime as dt

    from backend.models.tables import ExtractedData, Paper

    pid = str(uuid.uuid4())
    paper = Paper(
        id=pid,
        file_path=f"/fake/papers/{pid}.pdf",
        file_size=20480,
        page_count=5,
        title="Extracted Paper",
        authors=["Jane Smith"],
        year=2022,
        journal="Science",
        status="completed",
        is_scanned=False,
        extraction_attempts=1,
        extracted_at=dt.datetime.utcnow(),
    )
    db_session.add(paper)
    db_session.flush()  # 确保 Paper 入库后再插入 ExtractedData，满足 FK 约束

    extract = ExtractedData(
        id=str(uuid.uuid4()),
        paper_id=pid,
        background="This is the background.",
        methods="We used these methods.",
        key_results=["Result 1", "Result 2"],
        conclusion="This is the conclusion.",
        keywords=["keyword1", "keyword2"],
        raw_json={"summary": "test"},
        extracted_at=dt.datetime.utcnow(),
    )
    db_session.add(extract)
    db_session.commit()
    db_session.refresh(paper)
    return paper


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def make_pdf_bytes() -> bytes:
    """生成最小有效 PDF 字节流."""
    return b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n%%EOF"
