"""局限聚类服务 — ADR-7 版：按 topic 分桶 + LLM 辅助分组，产出候选组+evidence。

复用 _run_clustering.py 的核心逻辑，改造要点：
- ClaimRecord 加 subject 字段（ADR-7 命脉，区分"RPE65 vs 光感受器"）
- DB 读取用 ORM（SessionLocal），接受 project_id 泛化
- AI 调用用系统统一客户端 KimiClient（不写死 DeepSeek）
- 去除硬编码 DB 路径/论文名
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.models.tables import CandidateType, Claim, Paper
from backend.services.candidate_util import one_liner
from backend.services import db as db_mod
from backend.services.kimi_client import chat as kimi_chat, get_model_name

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 数据结构（ADR-7 版）
# ═══════════════════════════════════════════════════════════════


@dataclass
class ClaimRecord:
    """一条原子论断（含完整的可追溯证据）。"""
    id: str
    paper_id: str
    paper_title: str
    subject: str = ""          # ADR-7 命脉：研究对象（如 "hiPSC-derived RPE cells"）
    topic: str = "other"
    claim_form: str = ""
    quote: str = ""
    quote_page: int = 0
    is_limitation: bool = False
    context_summary: str = ""  # 从 context JSON 提取的紧凑摘要（物种/模型/细胞类型等）


@dataclass
class CandidateGroup:
    """一个候选组 = AI 召回的可能相关的一组局限（非 AI 结论！）。

    ADR-7: 这不是"信号"，这是"候选"。group_label 是描述性标签（如
    "topic=other 组内 LLM 辅助分组: 涉及免疫排斥与移植物存活"），不是
    AI 断言的那个"共同局限 X"。实质共性判断留给人的裁决面板。
    """
    group_label: str
    topic: str
    grouping_method: str
    grouping_basis: str
    claims: list[ClaimRecord] = field(default_factory=list)
    cross_paper: bool = False


# ═══════════════════════════════════════════════════════════════
# DB 读取（ORM 版，泛化 project_id）
# ═══════════════════════════════════════════════════════════════


def _format_context(context: dict | str | None) -> str:
    """从 context（ORM JSON dict 或旧版 JSON string）提取紧凑摘要。"""
    if not context:
        return ""
    if isinstance(context, str):
        try:
            ctx = json.loads(context)
        except (json.JSONDecodeError, TypeError):
            return ""
    elif isinstance(context, dict):
        ctx = context
    else:
        return ""
    if not isinstance(ctx, dict):
        return ""
    parts = []
    for key in ("model", "species", "cell_type", "route", "dose", "timepoint"):
        val = ctx.get(key)
        if val:
            parts.append(str(val))
    return " | ".join(parts) if parts else ""


def fetch_limitation_claims(project_id: str) -> list[ClaimRecord]:
    """从 DB 读取该项目下所有 is_limitation=True 的 claims。

    使用 ORM（不再硬编码 sqlite3 路径），接受 project_id 泛化。
    subject 字段必须读出并透传到 ClaimRecord。
    """
    db = db_mod.SessionLocal()
    try:
        rows = (
            db.query(Claim, Paper.title)
            .join(Paper, Claim.paper_id == Paper.id)
            .filter(
                Paper.project_id == project_id,
                Claim.is_limitation == True,  # noqa: E712
            )
            .order_by(Paper.title, Claim.id)
            .all()
        )
        records: list[ClaimRecord] = []
        for claim, paper_title in rows:
            ctx_summary = _format_context(claim.context)
            records.append(ClaimRecord(
                id=claim.id,
                paper_id=claim.paper_id,
                paper_title=paper_title or "Unknown",
                subject=claim.subject or "",
                topic=claim.topic or "other",
                claim_form=claim.claim_form,
                quote=claim.quote or "",
                quote_page=claim.quote_page,
                is_limitation=claim.is_limitation,
                context_summary=ctx_summary,
            ))
        return records
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# LLM 分组辅助（ADR-7: 只做分组，不做实质裁决）
# ═══════════════════════════════════════════════════════════════

GROUPING_PROMPT = """你是一位科研文献分析助手。以下是一组来自多篇文献的【研究局限性】原始论断，
它们已按大主题（topic）分过组。你的任务是：在组内进一步找出【表面相似/可能相关】的论断，
将它们归为几个候选组。

