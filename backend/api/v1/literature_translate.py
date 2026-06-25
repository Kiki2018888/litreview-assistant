"""文献摘要翻译 API.

路由: POST /api/v1/literature/{paper_id}/translate
调用 Kimi API 翻译结构化摘要，结果缓存到 extracted_data.translation。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.config import DEFAULT_TEMPERATURE, DEFAULT_MAX_TOKENS
from backend.models.tables import ExtractedData, Paper
from backend.services.db import SessionLocal
from backend.services.kimi_client import KimiClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/literature", tags=["translate"])

_TRANSLATE_PROMPT = """你是一位专业的学术翻译助手。请将以下英文学术论文摘要翻译为中文，要求：

1. 保持学术严谨性，术语翻译准确
2. 保留原文的段落结构（背景/方法/结果/结论分段对应）
3. 语句通顺自然，符合中文学术写作规范

待翻译摘要：
背景：{background}
方法：{methods}
核心结果：{key_results}
结论：{conclusion}
关键词：{keywords}

请以以下格式输出纯中文翻译：

【研究背景】
...

【研究方法】
...

【核心结果】
...

【研究结论】
...

【关键词】
..."""


# ---------------------------------------------------------------------------
# 响应体
# ---------------------------------------------------------------------------


class TranslateResponse(BaseModel):
    """翻译响应."""

    translation: str = Field(..., description="中文翻译全文")
    cached: bool = Field(False, description="是否来自缓存")


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _build_translate_prompt(ext: ExtractedData) -> str:
    """构建翻译 Prompt."""
    bg = ext.background or "（未提取）"
    mt = ext.methods or "（未提取）"
    kr = "; ".join(ext.key_results) if ext.key_results else "（未提取）"
    cc = ext.conclusion or "（未提取）"
    kw = ", ".join(ext.keywords) if ext.keywords else "（未提取）"
    return _TRANSLATE_PROMPT.format(
        background=bg,
        methods=mt,
        key_results=kr,
        conclusion=cc,
        keywords=kw,
    )


# ---------------------------------------------------------------------------
# POST /{paper_id}/translate
# ---------------------------------------------------------------------------


@router.post("/{paper_id}/translate")
async def translate_paper(paper_id: str):
    """翻译文献结构化摘要.

    优先返回缓存（extracted_data.translation），无缓存时调用 Kimi API 翻译。
    """
    db = SessionLocal()
    try:
        paper = db.query(Paper).filter(Paper.id == paper_id).first()
        if not paper:
            raise HTTPException(status_code=404, detail="文献不存在")

        ext = (
            db.query(ExtractedData)
            .filter(ExtractedData.paper_id == paper_id)
            .first()
        )
        if not ext:
            raise HTTPException(
                status_code=400,
                detail="文献尚未提取结构化摘要，请先执行 AI 提取",
            )

        # 检查是否有内容可翻译
        has_content = bool(
            ext.background or ext.methods or ext.conclusion
        )
        if not has_content:
            raise HTTPException(
                status_code=400,
                detail="文献摘要为空，无法翻译",
            )

        # 缓存命中
        if ext.translation:
            return TranslateResponse(translation=ext.translation, cached=True)

    finally:
        db.close()

    # 调用 Kimi API 翻译
    prompt = _build_translate_prompt(ext)
    client = KimiClient()

    try:
        translation = await client.chat(
            messages=[{"role": "user", "content": prompt}],
            model=client._model,
            temperature=DEFAULT_TEMPERATURE,
            max_tokens=DEFAULT_MAX_TOKENS,
        )
    except RuntimeError as exc:
        logger.error("翻译失败 paper_id=%s: %s", paper_id, exc)
        raise HTTPException(status_code=502, detail=str(exc))

    # 保存到数据库
    db_save = SessionLocal()
    try:
        ext_obj = (
            db_save.query(ExtractedData)
            .filter(ExtractedData.paper_id == paper_id)
            .first()
        )
        if ext_obj:
            ext_obj.translation = translation
            db_save.commit()
    finally:
        db_save.close()

    return TranslateResponse(translation=translation, cached=False)


__all__ = ["router"]
