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
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.models.tables import CandidateGroup, CandidateGroupClaim
from backend.services.db import SessionLocal

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
        如果中途失败，整个 run 的全部写入回滚，不产生半截数据。
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

    db: Session = SessionLocal()
    try:
        # 事务包裹：with db.begin() 会在退出时 commit 或 rollback
        with db.begin():
            for g in groups:
                # ── 写入 candidate_groups ──
                cg = CandidateGroup(
                    id=_uuid4(),
                    project_id=pid,
                    run_id=run_id,
                    group_label=g["group_label"],
                    topic=g["topic"],
                    grouping_method=g["grouping_method"],
                    grouping_basis=g.get("grouping_basis", ""),
                    cross_paper=g.get("cross_paper", False),
                    claim_count=g.get("claim_count", len(g.get("evidence", []))),
                )
                db.add(cg)
                db.flush()  # 确保 cg.id 可用

                # ── 写入 candidate_group_claims ──
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
