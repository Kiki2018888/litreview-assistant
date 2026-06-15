"""ADR-2 质量契约回归保护单测 —— 钉死 ExtractedDataContract 的行为契约。

防止未来误把 Field(..., min_length=1) 改成带默认值（如 default_factory=list）
而导致"字段省略 → 取默认空值 → 校验器不触发 → 空数据通过"的漏洞复现。

所有必填内容字段（省略/空值均须被拒）：
  - key_data        (list[str], 必填 + 非空 + 每条含数值)
  - limitations     (list[str], 必填 + 非空)
  - research_question (str,     必填 + 非空)
  - sample_source   (str,     必填 + 非空)
  - conclusion      (str,     必填 + 非空)
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.models.schemas import ExtractedDataContract


# ---------------------------------------------------------------------------
# 正常基准数据（所有必填字段齐全）
# ---------------------------------------------------------------------------

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
# 正常通过
# ---------------------------------------------------------------------------

def test_valid_data_passes():
    """正常完整数据 → 通过校验."""
    contract = ExtractedDataContract.model_validate(_valid_data())
    assert contract.key_data == ["PC使EV摄取增加2.3倍(p<0.01)"]
    assert contract.research_question == "How do EVs affect cancer cell migration?"
    assert contract.conclusion == "EVs significantly promote cancer cell migration in vitro."


# ---------------------------------------------------------------------------
# key_data 字段保护
# ---------------------------------------------------------------------------

def test_key_data_omitted():
    """省略 key_data 键 → ValidationError."""
    data = _valid_data()
    del data["key_data"]
    with pytest.raises(ValidationError) as exc:
        ExtractedDataContract.model_validate(data)
    assert "key_data" in str(exc.value)


def test_key_data_empty_list():
    """key_data=[] → ValidationError."""
    data = _valid_data()
    data["key_data"] = []
    with pytest.raises(ValidationError) as exc:
        ExtractedDataContract.model_validate(data)
    # 可能是 min_length 或 field_validator 的 len(v) < 1
    assert "key_data" in str(exc.value)


# ---------------------------------------------------------------------------
# limitations 字段保护
# ---------------------------------------------------------------------------

def test_limitations_omitted():
    """省略 limitations 键 → ValidationError."""
    data = _valid_data()
    del data["limitations"]
    with pytest.raises(ValidationError) as exc:
        ExtractedDataContract.model_validate(data)
    assert "limitations" in str(exc.value)


def test_limitations_empty_list():
    """limitations=[] → ValidationError."""
    data = _valid_data()
    data["limitations"] = []
    with pytest.raises(ValidationError) as exc:
        ExtractedDataContract.model_validate(data)
    assert "limitations" in str(exc.value)


# ---------------------------------------------------------------------------
# research_question 字段保护
# ---------------------------------------------------------------------------

def test_research_question_omitted():
    """省略 research_question 键 → ValidationError."""
    data = _valid_data()
    del data["research_question"]
    with pytest.raises(ValidationError) as exc:
        ExtractedDataContract.model_validate(data)
    assert "research_question" in str(exc.value)


def test_research_question_empty():
    """research_question=\"\" → ValidationError."""
    data = _valid_data()
    data["research_question"] = ""
    with pytest.raises(ValidationError) as exc:
        ExtractedDataContract.model_validate(data)
    assert "research_question" in str(exc.value)


# ---------------------------------------------------------------------------
# conclusion 字段保护
# ---------------------------------------------------------------------------

def test_conclusion_omitted():
    """省略 conclusion 键 → ValidationError."""
    data = _valid_data()
    del data["conclusion"]
    with pytest.raises(ValidationError) as exc:
        ExtractedDataContract.model_validate(data)
    assert "conclusion" in str(exc.value)


# ---------------------------------------------------------------------------
# sample_source 字段保护
# ---------------------------------------------------------------------------

def test_sample_source_empty():
    """sample_source=\"\" → ValidationError."""
    data = _valid_data()
    data["sample_source"] = ""
    with pytest.raises(ValidationError) as exc:
        ExtractedDataContract.model_validate(data)
    assert "sample_source" in str(exc.value)
