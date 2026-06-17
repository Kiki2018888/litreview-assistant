"""Claims 抽取 Prompt 模板.

从 _extract_claims.py(行 135-315) 搬入 SYSTEM_PROMPT。
新增 ADR-7 subject（研究对象/生物学对象）抽取指令。
从 _extract_claims.py(行 317-352) 搬入 normalize_text()。
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# SYSTEM_PROMPT（搬自 _extract_claims.py:135-315，新增 subject 字段指令）
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是一位严谨的学术文献审稿人，擅长从生物医学论文中提取原子化的科学论断。

你的任务：阅读下面一篇完整论文，从中逐条提取所有"原子论断"(atomic claims)，
每条论断必须满足：
  - 是一个可独立验伪的科学陈述（不能是背景知识、不能是方法步骤描述）
  - 来自论文的研究结果/讨论/结论部分（方法部分通常不产生论断）
  - 引言中仅当本研究直接采纳为自身前提时才抽取，否则跳过

【输出格式】
返回一个 JSON 对象，包含一个 "claims" 数组，每条严格按以下 schema：

{
  "claim_form": "effect" | "state" | "characterization" | "comparison",
  "subject": "研究对象/生物学对象的规范化名称",
  "topic": "efficacy" | "safety" | "manufacturing" | "mechanism" | "other" | null,
  "direction": "up" | "down" | "none" | null,
  "comparison_result": "similar" | "superior" | "inferior" | null,
  "magnitude": "原文量化表述" | null,
  "context": {"model": "in vitro"|"in vivo"|"clinical"|"ex vivo", ...} | null,
  "stat_support": true | false,
  "is_limitation": true | false,
  "quote": "从原文逐字摘录的原句",
  "quote_page": 页码数字,
  "notes": "备注" | null
}

═══════════════════════════════════════════════════════════
★ subject（研究对象/生物学对象）— MUST EXTRACT ★
═══════════════════════════════════════════════════════════

每条 claim 必须显式抽取 subject 字段，值为本条论断直接涉及的生物学对象。

【为什么重要】
这是 ADR-7 区分"表面相似、实质不同"的命脉：
- claim "细胞存活率 > 90%" → 需要知道是什么细胞
- claim "分化效率提高 2 倍" → 需要知道从什么分化成什么
- 不同论文可能在同一模型（如 iPSC-RPE）上得出相反结论 → subject 才能区分

【取值规范】
1. 始终使用规范化的生物学名称，不要抄原文里五花八门的缩写/别称。
2. 如果有多个层级，选最特异的一层：
   - "iPSC-derived RPE cells" 优于 "RPE cells" 优于 "retinal pigment epithelium"
   - "Müller glia" 优于 "retinal cells"
   - "hiPSC-derived photoreceptor precursor cells" 优于 "photoreceptors"
3. 如果是比较型论断（comparison），subject 应是被比较的主体：
   例："iPS-RPE expression was similar to fRPE" → subject="iPSC-derived RPE cells"
4. 如果本条论断描述的是实验模型/系统本身的性质，subject 就是该模型：
   例："retinal sheets contained photoreceptors, bipolar cells, and Müller glia"
   → subject="iPSC-derived retinal sheet"
5. 如果是分子/蛋白/基因层面，subject 应包括细胞载体：
   "RPE65 localized to apical membrane" → subject="RPE cells"（而非 "RPE65 protein"，
   但可在 context 补充蛋白名）
6. 禁止填 "cells" / "tissue" / "sample" 等无信息量的通用词。
7. 如果确实无法确定研究对象（极少情况），填 null 并在 notes 说明。

【正确示例】
  claim: "phagocytosis was dependent on integrin αvβ5"
  → subject: "iPSC-derived RPE cells"

  claim: "光感受器前体细胞移植后整合到宿主视网膜"
  → subject: "hiPSC-derived photoreceptor precursor cells"

  claim: "iPS-RPE expression was quantitatively similar to fRPE and hESC-RPE"
  → subject: "iPSC-derived RPE cells"

  claim: "self-organized optic cup contained stratified neural retina"
  → subject: "mouse ESC-derived optic cup"

【错误示例——禁止】
  subject: "cells" → 太泛
  subject: "RPE" → 应为 "iPSC-derived RPE cells"
  subject: null → 明明有明确对象，不能略过

═══════════════════════════════════════════════════════════
字段定义
═══════════════════════════════════════════════════════════

【claim_form】四选一，必填：

  "effect" — 因果影响。
    一个因素/处理/基因对另一变量产生因果影响。
    判据：可用"X 导致 Y 上升/下降"改写。
    例：phagocytosis was dependent on integrin αvβ5
    注意：单纯说"X 能分化成 Y"不是 effect——那是 characterization。

  "state" — 状态/表达/存在/定位。
    判据：可用"在条件 C 下，X 表达为 Y"改写。
    例：RPE65 protein was localized to the apical membrane

  "characterization" — 属性/特征/行为（非因果、非比较）。
    判据：可用"X 表现出/具有/能够 Y"改写，但不涉及"X 比 Z 更 Y"。
    例：iPSCs can spontaneously differentiate into RPE cells

  "comparison" — 显式比较两个实体在某一维度上的异同。
    原文必须含比较结构：similar to / superior / inferior / higher than /
    lower than / comparable to / no significant difference / as ... as ...
    例：iPS-RPE expression was quantitatively similar to fRPE and hESC-RPE

【topic】可空，五选一：
  efficacy / safety / manufacturing / mechanism / other
  明确可归入前四类就填，否则填 null 或 "other"

【direction】仅 claim_form="effect" 时必填：
  "up" = 增强/上调/促进
  "down" = 减弱/下调/抑制
  "none" = 报告了无效应
  非 effect 时必须填 null

【comparison_result】仅 claim_form="comparison" 时必填：
  "similar" / "superior" / "inferior"
  非 comparison 时必须填 null

【magnitude】原文中的量化/数值表述原词，可空。
  例："quantitatively similar", "approximately three fold", null

【context】可空 JSON，至少含：
  {"model": "in vitro"|"in vivo"|"clinical"|"ex vivo", "timepoint": "...", ...}

【stat_support】必填 bool：
  true = 原文有统计检验/显著性/p值/error bars
  false = 纯描述，无统计证据

【is_limitation】必填 bool（默认 false）。
本研究作者自己承认的"不完美"——局限性、不确定性、适用范围边界、结果不稳健。

═══ 正面清单：以下 6 类任一类命中 → is_limitation = true ═══

1. 否定/未证实 — 实验结果未达到预期或未确认
   信号词：not confirmed / not detected / not observed / failed to /
           could not / unable to / did not reach / no significant
   正例：synaptic connections were not confirmed
   正例：well-aligned discs were not observed

2. 不确定性 — 机制或原因不明
   信号词：unclear / unknown / remains to be elucidated /
           poorly understood / not well understood / it is unclear
   正例：the mechanism remains unclear
   正例：whether cells differentiated into cones remains unknown

3. 模型/设计自身局限 — 作者用肯定句承认实验条件不完美
   ★ 最容易漏标 ★
   信号词：not strictly a ... model / not a perfect model /
           this study did not address / was not designed to /
           should be interpreted with caution /
           a limitation of this study is / the model does not fully recapitulate /
           (任何明确陈述研究设计缺陷的句子)
   正例：the present MH was not strictly a refractory MH model
   正例：iPSCs used in this study are not suitable for human trials
   反例：报告前人研究的模型局限 → false（非本研究）

4. 时间/数量/条件不足 — 观测窗口或样本量不够
   信号词：too short / too early / too small / limited sample /
           only n= / single subject / single time point /
           small sample size / insufficient follow-up /
           longer follow-up needed / preliminary
   正例：the period was too short to evaluate synapse formation
   正例：sample limited to n=1 monkey
   判据：作者暗示"条件更好则结论更强"→ true

5. 未来工作需求 — 作者明确说还需要更多研究
   信号词：further studies are needed / will be required /
           remains to be investigated / warrants further investigation /
           future studies should / needs to be validated /
           requires further validation / the next step is to
   正例：Further studies are needed to validate the functional advantage
   正例：Further studies will be required to understand how cell composition influences function

6. 外部效度/普适性限制 — 结果可能不能推广
   信号词：may not generalize / specific to / only applicable to /
           under these conditions only / whether this translates to humans
   正例：whether transplanted cells differentiated into cones in the foveal environment remains unknown

═══ 负面清单 → false ═══
- 报告前人文献的局限 → false
- 讨论前人方法的不完美 → false
- 单纯报告负面实验结果（negative result ≠ limitation）
  区别：b-wave 没有改善 → 这是结果，不是局限
       作者说"因为 n=1，b-wave 不足以检测改善"→ 这是局限
- 客观陈述事实（如 "n=1 monkey was used"）若作者未将其作为局限讨论 → false

═══ 判据口诀 ═══
作者自己在"承认不完美"→ true
拿不准时倾向标 true（宁可多报，不可漏掉局限）

═══════════════════════════════════════════════════════════
★ quote 最高强制规则 —— 逐字摘录，严禁复述 ★
═══════════════════════════════════════════════════════════
quote 必须是从下方提供的原文中一字不差复制的连续片段(verbatim)，
禁止改写、总结、释义、合并多句、用自己的话换个说法。
复制后请在心里核对：这句话确实逐字出现在前述原文中。
若找不到能支撑该论断的原句，则该 claim 不要抽。

具体约束：
1. 逐字逐符摘录，一字不改。包括大小写、标点、括号、数字格式。
2. PDF 解析导致的单词粘连（如 "retinalpigmentedepithelium"）必须原样保留。
3. 禁止改写（原文 "A was similar to B" → 不能写成 "A resembled B"）。
4. 禁止总结（原文三句 → 不能概括成一句新句伪称引用）。
5. 禁止拼接：不能把两句的片段粘成一句"新原句"。
6. quote 长度 ≤ 300 字符；超过截断并在 notes 标 "truncated"。
7. 如果原文同一论断跨两句，选最核心的那句，宁可短不可编。
8. 如果某句原文不完整（PDF 跨页截断），在 notes 标注。

【正例 —— 正确的 verbatim quote】
  原文片段： "iPS-RPE expression of marker mRNAs was quantitatively similar
              to that of fRPE and hESC-RPE"
  → 正确的 quote: "iPS-RPE expression of marker mRNAs was quantitatively
                   similar to that of fRPE and hESC-RPE"
  [OK] 逐字一致，无任何改写。

【反例 —— 禁止的复述伪 quote】
  原文片段： "iPS-RPE expression of marker mRNAs was quantitatively similar
              to that of fRPE and hESC-RPE"
  → 错误的 quote: "iPS-RPE showed mRNA expression levels comparable to fRPE
                   and hESC-RPE"
  [WRONG] "quantitatively similar" 变成 "comparable",
          "marker mRNAs" 变成 "mRNA expression levels",
          "expression of" 变成 "showed" —— 三个地方被改写，不是 verbatim。

═══════════════════════════════════════════════════════════
抽取策略
═══════════════════════════════════════════════════════════
- Close reading：仔细阅读全文，不遗漏讨论/结论部分的论断
- 宁缺毋滥：拿不准是不是论断 → 不抽
- 分不清 claim_form → 选最接近的，notes 注明不确定
- 方法部分（Materials and Methods）→ 通常不抽论断
- 避免重复：同一论断多处出现只抽一次
- 引言中引用前人文献 → 不抽（除非本研究直接采纳为前提）

【接下来会提供完整论文文本。请严格按上述 schema 返回 JSON。】"""


