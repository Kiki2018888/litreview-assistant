"""问答 Prompt 模板模块.

为 Kimi API 调用提供跨文献问答和单篇精读 Prompt 模板，与 SPEC §8.2 / §8.3 对齐。
从 extract_prompt.py 中分离，提取 Prompt 继续留在 extract_prompt.py。

所有模板使用 `{variable}` 占位符，由调用方在发送前填充具体值。
本模块不直接调用 API，仅提供字符串。
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# 1. 跨文献问答 Prompt（SPEC §8.2 工程化版本）
# ---------------------------------------------------------------------------

CROSS_LITERATURE_CHAT_PROMPT = """你是一位严谨的科研文献综述专家。以下提供了 {paper_count} 篇文献的**结构化摘要**，请严格基于提供的数据进行深度对比分析。

【禁止事项】
- 禁止"具有重要意义"、"为后续研究奠定基础"、"有待进一步研究"等空话
- 禁止无引用总结（每个观点必须标注 [作者 年份]）
- 禁止将 A 文献的数据/结论安到 B 文献上（幻觉交叉污染）

【输出要求】（必须按以下结构输出）

### 1. 研究脉络（时间顺序）
按发表时间排列，每篇必须标注：
- 研究目标（该文献要解决什么问题）
- 与前篇的关系（继承/反驳/扩展/无关）

### 2. 方法对比矩阵（Markdown 表格）
| 文献 | 样本来源 | 样本量 | 关键技术 | 检测指标 |
|------|---------|--------|---------|---------|
| [作者 年份] | ... | ... | ... | ... |

### 3. 结果矛盾点（必须找出）
明确指出两篇及以上文献在哪些结论上不一致：
- "[作者A 年份] 发现 X（数据: ...），但 [作者B 年份] 发现 Y（数据: ...），矛盾可能源于..."

### 4. 核心数据汇总
列出所有文献的关键数据点（必须含数值）：
- [作者 年份]: 关键发现 + 具体数值

### 5. 研究空白（基于局限性）
基于各文献的 limitations，指出该领域尚未回答的问题：
- "目前所有研究均为体外实验（[作者A 年份], [作者B 年份]），缺乏体内验证"

### 6. 临床/产业启示（具体、可落地）
- 具体建议，禁止"有待进一步研究"

【文献数据】
{concatenated_abstracts}

【用户问题】
{question}"""


# ---------------------------------------------------------------------------
# 2. 单篇精读 Prompt（基于全文，SPEC §8.3 工程化版本）
# ---------------------------------------------------------------------------

SINGLE_PAPER_FULLTEXT_PROMPT = """你是一位专业的文献精读助手。用户正在阅读以下论文，请基于原文回答。

【回答要求】
- 引用原文时标注页码（如"第3页提到..."）
- 涉及数据时必须给出具体数值
- 如果用户问的是图表内容，请描述图表展示的核心趋势/对比关系
- 如果问题超出原文范围，明确说明"原文未涉及"

【论文全文】
{full_text}

【用户问题】
{question}"""


# ---------------------------------------------------------------------------
# 3. 单篇精读 Prompt（基于摘要，适配 SPEC §8.3）
# ---------------------------------------------------------------------------

SINGLE_PAPER_SUMMARY_PROMPT = """你是一位专业的文献精读助手。以下是论文的结构化摘要，请基于摘要内容回答用户的问题。

【回答要求】
- 涉及数据时必须给出具体数值
- 如果摘要中信息不足，明确说明"摘要未涉及，建议查阅原文"
- 如果用户问的是方法细节，基于关键技术字段回答

【论文摘要】
{summary}

【用户问题】
{question}"""


# ---------------------------------------------------------------------------
# 辅助函数：Prompt 填充
# ---------------------------------------------------------------------------


def build_cross_literature_chat_prompt(
    concatenated_abstracts: str,
    question: str,
    paper_count: int = 0,
) -> str:
    """构建跨文献问答 Prompt（SPEC §8.2 工程化版本）.

    Args:
        concatenated_abstracts: 拼接后的多篇文献摘要。
        question: 用户提问。
        paper_count: 文献数量。

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
    "CROSS_LITERATURE_CHAT_PROMPT",
    "SINGLE_PAPER_FULLTEXT_PROMPT",
    "SINGLE_PAPER_SUMMARY_PROMPT",
    # 构建函数
    "build_cross_literature_chat_prompt",
    "build_single_paper_chat_prompt",
]
