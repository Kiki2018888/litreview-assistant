"""裁决 API（ADR-7：AI召回候选组 → 人裁决信号）.

端点：
  GET    /candidate-groups        — 列出候选组（含裁决状态）
  GET    /candidate-groups/{id}   — 候选组详情（含 claims）
  GET    /signals                 — 列出所有裁决信号
  GET    /signals/{id}            — 信号详情
  POST   /signals                 — 创建裁决（accept/reject）
  PATCH  /signals/{id}            — 修改裁决（改名/改状态/改备注）
  DELETE /signals/{signal_id}/claims/{claim_id}  — 从信号中踢出 claim
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.models.schemas import (
    AdjudicateRequest,
    SignalUpdateRequest,
    SignalResponse,
    SignalDetailResponse,
    SignalClaimResponse,
    CandidateGroupResponse,
)
from backend.services.adjudication_service import (
    accept_group,
    reject_group,
    kick_claim,
    update_signal,
    list_signals,
    get_signal_detail,
    list_candidate_groups,
    get_candidate_group_claims,
)
from backend.services.db import SessionLocal

router = APIRouter(prefix="/api/v1/adjudication", tags=["adjudication"])


# ═══════════════════════════════════════════════
# 候选组
# ═══════════════════════════════════════════════


@router.get("/candidate-groups")
def get_candidate_groups(run_id: str | None = Query(None)):
    """列出所有候选组，附带裁决状态."""
    db = SessionLocal()
    try:
        groups = list_candidate_groups(db, run_id=run_id)
        return groups
    finally:
        db.close()


@router.get("/candidate-groups/{candidate_group_id}")
def get_candidate_group(candidate_group_id: str):
    """候选组详情（含 claims）."""
    db = SessionLocal()
    try:
        cg = db.query(
            __import__("backend.models.tables", fromlist=["CandidateGroup"]).CandidateGroup
        ).get(candidate_group_id)
        if not cg:
            raise HTTPException(status_code=404, detail="候选组不存在")

        claims = get_candidate_group_claims(db, candidate_group_id)
        return {
            "id": cg.id,
            "run_id": cg.run_id,
            "group_label": cg.group_label,
            "topic": cg.topic,
            "grouping_method": cg.grouping_method,
            "grouping_basis": cg.grouping_basis,
            "cross_paper": cg.cross_paper,
            "claim_count": cg.claim_count,
            "created_at": cg.created_at.isoformat() if cg.created_at else None,
            "claims": claims,
        }
    finally:
        db.close()


# ═══════════════════════════════════════════════
# 信号 — 查询
# ═══════════════════════════════════════════════


@router.get("/signals")
def get_signals(status: str | None = Query(None, pattern="^(pending|accepted|rejected)$")):
    """列出所有信号."""
    db = SessionLocal()
    try:
        sigs = list_signals(db, status_filter=status)
        return sigs
    finally:
        db.close()


@router.get("/signals/{signal_id}")
def get_signal(signal_id: str):
    """获取信号详情（含 claims）."""
    db = SessionLocal()
    try:
        detail = get_signal_detail(db, signal_id)
        if not detail:
            raise HTTPException(status_code=404, detail="信号不存在")
        return detail
    finally:
        db.close()


# ═══════════════════════════════════════════════
# 信号 — 创建裁决（A1 采纳 / A2 否决）
# ═══════════════════════════════════════════════


@router.post("/signals", status_code=201)
def create_signal(body: AdjudicateRequest):
    """创建裁决：采纳（accept）或否决（reject）一个候选组.

    采纳时 signal_name 必填；否决时 signal_name 留空。
    """
    db = SessionLocal()
    try:
        if body.action == "accept":
            if not body.signal_name:
                raise HTTPException(status_code=400, detail="采纳时必须提供 signal_name")
            sig = accept_group(
                db,
                candidate_group_id=body.candidate_group_id,
                signal_name=body.signal_name,
                human_rationale=body.human_rationale,
            )
        elif body.action == "reject":
            sig = reject_group(
                db,
                candidate_group_id=body.candidate_group_id,
                human_rationale=body.human_rationale,
            )
        else:
            raise HTTPException(status_code=400, detail="action 必须为 accept 或 reject")

        return SignalResponse.model_validate(sig)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(e))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ═══════════════════════════════════════════════
# 信号 — 修改裁决（A6）
# ═══════════════════════════════════════════════


@router.patch("/signals/{signal_id}")
def patch_signal(signal_id: str, body: SignalUpdateRequest):
    """修改已有裁决：改名 / 改状态（rejected→accepted 等）/ 改备注."""
    db = SessionLocal()
    try:
        sig = update_signal(
            db,
            signal_id=signal_id,
            signal_name=body.signal_name,
            status=body.status,
            human_rationale=body.human_rationale,
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
def remove_claim_from_signal(signal_id: str, claim_id: str):
    """从信号中踢出一条 claim（标记 manual_remove，留痕不删行）."""
    db = SessionLocal()
    try:
        sc = kick_claim(db, signal_id=signal_id, claim_id=claim_id)
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
