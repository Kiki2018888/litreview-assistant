"""Claims 抽取核心服务.

从 _extract_claims.py 搬入并改造：
- chunk_paper() + SectionChunk（行 402-519）
- _parse_json_safe() 三层兜底（行 539-673）
- validate_conditional() + ConditionalValidation（行 358-399）
- quote_locator 调用（行 676-822）

改造点：
- AI 客户端从硬编码 DeepSeek → 系统统一 KimiClient
- 入口从文件路径 → paper_id（从 DB 读全文）
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from backend.services.claim_extract_prompt import (
    CHUNK_USER_TEMPLATE,
    MAX_TOKENS,
    SYSTEM_PROMPT,
    normalize_text,
)
from backend.services.kimi_client import _get_client
from backend.services.quote_locator import PageMap, locate_quote

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 条件必填校验（搬自 _extract_claims.py:358-399）
# ---------------------------------------------------------------------------


@dataclass
class ConditionalValidation:
    passed: bool
    rule: str
    detail: str


def validate_conditional(claim: dict) -> list[ConditionalValidation]:
    """校验条件必填规则."""
    results: list[ConditionalValidation] = []
    cf = claim.get("claim_form", "")
    direction = claim.get("direction")
    comparison_result = claim.get("comparison_result")

    # effect → direction 必填
    if cf == "effect":
        if direction is None:
            results.append(
                ConditionalValidation(
                    False, "effect→direction",
                    "claim_form=effect but direction is null",
                )
            )
    # comparison → comparison_result 必填
    if cf == "comparison":
        if comparison_result is None:
            results.append(
                ConditionalValidation(
                    False, "comparison→comparison_result",
                    "claim_form=comparison but comparison_result is null",
                )
            )

    # 反向检查：非 effect 但填了 direction（警告）
    if cf != "effect" and direction is not None:
        results.append(
            ConditionalValidation(
                True, "non-effect-has-direction",
                f"claim_form={cf} but direction is {direction} (possible misclassification)",
            )
        )
    # 非 comparison 但填了 comparison_result（警告）
    if cf != "comparison" and comparison_result is not None:
        results.append(
            ConditionalValidation(
                True, "non-comparison-has-result",
                f"claim_form={cf} but comparison_result is {comparison_result} (possible misclassification)",
            )
        )

    return results


# ---------------------------------------------------------------------------
# 章节分块（搬自 _extract_claims.py:402-519）
# ---------------------------------------------------------------------------


_SECTION_RE = re.compile(
    r'(?:^|\n|(?<=[.\u2014\u2013]))\s*'
    r'(ABSTRACT|INTRODUCTION|'
    r'MATERIALS?\s*(?:AND|&)\s*METHODS?|'
    r'RESULTS(?:\s+AND\s+DISCUSSION)?|'
    r'DISCUSSION|'
    r'CONCLUSIONS?|'
    r'ACKNOWLEDGMENTS?|'
    r'REFERENCES|'
    r'DISCLOSURE\s+OF\s+POTENTIAL\s+CONFLICTS?)'
    r'\b',
    re.IGNORECASE | re.MULTILINE,
)

_DISCUSSION_FALLBACK_RE = re.compile(r'(?:by|of)\s*DISCUSSION\b', re.IGNORECASE)
_META_SECTIONS = {"ACKNOWLEDGMENTS", "ACKNOWLEDGEMENT", "REFERENCES", "DISCLOSURE OF POTENTIAL CONFLICTS"}


@dataclass
class PageBlock:
    page_number: int
    text: str


@dataclass
class SectionChunk:
    name: str
    text: str
    start_char: int
    page_start: int
    page_end: int


def chunk_paper(full_text: str, pages: list[PageBlock]) -> list[SectionChunk]:
    """按节标题切分全文."""
    # 构建字符偏移→页码映射
    offsets: list[tuple[int, int]] = []
    cumulative = 0
    for p in pages:
        offsets.append((cumulative, p.page_number))
        cumulative += len(p.text) + 1

    def _char_to_page(char_pos: int) -> int:
        for i in range(len(offsets) - 1, -1, -1):
            if offsets[i][0] <= char_pos:
                return offsets[i][1]
        return pages[0].page_number if pages else 1

    # 定位节标题
    matches: list[tuple[str, int, int]] = []
    for m in _SECTION_RE.finditer(full_text):
        name = m.group(1).strip().upper()
        matches.append((name, m.start(), m.end()))

    # DISCUSSION 备选
    if not any(m[0] == "DISCUSSION" for m in matches):
        for m in _DISCUSSION_FALLBACK_RE.finditer(full_text):
            start_in_match = m.group().upper().find("DISCUSSION")
            abs_start = m.start() + start_in_match
            abs_end = m.start() + start_in_match + len("DISCUSSION")
            matches.append(("DISCUSSION", abs_start, abs_end))
            break

    matches.sort(key=lambda x: x[1])
    chunks: list[SectionChunk] = []

    # Preamble
    if matches:
        first_heading_start = matches[0][1]
        preamble_text = full_text[:first_heading_start].strip()
        if preamble_text and len(preamble_text) >= 30:
            chunks.append(SectionChunk(
                name="PREAMBLE", text=preamble_text,
                start_char=0,
                page_start=_char_to_page(0),
                page_end=_char_to_page(first_heading_start),
            ))

    # 正文 chunk
    for i, (name, start, end) in enumerate(matches):
        if name in _META_SECTIONS:
            if name == "REFERENCES":
                break
            continue

        next_start = matches[i + 1][1] if i + 1 < len(matches) else len(full_text)
        chunk_text = full_text[end:next_start].strip()
        if not chunk_text or len(chunk_text) < 30:
            continue

        chunks.append(SectionChunk(
            name=name,
            text=chunk_text,
            start_char=start,
            page_start=_char_to_page(start),
            page_end=_char_to_page(next_start - 1),
        ))

    return chunks


# ---------------------------------------------------------------------------
# JSON 解析三层兜底（搬自 _extract_claims.py:556-596）
# ---------------------------------------------------------------------------


def _parse_json_safe(raw: str, chunk_label: str) -> dict:
    """解析 JSON，json-repair 兜底."""
    json_str = raw.strip()
    if json_str.startswith("```"):
        json_str = re.sub(r"^```(?:json)?\s*", "", json_str)
        json_str = re.sub(r"\s*```$", "", json_str)

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # json-repair 兜底
    try:
        from json_repair import repair_json
        repaired = repair_json(json_str)
        logger.info("[%s] json-repair 修复成功", chunk_label)
        return json.loads(repaired)
    except ImportError:
        logger.debug("[%s] json-repair 未安装", chunk_label)
    except Exception as e:
        logger.warning("[%s] json-repair 修复失败: %s", chunk_label, e)

    # 尾部截断修复
    truncated = json_str.rstrip()
    if truncated.endswith(","):
        truncated = truncated[:-1]
    if not truncated.endswith("]"):
        last_brace = truncated.rfind("}")
        if last_brace > 0:
            truncated = truncated[:last_brace + 1] + "\n]}"
        else:
            truncated += "\n]}"
    try:
        result = json.loads(truncated)
        logger.warning("[%s] 尾部截断修复成功（可能丢失最后一条 claim）", chunk_label)
        return result
    except json.JSONDecodeError:
        raise RuntimeError(f"[{chunk_label}] JSON 解析彻底失败 (原始 {len(raw)} 字符)")


# ---------------------------------------------------------------------------
# 单块抽取（改造：用 KimiClient 替代硬编码 DeepSeek）
# ---------------------------------------------------------------------------


async def _extract_one_chunk(
    title: str,
    chunk: SectionChunk,
) -> tuple[list[dict], str, dict, float]:
    """对单个 chunk 调用 AI，返回 (claims, finish_reason, usage, wall_seconds)."""
    user_message = CHUNK_USER_TEMPLATE.format(
        title=title,
        section_name=chunk.name,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        chunk_text=chunk.text,
    )

    client = _get_client()
    model = client._model

    logger.info(
        "[%s] 请求中... (%d chars, ~%d tokens, model=%s)",
        chunk.name, len(chunk.text), len(chunk.text) // 4, model,
    )

    t0 = time.perf_counter()
    try:
        content, finish_reason, usage = await client.chat_json(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            model=model,
            temperature=0.2,
            max_tokens=MAX_TOKENS,
            extra_body={"thinking": {"type": "disabled"}},
        )
    except Exception:
        logger.exception("[%s] AI 调用失败", chunk.name)
        raise

    t1 = time.perf_counter()
    wall_sec = t1 - t0

    logger.info(
        "[%s] %.1fs | finish=%s, output=%d tokens, content_len=%d chars",
        chunk.name, wall_sec, finish_reason,
        usage.get("completion_tokens", 0),
        len(content),
    )

    if finish_reason == "length":
        logger.warning("[%s] 输出被截断 (finish_reason=length)！", chunk.name)

    if not content:
        logger.error("[%s] API 返回空内容", chunk.name)
        return [], finish_reason, usage, wall_sec

    result = _parse_json_safe(content, chunk.name)
    claims = result.get("claims", [])
    if not isinstance(claims, list):
        claims = []
    return claims, finish_reason, usage, wall_sec


# ---------------------------------------------------------------------------
# 主入口：从 paper_id 抽取 claims
# ---------------------------------------------------------------------------


async def extract_claims_for_paper(
    paper_id: str,
    title: str,
    full_text: str,
    pages: list[PageBlock],
) -> dict:
    """对一篇文献执行完整 claims 抽取流程.

    Args:
        paper_id: 文献 ID
        title: 论文标题
        full_text: 全文（所有页面拼接）
        pages: 按页分块列表

    Returns:
        {
            "claims": list[dict],
            "chunk_stats": list[dict],
            "quote_locator_stats": {"verified": int, "unverified": int},
            "wall_time_seconds": float,
            "rejected": list[dict],  # 被 conditional 校验拒绝的记录
        }
    """
    t_total_start = time.perf_counter()

    # Phase 0: 分块
    t0 = time.perf_counter()
    chunks = chunk_paper(full_text, pages)
    t_chunk = time.perf_counter() - t0

    chunked_chars = sum(len(c.text) for c in chunks)
    coverage = chunked_chars / max(len(full_text), 1) * 100
    logger.info(
        "分块完成: %d 块, %d/%d 字符 (%.1f%%), %.2fs",
        len(chunks), chunked_chars, len(full_text), coverage, t_chunk,
    )
    for c in chunks:
        logger.info("  [%s] P%d-P%d | %d chars", c.name, c.page_start, c.page_end, len(c.text))

    # Phase 1: 并发调 AI
    t1 = time.perf_counter()
    tasks = [_extract_one_chunk(title, chunk) for chunk in chunks]
    results = await asyncio.gather(*tasks)

    all_claims: list[dict] = []
    chunk_stats: list[dict] = []
    api_wall_times: list[float] = []

    for chunk, (claims, fr, usage, wall_sec) in zip(chunks, results):
        all_claims.extend(claims)
        api_wall_times.append(wall_sec)
        chunk_stats.append({
            "name": chunk.name,
            "claims_count": len(claims),
            "finish_reason": fr,
            "usage": usage,
            "chars": len(chunk.text),
            "wall_seconds": round(wall_sec, 2),
        })
    t_api_total = time.perf_counter() - t1

    # Phase 2: 去重
    t2 = time.perf_counter()
    seen_quotes: set[str] = set()
    deduped: list[dict] = []
    dup_count = 0
    for c in all_claims:
        q = normalize_text(c.get("quote", ""))
        if q and q in seen_quotes:
            dup_count += 1
            continue
        if q:
            seen_quotes.add(q)
        deduped.append(c)
    t_dedup = time.perf_counter() - t2

    logger.info("合并: %d 条 → 去重 %d 条 → %d 条", len(all_claims), dup_count, len(deduped))

    # Phase 3: quote_locator 逐字定位
    t3 = time.perf_counter()
    page_map: PageMap = []
    offset = 0
    for page in pages:
        offset += len(page.text) + 1
        page_map.append((offset, page.page_number))

    verified = 0
    unverified = 0
    for claim in deduped:
        result = locate_quote(
            candidate_quote=claim.get("quote", ""),
            source_text=full_text,
            page_map=page_map,
            fuzzy_threshold=0.85,
        )
        if result.status == "located":
            claim["quote"] = result.verbatim_quote
            claim["quote_page"] = result.page or claim.get("quote_page", 0)
            claim["char_span_start"] = result.char_span[0] if result.char_span else None
            claim["char_span_end"] = result.char_span[1] if result.char_span else None
            claim["quote_status"] = "verified"
            verified += 1
        else:
            claim["quote_status"] = "unverified"
            unverified += 1

    t_align = time.perf_counter() - t3

    logger.info("quote_locator: verified=%d, unverified=%d (%.2fs)", verified, unverified, t_align)

    # Phase 4: 条件必填校验
    rejected: list[dict] = []
    passed_claims: list[dict] = []
    for claim in deduped:
        cv_results = validate_conditional(claim)
        failed = [r for r in cv_results if not r.passed]
        if failed:
            claim["_reject_reasons"] = [{"rule": r.rule, "detail": r.detail} for r in failed]
            rejected.append(claim)
            logger.warning(
                "条件校验拒绝: claim_form=%s, rules=%s",
                claim.get("claim_form"), [r.rule for r in failed],
            )
        else:
            passed_claims.append(claim)

    t_total = time.perf_counter() - t_total_start

    logger.info(
        "抽取完成: 共 %d 条, 通过 %d 条, 拒绝 %d 条 | "
        "分块=%.2fs API=%.2fs 去重=%.3fs 定位=%.2fs 总计=%.2fs",
        len(deduped), len(passed_claims), len(rejected),
        t_chunk, t_api_total, t_dedup, t_align, t_total,
    )

    return {
        "claims": passed_claims,
        "chunk_stats": chunk_stats,
        "quote_locator_stats": {"verified": verified, "unverified": unverified},
        "wall_time_seconds": round(t_total, 2),
        "rejected": rejected,
    }


# ---------------------------------------------------------------------------
# 模型预估（方案甲：基于模型名判断快慢）
# ---------------------------------------------------------------------------


# 快模型（秒级响应）：flash 系列、8k/32k 小模型
_FAST_MODEL_PATTERNS = ["flash", "v1-8k", "v1-32k", "kimi-latest"]

# 慢模型（需数分钟）：pro 系列、大上下文模型
_SLOW_MODEL_PATTERNS = ["pro", "v1-128k", "auto", "k2."]


def estimate_extraction_time(model_name: str, paper_count: int, chunk_count: int | None = None) -> dict:
    """预估抽取耗时/成本，返回结构化提示信息.

    Args:
        model_name: 当前配置的模型名
        paper_count: 待抽取文献数
        chunk_count: 预估 chunk 数（可选，基于典型论文 5-8 块估算）

    Returns:
        {
            "model": str,
            "speed_tier": "fast" | "slow" | "unknown",
            "per_chunk_seconds_estimated": float,
            "estimated_chunks": int,
            "estimated_total_seconds": float,
            "estimated_total_minutes": float,
            "warning": str | None,  # 慢模型警告
        }
    """
    model_lower = model_name.lower()

    # 判断快慢
    speed_tier = "unknown"
    per_chunk_seconds = 15.0  # 默认

    if any(p in model_lower for p in _FAST_MODEL_PATTERNS):
        speed_tier = "fast"
        per_chunk_seconds = 8.0
    elif any(p in model_lower for p in _SLOW_MODEL_PATTERNS):
        speed_tier = "slow"
        per_chunk_seconds = 30.0

    est_chunks = chunk_count or (paper_count * 7)  # 默认每篇 7 块
    est_seconds = est_chunks * per_chunk_seconds
    est_minutes = est_seconds / 60

    warning = None
    if speed_tier == "slow":
        warning = (
            f"检测到慢速模型 ({model_name})，预估 {paper_count} 篇文献需 "
            f"约 {est_minutes:.1f} 分钟。建议前往设置切换至 flash 系列模型以加速。"
        )

    return {
        "model": model_name,
        "speed_tier": speed_tier,
        "per_chunk_seconds_estimated": per_chunk_seconds,
        "estimated_chunks": est_chunks,
        "estimated_total_seconds": round(est_seconds, 0),
        "estimated_total_minutes": round(est_minutes, 1),
        "warning": warning,
    }


__all__ = [
    "PageBlock",
    "SectionChunk",
    "ConditionalValidation",
    "validate_conditional",
    "chunk_paper",
    "extract_claims_for_paper",
    "estimate_extraction_time",
]
