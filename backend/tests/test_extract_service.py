"""ADR-2 提取质量契约单元测试 —— parse_and_validate / json-repair / 修复循环."""
from __future__ import annotations

import json

import pytest

from backend.services.extract_service import (
    ExtractQualityError,
    JSONParseError,
    _MAX_REPAIR_ATTEMPTS,
    build_repair_prompt,
    parse_and_validate,
)


def _valid_json() -> str:
    """返回合法 JSON（含所有 ADR-2 必填字段）."""
    return json.dumps({
        "title": "Test Paper",
        "authors": ["Author A"],
        "year": 2024,
        "journal": "Nature",
        "research_question": "How does X affect Y?",
        "sample_source": "Human plasma",
        "sample_size": "n=30",
        "key_methods": ["Mass spectrometry"],
        "key_data": ["X increased by 2.3-fold (p<0.01)"],
        "conclusion": "X significantly affects Y.",
        "limitations": ["Only in vitro experiments"],
        "keywords": ["test", "example"],
    })


class TestParseAndValidate:
    """parse_and_validate 核心逻辑."""

    def test_valid_json_passes(self):
        """合法 JSON + 完整字段 → 通过校验."""
        result = parse_and_validate(_valid_json())
        assert result.contract.research_question == "How does X affect Y?"
        assert result.contract.key_data == ["X increased by 2.3-fold (p<0.01)"]

    def test_missing_required_field_marked_partial(self):
        """放宽后：核心字段为空 → 不判死，标记 partial."""
        data = json.dumps({
            "research_question": "",
            "sample_source": "Human plasma",
            "conclusion": "Conclusion",
            "key_data": ["n=30"],
            "limitations": ["Only in vitro"],
        })
        result = parse_and_validate(data)
        assert result.partial is True
        assert "research_question" in result.missing_fields

    def test_key_data_no_numeric_kept(self):
        """放宽后：key_data 无数值 → 保留内容，不判死."""
        data = json.dumps({
            "research_question": "Q",
            "sample_source": "S",
            "conclusion": "C",
            "key_data": ["显著增加"],
            "limitations": ["L"],
        })
        result = parse_and_validate(data)
        assert result.contract.key_data == ["显著增加"]
        assert "key_data" not in result.missing_fields

    def test_limitations_empty_marked_partial(self):
        """放宽后：limitations 为空 → 标记 partial，不判死."""
        data = json.dumps({
            "research_question": "Q",
            "sample_source": "S",
            "conclusion": "C",
            "key_data": ["n=30"],
            "limitations": [],
        })
        result = parse_and_validate(data)
        assert result.partial is True
        assert "limitations" in result.missing_fields

    def test_omit_key_data_field_marked_partial(self):
        """放宽后：省略 key_data → partial，保留其余字段入库."""
        data = json.dumps({
            "research_question": "Q",
            "sample_source": "S",
            "conclusion": "C",
            "limitations": ["Only in vitro"],
        })
        result = parse_and_validate(data)
        assert result.partial is True
        assert "key_data" in result.missing_fields

    def test_completely_empty_still_fails(self):
        """最低门槛：完全空响应仍判失败."""
        with pytest.raises(ExtractQualityError):
            parse_and_validate(json.dumps({}))

    def test_key_data_with_percent_passes(self):
        """key_data 含百分比 → 通过."""
        data = json.dumps({
            "research_question": "Q",
            "sample_source": "S",
            "conclusion": "C",
            "key_data": ["增长30%"],
            "limitations": ["L"],
        })
        result = parse_and_validate(data)
        assert result.contract.key_data == ["增长30%"]

    def test_key_data_with_pvalue_passes(self):
        """key_data 含 p 值 → 通过."""
        data = json.dumps({
            "research_question": "Q",
            "sample_source": "S",
            "conclusion": "C",
            "key_data": ["p<0.05"],
            "limitations": ["L"],
        })
        result = parse_and_validate(data)
        assert result.contract.key_data == ["p<0.05"]


class TestJsonRepair:
    """json-repair 兜底."""

    def test_truncated_json_repaired(self):
        """截断 JSON → json-repair 修复成功."""
        data = (
            '{"research_question":"Q","sample_source":"S",'
            '"conclusion":"C","key_data":["n=30"],"limitations":["L"],'
        )
        # 截断：少闭合 }
        result = parse_and_validate(data)
        assert result.contract.research_question == "Q"

    def test_trailing_comma_repaired(self):
        """尾部多余逗号 → json-repair 修复成功."""
        data = json.dumps({
            "research_question": "Q",
            "sample_source": "S",
            "conclusion": "C",
            "key_data": ["n=30"],
            "limitations": ["L"],
        }) + ","  # trailing comma
        result = parse_and_validate(data)
        assert result.contract.research_question == "Q"

    def test_badly_damaged_json_fails(self):
        """严重损坏 JSON → json-repair 也失败."""
        data = "this is not json at all { broken ["
        with pytest.raises(JSONParseError):
            parse_and_validate(data)


class TestRepairPrompt:
    """修复 Prompt 构建."""

    def test_build_repair_prompt(self):
        """修复 Prompt 包含错误列表."""
        errors = ["字段 'research_question': 不能为空", "字段 'key_data[0]': 缺少数值"]
        prompt = build_repair_prompt("paper text here", errors)
        assert "你之前的输出存在以下问题" in prompt
        assert "research_question" in prompt
        assert "key_data" in prompt
        assert "paper text here" in prompt

    def test_max_repair_constant(self):
        """_MAX_REPAIR_ATTEMPTS 为 2."""
        assert _MAX_REPAIR_ATTEMPTS == 2


class TestExtraFieldsAllowed:
    """extra=allow 策略."""

    def test_extra_fields_passes(self):
        """多余字段不阻塞校验."""
        data = json.dumps({
            "research_question": "Q",
            "sample_source": "S",
            "conclusion": "C",
            "key_data": ["n=30"],
            "limitations": ["L"],
            "unknown_field": "should be ignored",
        })
        result = parse_and_validate(data)
        assert result.contract.research_question == "Q"
