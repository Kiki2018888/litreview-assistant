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
    CandidateType,
    Claim,
    ClaimAddition,
    Paper,
    Project,
    Signal,
    SignalClaim,
    SignalStatus,
)
from backend.services.candidate_util import candidate_fingerprint, one_liner

WEAK_ACCEPT_MSG = "弱候选不可走主采纳路径，请显式传入 accept_weak=true"

# ── 内部辅助 ──


def _uuid4() -> str:
    return str(uuid.uuid4())


def _now_utc() -> str:
    """SQLite 兼容的 UTC 时间字符串（避免时区问题）."""
    return datetime.utcnow().isoformat() + "Z"


# ── 查询：获取候选组列表（含裁决状态） ──


def _matches_project(stored_project_id: Optional[str], project_id: Optional[str]) -> bool:
    """project_id 未指定则不过滤；指定则必须与存储值一致。"""
    if project_id is None:
        return True
    return stored_project_id == project_id


def get_candidate_group_for_project(
    db: Session,
    candidate_group_id: str,
    project_id: Optional[str] = None,
) -> Optional[CandidateGroup]:
    """按 id 取候选组；指定 project_id 时跨项目视为不存在。"""
    cg = db.get(CandidateGroup, candidate_group_id)
    if not cg or not _matches_project(cg.project_id, project_id):
        return None
    return cg


def get_signal_for_project(
    db: Session,
    signal_id: str,
    project_id: Optional[str] = None,
) -> Optional[Signal]:
    """按 id 取信号；指定 project_id 时跨项目视为不存在。"""
    sig = db.get(Signal, signal_id)
    if not sig or not _matches_project(sig.project_id, project_id):
        return None
    return sig


def list_candidate_groups(
    db: Session,
    project_id: str,
    run_id: Optional[str] = None,
    candidate_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    is_weak: Optional[bool] = None,
    previously_rejected: Optional[bool] = None,
) -> list[dict]:
    """列出指定项目的候选组，附带裁决状态（已裁决则显示 signal_id/signal_name/status）."""
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
        .where(CandidateGroup.project_id == project_id)
        .order_by(CandidateGroup.created_at.desc())
    )

    if run_id:
        query = query.where(CandidateGroup.run_id == run_id)
    if candidate_type:
        query = query.where(CandidateGroup.candidate_type == candidate_type)
    if is_weak is not None:
        query = query.where(CandidateGroup.is_weak == is_weak)
    if previously_rejected is not None:
        query = query.where(CandidateGroup.previously_rejected == previously_rejected)
    if status_filter == "pending":
        query = query.where(signal_sub.c.status.is_(None))
    elif status_filter:
        query = query.where(signal_sub.c.status == status_filter)

    rows = db.execute(query).all()
    return [
        {
            "id": cg.id,
            "project_id": cg.project_id,
            "run_id": cg.run_id,
            "type": cg.candidate_type,
            "candidate_type": cg.candidate_type,
            "group_label": cg.group_label,
            "statement": cg.statement or cg.group_label,
            "topic": cg.topic,
            "grouping_method": cg.grouping_method,
            "grouping_basis": cg.grouping_basis,
            "cross_paper": cg.cross_paper,
            "claim_count": cg.claim_count,
            "paper_count": cg.paper_count,
            "is_weak": bool(cg.is_weak),
            "previously_rejected": bool(getattr(cg, "previously_rejected", False)),
            "is_solo": cg.claim_count == 1,
            "created_at": cg.created_at.isoformat() if cg.created_at else None,
            "adjudication_status": adj_status,
            "status": adj_status or "pending",
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
            "page": claim.quote_page,
            "topic": claim.topic,
            "subject": getattr(claim, "subject", None),
            "is_limitation": bool(getattr(claim, "is_limitation", False)),
            "context_summary": ctx,
            "claim_form": claim.claim_form,
            "quote_status": claim.quote_status,
            "direction": getattr(claim, "direction", None),
            "comparison_result": getattr(claim, "comparison_result", None),
        })
    return result


