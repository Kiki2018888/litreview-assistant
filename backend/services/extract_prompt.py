"""Prompt 模板模块.

为 Kimi API 调用提供 3 类 Prompt 模板字符串，与 SPEC §7 完全一致。

所有模板使用 `{variable}` 占位符，由调用方在发送前填充具体值。
本模块不直接调用 API，仅提供字符串。
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# 1. 结构化摘要提取 Prompt（JSON Mode）
# ---------------------------------------------------------------------------

EXTRACT_ABSTRACT_PROMPT = """你是一位专业的科研文献分析助手。请仔细阅读以下论文全文，提取关键信息并以 JSON 格式返回。

要求字段：
- title: 论文标题
- authors: 作者列表（数组）
- year: 发表年份（整数）
- journal: 期刊名
- background: 研究背景（200字内）
- methods: 核心研究方法（200字内）
- key_results: 核心结果列表（3-5条，每条100字内）
- conclusion: 结论（150字内）
- keywords: 关键词列表（5-8个）

注意：
1. 如果某字段信息缺失，返回空字符串或空数组，不要编造
2. 保持学术准确性，不要过度概括
3. 输出必须是合法 JSON，不要包含 markdown 代码块标记

论文全文：
{paper_text}"""


# ---------------------------------------------------------------------------
# 2. 跨文献问答 Prompt
# ---------------------------------------------------------------------------

CROSS_LITERATURE_CHAT_PROMPT = """你是一位专业的科研综述助手。以下是 {paper_count} 篇文献的结构化摘要，请基于这些信息回答用户的问题。

注意：
1. 回答必须基于提供的文献，不要引入外部知识
2. 如果多篇文献观点冲突，请明确指出分歧
3. 引用文献时标注 [作者 年份]
4. 如果信息不足以回答问题，请明确说明

{concatenated_abstracts}

用户问题：{question}"""


# ---------------------------------------------------------------------------
# 3. 单篇精读 Prompt（基于原文）
# ---------------------------------------------------------------------------

SINGLE_PAPER_FULLTEXT_PROMPT = """你是一位专业的科研文献精读助手。以下是论文的完整原文，请基于原文内容回答用户的问题。

注意：
1. 回答必须基于提供的原文，不要引入外部知识
2. 引用原文时标注页码（如"第3页提到..."），帮助用户定位
3. 如果原文中没有相关信息，请明确说明
4. 回答保持学术性和准确性

论文原文：
{full_text}

用户问题：{question}"""


# ---------------------------------------------------------------------------
# 4. 单篇精读 Prompt（基于摘要）
# ---------------------------------------------------------------------------

SINGLE_PAPER_SUMMARY_PROMPT = """你是一位专业的科研文献精读助手。以下是论文的结构化摘要，请基于摘要内容回答用户的问题。

注意：
1. 回答必须基于提供的摘要，不要引入外部知识
2. 如需更详细的信息，可以建议用户查看原文
3. 如果摘要中信息不足，请明确说明
4. 回答保持学术性和准确性

论文摘要：
{summary}

用户问题：{question}"""


# ---------------------------------------------------------------------------
# 辅助函数：Prompt 填充
# ---------------------------------------------------------------------------


def build_extract_prompt(paper_text: str) -> str:
    """构建结构化摘要提取 Prompt.

    Args:
        paper_text: 论文全文文本。

    Returns:
        填充后的 Prompt 字符串。
    """
    return EXTRACT_ABSTRACT_PROMPT.format(paper_text=paper_text)


def build_cross_literature_chat_prompt(
    concatenated_abstracts: str,
    question: str,
    paper_count: int = 0,
) -> str:
    """构建跨文献问答 Prompt.

    Args:
        concatenated_abstracts: 拼接后的多篇文献摘要。
        question: 用户提问。
        paper_count: 文献数量（可选，用于显示）。

    Returns:
        填充后的 Prompt 字符串。
    """
    return CROSS_LITERATURE_CHAT_PROMPT.format(
        paper_count=paper_count if paper_count > 0 else "多",
        concatenated_abstracts=concatenated_abstracts,
        question=question,
    )


def build_single_paper_chat_prompt(
    *,
    full_text: str = "",
    summary: str = "",
    question: str = "",
    use_fulltext: bool = False,
) -> str:
    """构建单篇精读问答 Prompt.

    Args:
        full_text: 论文全文文本（use_fulltext=True 时必填）。
        summary: 论文结构化摘要（use_fulltext=False 时使用）。
        question: 用户提问。
        use_fulltext: 是否使用全文模式。

    Returns:
        填充后的 Prompt 字符串。

    Raises:
        ValueError: use_fulltext=True 时 full_text 为空，或 use_fulltext=False 时 summary 为空。
    """
    if use_fulltext:
        if not full_text:
            raise ValueError("use_fulltext=True 时必须提供 full_text 参数")
        return SINGLE_PAPER_FULLTEXT_PROMPT.format(
            full_text=full_text,
            question=question,
        )
    else:
        if not summary:
            raise ValueError("use_fulltext=False 时必须提供 summary 参数")
        return SINGLE_PAPER_SUMMARY_PROMPT.format(
            summary=summary,
            question=question,
        )


__all__ = [
    # 模板
    "EXTRACT_ABSTRACT_PROMPT",
    "CROSS_LITERATURE_CHAT_PROMPT",
    "SINGLE_PAPER_FULLTEXT_PROMPT",
    "SINGLE_PAPER_SUMMARY_PROMPT",
    # 构建函数
    "build_extract_prompt",
    "build_cross_literature_chat_prompt",
    "build_single_paper_chat_prompt",
]
