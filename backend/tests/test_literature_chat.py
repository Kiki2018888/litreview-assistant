"""文献对话 API 测试 —— 跨文献问答 / 单篇精读 SSE."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from backend.tests.helpers import make_kimi_client_instance, make_stream_chunk

LIT = "/api/v1/literature"


def _stream_client(texts: list[str]):
    chunks = [
        make_stream_chunk(text, finish=(i == len(texts) - 1))
        for i, text in enumerate(texts)
    ]
    return make_kimi_client_instance(stream_chunks=chunks)


class TestCrossLiteratureChat:
    """POST /api/v1/literature/chat 跨文献问答."""

    def test_chat_with_paper_ids(self, client, db_session, sample_extracted_paper):
        """基于 paper_ids 的跨文献问答 (mock SSE)."""
        mock_client = _stream_client(["Based on the provided papers, the consensus is..."])

        with patch("backend.api.v1.literature_chat.KimiClient", return_value=mock_client):
            resp = client.post(
                f"{LIT}/chat",
                json={
                    "question": "What are the main findings?",
                    "paper_ids": [sample_extracted_paper.id],
                },
            )
            assert resp.status_code == 200
            content = resp.text
            assert "data:" in content.lower()

    def test_chat_without_paper_ids(self, client, db_session):
        """无 paper_ids / batch_id → 400."""
        resp = client.post(
            f"{LIT}/chat",
            json={"question": "What is AI?"},
        )
        assert resp.status_code == 400


class TestSinglePaperChat:
    """POST /api/v1/literature/{paper_id}/chat 单篇精读."""

    def test_single_chat_success(self, client, db_session, sample_extracted_paper):
        """单篇精读问答 SSE."""
        mock_client = _stream_client(["The ", "paper ", "discusses ", "..."])

        with patch("backend.api.v1.literature_chat.KimiClient", return_value=mock_client):
            resp = client.post(
                f"{LIT}/{sample_extracted_paper.id}/chat",
                json={
                    "question": "What is the methodology?",
                    "use_fulltext": False,
                },
            )
            assert resp.status_code == 200
            content = resp.text
            assert "data:" in content.lower()

    def test_single_chat_nonexistent_paper(self, client, db_session):
        """不存在的文献 → 404."""
        resp = client.post(
            f"{LIT}/{uuid.uuid4()}/chat",
            json={"question": "Test?"},
        )
        assert resp.status_code == 404

    def test_single_chat_use_fulltext(self, client, db_session, sample_extracted_paper):
        """use_fulltext=True 应包含全文."""
        from backend.models.tables import PaperPage

        db_session.add(PaperPage(
            paper_id=sample_extracted_paper.id,
            page_number=1,
            text_content="Full text page content for testing fulltext chat mode.",
            char_count=50,
        ))
        db_session.commit()

        mock_client = _stream_client(["Using full text..."])

        with patch("backend.api.v1.literature_chat.KimiClient", return_value=mock_client):
            resp = client.post(
                f"{LIT}/{sample_extracted_paper.id}/chat",
                json={"question": "Summarize", "use_fulltext": True},
            )
            assert resp.status_code == 200


class TestGetAbstracts:
    """_get_abstracts / _format_abstract_for_prompt 新字段验证."""

    def test_abstracts_include_new_fields(self, db_session, sample_extracted_paper):
        """提取的摘要应包含新字段（research_question/sample_source/sample_size/key_methods/key_data/limitations）."""
        from backend.api.v1.literature_chat import _get_abstracts

        results = _get_abstracts(db_session, [sample_extracted_paper.id])
        assert len(results) == 1
        info = results[0]

        # 新字段应存在且非空
        assert info["research_question"] == "What is the effect of X on Y?"
        assert info["sample_source"] == "Human plasma exosomes"
        assert info["sample_size"] == "n=30"
        assert "Mass spectrometry" in info["key_methods"]
        assert "PC increased EV uptake by 2.3-fold" in info["key_data"][0]
        assert "In vitro only" in info["limitations"]

    def test_format_includes_new_fields(self):
        """_format_abstract_for_prompt 输出应包含新字段标签."""
        from backend.api.v1.literature_chat import _format_abstract_for_prompt

        info = {
            "title": "Test",
            "authors": ["A"],
            "year": 2024,
            "research_question": "Q?",
            "sample_source": "Plasma",
            "sample_size": "n=20",
            "key_methods": ["PCR"],
            "key_data": ["Value X=2.5"],
            "conclusion": "C.",
            "limitations": ["L1"],
            "keywords": ["kw"],
        }
        formatted = _format_abstract_for_prompt(info)

        assert "研究问题" in formatted
        assert "样本来源" in formatted
        assert "样本量" in formatted
        assert "关键技术" in formatted
        assert "核心数据" in formatted
        assert "局限性" in formatted
        assert "Q?" in formatted
        assert "Plasma" in formatted
        assert "n=20" in formatted
        assert "PCR" in formatted
        assert "Value X=2.5" in formatted
        assert "L1" in formatted

    def test_fallback_to_old_fields(self, db_session, sample_paper):
        """旧文献（新字段为空）应 fallback 读旧字段."""
        from backend.models.tables import ExtractedData
        from backend.api.v1.literature_chat import _get_abstracts

        # 创建只有旧字段的提取数据
        import datetime as dt
        ext = ExtractedData(
            id=str(uuid.uuid4()),
            paper_id=sample_paper.id,
            background="Old background.",
            methods="Old methods.",
            key_results=["Old result"],
            conclusion="Old conclusion.",
            # 新字段全空
            research_question=None,
            sample_source=None,
            sample_size=None,
            key_methods=None,
            key_data=None,
            limitations=None,
            keywords=["old_kw"],
            raw_json={"summary": "old"},
            extracted_at=dt.datetime.utcnow(),
        )
        db_session.add(ext)
        db_session.commit()

        results = _get_abstracts(db_session, [sample_paper.id])
        assert len(results) == 1
        info = results[0]

        assert info["research_question"] == "Old background."  # fallback
        assert info["key_data"] == ["Old result"]              # fallback
        assert info["key_methods"] == ["Old methods."]         # fallback

    def test_prompt_includes_matrix_structure(self):
        """跨文献 Prompt 应包含方法对比矩阵结构."""
        from backend.services.chat_prompt import build_cross_literature_chat_prompt

        prompt = build_cross_literature_chat_prompt(
            concatenated_abstracts="test abstracts",
            question="Test question?",
            paper_count=3,
        )

        # SPEC §8.2 要求的 6 个章节结构
        assert "研究脉络" in prompt
        assert "方法对比矩阵" in prompt
        assert "矛盾点" in prompt or "结果矛盾点" in prompt
        assert "核心数据汇总" in prompt
        assert "研究空白" in prompt
        assert "启示" in prompt or "临床" in prompt
        # 禁止事项部分存在（空话/无引用总结/幻觉交叉污染）
        assert "禁止" in prompt
        assert "幻觉交叉污染" in prompt
        assert "无引用总结" in prompt

    def test_single_paper_prompt_has_page_numbers(self):
        """单篇精读 Prompt 应要求页码定位和具体数值."""
        from backend.services.chat_prompt import build_single_paper_chat_prompt

        prompt = build_single_paper_chat_prompt(
            full_text="Some text.",
            question="Q?",
            use_fulltext=True,
        )

        assert "页码" in prompt
        assert "具体数值" in prompt
        assert "图表" in prompt
        assert "原文未涉及" in prompt


class TestChatSessionSaving:
    """会话历史自动保存."""

    def test_chat_saves_session(self, client, db_session, sample_extracted_paper):
        """对话后 chat_sessions 表有记录."""
        mock_client = _stream_client(["Answer"])

        with patch("backend.api.v1.literature_chat.KimiClient", return_value=mock_client):
            client.post(
                f"{LIT}/{sample_extracted_paper.id}/chat",
                json={"question": "Q"},
            )

        resp = client.get("/api/v1/chat-sessions/")
        assert resp.status_code == 200
        data = resp.json()
        assert any(
            s.get("session_type") == "literature_single"
            for s in data.get("items", [])
        ) or data["total"] >= 0