def serialize_candidate_group_detail(
    db: Session,
    cg: CandidateGroup,
) -> dict:
    """候选组详情：statement / type / papers / evidence quotes."""
    claims = get_candidate_group_claims(db, cg.id)
    papers_map: dict[str, dict] = {}
    evidence = []
    for claim in claims:
        pid = claim["paper_id"]
        if pid not in papers_map:
            papers_map[pid] = {
                "paper_id": pid,
                "paper_title": claim.get("paper_title") or "Unknown",
            }
        evidence.append({
            "claim_id": claim["claim_id"],
            "paper_id": pid,
            "paper_title": claim.get("paper_title") or "Unknown",
            "quote": claim.get("quote") or "",
            "page": claim.get("quote_page") or 0,
            "quote_page": claim.get("quote_page") or 0,
            "subject": claim.get("subject"),
            "topic": claim.get("topic"),
        })
    return {
        "id": cg.id,
        "project_id": cg.project_id,
        "run_id": cg.run_id,
        "type": getattr(cg, "candidate_type", None) or "limitation_cluster",
        "candidate_type": getattr(cg, "candidate_type", None) or "limitation_cluster",
        "group_label": cg.group_label,
        "statement": getattr(cg, "statement", None) or cg.group_label,
        "topic": cg.topic,
        "grouping_method": cg.grouping_method,
        "grouping_basis": cg.grouping_basis,
        "cross_paper": cg.cross_paper,
        "claim_count": cg.claim_count,
        "paper_count": int(getattr(cg, "paper_count", 0) or 0),
        "is_weak": bool(getattr(cg, "is_weak", False)),
        "previously_rejected": bool(getattr(cg, "previously_rejected", False)),
        "created_at": cg.created_at.isoformat() if cg.created_at else None,
        "papers": list(papers_map.values()),
        "evidence": evidence,
        "claims": claims,
    }


# ── A1: 采纳候选组 → 创建 signal（status=accepted） ──


def _group_claim_ids(db: Session, candidate_group_id: str) -> list[str]:
    rows = (
        db.query(CandidateGroupClaim.claim_id)
        .filter(CandidateGroupClaim.candidate_group_id == candidate_group_id)
        .order_by(CandidateGroupClaim.claim_order)
        .all()
    )
    return [row[0] for row in rows]


def _build_evidence_snapshot(db: Session, candidate_group_id: str) -> list[dict]:
    """Freeze quote+page (and paper) at adjudication time."""
    snapshot = []
    for claim in get_candidate_group_claims(db, candidate_group_id):
        page = int(claim.get("quote_page") or claim.get("page") or 0)
        snapshot.append({
            "claim_id": claim["claim_id"],
            "paper_id": claim.get("paper_id"),
            "paper_title": claim.get("paper_title") or "Unknown",
            "quote": claim.get("quote") or "",
            "page": page,
            "quote_page": page,
            "subject": claim.get("subject"),
            "topic": claim.get("topic"),
        })
    return snapshot


def _signal_identity_from_group(db: Session, cg: CandidateGroup) -> tuple[str, str, str]:
    """Return (candidate_type, statement, fingerprint) stamped onto a Signal."""
    candidate_type = (
        getattr(cg, "candidate_type", None) or CandidateType.LIMITATION_CLUSTER.value
    )
    statement = one_liner(getattr(cg, "statement", None) or cg.group_label)
    fingerprint = getattr(cg, "fingerprint", None) or candidate_fingerprint(
        candidate_type, _group_claim_ids(db, cg.id),
    )
    return candidate_type, statement, fingerprint


def list_rejected_fingerprints(db: Session, project_id: str) -> set[str]:
    """Fingerprints of rejected Signals in this project (for re-discover marking)."""
    fps: set[str] = set()
    rejected = (
        db.query(Signal)
        .filter(
            Signal.project_id == project_id,
            Signal.status == SignalStatus.REJECTED.value,
        )
        .all()
    )
    for sig in rejected:
        if sig.fingerprint:
            fps.add(sig.fingerprint)
            continue
        if not sig.candidate_group_id:
            continue
        cg = db.get(CandidateGroup, sig.candidate_group_id)
        ctype = (
            (cg.candidate_type if cg else None)
            or CandidateType.LIMITATION_CLUSTER.value
        )
        fps.add(candidate_fingerprint(ctype, _group_claim_ids(db, sig.candidate_group_id)))
    return fps


