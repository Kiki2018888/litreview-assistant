"""候选组落库 (Step 5) — 将聚类结果写入 candidate_groups + candidate_group_claims.

设计原则:
- 每次聚类生成新 run_id，旧批次保留为不可变快照（不覆盖）。
- 事务包裹：一个候选组的 candidate_group + claims 要么全写、要么全不写。
- 不碰 signals 表（信号由人裁决后才产生，ADR-7）。
- subject 不在此表冗余，裁决面板通过 candidate_group_claims JOIN claims 获取。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.models.tables import CandidateGroup, CandidateGroupClaim, CandidateType
from backend.services.adjudication_service import list_rejected_fingerprints
from backend.services.candidate_util import (
    candidate_fingerprint,
    evidence_paper_ids,
    has_quote_evidence,
    one_liner,
)
from backend.services import db as db_mod

logger = logging.getLogger(__name__)


def _uuid4() -> str:
    return str(uuid.uuid4())


def save_clustering_result(
    result: dict[str, Any],
    project_id: str | None = None,
) -> str:
    """将聚类结果字典写入 candidate_groups + candidate_group_claims。

    参数:
        result: run_clustering() 返回的 dict，结构见 limitation_clusterer.py。
        project_id: 项目 ID（优先于 result["project_id"]，必须有值才能落库）。

    返回:
        run_id: 本次聚类运行的批次 ID（UUID 字符串）。

    要求:
        - result["groups"] 必须非空。
        - 每条 group 含 candidate_group_id(int) + evidence(list[dict])。
        - 每个 evidence 含 claim_id(str)。
        - project_id 必须可解析（参数或 result["project_id"]）。

    事务行为:
        如果中途失败，整个 run 的全部写入回滚，不产生半截数据.

    ADR-7:
        只 INSERT 新的 candidate_groups。绝不 UPDATE/DELETE signals。
        已否决候选（同 project + type + claim-set fingerprint）落库时标记
        previously_rejected=True，而不是跳过，便于复查。
    """
    groups = result.get("groups", [])
    if not groups:
        logger.warning("save_clustering_result: 无候选组可写入，跳过")
        return ""

    pid = project_id or result.get("project_id") or ""
    if not pid:
        raise ValueError("save_clustering_result 需要 project_id")

    run_id = _uuid4()
    logger.info(
        "开始落库: run_id=%s, project_id=%s, 候选组数=%d",
        run_id[:12], str(pid)[:12], len(groups),
    )

    db: Session = db_mod.SessionLocal()
    try:
        # 事务包裹：with db.begin() 会在退出时 commit 或 rollback
        with db.begin():
            rejected_fps = list_rejected_fingerprints(db, pid)
            for g in groups:
                evidence = g.get("evidence", [])
                candidate_type = (
                    g.get("candidate_type")
                    or CandidateType.LIMITATION_CLUSTER.value
                )
                paper_ids = evidence_paper_ids(evidence)
                paper_count = int(g.get("paper_count") or len(paper_ids) or 0)
                if "is_weak" in g:
                    is_weak = bool(g.get("is_weak"))
                elif candidate_type == CandidateType.CONTRADICTION.value:
                    is_weak = any(
                        not has_quote_evidence(ev.get("quote"), ev.get("page"))
                        for ev in evidence
                    )
                else:
                    is_weak = paper_count < 2
                statement = one_liner(g.get("statement") or g.get("group_label"))
                label = statement or one_liner(g["group_label"])
                method = (g.get("grouping_method") or "")[:50]
                claim_ids = [
                    str(ev["claim_id"]) for ev in evidence if ev.get("claim_id")
                ]
                fingerprint = candidate_fingerprint(candidate_type, claim_ids)
                previously_rejected = fingerprint in rejected_fps

                # ── 写入 candidate_groups（不碰 signals） ──
                cg = CandidateGroup(
                    id=_uuid4(),
                    project_id=pid,
                    run_id=run_id,
                    candidate_type=candidate_type,
                    group_label=label[:200],
                    statement=(statement or None) and statement[:200],
                    topic=g["topic"],
                    grouping_method=method,
                    grouping_basis=g.get("grouping_basis", ""),
                    cross_paper=g.get("cross_paper", False),
                    claim_count=g.get("claim_count", len(evidence)),
                    paper_count=paper_count,
                    is_weak=is_weak,
                    fingerprint=fingerprint,
                    previously_rejected=previously_rejected,
                )
                db.add(cg)
                db.flush()  # 确保 cg.id 可用

                evidence = g.get("evidence", [])
                for order_idx, ev in enumerate(evidence):
                    cgc = CandidateGroupClaim(
                        candidate_group_id=cg.id,
                        claim_id=ev["claim_id"],
                        claim_order=order_idx,
                    )
                    db.add(cgc)

                logger.debug(
                    "  group=%s label=%s claims=%d",
                    cg.id[:12], g["group_label"][:40], len(evidence),
                )

        total_claims = sum(len(g.get("evidence", [])) for g in groups)
        logger.info(
            "落库完成: run_id=%s, %d 候选组, %d 条 claim 关联",
            run_id[:12], len(groups), total_claims,
        )
    except Exception:
        logger.exception("落库失败: run_id=%s", run_id[:12])
        raise
    finally:
        db.close()

    return run_id


__all__ = ["save_clustering_result"]
