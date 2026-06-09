"""文献 CRUD API.

路由前缀: /api/v1/literature
路由顺序（固定路径 → 参数化路径）:
  POST /upload  → GET /tags → GET /stats → GET /
  → POST /{id}/parse → GET /{id} → GET /{id}/pages
  → GET /{id}/page/{page_num} → PUT /{id}/tags → DELETE /{id}
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, literal_column, select, text
from sqlalchemy.orm import Session

from backend.config import MAX_UPLOAD_FILE_COUNT, MAX_UPLOAD_FILE_SIZE_MB, PDF_DIR
from backend.models.schemas import (
    DeleteResponse,
    ExtractedDataResponse,
    ListResponse,
    PageTextResponse,
    PaperDetailResponse,
    PaperListItem,
    PaperParseResponse,
    PaperStatsResponse,
    PaperTagsUpdateRequest,
    PaperTagsUpdateResponse,
    PaperUploadResponse,
    PaperUploadResult,
    TagSummaryItem,
    TagSummaryResponse,
)
from backend.models.tables import (
    Batch,
    ExtractedData,
    Paper,
    PaperPage,
    PaperStatus,
    PaperTag,
)
from backend.services.db import get_db
from backend.services.pdf_parser import PageInfo, ParsedPDF, parse_pdf

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/literature", tags=["literature"])

_ONE_MB = 1024 * 1024
_MAX_FILE_BYTES = MAX_UPLOAD_FILE_SIZE_MB * _ONE_MB


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _batch_load_tags(db: Session, paper_ids: list[str]) -> dict[str, list[str]]:
    """批量加载 paper_id → [tag, ...] 映射."""
    if not paper_ids:
        return {}
    rows = db.execute(
        select(PaperTag).where(PaperTag.paper_id.in_(paper_ids))
    ).scalars().all()
    mapping: dict[str, list[str]] = {}
    for row in rows:
        mapping.setdefault(row.paper_id, []).append(row.tag)
    return mapping


def _save_pages(db: Session, paper_id: str, pages: list[PageInfo]) -> int:
    """将解析结果写入 paper_pages，返回总页数."""
    for p in pages:
        db.add(PaperPage(
            paper_id=paper_id,
            page_number=p.page_number,
            text_content=p.text_content,
            char_count=p.char_count,
        ))
    return len(pages)


def _clear_pages(db: Session, paper_id: str) -> None:
    """清空指定文献的所有页面记录."""
    db.execute(delete(PaperPage).where(PaperPage.paper_id == paper_id))


def escape_fts_query(query: str) -> str:
    """转义用户输入，安全用于 FTS5 MATCH.

    策略：
    1. 移除 FTS5 操作符（* - " ( )）避免语法错误
    2. 双引号包裹 → 短语匹配，防止 AND/OR/NEAR 被解析为布尔操作符
    3. 空/无效输入返回空字符串，调用方返回 400 或空结果
    """
    query = query.strip()
    if not query:
        return ""
    # 移除 FTS5 特殊字符
    cleaned = re.sub(r'[*"()\-]', ' ', query)
    # 合并连续空白
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if not cleaned:
        return ""
    return f'"{cleaned}"'


# ===================================================================
# 固定路径路由组（必须在参数化路径之前注册）
# ===================================================================


# -------------------------------------------------------------------
# 1. 批量上传 PDF
# -------------------------------------------------------------------


@router.post("/upload", response_model=PaperUploadResponse)
async def upload_pdfs(
    files: list[UploadFile] = File(..., alias="files[]"),
    batch_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
) -> PaperUploadResponse:
    """批量上传 PDF 文献.

    单次上限 50 个，单个上限 50MB，仅接受 .pdf。
    上传后自动解析 pdfplumber → pymupdf 逐页存入 paper_pages。
    """
    # -- 数量校验 --
    if len(files) > MAX_UPLOAD_FILE_COUNT:
        raise HTTPException(
            status_code=400,
            detail=f"单次最多上传 {MAX_UPLOAD_FILE_COUNT} 个文件",
        )

    # -- 逐文件预检（类型 + 大小） --
    file_trios: list[tuple[UploadFile, bytes, int]] = []
    for f in files:
        if not f.filename or not f.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=400,
                detail=f"仅支持 PDF 格式，收到: {f.filename}",
            )
        content = await f.read()
        size = len(content)
        if size > _MAX_FILE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"文件过大（单文件上限 {MAX_UPLOAD_FILE_SIZE_MB}MB）: {f.filename}",
            )
        file_trios.append((f, content, size))

    # -- 批次校验 --
    if batch_id:
        batch = db.get(Batch, batch_id)
        if not batch:
            raise HTTPException(status_code=404, detail="批次不存在")

    # -- 确保保存目录 --
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    results: list[PaperUploadResult] = []

    for f, content, size in file_trios:
        paper = Paper(
            file_size=size,
            status=PaperStatus.PENDING.value,
            batch_id=batch_id,
        )
        db.add(paper)
        db.flush()  # 获取 UUID

        # 保存 PDF 到磁盘
        pdf_path = PDF_DIR / f"{paper.id}.pdf"
        pdf_path.write_bytes(content)
        paper.file_path = str(pdf_path)

        # 解析
        try:
            parsed: ParsedPDF = await asyncio.to_thread(parse_pdf, str(pdf_path))
            paper.page_count = parsed.page_count
            paper.is_scanned = parsed.is_scanned
            paper.title = parsed.metadata.title
            paper.authors = parsed.metadata.authors
            paper.year = parsed.metadata.year
            paper.journal = parsed.metadata.journal
            _save_pages(db, paper.id, parsed.pages)
            if parsed.is_scanned:
                paper.status = PaperStatus.EXTRACT_FAILED.value
                paper.last_error = "检测到扫描版 PDF，已跳过自动提取"
        except Exception as exc:
            paper.status = PaperStatus.FAILED.value
            paper.last_error = str(exc)
            logger.warning("PDF 解析失败 paper_id=%s: %s", paper.id, exc)

        db.flush()

        display_title = paper.title or (f.filename or "未命名")
        results.append(PaperUploadResult(
            id=paper.id,
            title=display_title,
            status=paper.status,  # type: ignore[arg-type]
            page_count=paper.page_count,
        ))

    # 更新批次 paper_count
    if batch_id:
        db.execute(
            text(
                "UPDATE batches SET paper_count = paper_count + :c, "
                "updated_at = datetime('now') WHERE id = :bid"
            ),
            {"c": len(file_trios), "bid": batch_id},
        )

    db.commit()
    return PaperUploadResponse(uploaded=results)


# -------------------------------------------------------------------
# 2. 标签汇总
# -------------------------------------------------------------------


@router.get("/tags", response_model=TagSummaryResponse)
def list_tags(db: Session = Depends(get_db)) -> TagSummaryResponse:
    """返回所有标签及每个标签的文献数量."""
    rows = db.execute(
        select(PaperTag.tag, func.count(PaperTag.paper_id))
        .group_by(PaperTag.tag)
        .order_by(func.count(PaperTag.paper_id).desc())
    ).all()
    return TagSummaryResponse(
        tags=[TagSummaryItem(tag=row[0], count=row[1]) for row in rows]
    )


# -------------------------------------------------------------------
# 3. 文献统计
# -------------------------------------------------------------------


@router.get("/stats", response_model=PaperStatsResponse)
def get_stats(db: Session = Depends(get_db)) -> PaperStatsResponse:
    """文献处理状态统计."""
    total = db.scalar(select(func.count(Paper.id)).select_from(Paper)) or 0
    rows = db.execute(
        select(Paper.status, func.count(Paper.id)).group_by(Paper.status)
    ).all()
    counts = {row[0]: row[1] for row in rows}
    return PaperStatsResponse(
        total=total,
        pending=counts.get("pending", 0),
        extracting=counts.get("extracting", 0),
        completed=counts.get("completed", 0),
        failed=counts.get("failed", 0),
        extract_failed=counts.get("extract_failed", 0),
    )


# -------------------------------------------------------------------
# 4. 文献列表（GET /  必须在 GET /{paper_id} 之前）
# -------------------------------------------------------------------


@router.get("/")
def list_papers(
    search: Optional[str] = Query(None, description="FTS5 全文搜索"),
    tag: Optional[str] = Query(None, description="标签筛选"),
    year: Optional[int] = Query(None, description="年份筛选"),
    status: Optional[str] = Query(None, description="状态筛选"),
    sort: Optional[str] = Query(None, description="排序: year / time / title"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ListResponse:
    """文献列表，支持分页、FTS5 搜索、标签/年份/状态筛选、排序."""

    stmt = select(Paper)
    count_stmt = select(func.count(Paper.id))

    # ── FTS5 全文搜索 ──
    if search:
        safe_query = escape_fts_query(search)
        if not safe_query:
            return ListResponse(items=[], total=0, page=page, page_size=page_size)
        try:
            fts_ids = db.execute(
                text("SELECT rowid FROM papers_fts WHERE papers_fts MATCH :q"),
                {"q": safe_query},
            ).scalars().all()
        except Exception:
            raise HTTPException(
                status_code=400,
                detail=f"无效的搜索查询，请尝试更换关键词",
            )
        if not fts_ids:
            return ListResponse(items=[], total=0, page=page, page_size=page_size)
        stmt = stmt.where(literal_column("rowid").in_(fts_ids))
        count_stmt = count_stmt.where(literal_column("rowid").in_(fts_ids))

    # ── 标签筛选 ──
    if tag:
        tagged = db.execute(
            select(PaperTag.paper_id).where(PaperTag.tag == tag)
        ).scalars().all()
        if not tagged:
            return ListResponse(items=[], total=0, page=page, page_size=page_size)
        stmt = stmt.where(Paper.id.in_(tagged))
        count_stmt = count_stmt.where(Paper.id.in_(tagged))

    # ── 年份 / 状态筛选 ──
    if year is not None:
        stmt = stmt.where(Paper.year == year)
        count_stmt = count_stmt.where(Paper.year == year)
    if status:
        stmt = stmt.where(Paper.status == status)
        count_stmt = count_stmt.where(Paper.status == status)

    # ── 排序 ──
    if sort == "year":
        stmt = stmt.order_by(Paper.year.desc().nullslast(), Paper.title.asc())
    elif sort == "title":
        stmt = stmt.order_by(Paper.title.asc().nullslast())
    else:
        stmt = stmt.order_by(Paper.created_at.desc())

    # ── 分页 ──
    total = db.scalar(count_stmt) or 0
    offset = (page - 1) * page_size
    papers = db.execute(stmt.offset(offset).limit(page_size)).scalars().all()

    # ── 批量加载标签 ──
    tags_map = _batch_load_tags(db, [p.id for p in papers])

    items = [
        PaperListItem(
            id=p.id,
            title=p.title,
            authors=p.authors if isinstance(p.authors, list) else None,
            year=p.year,
            journal=p.journal,
            status=p.status,  # type: ignore[arg-type]
            tags=tags_map.get(p.id, []),
            batch_id=p.batch_id,
            created_at=p.created_at,  # type: ignore[arg-type]
        )
        for p in papers
    ]

    return ListResponse(items=items, total=total, page=page, page_size=page_size)


# ===================================================================
# 参数化路径路由组 ({paper_id}  必须在固定路径之后)
# ===================================================================


# -------------------------------------------------------------------
# 4.5. 获取 PDF 文件二进制（用于 Electron blob URL 预览）
# -------------------------------------------------------------------


@router.get("/{paper_id}/file")
def get_paper_file(
    paper_id: str,
    db: Session = Depends(get_db),
):
    """返回 PDF 二进制，供前端通过 blob URL 预览（绕过 Electron webSecurity 拦截）."""
    paper = db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="文献不存在")

    pdf_path = paper.file_path
    if not pdf_path or not os.path.isfile(pdf_path):
        raise HTTPException(status_code=404, detail="PDF 文件不存在")

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=f"{paper_id}.pdf",
    )


# -------------------------------------------------------------------
# 5. 手动触发解析
# -------------------------------------------------------------------


@router.post("/{paper_id}/parse", response_model=PaperParseResponse)
async def reparse_paper(
    paper_id: str,
    db: Session = Depends(get_db),
) -> PaperParseResponse:
    """重新解析指定文献：清空旧 page → 重新提取 → 更新元数据."""
    paper = db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="文献不存在")

    _clear_pages(db, paper_id)
    # 清除旧的结构化摘要，避免 AI 问答基于过期信息
    db.execute(delete(ExtractedData).where(ExtractedData.paper_id == paper_id))
    # 重置提取状态
    paper.extraction_attempts = 0
    paper.extracted_at = None
    db.flush()

    try:
        parsed = await asyncio.to_thread(parse_pdf, paper.file_path)
        paper.page_count = parsed.page_count
        paper.is_scanned = parsed.is_scanned
        paper.title = parsed.metadata.title or paper.title
        paper.authors = parsed.metadata.authors or paper.authors
        paper.year = parsed.metadata.year or paper.year
        paper.journal = parsed.metadata.journal or paper.journal
        _save_pages(db, paper.id, parsed.pages)
        if parsed.is_scanned:
            paper.status = PaperStatus.EXTRACT_FAILED.value
            paper.last_error = "检测到扫描版 PDF"
        else:
            paper.status = PaperStatus.PENDING.value
            paper.last_error = None
    except Exception as exc:
        paper.status = PaperStatus.FAILED.value
        paper.last_error = str(exc)
        logger.warning("重新解析失败 paper_id=%s: %s", paper_id, exc)

    db.commit()
    db.refresh(paper)
    return PaperParseResponse(
        paper_id=paper.id,
        page_count=paper.page_count,
        status=paper.status,  # type: ignore[arg-type]
    )


# -------------------------------------------------------------------
# 6. 单篇详情
# -------------------------------------------------------------------


@router.get("/{paper_id}", response_model=PaperDetailResponse)
def get_paper_detail(
    paper_id: str,
    db: Session = Depends(get_db),
) -> PaperDetailResponse:
    """返回文献完整信息（含 extracted_data 和 tags，不含 pages）."""
    paper = db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="文献不存在")

    ext_data = db.execute(
        select(ExtractedData).where(ExtractedData.paper_id == paper_id)
    ).scalar_one_or_none()

    tags_map = _batch_load_tags(db, [paper_id])

    return PaperDetailResponse(
        id=paper.id,
        file_path=paper.file_path,
        file_size=paper.file_size,
        page_count=paper.page_count,
        title=paper.title,
        authors=paper.authors if isinstance(paper.authors, list) else None,
        year=paper.year,
        journal=paper.journal,
        doi=paper.doi,
        status=paper.status,  # type: ignore[arg-type]
        batch_id=paper.batch_id,
        is_scanned=paper.is_scanned,
        extraction_attempts=paper.extraction_attempts,
        last_error=paper.last_error,
        created_at=paper.created_at,  # type: ignore[arg-type]
        extracted_at=paper.extracted_at,
        updated_at=paper.updated_at,  # type: ignore[arg-type]
        tags=tags_map.get(paper_id, []),
        extracted_data=(
            ExtractedDataResponse.model_validate(ext_data) if ext_data else None
        ),
    )


# -------------------------------------------------------------------
# 7. 获取全部页面
# -------------------------------------------------------------------


@router.get("/{paper_id}/pages")
def get_all_pages(
    paper_id: str,
    db: Session = Depends(get_db),
) -> dict:
    """返回该文献所有页面文本."""
    paper = db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="文献不存在")

    pages = db.execute(
        select(PaperPage)
        .where(PaperPage.paper_id == paper_id)
        .order_by(PaperPage.page_number)
    ).scalars().all()

    return {
        "paper_id": paper_id,
        "pages": [
            {
                "page_number": p.page_number,
                "text_content": p.text_content,
                "char_count": p.char_count,
            }
            for p in pages
        ],
    }


# -------------------------------------------------------------------
# 8. 获取单页原文
# -------------------------------------------------------------------


@router.get("/{paper_id}/page/{page_num}", response_model=PageTextResponse)
def get_single_page(
    paper_id: str,
    page_num: int,
    db: Session = Depends(get_db),
) -> PageTextResponse:
    """返回指定页码的文本内容."""
    paper = db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="文献不存在")

    pp = db.execute(
        select(PaperPage).where(
            PaperPage.paper_id == paper_id,
            PaperPage.page_number == page_num,
        )
    ).scalar_one_or_none()

    if not pp:
        raise HTTPException(
            status_code=404,
            detail=f"第 {page_num} 页不存在",
        )

    return PageTextResponse(
        page_number=pp.page_number,
        text_content=pp.text_content,
        char_count=pp.char_count,
    )


# -------------------------------------------------------------------
# 9. 更新标签
# -------------------------------------------------------------------


@router.put("/{paper_id}/tags", response_model=PaperTagsUpdateResponse)
def update_tags(
    paper_id: str,
    body: PaperTagsUpdateRequest,
    db: Session = Depends(get_db),
) -> PaperTagsUpdateResponse:
    """全量替换文献标签：先删后插."""
    paper = db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="文献不存在")

    db.execute(delete(PaperTag).where(PaperTag.paper_id == paper_id))
    unique = sorted(set(t.strip() for t in body.tags if t.strip()))
    for t in unique:
        db.add(PaperTag(paper_id=paper_id, tag=t))

    db.commit()
    return PaperTagsUpdateResponse(id=paper_id, tags=unique)


# -------------------------------------------------------------------
# 10. 删除文献
# -------------------------------------------------------------------


@router.delete("/{paper_id}", response_model=DeleteResponse)
def delete_paper(
    paper_id: str,
    db: Session = Depends(get_db),
) -> DeleteResponse:
    """硬删除文献：DB 记录 + 本地 PDF + 批次计数减 1."""
    paper = db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="文献不存在")

    pdf_path = paper.file_path
    batch_id = paper.batch_id

    db.delete(paper)  # CASCADE 自动处理 pages/extracted_data/tags

    if batch_id:
        db.execute(
            text(
                "UPDATE batches SET paper_count = MAX(0, paper_count - 1), "
                "updated_at = datetime('now') WHERE id = :bid"
            ),
            {"bid": batch_id},
        )

    db.commit()

    # 物理删除 PDF 文件
    if pdf_path and os.path.isfile(pdf_path):
        try:
            os.remove(pdf_path)
        except OSError as exc:
            logger.warning("删除 PDF 文件失败 %s: %s", pdf_path, exc)

    return DeleteResponse(success=True)


__all__ = ["router"]
