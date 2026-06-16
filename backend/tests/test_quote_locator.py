"""
test_quote_locator — 7 个用例验证 quote_locator 模块的定位与拒绝行为。

用例设计契约（来自 STEP 1 评审通过）：
  (a) 精确逐字命中         → Step 2 直达, score=1.0
  (b) 模型删了开头 / 中间    → Step 3 模糊命中, 返回原文完整句
  (c) 模型改了连接词         → Step 3 命中
  (d) 词粘连 (maintenanceof) → 归一化后能命中
  (e) 特殊字符 (αvβ5 → avb5) → 归一化降级映射后命中
  (f) 连字符换行 (integ-\\nrin)→ 归一化拼接后命中
  (g) 负例：编造不存在的句子  → not_found（防张冠李戴）

每项测试额外打印实际 score 以供阈值余量审计。
"""

from __future__ import annotations

import pytest

from backend.services.quote_locator import LocateResult, locate_quote


# ═══════════════════════════════════════════════════════════════════
# Helper
# ═══════════════════════════════════════════════════════════════════


def _run(candidate: str, source: str, **kw) -> LocateResult:
    """Run locator + print score for audit."""
    result = locate_quote(candidate, source, **kw)
    print(f"  → status={result.status!r}  score={result.score:.4f}  page={result.page}")
    if result.status == "located":
        snippet = result.verbatim_quote.replace("\n", "\\n") if result.verbatim_quote else ""
        if len(snippet) > 120:
            snippet = snippet[:120] + "..."
        print(f"     verbatim_quote = {snippet!r}")
    return result


# ═══════════════════════════════════════════════════════════════════
# Case (a) — 精确逐字命中  (Buchholz2009 p2, Results 段)
# ═══════════════════════════════════════════════════════════════════

CASE_A_SOURCE = (
    "Cells could be serially passaged using trypsin for\n"
    "several passages (4\u20135), regaining epithelial morphology and\n"
    "pigment after each passage."
)

CASE_A_CANDIDATE = (
    "Cells could be serially passaged using trypsin for "
    "several passages (4\u20135), regaining epithelial morphology and "
    "pigment after each passage."
)


def test_a_exact_match():
    """(a) 模型给的即逐字原句 → Step 2 精确子串命中, score=1.0."""
    print("\n[test_a] exact verbatim match (step 2)")
    r = _run(CASE_A_CANDIDATE, CASE_A_SOURCE)

    assert r.status == "located"
    assert r.score == 1.0
    # verbatim_quote 必须是 source 原样（包含换行符）
    assert r.verbatim_quote is not None
    assert "\n" in r.verbatim_quote, "verbatim 应保留原文换行"
    assert "pigment after each passage" in r.verbatim_quote


# ═══════════════════════════════════════════════════════════════════
# Case (b) — 模型删了开头状语 + 改连接词  (Iwama2024 Introduction)
# ═══════════════════════════════════════════════════════════════════

CASE_B_SOURCE = (
    "Macular hole (MH) is a retinal break involving the fovea, "
    "which causes impaired vision including distortion and/or "
    "defect in central vision, and most often occurs in the "
    "elderly and females (McCannel et al., 2009)."
)

CASE_B_CANDIDATE = (
    "a retinal break involving the fovea that causes impaired "
    "vision including distortion and defect in central vision"
)


def test_b_trimmed_head():
    """(b) 模型删了开头 "Macular hole (MH)" + which→that → Step 3 模糊命中."""
    print("\n[test_b] model trimmed head + paraphrased conjunction (step 3)")
    r = _run(CASE_B_CANDIDATE, CASE_B_SOURCE)

    assert r.status == "located"
    assert r.score >= 0.85
    # 必须返回原文完整句，而非模型的缩略版
    assert r.verbatim_quote is not None
    assert "Macular hole (MH)" in r.verbatim_quote, \
        "verbatim 必须包含被模型删掉的 'Macular hole (MH)' 开头"
    assert "and/or" in r.verbatim_quote, \
        "verbatim 应保留原文 'and/or'（而非模型改写的 'and'）"