【你的角色（关键！）】
你只做"分组辅助"——找出措辞或话题上相似的条目，归在一起供人审查。
你**不判断**它们是否"真的是同一个局限"——那是人（领域专家）的事。
你的输出不是"结论"，是"待审核的候选"。

【分组原则】
1. 两条论断如果讨论【同一类对象/同一类问题】（如都关于突触连接/都关于免疫排斥/
   都关于细胞分化状态），归为一组。
2. 宁可多分组、每组少几条，也不要粗暴合并话题不同的条目。
3. 孤例（与其他都不同）可自成一組。
4. 只返回 JSON，一个字符都不能多。

【输出格式】
[
  {{
    "group_label": "描述性标签（如'涉及突触连接确认与否'或'涉及免疫排斥与移植物存活'）",
    "claim_indices": [1, 3],
    "grouping_basis": "分组依据（客观事实，如'两条都讨论突触连接未被确认'或'都提到免疫排斥'）"
  }}
]

【待分组论断】
{topic_label}

{claims_text}
"""


def _build_claims_for_prompt(claims: list[ClaimRecord]) -> tuple[str, dict[int, str]]:
    """构建 prompt 用的 claims 列表，含 subject 信息帮助 LLM 识别对象差异。

    返回 (文本, {index: full_id})。
    """
    lines = []
    idx_map: dict[int, str] = {}
    for i, c in enumerate(claims, 1):
        paper_short = c.paper_title.split(":")[0].split(".")[0][:40]
        subject_info = f" [对象: {c.subject}]" if c.subject else ""
        ctx = f" [{c.context_summary}]" if c.context_summary else ""
        lines.append(
            f"[{i}] [{paper_short}] p{c.quote_page}{subject_info}{ctx}\n"
            f"    \"{c.quote[:250]}\""
        )
        idx_map[i] = c.id
    return "\n\n".join(lines), idx_map


async def group_one_topic(topic: str, claims: list[ClaimRecord]) -> list[CandidateGroup]:
    """对同一个 topic 下的 limitation claims 调用 LLM 做分组辅助。

    使用系统统一客户端 KimiClient（同 Step1），不写死模型。
    ADR-7: 这里只返回候选组，不做实质裁决。
    """
    if len(claims) <= 1:
        return [_make_solo_group(topic, claims)]

    claims_text, idx_to_id = _build_claims_for_prompt(claims)
    prompt = GROUPING_PROMPT.format(
        topic_label=f"大主题: {topic.upper()} | 共 {len(claims)} 条",
        claims_text=claims_text,
    )

    try:
        content = await kimi_chat(
            messages=[
                {
                    "role": "system",
                    "content": "你是文献分析助手。只输出 JSON，不输出其他文字。不代替人类专家做实质判断。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=4096,
        )
    except Exception as exc:
        logger.exception("LLM 分组调用失败 topic=%s", topic)
        # 回退：每条孤例自成一組
        return [_make_solo_group(topic, [c]) for c in claims]

    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1].rsplit("\n```", 1)[0]

    try:
        raw_groups = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("LLM returned invalid JSON for topic=%s, falling back to solo groups", topic)
        return [_make_solo_group(topic, [c]) for c in claims]

    full_id_to_claim = {c.id: c for c in claims}
    groups: list[CandidateGroup] = []
    assigned: set[str] = set()

    for rg in raw_groups:
        indices = rg.get("claim_indices", [])
        found_claims = [
            full_id_to_claim[idx_to_id[idx]]
            for idx in indices
            if idx in idx_to_id and idx_to_id[idx] in full_id_to_claim
        ]
        if not found_claims:
            continue
        for c in found_claims:
            assigned.add(c.id)
        num_papers = len(set(c.paper_id for c in found_claims))
        group = CandidateGroup(
            group_label=rg.get("group_label", f"候选组: {topic}"),
            topic=topic,
            grouping_method="topic + LLM 辅助分组",
            grouping_basis=rg.get("grouping_basis", f"LLM 按表面相似度分组（{topic} 主题）"),
            claims=found_claims,
            cross_paper=num_papers > 1,
        )
        groups.append(group)

    # 未分配的：各成孤例
    for c in claims:
        if c.id not in assigned:
            groups.append(_make_solo_group(topic, [c]))

    return groups


def _make_solo_group(topic: str, claims: list[ClaimRecord]) -> CandidateGroup:
    """构造孤例候选组（确定性，不调 LLM）。"""
    if len(claims) == 1:
        label = one_liner(f"孤例: {claims[0].quote}")
    else:
        label = one_liner(f"候选组: {topic}")
    return CandidateGroup(
        group_label=label,
        topic=topic,
        grouping_method="topic only (孤例 / 确定性自成一組)",
        grouping_basis=f"确定性分组: topic={topic}, 无其他条目可配对",
        claims=claims,
        cross_paper=len(set(c.paper_id for c in claims)) > 1,
    )


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════


async def run_clustering(project_id: str) -> dict[str, Any]:
    """对指定项目执行局限聚类，返回 ADR-7 结构的结果字典。

    结果不落库（落库是 Step5），直接返回给 API 层。

    返回结构:
    {
        "project_id": str,
        "total_claims": int,
        "total_candidate_groups": int,
        "model_used": str,
        "wall_time_seconds": float,
        "groups": [ { candidate_group_id, topic, group_label, grouping_method,
                      grouping_basis, cross_paper, paper_count, claim_count,
                      adjudication: {status, signal_name, ...},
                      evidence: [{claim_id, paper_id, paper_title, subject,
                                  topic, quote, page, context}] } ]
    }
    """
    t0 = time.perf_counter()
    model_name = get_model_name()

    # 1. 从 DB 读取该项目的 limitation claims
    claims = fetch_limitation_claims(project_id)
    logger.info(
        "项目 %s: 读取 %d 条 is_limitation=true 的 claims，模型=%s",
        project_id[:12], len(claims), model_name,
    )

    if not claims:
        elapsed = time.perf_counter() - t0
        return {
            "project_id": project_id,
            "total_claims": 0,
            "total_candidate_groups": 0,
            "model_used": model_name,
            "wall_time_seconds": round(elapsed, 2),
            "groups": [],
        }

    # 2. 按 topic 确定性分组（召回层）
    topics: dict[str, list[ClaimRecord]] = {}
    for c in claims:
        topics.setdefault(c.topic, []).append(c)

    logger.info(
        "按 topic 确定性分组: %s",
        {k: len(v) for k, v in topics.items()},
    )

    # 3. 每个 topic 调 LLM 做分组辅助
    all_groups: list[CandidateGroup] = []
    for topic, group_claims in sorted(topics.items()):
        n = len(group_claims)
        logger.info("处理 topic=%s (%d claims)...", topic, n)
        groups = await group_one_topic(topic, group_claims)
        logger.info("  → %d 个候选组", len(groups))
        all_groups.extend(groups)

    # 4. 构建 ADR-7 输出结构
    elapsed = time.perf_counter() - t0
    groups_output = []
    for i, g in enumerate(all_groups, 1):
        evidence = []
        for c in g.claims:
            evidence.append({
                "claim_id": c.id,
                "paper_id": c.paper_id,
                "paper_title": c.paper_title,
                "subject": c.subject,              # ← ADR-7 命脉
                "topic": c.topic,
                "quote": c.quote,
                "page": c.quote_page,
                "context": c.context_summary,
            })
        paper_count = len(set(c.paper_id for c in g.claims))
        statement = one_liner(g.group_label)
        groups_output.append({
            "candidate_group_id": i,
            "candidate_type": CandidateType.LIMITATION_CLUSTER.value,
            "topic": g.topic,
            "group_label": statement,
            "statement": statement,
            "grouping_method": g.grouping_method,
            "grouping_basis": g.grouping_basis,
            "cross_paper": g.cross_paper,
            "paper_count": paper_count,
            "claim_count": len(g.claims),
            # < 2 papers: weak / foldable, not a primary adoptable cluster
            "is_weak": paper_count < 2,
            # ADR-7: 裁决状态仅在人有操作后填充，初始为 pending
            "adjudication": {
                "status": "pending",
                "signal_name": None,
                "human_rationale": None,
                "reviewed_at": None,
            },
            "evidence": evidence,
        })

    logger.info(
        "聚类完成: %d claims → %d topics → %d 候选组，耗时 %.1fs",
        len(claims), len(topics), len(all_groups), elapsed,
    )

    return {
        "project_id": project_id,
        "total_claims": len(claims),
        "total_candidate_groups": len(all_groups),
        "model_used": model_name,
        "wall_time_seconds": round(elapsed, 2),
        "groups": groups_output,
    }


__all__ = [
    "ClaimRecord",
    "CandidateGroup",
    "fetch_limitation_claims",
    "GROUPING_PROMPT",
    "group_one_topic",
    "_make_solo_group",
    "run_clustering",
]
