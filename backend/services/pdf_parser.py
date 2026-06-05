"""PDF 文本提取服务.

使用 pdfplumber 作为主力解析器，pymupdf 作为 fallback。
提供扫描版 PDF 检测与元数据提取。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from backend.config import SCANNED_PAGE_MIN_CHARS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 解析结果数据结构
# ---------------------------------------------------------------------------


@dataclass
class PageInfo:
    """单页解析结果."""

    page_number: int                       # 页码，从 1 开始
    text_content: str                      # 提取的文本
    char_count: int                        # 字符数
    is_scanned: bool = False               # 是否为扫描页（字符过少）


@dataclass
class PaperMetadata:
    """PDF 元数据."""

    title: Optional[str] = None
    authors: Optional[list[str]] = None
    year: Optional[int] = None
    journal: Optional[str] = None


@dataclass
class ParsedPDF:
    """PDF 完整解析结果."""

    file_path: str                         # 原始文件路径
    page_count: int                        # 总页数
    pages: list[PageInfo]                  # 每页信息
    total_chars: int                       # 总字符数
    is_scanned: bool                       # 是否为扫描版（任一页字符 < 阈值）
    metadata: PaperMetadata = field(default_factory=PaperMetadata)
    parser_used: str = ""                  # 实际使用的解析器名称


# ---------------------------------------------------------------------------
# 解析器实现
# ---------------------------------------------------------------------------


def _parse_with_pdfplumber(file_path: str) -> Optional[list[PageInfo]]:
    """使用 pdfplumber 逐页提取文本.

    Returns:
        成功返回 PageInfo 列表，失败返回 None。
    """
    try:
        import pdfplumber
    except ImportError:
        logger.warning("pdfplumber 未安装，无法使用")
        return None

    pages: list[PageInfo] = []
    try:
        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                char_count = len(text)
                pages.append(PageInfo(
                    page_number=page_num,
                    text_content=text,
                    char_count=char_count,
                ))
    except Exception as exc:
        logger.warning("pdfplumber 解析失败 (%s): %s", file_path, exc)
        return None

    return pages


def _parse_with_pymupdf(file_path: str) -> Optional[list[PageInfo]]:
    """使用 pymupdf 作为 fallback 逐页提取文本.

    Returns:
        成功返回 PageInfo 列表，失败返回 None。
    """
    try:
        import fitz  # pymupdf
    except ImportError:
        logger.warning("pymupdf 未安装，无法使用")
        return None

    pages: list[PageInfo] = []
    try:
        doc = fitz.open(file_path)
        for page_num in range(1, doc.page_count + 1):
            page = doc[page_num - 1]
            text = page.get_text() or ""
            char_count = len(text)
            pages.append(PageInfo(
                page_number=page_num,
                text_content=text,
                char_count=char_count,
            ))
        doc.close()
    except Exception as exc:
        logger.error("pymupdf 解析失败 (%s): %s", file_path, exc)
        return None

    return pages


# ---------------------------------------------------------------------------
# 元数据提取
# ---------------------------------------------------------------------------


def _extract_metadata_pdfplumber(file_path: str) -> PaperMetadata:
    """从 PDF 元数据中提取标题、作者、年份、期刊."""
    meta = PaperMetadata()
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            doc_info = pdf.metadata or {}

        raw_author = doc_info.get("Author", "") or ""
        if raw_author:
            raw_author = str(raw_author)
            # 常见分隔符：, ; and
            import re
            parts = re.split(r"[,;]|\band\b", raw_author)
            meta.authors = [a.strip() for a in parts if a.strip()]

        raw_title = doc_info.get("Title", "") or ""
        if raw_title:
            meta.title = str(raw_title)

        raw_created = doc_info.get("CreationDate", "") or ""
        if isinstance(raw_created, str) and len(raw_created) >= 4:
            # D:YYYYMMDDHHmmSS 或 D:YYYY
            import re
            m = re.search(r"\d{4}", str(raw_created))
            if m:
                try:
                    meta.year = int(m.group())
                except (ValueError, TypeError):
                    pass

    except Exception as exc:
        logger.debug("元数据提取失败 (%s): %s", file_path, exc)

    return meta


def _extract_metadata_pymupdf(file_path: str) -> PaperMetadata:
    """使用 pymupdf 从 PDF 元数据中提取信息（fallback）."""
    meta = PaperMetadata()
    try:
        import fitz
        doc = fitz.open(file_path)
        doc_info = doc.metadata or {}
        doc.close()

        raw_author = doc_info.get("author", "") or ""
        if raw_author:
            import re
            parts = re.split(r"[,;]|\band\b", str(raw_author))
            meta.authors = [a.strip() for a in parts if a.strip()]

        raw_title = doc_info.get("title", "") or ""
        if raw_title:
            meta.title = str(raw_title)

        raw_created = doc_info.get("creationDate", "") or ""
        if isinstance(raw_created, str) and len(raw_created) >= 4:
            import re
            m = re.search(r"\d{4}", str(raw_created))
            if m:
                try:
                    meta.year = int(m.group())
                except (ValueError, TypeError):
                    pass

    except Exception as exc:
        logger.debug("pymupdf 元数据提取失败 (%s): %s", file_path, exc)

    return meta


# ---------------------------------------------------------------------------
# 公共接口
# ---------------------------------------------------------------------------


def parse_pdf(file_path: str) -> ParsedPDF:
    """解析 PDF 文件，提取文本、元数据并检测扫描版.

    解析策略：
    1. 首选 pdfplumber 逐页提取文本
    2. 失败时 fallback 到 pymupdf
    3. 两者都失败时抛出 RuntimeError

    Args:
        file_path: PDF 文件的绝对路径或相对路径（相对于工作目录）。

    Returns:
        ParsedPDF: 包含页文本、元数据、扫描检测结果的解析对象。

    Raises:
        FileNotFoundError: 文件不存在。
        RuntimeError: 两种解析器均失败。
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF 文件不存在: {file_path}")
    if not path.is_file():
        raise FileNotFoundError(f"路径不是文件: {file_path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"文件不是 PDF 格式: {file_path}")

    # 尝试 pdfplumber 解析
    pages: Optional[list[PageInfo]] = _parse_with_pdfplumber(str(path))
    parser_used = "pdfplumber"

    # fallback 到 pymupdf
    if pages is None:
        parser_used = "pymupdf"
        pages = _parse_with_pymupdf(str(path))

    if pages is None:
        raise RuntimeError(
            f"无法解析 PDF 文件 {file_path}，pdfplumber 和 pymupdf 均失败。"
            "请检查文件是否损坏或为加密 PDF。"
        )

    # 检测扫描版：任一页字符少于阈值即标记
    is_scanned = False
    for p in pages:
        if p.char_count < SCANNED_PAGE_MIN_CHARS:
            p.is_scanned = True
            is_scanned = True

    total_chars = sum(p.char_count for p in pages)

    # 提取元数据（用对应解析器）
    if parser_used == "pdfplumber":
        metadata = _extract_metadata_pdfplumber(str(path))
    else:
        metadata = _extract_metadata_pymupdf(str(path))

    return ParsedPDF(
        file_path=str(path),
        page_count=len(pages),
        pages=pages,
        total_chars=total_chars,
        is_scanned=is_scanned,
        metadata=metadata,
        parser_used=parser_used,
    )


def extract_full_text(file_path: str) -> str:
    """提取 PDF 全文文本（所有页拼接），方便快速传参.

    Args:
        file_path: PDF 文件路径。

    Returns:
        拼接后的全文文本。
    """
    result = parse_pdf(file_path)
    return "\n".join(page.text_content for page in result.pages)


__all__ = [
    "parse_pdf",
    "extract_full_text",
    "ParsedPDF",
    "PageInfo",
    "PaperMetadata",
]