# ═══════════════════════════════════════════════════════════════════
# Case (c) — 模型改连接词  (Buchholz2009 Abstract)
# ═══════════════════════════════════════════════════════════════════

CASE_C_SOURCE = (
    "iPS-RPE expression of marker mRNAs was quantitatively "
    "similar to that of fRPE and hESC-RPE, and marker proteins "
    "were appropriately expressed and localized in polarized "
    "monolayers."
)

CASE_C_CANDIDATE = (
    "iPS-RPE expression of marker mRNAs showed similar levels "
    "to that of fRPE and hESC-RPE, and marker proteins were "
    "properly expressed and localized in polarized monolayers"
)


def test_c_paraphrased_conjunction():
    """(c) 模型改写措辞 (was quantitatively similar→showed similar levels, appropriately→properly) → Step 3."""
    print("\n[test_c] model changed conjunction wording (step 3)")
    r = _run(CASE_C_CANDIDATE, CASE_C_SOURCE)

    assert r.status == "located", \
        f"期望 located，实际 {r.status!r} score={r.score:.4f}"
    assert r.score >= 0.85, \
        f"score={r.score:.4f} 低于 0.85 阈值"
    assert r.verbatim_quote is not None
    assert "was quantitatively similar" in r.verbatim_quote, \
        "verbatim 应保留原文 'was quantitatively similar'"


# ═══════════════════════════════════════════════════════════════════
# Case (d) — 词粘连 maintenanceof  (Zhang2021 Background)
# ═══════════════════════════════════════════════════════════════════

CASE_D_SOURCE = (
    "RPE cells form a monolayer located between the choroid "
    "and the outer segments of photoreceptors, playing multifarious "
    "roles in maintenanceof visual function."
)

CASE_D_CANDIDATE = (
    "RPE cells form a monolayer located between the choroid "
    "and the outer segments of photoreceptors, playing multifarious "
    "roles in maintenance of visual function"
)


def test_d_word_conglutination():
    """(d) 原文 'maintenanceof' 粘连 → 归一化后能匹配正常 'maintenance of'."""
    print("\n[test_d] word conglutination 'maintenanceof' ")
    r = _run(CASE_D_CANDIDATE, CASE_D_SOURCE)

    assert r.status == "located"
    assert r.score >= 0.85
    assert r.verbatim_quote is not None
    # 关键：verbatim 必须保留原文粘连形式
    assert "maintenanceof" in r.verbatim_quote, \
        "verbatim 必须保留原文粘连 'maintenanceof'（而非 model 的 'maintenance of'）"


# ═══════════════════════════════════════════════════════════════════
# Case (e) — 特殊字符 αvβ5 归一化  (Buchholz2009 Abstract, 含 Unicode)
# ═══════════════════════════════════════════════════════════════════

CASE_E_SOURCE = (
    "Levels of rod outer segment phagocytosis by iPS-RPE, "
    "fRPE, and hESC-RPE were likewise similar and dependent on "
    "integrin \u03b1v\u03b25."
)  # αvβ5 (Unicode Greek letters)

CASE_E_CANDIDATE = (
    "phagocytosis by iPS-RPE, fRPE, and hESC-RPE were "
    "similar and dependent on integrin avb5"
)


def test_e_unicode_normalization():
    """(e) 原文 αvβ5 (Unicode) → 归一化降级 avb5 后匹配, verbatim 保留原 Unicode."""
    print("\n[test_e] unicode αβ→ab normalization")
    r = _run(CASE_E_CANDIDATE, CASE_E_SOURCE)

    assert r.status == "located"
    assert r.score >= 0.85
    assert r.verbatim_quote is not None
    # verbatim 必须保留原文 Unicode 字符
    assert "\u03b1v\u03b25" in r.verbatim_quote, \
        "verbatim 必须保留原文 Unicode αvβ5（不能降级为 avb5）"


