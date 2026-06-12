"""提取服务：JSON 解析 + Pydantic 校验 + json-repair + 修复循环.

ADR-2 提取质量契约的核心实现。
纯计算层，无 IO，无 DB 操作。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from json_repair import repair_json
from pydantic import ValidationError as PydanticValidationError

from backend.models.schemas import ExtractedDataContract

logger = logging.getLogger(__name__)

# 修复循环最大次数（避免 token 放大）
_MAX_REPAIR_ATTEMPTS = 2


# ---------------------------------------------------------------------------
# 异常定义
# ---------------------------------------------------------------------------


class JSONParseError(Exception):
    """JSON 解析失败（json-repair 也无法修复）."""


class ExtractQualityError(Exception):
    """提取质量不达标（schema 校验失败，修复循环耗尽）."""


# ---------------------------------------------------------------------------
# 清理与修复
# ---------------------------------------------------------------------------


def _strip_markdown_fence(text: str) -> str:
    """移除 markdown 代码块标记."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def _try_parse_json(text: str) -> dict[str, Any]:
    """尝试解析 JSON 文本为 dict.

    流程：json-repair → json.loads → { } 区间提取。
    全部失败抛出 JSONParseError。
    """
    # 1. json-repair 修复
    try:
        repaired = repair_json(text)
        data = json.loads(repaired)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # 2. 标准 json.loads
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # 3. 提取 { } 区间
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    raise JSONParseError("AI 返回内容无法解析为 JSON，json-repair 与标准解析均失败")


# ---------------------------------------------------------------------------
# 解析 + 校验
# ---------------------------------------------------------------------------


@dataclass
class ParseResult:
    """解析结果."""

    data: dict[str, Any]
    """原始解析 dict（写入 raw_json）."""

    contract: ExtractedDataContract
    """通过质量校验的 schema 实例."""


def parse_and_validate(raw_text: str) -> ParseResult:
    """解析 AI 返回文本并校验质量.

    Args:
        raw_text: AI 返回的原始文本（可能含 markdown 包裹）。

    Returns:
        ParseResult：含原始 dict 与通过校验的 ExtractedDataContract。

    Raises:
        JSONParseError: JSON 无法解析。
        PydanticValidationError: Schema 校验不通过（含具体错误列表）。
    """
    cleaned = _strip_markdown_fence(raw_text)
    data = _try_parse_json(cleaned)

    # Pydantic 校验（会抛出 ValidationError 含错误详情）
    contract = ExtractedDataContract.model_validate(data)
    return ParseResult(data=data, contract=contract)


# ---------------------------------------------------------------------------
# 修复循环 Prompt
# ---------------------------------------------------------------------------


_REPAIR_PROMPT_TEMPLATE = """你是一位专业的科研文献分析助手。请仔细阅读以下论文全文，提取关键信息并以 JSON 格式返回。

要求字段（共12个）：
1. title: 论文标题
2. authors: 作者列表（数组）
3. year: 发表年份（整数）
4. journal: 期刊名
5. research_question: 该研究要回答的科学问题（50字内）
6. sample_source: 样本来源（如'人血浆外泌体'、'小鼠骨髓间充质干细胞'）
7. sample_size: 样本量（如'n=30'、'3个独立批次'）
8. key_methods: 核心技术列表
9. key_data: 核心数据点列表（必须含具体数值，如'PC使EV摄取增加2.3倍(p<0.01)'）
10. conclusion: 结论（150字内）
11. limitations: 研究局限性列表（至少1条，如['仅体外实验', '样本量小(n=5)']）
12. keywords: 关键词列表（5-8个）

【你之前的输出存在以下问题，请修正】
{validation_errors}

【质量要求】
- key_data 必须包含具体数值/指标，禁止'显著增加'、'明显降低'等模糊表述
- limitations 必须基于原文真实局限，禁止编造
- 如果某字段信息缺失，返回空字符串或空数组，不要编造
- 输出必须是合法 JSON，不要包含 markdown 代码块标记

论文全文：
{paper_text}"""


def build_repair_prompt(paper_text: str, errors: list[str]) -> str:
    """构建修复 Prompt，将校验错误回灌给模型.

    Args:
        paper_text: 论文全文。
        errors: 校验错误描述列表。

    Returns:
        修复 Prompt 字符串。
    """
    error_text = "\n".join(f"- {e}" for e in errors)
    return _REPAIR_PROMPT_TEMPLATE.format(
        validation_errors=error_text,
        paper_text=paper_text,
    )


# ---------------------------------------------------------------------------
# 校验错误提取
# ---------------------------------------------------------------------------


def _extract_validation_errors(exc: Exception) -> list[str]:
    """从 Pydantic ValidationError 或 JSONParseError 提取可读错误列表."""
    if isinstance(exc, JSONParseError):
        return [str(exc)]
    if isinstance(exc, PydanticValidationError):
        return [
            f"字段 '{'.'.join(str(p) for p in e['loc'])}': {e['msg']}"
            for e in exc.errors()
        ]
    return [str(exc)]


# ---------------------------------------------------------------------------
# 修复循环结果
# ---------------------------------------------------------------------------


@dataclass
class ExtractResult:
    """提取最终结果."""

    success: bool
    """是否成功通过质量契约."""

    parse_result: Optional[ParseResult] = None
    """成功时的解析结果."""

    errors: list[str] = field(default_factory=list)
    """失败时的错误列表（用于记录 last_error）."""

    repair_attempts: int = 0
    """修复尝试次数."""


__all__ = [
    "JSONParseError",
    "ExtractQualityError",
    "ParseResult",
    "ExtractResult",
    "parse_and_validate",
    "build_repair_prompt",
    "_extract_validation_errors",
    "_MAX_REPAIR_ATTEMPTS",
]