def accept_group(
    db: Session,
    candidate_group_id: str,
    signal_name: Optional[str] = None,
    human_rationale: Optional[str] = None,
    project_id: Optional[str] = None,
    accept_weak: bool = False,
) -> Signal:
    """采纳整个候选组为确认信号.

    弱候选（is_weak）默认不可走主采纳路径，除非 accept_weak=True。
    """
    cg = get_candidate_group_for_project(db, candidate_group_id, project_id)
    if not cg:
        raise ValueError("候选组不存在")

    if bool(getattr(cg, "is_weak", False)) and not accept_weak:
        raise ValueError(WEAK_ACCEPT_MSG)

    # 检查是否已被裁决
    existing = db.query(Signal).filter(
        Signal.candidate_group_id == candidate_group_id,
    ).first()
    if existing:
        raise ValueError(f"该候选组已被裁决（signal_id={existing.id}, status={existing.status}）")

    candidate_type, statement, fingerprint = _signal_identity_from_group(db, cg)
    name = (signal_name or "").strip() or statement or cg.group_label
    evidence = _build_evidence_snapshot(db, candidate_group_id)

    sig = Signal(
        id=_uuid4(),
        project_id=cg.project_id or project_id,
        signal_name=name,
        status=SignalStatus.ACCEPTED.value,
        candidate_type=candidate_type,
        statement=statement or None,
        topic=cg.topic,
        candidate_group_id=candidate_group_id,
        human_rationale=human_rationale,
        evidence_snapshot=evidence,
        fingerprint=fingerprint,
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
    project_id: Optional[str] = None,
) -> Signal:
    """否决候选组（不采纳）. 写入 rejected 记录，不创建 accepted 信号."""
    cg = get_candidate_group_for_project(db, candidate_group_id, project_id)
    if not cg:
        raise ValueError("候选组不存在")

    existing = db.query(Signal).filter(
        Signal.candidate_group_id == candidate_group_id,
    ).first()
    if existing:
        raise ValueError(f"该候选组已被裁决（signal_id={existing.id}, status={existing.status}）")

    candidate_type, statement, fingerprint = _signal_identity_from_group(db, cg)

    sig = Signal(
        id=_uuid4(),
        project_id=cg.project_id or project_id,
        signal_name=None,  # 否决的信号不用命名
        status=SignalStatus.REJECTED.value,
        candidate_type=candidate_type,
        statement=statement or None,
        topic=cg.topic,
        candidate_group_id=candidate_group_id,
        human_rationale=human_rationale,
        evidence_snapshot=[],
        fingerprint=fingerprint,
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
    project_id: Optional[str] = None,
) -> SignalClaim:
    """从信号中移除一条 claim（标记为 manual_remove）."""
    sig = get_signal_for_project(db, signal_id, project_id)
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
    project_id: Optional[str] = None,
) -> Signal:
    """修改信号（改名/改状态/改备注）.

    F-04 fix: 当 status 从 rejected/pending 变为 accepted、且信号当前无 signal_claims
    桥接行时，从 candidate_group_claims 重新导入全部 claim 到 signal_claims。
    """
    sig = get_signal_for_project(db, signal_id, project_id)
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
    project_id: str,
    status_filter: Optional[str] = None,
    candidate_type: Optional[str] = None,
) -> list[Signal]:
    """列出指定项目的信号，可选按状态 / 候选类型过滤."""
    q = db.query(Signal).filter(Signal.project_id == project_id)
    if status_filter:
        q = q.filter(Signal.status == status_filter)
    if candidate_type:
        q = q.filter(Signal.candidate_type == candidate_type)
    return q.order_by(Signal.updated_at.desc()).all()


# ── 查询：获取信号详情（含 claims） ──


def get_signal_detail(
    db: Session,
    signal_id: str,
    project_id: Optional[str] = None,
) -> Optional[dict]:
    """获取信号详情，含 claims。指定 project_id 时跨项目返回 None。"""
    sig = get_signal_for_project(db, signal_id, project_id)
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
            "page": claim.quote_page,
            "topic": claim.topic,
            "subject": getattr(claim, "subject", None),
            "is_limitation": bool(getattr(claim, "is_limitation", False)),
            "context_summary": ctx,
            "claim_form": claim.claim_form,
            "quote_status": claim.quote_status,
            "added_by": sc.added_by,
            "added_at": sc.added_at.isoformat() if sc.added_at else None,
        })

    evidence = list(sig.evidence_snapshot or [])
    if not evidence and sig.status == SignalStatus.ACCEPTED.value:
        evidence = [
            {
                "claim_id": c["claim_id"],
                "paper_id": c.get("paper_id"),
                "paper_title": c.get("paper_title") or "Unknown",
                "quote": c.get("quote") or "",
                "page": int(c.get("quote_page") or c.get("page") or 0),
                "quote_page": int(c.get("quote_page") or c.get("page") or 0),
                "subject": c.get("subject"),
                "topic": c.get("topic"),
            }
            for c in claims
            if c.get("added_by") != ClaimAddition.MANUAL_REMOVE.value
        ]

    return {
        "id": sig.id,
        "project_id": sig.project_id,
        "signal_name": sig.signal_name,
        "status": sig.status,
        "type": sig.candidate_type,
        "candidate_type": sig.candidate_type,
        "statement": sig.statement,
        "topic": sig.topic,
        "candidate_group_id": sig.candidate_group_id,
        "human_rationale": sig.human_rationale,
        "claim_count": sig.claim_count,
        "created_at": sig.created_at.isoformat() if sig.created_at else None,
        "updated_at": sig.updated_at.isoformat() if sig.updated_at else None,
        "adjudicated_at": sig.adjudicated_at.isoformat() if sig.adjudicated_at else None,
        "claims": claims,
        "evidence": evidence,
    }