# ═══════════════════════════════════════════════════════════════════
# Case (f) — 连字符换行 integ-\nrin  (Buchholz2009 Abstract, 第1页)
# ═══════════════════════════════════════════════════════════════════

CASE_F_SOURCE = (
    "Levels of rod outer segment phagocytosis by "
    "iPS-RPE, fRPE, and hESC-RPE were likewise similar and "
    "dependent on integ-\nrin avb5."
)

CASE_F_CANDIDATE = (
    "phagocytosis by iPS-RPE, fRPE, and hESC-RPE were "
    "likewise similar and dependent on integrin avb5"
)


def test_f_hyphen_join():
    """(f) 原文 integ-\\nrin 连字符换行 → 归一化拼接为 integrin 后匹配."""
    print("\n[test_f] hyphenated line-break 'integ-\\nrin' ")
    r = _run(CASE_F_CANDIDATE, CASE_F_SOURCE)

    assert r.status == "located"
    assert r.score >= 0.85
    assert r.verbatim_quote is not None
    # verbatim 必须保留原文连字符换行
    assert "integ-\nrin" in r.verbatim_quote, \
        "verbatim 必须保留原始连字符换行 'integ-\\nrin'"


# ═══════════════════════════════════════════════════════════════════
# Case (g) — 负例：编造的句子  (Zhang2021 Abstract 作为来源)
# ═══════════════════════════════════════════════════════════════════

CASE_G_SOURCE = (
    "Background: Age-related macular degeneration (AMD) is the "
    "leading cause of blindness in the elderly due in large part "
    "to age-dependent atrophy of retinal pigment epithelium (RPE) "
    "cells. RPE cells form a monolayer located between the choroid "
    "and the outer segments of photoreceptors, playing multifarious "
    "roles in maintenance of visual function."
)

CASE_G_CANDIDATE = (
    "RPE cells play a critical role in the visual cycle by "
    "regenerating 11-cis-retinal through the retinoid cycle, "
    "which is essential for photoreceptor function"
)


def test_g_fabricated_sentence():
    """(g) 模型编造了原文不存在的句子 → not_found（防张冠李戴）."""
    print("\n[test_g] NEGATIVE: fabricated sentence must be NOT_FOUND")
    r = _run(CASE_G_CANDIDATE, CASE_G_SOURCE)

    assert r.status == "not_found", \
        f"编造句子必须 not_found，但得到 status={r.status!r} score={r.score:.4f} — 存在张冠李戴风险！"
    assert r.verbatim_quote is None
    assert r.page is None
    assert r.char_span is None
    # 额外断言：score 必须明显低于 0.85（安全余量）
    assert r.score < 0.85, \
        f"编造句子 score={r.score:.4f} ≥ 0.85 阈值 — 阈值余量不足，需提高阈值或增加额外判据！"




# ═══════════════════════════════════════════════════════════════════
# 辅助用例：空输入防护
# ═══════════════════════════════════════════════════════════════════


def test_empty_input():
    """空 candidate 或空 source 应返回 not_found 而非崩溃."""
    assert locate_quote("", "some text").status == "not_found"
    assert locate_quote("some text", "").status == "not_found"
    assert locate_quote("   ", "text").status == "not_found"


# ═══════════════════════════════════════════════════════════════════
# Case (h) — 负例：编造句含真实实体 RPE65 (Buchholz2009 excerpt)
# ═══════════════════════════════════════════════════════════════════

CASE_H_SOURCE = (
    "iPS-RPE molecularly and functionally resembles fRPE and hESC-RPE. "
    "Marker mRNAs (RPE65, CRALBP, ZO-1, EMMPRIN, PEDF, Mitf, Otx2, Pax6, "
    "Tyrp1, and Tyrp2) were quantitatively similar. "
    "Levels of rod outer segment phagocytosis by iPS-RPE, fRPE, and "
    "hESC-RPE were likewise similar and dependent on integrin avb5. "
    "Pigmented foci were large enough for mechanical dissection after "
    "2\u20133 months of bFGF-free culture."
)

