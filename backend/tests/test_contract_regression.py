"""ADR-2 质量契约（可靠性放宽版）回归保护单测。

放宽后行为契约（替代旧的"严格判死"）：
  - 核心字段缺失/为空 → 不再抛 ValidationError，填默认值，由 parse_and_validate 标记 partial。
  - key_data 无具体数值 → 保留内容，不判废。
  - 仅"完全空响应"或"无法解析为 JSON"才算失败。

本测试钉死"尽力而为"语义，防止未来误改回"一票否决"导致不完美摘要被整条丢弃。
"""
from __future__ import annotations

import json

import pytest

from backend.models.schemas import ExtractedDataContract
from backend.services.extract_service import (
    ExtractQualityError,
    parse_and_validate,
)


def _valid_data() -> dict:
    return {
        "title": "A Study on Extracellular Vesicles",
        "authors": ["Smith J", "Doe A"],
        "year": 2024,
        "journal": "Nature Communications",
        "research_question": "How do EVs affect cancer cell migration?",
        "sample_source": "Human plasma from healthy donors",
        "sample_size": "n=45",
        "key_methods": ["Nanoparticle tracking analysis", "Western blot"],
        "key_data": ["PC使EV摄取增加2.3倍(p<0.01)"],
        "conclusion": "EVs significantly promote cancer cell migration in vitro.",
        "limitations": ["Only in vitro experiments, no in vivo validation"],
        "keywords": ["EVs", "cancer", "migration"],
    }


# ---------------------------------------------------------------------------
# 完整数据：通过且非 partial
# ---------------------------------------------------------------------------

def test_valid_data_passes_not_partial():
    contract = ExtractedDataContract.model_validate(_valid_data())
    assert contract.key_data == ["PC使EV摄取增加2.3倍(p<0.01)"]
    result = parse_and_validate(json.dumps(_valid_data()))
    assert result.partial is False
    assert result.missing_fields == []


# ---------------------------------------------------------------------------
# 契约层：缺字段/空值不再抛错（填默认值）
# ---------------------------------------------------------------------------

def test_contract_omitted_fields_no_raise():
    contract = ExtractedDataContract.model_validate({"title": "only title"})
    assert contract.research_question == ""
    assert contract.key_data == []
    assert contract.limitations == []


def test_contract_key_data_no_numeric_kept():
    """key_data 无数值也保留（剔除空项但不判废）."""
    contract = ExtractedDataContract.model_validate({"key_data": ["显著增加", "", "明显改善"]})
    assert contract.key_data == ["显著增加", "明显改善"]


# ---------------------------------------------------------------------------
# parse_and_validate：缺失/空 → partial，不判死
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("drop_field", [
    "research_question", "sample_source", "key_data", "conclusion", "limitations",
])
def test_missing_core_field_marked_partial(drop_field):
    data = _valid_data()
    del data[drop_field]
    result = parse_and_validate(json.dumps(data))
    assert result.partial is True
    assert drop_field in result.missing_fields


def test_empty_lists_marked_partial_not_failed():
    data = _valid_data()
    data["key_data"] = []
    data["limitations"] = []
    result = parse_and_validate(json.dumps(data))
    assert result.partial is True
    assert "key_data" in result.missing_fields
    assert "limitations" in result.missing_fields


def test_key_data_no_numeric_not_failed():
    data = _valid_data()
    data["key_data"] = ["显著增加"]   # 无数值
    result = parse_and_validate(json.dumps(data))
    # 不判死：key_data 非空 → 不在缺失列表
    assert "key_data" not in result.missing_fields
    assert result.contract.key_data == ["显著增加"]


# ---------------------------------------------------------------------------
# 最低门槛：完全空响应仍判失败
# ---------------------------------------------------------------------------

def test_completely_empty_response_fails():
    with pytest.raises(ExtractQualityError):
        parse_and_validate(json.dumps({}))


def test_all_core_empty_with_title_is_partial_not_failed():
    """有标题但核心字段全空 → 仍入库（partial），不判失败."""
    result = parse_and_validate(json.dumps({"title": "Some Title"}))
    assert result.partial is True
    assert set(result.missing_fields) >= {
        "research_question", "sample_source", "key_data", "conclusion", "limitations",
    }