# ── 导出：已采纳 Signal → Markdown ──


TYPE_LABEL_ZH = {
    CandidateType.LIMITATION_CLUSTER.value: "局限聚类",
    CandidateType.CONTRADICTION.value: "矛盾",
}

_EMPTY_EXPORT_BODY = "当前项目没有已采纳的 Signal。"


def _blockquote(quote: str) -> str:
    text = (quote or "").strip() or "（无摘录）"
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def _evidence_page(ev: dict) -> int:
    raw = ev.get("page")
    if raw is None:
        raw = ev.get("quote_page")
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _format_evidence_item(ev: dict, heading: Optional[str] = None) -> list[str]:
    title = str(ev.get("paper_title") or "Unknown").strip() or "Unknown"
    page_n = _evidence_page(ev)
    page_bit = f"（第 {page_n} 页）" if page_n > 0 else "（页码未知）"
    lines: list[str] = []
    if heading:
        lines.append(f"**{heading}**")
        lines.append("")
    lines.append(f"- **{title}**{page_bit}")
    lines.append("")
    lines.append(_blockquote(str(ev.get("quote") or "")))
    lines.append("")
    return lines


def _signal_evidence(db: Session, sig: Signal) -> list[dict]:
    snapshot = list(sig.evidence_snapshot or [])
    if snapshot:
        return snapshot
    detail = get_signal_detail(db, sig.id, project_id=sig.project_id)
    return list((detail or {}).get("evidence") or [])


def render_accepted_signals_markdown(
    *,
    project_id: str,
    project_name: str,
    signals: list[tuple[Signal, list[dict]]],
    exported_at: Optional[str] = None,
) -> str:
    """Pure Markdown renderer (empty list → valid 'no accepted Signals' doc)."""
    stamp = exported_at or (datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    lines = [
        "# 已采纳 Signal",
        "",
        f"- 项目：{project_name}",
        f"- 项目 ID：`{project_id}`",
        f"- 导出时间：{stamp}",
        "",
    ]
    if not signals:
        lines.append(_EMPTY_EXPORT_BODY)
        lines.append("")
        return "\n".join(lines)

    lines.append(f"共 **{len(signals)}** 条已采纳 Signal。")
    lines.append("")

    for idx, (sig, evidence) in enumerate(signals, start=1):
        title = (
            (sig.signal_name or sig.statement or "（无陈述）").strip() or "（无陈述）"
        )
        ctype = sig.candidate_type or CandidateType.LIMITATION_CLUSTER.value
        label = TYPE_LABEL_ZH.get(ctype, ctype)
        lines.append(f"## {idx}. {title}")
        lines.append("")
        lines.append(f"- 类型：{label}（`{ctype}`）")
        statement = (sig.statement or "").strip()
        if statement and statement != title:
            lines.append(f"- 陈述：{statement}")
        lines.append("")

        is_contradiction = ctype == CandidateType.CONTRADICTION.value
        lines.append("### 双方证据" if is_contradiction else "### 证据")
        lines.append("")
        if not evidence:
            lines.append("（无证据指针）")
            lines.append("")
            continue
        if is_contradiction:
            side_labels = ("一方", "另一方")
            for ev_i, ev in enumerate(evidence):
                heading = side_labels[ev_i] if ev_i < 2 else f"证据 {ev_i + 1}"
                lines.extend(_format_evidence_item(ev, heading=heading))
        else:
            for ev in evidence:
                lines.extend(_format_evidence_item(ev))

    return "\n".join(lines)


def export_accepted_signals_markdown(db: Session, project_id: str) -> str:
    """Build Markdown of accepted Signals for this project.

    Missing project → ValueError（路由映射 404）。空项目仍返回合法 Markdown。
    """
    project = db.get(Project, project_id)
    if not project:
        raise ValueError("项目不存在")

    accepted = list_signals(
        db,
        project_id=project_id,
        status_filter=SignalStatus.ACCEPTED.value,
    )
    packed = [(sig, _signal_evidence(db, sig)) for sig in accepted]
    return render_accepted_signals_markdown(
        project_id=project_id,
        project_name=project.name or project_id,
        signals=packed,
    )


__all__ = [
    "accept_group",
    "reject_group",
    "kick_claim",
    "update_signal",
    "list_signals",
    "get_signal_detail",
    "list_candidate_groups",
    "get_candidate_group_claims",
    "serialize_candidate_group_detail",
    "get_candidate_group_for_project",
    "get_signal_for_project",
    "list_rejected_fingerprints",
    "export_accepted_signals_markdown",
    "render_accepted_signals_markdown",
    "WEAK_ACCEPT_MSG",
]
