"""提取 Prompt 模板模块.

为 Kimi API 调用提供结构化摘要提取 Prompt 模板，与 SPEC §8.1 对齐。

问答 Prompt 已迁移至 chat_prompt.py。
本模块仅保留提取 Prompt。

所有模板使用 `{variable}` 占位符，由调用方在发送前填充具体值。
本模块不直接调用 API，仅提供字符串。
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# 结构化摘要提取 Prompt（JSON Mode，SPEC §8.1）
# ---------------------------------------------------------------------------

EXTRACT_ABSTRACT_PROMPT = """你是一位专业的科研文献分析助手。请仔细阅读以下论文全文，提取关键信息并以 JSON 格式返回。

要求字段（共12个）：
1. title: 论文标题
2. authors: 作者列表（数组）
3. year: 发表年份（整数）
4. journal: 期刊名
5. research_question: 该研究要回答的科学问题（50字内）
6. sample_source: 样本来源（如'人血浆外泌体'、'小鼠骨髓间充质干细胞'）
7. sample_size: 样本量（如'n=30'、'3个独立批次'）
8. key_methods: 核心技术列表（如['质谱分析', '流式细胞术']）
9. key_data: 核心数据点列表（必须含具体数值，如'PC使EV摄取增加2.3倍(p<0.01)'）
10. conclusion: 结论（150字内）
11. limitations: 研究局限性列表（至少1条，如['仅体外实验', '样本量小(n=5)']）
12. keywords: 关键词列表（5-8个）

以下为兼容旧版保留字段（新提取也请填写，未来将退场）：
- background: 研究背景（200字内）
- methods: 核心研究方法（200字内）
- key_results: 核心结果列表（3-5条，每条100字内）

【质量要求】
- key_data 必须包含具体数值/指标，禁止'显著增加'、'明显降低'等模糊表述
- limitations 必须基于原文真实局限，禁止编造
- 如果某字段信息缺失，返回空字符串或空数组，不要编造
- 保持学术准确性，不要过度概括
- 输出必须是合法 JSON，不要包含 markdown 代码块标记

论文全文：
{paper_text}"""


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


__all__ = [
    "EXTRACT_ABSTRACT_PROMPT",
    "build_extract_prompt",
]
