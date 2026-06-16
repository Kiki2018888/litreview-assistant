"""裁决领域逻辑（ADR-7：AI召回候选组 → 人裁决信号）.

支持动作：A1 采纳 / A2 否决 / A3 踢出claim / A5 待定(默认) / A6 改裁决.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from backend.models.tables import (
    CandidateGroup,
    CandidateGroupClaim,
    Claim,
    ClaimAddition,
    Paper,
    Signal,
    SignalClaim,
    SignalStatus,
)

# ── 内部辅助 ──


def _uuid4() -> str:
    return str(uuid.uuid4())


def _now_utc() -> str:
    """SQLite 兼容的 UTC 时间字符串（避免时区问题）."""
    return datetime.utcnow().isoformat() + "Z"


# ── 查询：获取候选组列表（含裁决状态） ──


def list_candidate_groups(
    db: Session,
    run_id: Optional[str] = None,
) -> list[dict]:
    """列出候选组，附带裁决状态（已裁决则显示 signal_id/signal_name/status）."""
    # 子查询：每个 candidate_group 关联的 signal
    signal_sub = (
        select(
            Signal.candidate_group_id,
            Signal.id.label("signal_id"),
            Signal.signal_name,
            Signal.status,
        )
        .where(Signal.candidate_group_id.isnot(None))
        .subquery("sig")
    )

    query = (
        select(
            CandidateGroup,
            signal_sub.c.signal_id,
            signal_sub.c.signal_name,
            signal_sub.c.status.label("adjudication_status"),
        )
        .outerjoin(signal_sub, CandidateGroup.id == signal_sub.c.candidate_group_id)
        .order_by(CandidateGroup.created_at.desc())
    )

    if run_id:
        query = query.where(CandidateGroup.run_id == run_id)

    rows = db.execute(query).all()
    return [
        {
            "id": cg.id,
            "run_id": cg.run_id,
            "group_label": cg.group_label,
            "topic": cg.topic,
            "grouping_method": cg.grouping_method,
            "grouping_basis": cg.grouping_basis,
            "cross_paper": cg.cross_paper,
            "claim_count": cg.claim_count,
            "created_at": cg.created_at.isoformat() if cg.created_at else None,
            "adjudication_status": adj_status,
            "signal_id": sig_id,
            "signal_name": sig_name,
        }
        for cg, sig_id, sig_name, adj_status in rows
    ]


# ── 查询：获取候选组的 claims（含论文信息） ──


def get_candidate_group_claims(
    db: Session,
    candidate_group_id: str,
) -> list[dict]:
    """获取候选组内的全部 claim，附带论文标题和 context 摘要."""
    import json

    rows = (
        db.query(CandidateGroupClaim, Claim, Paper.title)
        .join(Claim, CandidateGroupClaim.claim_id == Claim.id)
        .join(Paper, Claim.paper_id == Paper.id)
        .filter(CandidateGroupClaim.candidate_group_id == candidate_group_id)
        .order_by(CandidateGroupClaim.claim_order)
        .all()
    )

    result = []
    for cgc, claim, paper_title in rows:
        ctx = ""
        if claim.context:
            try:
                ctx_obj = json.loads(claim.context) if isinstance(claim.context, str) else claim.context
                parts = []
                for k in ("model", "species", "cell_type"):
                    v = ctx_obj.get(k)
                    if v:
                        parts.append(str(v))
                ctx = " | ".join(parts) if parts else ""
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
        result.append({
            "claim_id": claim.id,
            "paper_id": claim.paper_id,
            "paper_title": paper_title or "Unknown",
            "quote": claim.quote,
            "quote_page": claim.quote_page,
            "topic": claim.topic,
            "context_summary": ctx,
            "claim_form": claim.claim_form,
            "quote_status": claim.quote_status,
        })
    return result


# ── A1: 采纳候选组 → 创建 signal（status=accepted） ──


def accept_group(
    db: Session,
    candidate_group_id: str,
    signal_name: str,
    human_rationale: Optional[str] = None,
) -> Signal:
    """采纳整个候选组为确认信号."""
    cg = db.get(CandidateGroup, candidate_group_id)
    if not cg:
        raise ValueError("候选组不存在")

    # 检查是否已被裁决
    existing = db.query(Signal).filter(
        Signal.candidate_group_id == candidate_group_id,
    ).first()
    if existing:
        raise ValueError(f"该候选组已被裁决（signal_id={existing.id}, status={existing.status}）")

    sig = Signal(
        id=_uuid4(),
        signal_name=signal_name,
        status=SignalStatus.ACCEPTED.value,
        topic=cg.topic,
        candidate_group_id=candidate_group_id,
        human_rationale=human_rationale,
        claim_count=cg.claim_count,
        adjudicated_at=datetime.utcnow(),
    )
    db.add(sig)
    db.flush()

    # 将候选组的全部 claim 导入 signal_claims
    cgc_rows = (
        db.query(CandidateGroupClaim)
        .filter(CandidateGroupClaim.candidate_group_id == candidate_group_id)
        .all()
    )
    for cgc in cgc_rows:
        sc = SignalClaim(
            signal_id=sig.id,
            claim_id=cgc.claim_id,
            added_by=ClaimAddition.ADOPTED_FROM_GROUP.value,
        )
        db.add(sc)

    db.commit()
    db.refresh(sig)
    return sig


# ── A2: 否决候选组 → 创建 signal（status=rejected, 不关联 claims） ──


def reject_group(
    db: Session,
    candidate_group_id: str,
    human_rationale: Optional[str] = None,
) -> Signal:
    """否决候选组（不采纳）."""
    cg = db.get(CandidateGroup, candidate_group_id)
    if not cg:
        raise ValueError("候选组不存在")

    existing = db.query(Signal).filter(
        Signal.candidate_group_id == candidate_group_id,
    ).first()
    if existing:
        raise ValueError(f"该候选组已被裁决（signal_id={existing.id}, status={existing.status}）")

    sig = Signal(
        id=_uuid4(),
        signal_name=None,  # 否决的信号不用命名
        status=SignalStatus.REJECTED.value,
        topic=cg.topic,
        candidate_group_id=candidate_group_id,
        human_rationale=human_rationale,
        claim_count=0,  # 否决的不计 claim
        adjudicated_at=datetime.utcnow(),
    )
    db.add(sig)
    db.commit()
    db.refresh(sig)
    return sig


# ── A3: 从信号中踢出单条 claim（标 manual_remove，留痕不删行） ──


def kick_claim(
    db: Session,
    signal_id: str,
    claim_id: str,
) -> SignalClaim:
    """从信号中移除一条 claim（标记为 manual_remove）."""
    sig = db.get(Signal, signal_id)
    if not sig:
        raise ValueError("信号不存在")

    sc = db.query(SignalClaim).filter(
        and_(
            SignalClaim.signal_id == signal_id,
            SignalClaim.claim_id == claim_id,
        )
    ).first()
    if not sc:
        raise ValueError("该 claim 不属于此信号")

    if sc.added_by == ClaimAddition.MANUAL_REMOVE.value:
        raise ValueError("该 claim 已被踢出")

    sc.added_by = ClaimAddition.MANUAL_REMOVE.value

    # Must flush before the count query — SQLAlchemy's autoflush
    # may not reliably make the UPDATE visible to the subsequent
    # SELECT in SQLite, causing claim_count to stay stale.
    db.flush()

    # 更新信号 claim_count
    active_count = (
        db.query(SignalClaim)
        .filter(
            and_(
                SignalClaim.signal_id == signal_id,
                SignalClaim.added_by != ClaimAddition.MANUAL_REMOVE.value,
            )
        )
        .count()
    )
    sig.claim_count = active_count
    sig.updated_at = datetime.utcnow()  # type: ignore[assignment]

    db.commit()
    db.refresh(sc)
    return sc


# ── A6: 修改已有裁决 ──


def update_signal(
    db: Session,
    signal_id: str,
    signal_name: Optional[str] = None,
    status: Optional[SignalStatus] = None,
    human_rationale: Optional[str] = None,
) -> Signal:
    """修改信号（改名/改状态/改备注）.

    F-04 fix: 当 status 从 rejected/pending 变为 accepted、且信号当前无 signal_claims
    桥接行时，从 candidate_group_claims 重新导入全部 claim 到 signal_claims。
    """
    sig = db.get(Signal, signal_id)
    if not sig:
        raise ValueError("信号不存在")

    changed = False

    if signal_name is not None:
        sig.signal_name = signal_name
        changed = True

    if status is not None:
        old_status = sig.status
        sig.status = status.value
        changed = True
        # 首次从 pending → accepted/rejected 时记录裁决时间
        if old_status == SignalStatus.PENDING.value and status in (
            SignalStatus.ACCEPTED,
            SignalStatus.REJECTED,
        ):
            sig.adjudicated_at = datetime.utcnow()

        # F-04: rejected/pending → accepted + 无桥接行 → 从候选组重新导入 claims
        if (
            status == SignalStatus.ACCEPTED
            and old_status != SignalStatus.ACCEPTED.value
            and sig.candidate_group_id
        ):
            db.flush()  # 确保 status 变更对后续查询可见
            existing_count = (
                db.query(SignalClaim)
                .filter(
                    and_(
                        SignalClaim.signal_id == signal_id,
                        SignalClaim.added_by != ClaimAddition.MANUAL_REMOVE.value,
                    )
                )
                .count()
            )
            if existing_count == 0:
                cgc_rows = (
                    db.query(CandidateGroupClaim)
                    .filter(CandidateGroupClaim.candidate_group_id == sig.candidate_group_id)
                    .all()
                )
                for cgc in cgc_rows:
                    db.add(SignalClaim(
                        signal_id=sig.id,
                        claim_id=cgc.claim_id,
                        added_by=ClaimAddition.ADOPTED_FROM_GROUP.value,
                    ))
                sig.claim_count = len(cgc_rows)

    if human_rationale is not None:
        sig.human_rationale = human_rationale
        changed = True

    if changed:
        sig.updated_at = datetime.utcnow()  # type: ignore[assignment]
        db.commit()
        db.refresh(sig)

    return sig


# ── 查询：获取信号列表 ──


def list_signals(
    db: Session,
    status_filter: Optional[str] = None,
) -> list[Signal]:
    """列出所有信号，可选按状态过滤."""
    q = db.query(Signal)
    if status_filter:
        q = q.filter(Signal.status == status_filter)
    return q.order_by(Signal.updated_at.desc()).all()


# ── 查询：获取信号详情（含 claims） ──


def get_signal_detail(db: Session, signal_id: str) -> Optional[dict]:
    """获取信号详情，含 claims."""
    sig = db.get(Signal, signal_id)
    if not sig:
        return None

    import json

    sc_rows = (
        db.query(SignalClaim, Claim, Paper.title)
        .join(Claim, SignalClaim.claim_id == Claim.id)
        .join(Paper, Claim.paper_id == Paper.id)
        .filter(SignalClaim.signal_id == signal_id)
        .order_by(SignalClaim.added_at)
        .all()
    )

    claims = []
    for sc, claim, paper_title in sc_rows:
        ctx = ""
        if claim.context:
            try:
                ctx_obj = json.loads(claim.context) if isinstance(claim.context, str) else claim.context
                parts = []
                for k in ("model", "species", "cell_type"):
                    v = ctx_obj.get(k)
                    if v:
                        parts.append(str(v))
                ctx = " | ".join(parts) if parts else ""
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
        claims.append({
            "claim_id": claim.id,
            "paper_id": claim.paper_id,
            "paper_title": paper_title or "Unknown",
            "quote": claim.quote,
            "quote_page": claim.quote_page,
            "topic": claim.topic,
            "context_summary": ctx,
            "claim_form": claim.claim_form,
            "quote_status": claim.quote_status,
            "added_by": sc.added_by,
            "added_at": sc.added_at.isoformat() if sc.added_at else None,
        })

    return {
        "id": sig.id,
        "signal_name": sig.signal_name,
        "status": sig.status,
        "topic": sig.topic,
        "candidate_group_id": sig.candidate_group_id,
        "human_rationale": sig.human_rationale,
        "claim_count": sig.claim_count,
        "created_at": sig.created_at.isoformat() if sig.created_at else None,
        "updated_at": sig.updated_at.isoformat() if sig.updated_at else None,
        "adjudicated_at": sig.adjudicated_at.isoformat() if sig.adjudicated_at else None,
        "claims": claims,
    }


__all__ = [
    "accept_group",
    "reject_group",
    "kick_claim",
    "update_signal",
    "list_signals",
    "get_signal_detail",
    "list_candidate_groups",
    "get_candidate_group_claims",
]