CASE_H_CANDIDATE = (
    "RPE65 plays a critical role in mitochondrial DNA repair through "
    "a novel CRISPR-based pathway that enhances cellular metabolism"
)


def test_h_fabricated_with_real_entity_rpe65():
    """(h) NEGATIVE: fabricated sentence containing genuine entity 'RPE65'.
    
    硬锚点最危险的盲点：锚点命中了真实实体(RPE65)，但整句内容纯属编造。
    必须仍返回 not_found，不能因锚点命中而误判为 located。
    """
    print("\n[test_h] NEGATIVE: fabricated + real entity (RPE65) => NOT_FOUND")
    r = _run(CASE_H_CANDIDATE, CASE_H_SOURCE)

    assert r.status == "not_found", (
        f"编造句子(含真实体RPE65)必须 not_found，"
        f"但得到 status={r.status!r} score={r.score:.4f} — "
        f"硬锚点误将编造内容锚定到了真段落！"
    )
    assert r.verbatim_quote is None
    assert r.score < 0.85, (
        f"编造句子 score={r.score:.4f} >= 0.85 阈值 — "
        f"锚点定位虽然正确但模糊匹配余量不足，需确认安全"
    )


# ═══════════════════════════════════════════════════════════════════
# Case (i) — 负例：编造句含真实实体 iPSC/RPE 但内容错误
# ═══════════════════════════════════════════════════════════════════

CASE_I_SOURCE = CASE_H_SOURCE  # 复用同一原文

CASE_I_CANDIDATE = (
    "iPSC-derived RPE cells show significant improvement in treating "
    "Parkinson's disease through dopamine secretion and synaptic repair"
)


def test_i_fabricated_with_real_entity_ipsc_rpe():
    """(i) NEGATIVE: fabricated sentence with real entities 'iPSC' and 'RPE'.
    
    锚点 iPSC + RPE 在原文中出现多次，但整句内容("Parkinson's disease",
    "dopamine secretion")与原文(RPE phagocytosis)毫无关系——必须 not_found。
    """
    print("\n[test_i] NEGATIVE: fabricated + real entities (iPSC,RPE) => NOT_FOUND")
    r = _run(CASE_I_CANDIDATE, CASE_I_SOURCE)

    assert r.status == "not_found", (
        f"编造句子(含真实体iPSC/RPE但内容错误)必须 not_found，"
        f"但得到 status={r.status!r} score={r.score:.4f}"
    )
    assert r.score < 0.85


# ═══════════════════════════════════════════════════════════════════
# Case (j) — 负例：编造句含多个真实实体但编造了机制
# ═══════════════════════════════════════════════════════════════════

CASE_J_SOURCE = CASE_H_SOURCE

CASE_J_CANDIDATE = (
    "Oct4 and Sox2 expression in fRPE was found to regulate lipid "
    "metabolism via PPAR-gamma pathway activation, independent of "
    "the canonical pluripotency network"
)


def test_j_fabricated_with_multiple_real_entities():
    """(j) NEGATIVE: fabricated with multiple real entities (Oct4,Sox2,fRPE).
    
    多个真实体同时出现可能形成"强锚点组合"，但整句语义仍是编造的。
    硬锚点必须仍然拒绝(not_found)——多个真实体锚定到一个区域后，
    模糊匹配仍因内容不符而低于阈值。
    """
    print("\n[test_j] NEGATIVE: fabricated + multiple real entities => NOT_FOUND")
    r = _run(CASE_J_CANDIDATE, CASE_J_SOURCE)

    assert r.status == "not_found", (
        f"编造句子(含多个真实体Oct4/Sox2/fRPE)必须 not_found，"
        f"但得到 status={r.status!r} score={r.score:.4f} — "
        f"多锚点组合可能导致误判为 located！"
    )
    assert r.score < 0.85, (
        f"多实体编造句 score={r.score:.4f} >= 0.85 — "
        f"硬锚点的多锚点+模糊匹配组合存在安全盲区！"
    )
