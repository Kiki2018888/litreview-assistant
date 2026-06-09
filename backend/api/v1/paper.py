"""论文撰写 API.

路由前缀: /api/v1/paper
- GET  /blocks                 — 获取五个分块
- PUT  /blocks/{block_name}    — 保存指定分块
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.models import tables, schemas
from backend.services.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/paper", tags=["paper"])

BLOCK_NAMES = ["abstract", "introduction", "methods", "results", "discussion"]


# ---------------------------------------------------------------------------
# GET /blocks — 获取五个分块
# ---------------------------------------------------------------------------


@router.get("/blocks", response_model=schemas.PaperBlocksResponse)
async def get_blocks(db: Session = Depends(get_db)):
    """获取五个分块，缺失的返回 null."""
    blocks = db.query(tables.PaperBlock).all()

    result: dict[str, schemas.PaperBlockResponse | None] = {}
    for block in blocks:
        result[block.block_name] = schemas.PaperBlockResponse.model_validate(block)

    # 确保五个字段都存在，缺失的返回 None
    for name in BLOCK_NAMES:
        if name not in result:
            result[name] = None

    return result


# ---------------------------------------------------------------------------
# PUT /blocks/{block_name} — 保存指定分块
# ---------------------------------------------------------------------------


@router.put("/blocks/{block_name}", response_model=schemas.PaperBlockResponse)
async def update_block(
    block_name: str,
    data: schemas.PaperBlockUpdate,
    db: Session = Depends(get_db),
):
    """保存指定分块，block_name 不存在则创建."""
    if block_name not in BLOCK_NAMES:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail=f"无效的分块名称，可选值: {', '.join(BLOCK_NAMES)}",
        )

    block = db.query(tables.PaperBlock).filter(
        tables.PaperBlock.block_name == block_name
    ).first()

    if not block:
        block = tables.PaperBlock(block_name=block_name, content=data.content)
        db.add(block)
    else:
        block.content = data.content

    db.commit()
    db.refresh(block)
    return schemas.PaperBlockResponse.model_validate(block)


__all__ = ["router"]
