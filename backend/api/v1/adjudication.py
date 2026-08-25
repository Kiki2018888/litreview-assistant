"""裁决 API（ADR-7：AI召回候选组 → 人裁决信号）.

端点（均需 project_id 查询参数，按项目隔离）:
  GET    /candidate-groups        — 列出候选组（含裁决状态 / previously_rejected）
  GET    /candidate-groups/{id}   — 候选组详情（含 claims）
  GET    /signals                 — 列出项目内裁决信号（可按 type/status）
  GET    /signals/export.md       — 导出已采纳 Signal 为 Markdown
  GET    /signals/{id}            — 信号详情（含 evidence 快照）
  POST   /signals                 — 创建裁决（accept/reject）
  PATCH  /signals/{id}            — 修改裁决（改名/改状态/改备注）
  DELETE /signals/{signal_id}/claims/{claim_id}  — 从信号中踢出 claim
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from backend.models.schemas import (
    AdjudicateRequest,
    SignalUpdateRequest,
    SignalResponse,
)
from backend.services.adjudication_service import (
    accept_group,
    reject_group,
    kick_claim,
    update_signal,
    list_signals,
    get_signal_detail,
    list_candidate_groups,
    get_candidate_group_for_project,
    serialize_candidate_group_detail,
    export_accepted_signals_markdown,
    WEAK_ACCEPT_MSG,
)
from backend.services.db import SessionLocal

router = APIRouter(prefix="/api/v1/adjudication", tags=["adjudication"])


# ═══════════════════════════════════════════════
# 候选组
# ═══════════════════════════════════════════════


@router.get("/candidate-groups")
def get_candidate_groups(
    project_id: str = Query(..., description="项目 ID"),
    run_id: str | None = Query(None),
    type: str | None = Query(
        None,
        pattern="^(limitation_cluster|contradiction)$",
        description="候选类型",
    ),
    status: str | None = Query(
        None,
        pattern="^(pending|accepted|rejected)$",
        description="裁决状态",
    ),
    is_weak: bool | None = Query(None, description="弱候选过滤；false 仅返回可主路径采纳的"),
    previously_rejected: bool | None = Query(
        None, description="是否曾在先前 run 被否决（同 fingerprint）",
    ),
):
    """列出指定项目的候选组，附带裁决状态. 可按 type / status / is_weak 过滤."""
    db = SessionLocal()
    try:
        groups = list_candidate_groups(
            db,
            project_id=project_id,
            run_id=run_id,
            candidate_type=type,
            status_filter=status,
            is_weak=is_weak,
            previously_rejected=previously_rejected,
        )
        return groups
    finally:
        db.close()


@router.get("/candidate-groups/{candidate_group_id}")
def get_candidate_group(
    candidate_group_id: str,
    project_id: str = Query(..., description="项目 ID"),
):
    """候选组详情（含 claims）。跨项目 id 视为不存在。"""
    db = SessionLocal()
    try:
        cg = get_candidate_group_for_project(db, candidate_group_id, project_id)
        if not cg:
            raise HTTPException(status_code=404, detail="候选组不存在")

        return serialize_candidate_group_detail(db, cg)
    finally:
        db.close()


# ═══════════════════════════════════════════════
# 信号 — 查询
# ═══════════════════════════════════════════════


@router.get("/signals")
def get_signals(
    project_id: str = Query(..., description="项目 ID"),
    status: str | None = Query(None, pattern="^(pending|accepted|rejected)$"),
    type: str | None = Query(
        None,
        pattern="^(limitation_cluster|contradiction)$",
        description="候选类型",
    ),
):
    """列出指定项目的信号，可按 status / type 过滤."""
    db = SessionLocal()
    try:
        sigs = list_signals(
            db,
            project_id=project_id,
            status_filter=status,
            candidate_type=type,
        )
        return [SignalResponse.model_validate(s) for s in sigs]
    finally:
        db.close()


@router.get(
    "/signals/export.md",
    summary="导出当前项目已采纳 Signal 为 Markdown",
)
def export_signals_markdown(
    project_id: str = Query(..., description="项目 ID"),
):
    """仅导出本项目 status=accepted 的 Signal（含证据指针）。空项目返回合法 Markdown，不 500。"""
    db = SessionLocal()
    try:
        markdown = export_accepted_signals_markdown(db, project_id)
        filename = f"signals-{project_id}.md"
        return Response(
            content=markdown,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    finally:
        db.close()


@router.get("/signals/{signal_id}")
def get_signal(
    signal_id: str,
    project_id: str = Query(..., description="项目 ID"),
):
    """获取信号详情（含 claims）。跨项目 id 视为不存在。"""
    db = SessionLocal()
    try:
        detail = get_signal_detail(db, signal_id, project_id=project_id)
        if not detail:
            raise HTTPException(status_code=404, detail="信号不存在")
        return detail
    finally:
        db.close()


# ═══════════════════════════════════════════════
# 信号 — 创建裁决（A1 采纳 / A2 否决）
# ═══════════════════════════════════════════════


@router.post("/signals", status_code=201)
def create_signal(
    body: AdjudicateRequest,
    project_id: str = Query(..., description="项目 ID"),
):
    """创建裁决：采纳（accept）或否决（reject）一个候选组.

    采纳时 signal_name 可省略，默认用候选组 one-liner/statement。
    弱候选（is_weak）采纳必须显式 accept_weak=true，否则 400。
    候选组必须属于 project_id，否则 404。
    """
    db = SessionLocal()
    try:
        if body.action == "accept":
            sig = accept_group(
                db,
                candidate_group_id=body.candidate_group_id,
                signal_name=body.signal_name,
                human_rationale=body.human_rationale,
                project_id=project_id,
                accept_weak=body.accept_weak,
            )
        elif body.action == "reject":
            sig = reject_group(
                db,
                candidate_group_id=body.candidate_group_id,
                human_rationale=body.human_rationale,
                project_id=project_id,
            )
        else:
            raise HTTPException(status_code=400, detail="action 必须为 accept 或 reject")

        return SignalResponse.model_validate(sig)
    except ValueError as e:
        db.rollback()
        msg = str(e)
        if msg == WEAK_ACCEPT_MSG or "弱候选" in msg:
            status_code = 400
        elif "已被裁决" in msg:
            status_code = 409
        else:
            status_code = 404
        raise HTTPException(status_code=status_code, detail=msg)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ═══════════════════════════════════════════════
# 信号 — 修改裁决（A6）
# ═══════════════════════════════════════════════


@router.patch("/signals/{signal_id}")
def patch_signal(
    signal_id: str,
    body: SignalUpdateRequest,
    project_id: str = Query(..., description="项目 ID"),
):
    """修改已有裁决：改名 / 改状态（rejected→accepted 等）/ 改备注."""
    db = SessionLocal()
    try:
        sig = update_signal(
            db,
            signal_id=signal_id,
            signal_name=body.signal_name,
            status=body.status,
            human_rationale=body.human_rationale,
            project_id=project_id,
        )
        return SignalResponse.model_validate(sig)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ═══════════════════════════════════════════════
# 信号 — 踢出 claim（A3）
# ═══════════════════════════════════════════════


@router.delete("/signals/{signal_id}/claims/{claim_id}")
def remove_claim_from_signal(
    signal_id: str,
    claim_id: str,
    project_id: str = Query(..., description="项目 ID"),
):
    """从信号中踢出一条 claim（标记 manual_remove，留痕不删行）."""
    db = SessionLocal()
    try:
        sc = kick_claim(db, signal_id=signal_id, claim_id=claim_id, project_id=project_id)
        return {
            "success": True,
            "signal_id": sc.signal_id,
            "claim_id": sc.claim_id,
            "added_by": sc.added_by,
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
