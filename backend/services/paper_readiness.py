"""文献解析就绪判定（claims / 摘要共用）.

claims 与摘要均读 paper_pages 全文，不依赖 extracted_data。
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.config import SCANNED_DOC_MIN_CHARS
from backend.models.tables import ExtractedData, Paper, PaperPage, PaperStatus
from backend.services.pdf_parser import is_document_scanned

# 与扫描版全篇下限对齐：低于此视为“未解析出可用全文”
MIN_PARSED_CHARS = SCANNED_DOC_MIN_CHARS


def paper_total_chars(db: Session, paper_id: str) -> int:
    return (
        db.query(func.coalesce(func.sum(PaperPage.char_count), 0))
        .filter(PaperPage.paper_id == paper_id)
        .scalar()
        or 0
    )


def paper_page_char_counts(db: Session, paper_id: str) -> list[int]:
    return [
        row[0]
        for row in db.query(PaperPage.char_count)
        .filter(PaperPage.paper_id == paper_id)
        .order_by(PaperPage.page_number)
        .all()
    ]


def is_paper_parsed_ready(db: Session, paper: Paper) -> bool:
    """PDF 已解析出可用全文（可抽 claims / 可尝试摘要），不要求已有摘要."""
    if paper.status == PaperStatus.FAILED.value:
        return False
    counts = paper_page_char_counts(db, paper.id)
    if not counts:
        return False
    total = sum(counts)
    if total < MIN_PARSED_CHARS:
        return False
    if is_document_scanned(counts):
        return False
    return True


def parsed_papers_in_project(db: Session, project_id: str) -> list[Paper]:
    """项目下所有已解析出可用全文的文献."""
    papers = db.query(Paper).filter(Paper.project_id == project_id).all()
    return [p for p in papers if is_paper_parsed_ready(db, p)]


def papers_pending_summary(db: Session, project_id: str, *, force: bool = False) -> list[Paper]:
    """待提取摘要的文献：已解析全文且尚无 extracted_data（force 时含已有摘要的）."""
    eligible = parsed_papers_in_project(db, project_id)
    if not eligible:
        return []
    if force:
        return eligible
    with_summary = {
        row[0]
        for row in db.query(ExtractedData.paper_id)
        .filter(ExtractedData.paper_id.in_([p.id for p in eligible]))
        .all()
    }
    return [p for p in eligible if p.id not in with_summary]


__all__ = [
    "MIN_PARSED_CHARS",
    "is_paper_parsed_ready",
    "parsed_papers_in_project",
    "paper_page_char_counts",
    "paper_total_chars",
    "papers_pending_summary",
]