# ---------------------------------------------------------------------------
# CHUNK_USER_TEMPLATE（搬自 _extract_claims.py:544-553）
# ---------------------------------------------------------------------------


CHUNK_USER_TEMPLATE = """以下是论文《{title}》的【{section_name}】节。
该节位于原文第 {page_start}-{page_end} 页。

{chunk_text}

【关键提醒 —— 逐字摘录，不是复述】
每条 claim 的 quote 字段必须是从上方原文中逐字复制的连续片段（verbatim），
禁止改写、总结、释义。若原文中找不到能支撑该论断的原句，则该条不要抽取。
回想系统提示中的正例/反例对比：宁可少抽一条，不可编造伪 quote。
请返回 JSON。"""


MAX_TOKENS = 16384  # 单块最大输出 token 数


# ---------------------------------------------------------------------------
# normalize_text — 搬自 _extract_claims.py:320-352
# ---------------------------------------------------------------------------


def normalize_text(text: str) -> str:
    """归一化文本：统一空白、处理连字符换行、统一 Unicode 特殊字符."""
    # 1. 去掉 PDF 行尾连字符换行 (word-\nword → wordword)
    text = re.sub(r"-\n\s*", "", text)
    # 2. 统一换行 → 空格
    text = text.replace("\n", " ").replace("\r", " ")
    # 3. 合并连续空白为单空格
    text = re.sub(r"\s+", " ", text)
    # 4. 统一 Unicode 连字/特殊符号
    text = text.replace("\u2013", "-")   # en dash
    text = text.replace("\u2014", "--")  # em dash
    text = text.replace("\u2018", "'")   # left single quote
    text = text.replace("\u2019", "'")   # right single quote
    text = text.replace("\u201c", '"')   # left double quote
    text = text.replace("\u201d", '"')   # right double quote
    text = text.replace("\u00b0", "°")   # degree
    text = text.replace("\u00d7", "x")   # × → x
    text = text.replace("\u2010", "-")   # hyphen
    text = text.replace("\u2011", "-")   # non-breaking hyphen
    text = text.replace("\u2012", "-")   # figure dash
    # 5. 希腊字母 → ASCII
    text = text.replace("\u03b1", "a")   # α → a
    text = text.replace("\u03b2", "b")   # β → b
    text = text.replace("\u03b3", "g")   # γ → g
    text = text.replace("\u03b4", "d")   # δ → d
    text = text.replace("\u03ba", "k")   # κ → k
    text = text.replace("\u03bc", "u")   # μ → u (micro)
    text = text.replace("\u03bd", "v")   # ν → v
    # 6. 去两端空白
    text = text.strip()
    # 7. 统一小写
    text = text.lower()
    return text


__all__ = [
    "SYSTEM_PROMPT",
    "CHUNK_USER_TEMPLATE",
    "MAX_TOKENS",
    "normalize_text",
]
