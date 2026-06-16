"""
quote_locator: LLM 引用句 → 原文逐字定位。

Solves F17 (Verbatim Quote Traceability):
- LLM gives an approximate sentence → this module finds its exact position in source text
- Uses Unicode normalization + fuzzy sliding window matching
- Returns the ORIGINAL (verbatim) text from source, not LLM's paraphrased version

Architecture (4 steps):
  1. Bidirectional normalization with position mapping
  2. Exact substring match (fast path)
  3. Fuzzy sliding-window match (rapidfuzz, threshold 0.85)
  4. Page + char_span backfill via page_map
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple

try:
    from rapidfuzz import fuzz as _fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False


# ═══════════════════════════════════════════════════════════════════
# Unicode / PDF noise → ASCII-friendly normalization map
# ═══════════════════════════════════════════════════════════════════

_UNICODE_MAP = {
    # Greek letters → single-char Latin (F17 key fix: α→a not alpha,
    # so αvβ5 matches avb5)
    "\u03b1": "a",  # α
    "\u03b2": "b",  # β
    "\u03b3": "g",  # γ
    "\u03b4": "d",  # δ
    "\u03b5": "e",  # ε
    "\u03bc": "u",  # μ
    # En/em dashes
    "\u2013": "-",
    "\u2014": "-",
    "\u2015": "-",
    # Smart quotes
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    # Special spaces
    "\u00a0": " ",
    "\u2009": " ",
}


# ═══════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════

@dataclass
class LocateResult:
    """Result of quote location in source text."""

    status: str  # "located" | "not_found"
    verbatim_quote: Optional[str] = None  # exact snippet from source_text
    page: Optional[int] = None
    char_span: Optional[Tuple[int, int]] = None  # (start, end) in source_text
    score: float = 0.0


# PageMap: [(page_end_char_exclusive, page_number), ...]
# e.g. [(5532, 1), (14237, 2)] means positions [0, 5532) = page 1
PageMap = List[Tuple[int, int]]


# ═══════════════════════════════════════════════════════════════════
# Step 1 — Normalise with position mapping
# ═══════════════════════════════════════════════════════════════════

def _build_normalised(text: str) -> Tuple[str, Callable[[int, int], Tuple[int, int]]]:
    """Normalise *text* for matching and return a callable that maps
    normalised-span → original-source-span.

    Normalisation rules (applied in order):
      (a) Remove ``(cid:N)`` noise patterns from PDF extraction
      (b) Join hyphenated line-breaks: ``integ-\\nrin`` → skipped
      (c) Map Unicode chars to ASCII (α→a …)
      (d) Collapse consecutive whitespace → single space
      (e) No lowercasing here — caller lowercases both sides identically.

    Returns
    -------
    (norm_text, get_source_span)
      norm_text : str
          Normalised text ready for matching.
      get_source_span(norm_start, norm_end) → (src_start, src_end)
          Map a normalised-span back to the original *text* span so we
          can return ``text[src_start:src_end]`` verbatim.
    """
    norm_chars: List[str] = []
    # Each normalised char maps to a contiguous source range [src_a, src_b)
    norm_src_ranges: List[Tuple[int, int]] = []

    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        # ── (a) (cid:N) removal ──
        if ch == "(" and i + 4 < n and text[i + 1 : i + 4] == "cid":
            end = text.find(")", i)
            i = (end + 1) if end != -1 else i + 4
            continue

        # ── (b) hyphenated line-break: "integ-\nrin" → skip "-\n" ──
        if ch == "-" and i + 1 < n and text[i + 1] == "\n":
            i += 2  # skip dash + newline
            continue

        # ── (c) Unicode char mapping ──
        mapped = _UNICODE_MAP.get(ch, ch)

        # ── (d) whitespace collapse (including newlines → space) ──
        if mapped.isspace():
            # Scan forward over the whitespace run
            j = i
            while j < n:
                cj = _UNICODE_MAP.get(text[j], text[j])
                if not cj.isspace():
                    break
                j += 1
            # Only emit a space if the previous normalised char isn't already space
            if norm_chars and norm_chars[-1] != " ":
                norm_chars.append(" ")
                norm_src_ranges.append((i, j))
            i = j
            continue

        # ── Normal (keep) ──
        norm_chars.append(mapped)
        norm_src_ranges.append((i, i + 1))
        i += 1

    # Trim leading/trailing whitespace from normalised text,
    # keeping ranges in sync by tracking how many chars are trimmed.
    leading_trim = 0
    while leading_trim < len(norm_chars) and norm_chars[leading_trim] == " ":
        leading_trim += 1
    if leading_trim > 0:
        norm_chars = norm_chars[leading_trim:]
        norm_src_ranges = norm_src_ranges[leading_trim:]

    trailing_trim = 0
    while trailing_trim < len(norm_chars) and norm_chars[-trailing_trim - 1] == " ":
        trailing_trim += 1
    if trailing_trim > 0:
        norm_chars = norm_chars[: len(norm_chars) - trailing_trim]
        norm_src_ranges = norm_src_ranges[: len(norm_src_ranges) - trailing_trim]

    norm_text = "".join(norm_chars)

    def get_source_span(norm_start: int, norm_end: int) -> Tuple[int, int]:
        """Map [norm_start, norm_end) back to [src_start, src_end) in *text*."""
        src_start = norm_src_ranges[norm_start][0]
        src_end = norm_src_ranges[norm_end - 1][1]
        return (src_start, src_end)

    return norm_text, get_source_span


def _normalise(text: str) -> str:
    """Lightweight normalise without position tracking (for candidate_quote)."""
    norm, _ = _build_normalised(text)
    return norm


# ═══════════════════════════════════════════════════════════════════
# Step 4 helper — page lookup
# ═══════════════════════════════════════════════════════════════════


def _get_page(char_pos: int, page_map: Optional[PageMap]) -> Optional[int]:
    """Return page number for *char_pos* using binary search on page_map."""
    if not page_map:
        return None
    for end_exclusive, page_num in page_map:
        if char_pos < end_exclusive:
            return page_num
    return None


# ═══════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════


def locate_quote(
    candidate_quote: str,
    source_text: str,
    page_map: Optional[PageMap] = None,
    fuzzy_threshold: float = 0.85,
) -> LocateResult:
    """Locate an LLM-produced candidate quote in source text.

    Internally routes to hard-anchor mode (extracts domain entities to
    constrain the search region) and falls back to global fuzzy matching
    when anchors are insufficient.

    Parameters
    ----------
    candidate_quote : str
        The approximate quote returned by the LLM (may be slightly rewritten).
    source_text : str
        Full-text extracted from PDF (with noise, hyphenation artefacts, etc.).
    page_map : PageMap or None
        List of ``(char_end_exclusive, page_number)`` tuples.  Character
        positions ``[0, end_0)`` are page 1, ``[end_0, end_1)`` are page 2, …
    fuzzy_threshold : float
        Minimum fuzzy-ratio (0..1) for Step 3 to accept a match.

    Returns
    -------
    LocateResult
    """
    # Delegate to anchored mode (which internally falls back to global
    # fuzzy when anchors are insufficient or ambiguous).
    return locate_quote_anchored(
        candidate_quote=candidate_quote,
        source_text=source_text,
        page_map=page_map,
        fuzzy_threshold=fuzzy_threshold,
    )


def _fuzzy_locate(
    norm_source: str,
    norm_candidate: str,
    min_score: float = 0.85,
) -> Optional[Tuple[int, int, float]]:
    """Sliding-window fuzzy match over normalised source.

    Tries multiple window sizes (candidate_len × 0.7 … 1.3).
    Slides by ~10 % of candidate length.
    """
    c_len = len(norm_candidate)
    s_len = len(norm_source)
    if c_len == 0 or s_len == 0 or c_len > s_len * 2:
        return None

    # Window sizes to try (extended to 1.5× for sentences with extra words)
    window_sizes: List[int] = []
    for ratio in (0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5):
        w = int(c_len * ratio)
        if 5 <= w <= s_len and w not in window_sizes:
            window_sizes.append(w)
    if not window_sizes:
        window_sizes = [c_len]

    step = max(1, c_len // 10)
    best_start, best_end, best_score = 0, 0, 0.0

    for start in range(0, s_len, step):
        for w in window_sizes:
            end = start + w
            if end > s_len:
                continue
            window = norm_source[start:end]
            score = _fuzz.ratio(norm_candidate, window) / 100.0
            if score > best_score:
                best_score = score
                best_start = start
                best_end = end

    if best_score >= min_score:
        return (best_start, best_end, best_score)
    return None


def _expand_to_sentence(
    norm_text: str,
    match_start: int,
    match_end: int,
    max_extend: int = 800,
) -> Tuple[int, int]:
    """Extend a match window to the nearest sentence boundaries.

    Sentence delimiters: ``. ! ?`` followed by space or end-of-string.
    Returns ``(expanded_start, expanded_end)`` in normalised-text space.
    """
    n = len(norm_text)

    # ── Expand backward to sentence start ──
    new_start = 0
    search_start = max(match_start - 1, 0)
    search_end = max(match_start - max_extend, 0)
    for i in range(search_start, search_end - 1, -1):
        if norm_text[i] in ".!?":
            # Jump past the delimiter; skip any trailing space
            j = i + 1
            while j < n and norm_text[j] == " ":
                j += 1
            new_start = j
            break
    else:
        new_start = max(0, match_start - max_extend)

    # ── Expand forward to sentence end ──
    new_end = n
    for i in range(match_end, min(match_end + max_extend, n)):
        if norm_text[i] in ".!?":
            new_end = i + 1
            break
    else:
        new_end = min(n, match_end + max_extend)

    # Safety: don't shrink below the original match
    new_start = min(new_start, match_start)
    new_end = max(new_end, match_end)

    return (new_start, new_end)


# ═══════════════════════════════════════════════════════════════════
# Step 3b — Hard Anchor Mode
# ═══════════════════════════════════════════════════════════════════
#
# Rationale: LLM paraphrases wording but preserves domain entities
# (gene names, abbreviations, numbers).  Extract those → find where
# they cluster in the source → constrain fuzzy matching to that region.
# This fixes the ~79% unverified rate where the global sliding window
# latches onto a "locally similar but semantically wrong" passage.

# Anchor extraction regexes
_ANCHOR_GENE_RE = re.compile(r"\b[A-Z][a-z]+\d+\b")          # RPE65, Oct4, Tyrp1
_ANCHOR_CAPITAL_RE = re.compile(r"\b[A-Z][A-Z0-9\-]+[A-Z0-9]\b")  # iPSC, ZO-1, AMD
_ANCHOR_NUMBER_RE = re.compile(r"\d+(?:[-–]\d+)?(?:\^?\d+)?")    # 10^7, 65-70, 30
_MIN_ANCHOR_LEN = 3  # skip anchors shorter than this (e.g. "av" is too common)

# Domain-specific entities that regex alone can't capture reliably
_ANCHOR_SPECIAL = {
    "ipsc", "ipscs", "ips-rpe", "ips(imr90)", "ips(foreskin)",
    "hesc", "hescs", "hesc-rpe", "frpe", "rpe65", "cralbp",
    "zo-1", "emmprin", "pedf", "mitf", "otx2", "pax6",
    "oct4", "sox2", "nanog", "lin28", "rax", "six3",
    "tyrp1", "tyrp2", "silver", "p1f6", "bfgf",
    "thomson factors", "amd", "retinitis pigmentosa",
    "drusen", "bruch", "ros", "kda", "integrin avb5",
    "avb5",
}


def _extract_anchors(normalised_candidate: str) -> list[str]:
    """Extract hard anchors (gene names, abbreviations, numbers) from
    a *normalised and lowercased* candidate quote.

    Anchors are the "sticky" tokens that LLMs rarely rewrite, making them
    ideal for constraining the fuzzy-match search region.
    """
    anchors: list[str] = []

    # 1. Gene-like: RPE65, Oct4, Tyrp1
    for m in _ANCHOR_GENE_RE.finditer(normalised_candidate):
        token = m.group().lower()
        if len(token) >= _MIN_ANCHOR_LEN and token not in anchors:
            anchors.append(token)

    # 2. Capitalised abbreviations: iPSC, ZO-1, AMD
    for m in _ANCHOR_CAPITAL_RE.finditer(normalised_candidate):
        token = m.group().lower()
        if len(token) >= _MIN_ANCHOR_LEN and token not in anchors:
            anchors.append(token)

    # 3. Domain special entities
    for ent in _ANCHOR_SPECIAL:
        if ent in normalised_candidate and ent not in anchors:
            anchors.append(ent)

    # 4. Numbers (must be non-trivial: > 1 digit, or has special chars)
    for m in _ANCHOR_NUMBER_RE.finditer(normalised_candidate):
        token = m.group()
        # Skip trivial single-digit numbers (too common)
        if len(token) >= 2 and token.lower() not in anchors:
            anchors.append(token.lower())

    return anchors


def _find_anchor_positions(
    anchors: list[str],
    norm_source_lower: str,
    max_occurrences: int = 200,
) -> list[tuple[int, str]]:
    """Find all occurrences of each anchor in the normalised source.

    Anchors that appear too frequently (> max_occurrences) are discarded
    as non-discriminative noise.
    """
    positions: list[tuple[int, str]] = []

    for anchor in anchors:
        count = 0
        pos = 0
        while True:
            idx = norm_source_lower.find(anchor, pos)
            if idx == -1:
                break
            positions.append((idx, anchor))
            count += 1
            pos = idx + len(anchor)
            if count >= max_occurrences:
                break
        # If anchor is too frequent, remove all its occurrences (not just extras)
        if count >= max_occurrences:
            positions = [(p, a) for p, a in positions if a != anchor]

    return positions


def _best_anchor_regions(
    anchor_positions: list[tuple[int, str]],
    source_len: int,
    candidate_len: int,
) -> list[tuple[int, int]]:
    """Find contiguous region(s) that contain the most *unique* anchors
    in the tightest span.

    Uses two-pointer sliding window over sorted positions (by anchor type):
    finds the minimal window that contains at least one occurrence of each
    unique anchor.  Falls back to density-based clustering when no single
    window covers all anchors.

    Returns up to 5 candidate regions, sorted by anchor density.
    """
    if len(anchor_positions) < 2:
        return []

    # Group positions by anchor name
    from collections import defaultdict
    by_anchor: dict[str, list[int]] = defaultdict(list)
    for pos, name in anchor_positions:
        by_anchor[name].append(pos)

    unique_anchors = list(by_anchor.keys())
    if len(unique_anchors) < 2:
        return []

    # Strategy A: Minimal window containing all unique anchors
    # Flatten: (position, anchor_name) sorted by position
    all_hits = sorted(anchor_positions, key=lambda x: x[0])

    # Sliding window to find the tightest span with all unique anchors present
    anchor_count: dict[str, int] = defaultdict(int)
    left = 0
    best_span = (0, source_len)
    covered = 0

    for right in range(len(all_hits)):
        r_name = all_hits[right][1]
        if anchor_count[r_name] == 0:
            covered += 1
        anchor_count[r_name] += 1

        while covered == len(unique_anchors) and left <= right:
            span_start = all_hits[left][0]
            span_end = all_hits[right][0]
            if (span_end - span_start) < (best_span[1] - best_span[0]):
                best_span = (span_start, span_end)

            l_name = all_hits[left][1]
            anchor_count[l_name] -= 1
            if anchor_count[l_name] == 0:
                covered -= 1
            left += 1

    # Expand the best span to ~2000 chars (or candidate_len * 3)
    margin = max(candidate_len * 3, 2000) // 2
    if best_span[0] < source_len:  # valid span found
        region_start = max(0, best_span[0] - margin)
        region_end = min(source_len, best_span[1] + margin)
        return [(region_start, region_end)]

    # Strategy B: Fallback — density-based (pick positions with most neighbors)
    positions = sorted(set(p for p, _ in anchor_positions))
    window_size = max(candidate_len * 3, 2000)

    # Score each position by how many anchor hits are within window_size
    scored: list[tuple[int, int]] = []
    for pos in positions:
        count = sum(1 for p, _ in anchor_positions
                    if abs(p - pos) <= window_size // 2)
        scored.append((count, pos))

    scored.sort(reverse=True)
    top_positions = [p for _, p in scored[:3]]

    regions: list[tuple[int, int]] = []
    for pos in top_positions:
        r_start = max(0, pos - window_size // 2)
        r_end = min(source_len, pos + window_size // 2)
        # Merge with existing
        merged = False
        for i, (rs, re) in enumerate(regions):
            if r_start < re and r_end > rs:
                regions[i] = (min(rs, r_start), max(re, r_end))
                merged = True
                break
        if not merged:
            regions.append((r_start, r_end))

    return regions[:5]


def _try_anchored_match(
    ns_lower: str,
    nc_lower: str,
    get_src_span,
    source_text: str,
    page_map: Optional[PageMap],
    fuzzy_threshold: float,
) -> Optional[LocateResult]:
    """Try hard-anchor matching: extract anchors → generate candidate regions
    → fuzzy-match within each → return best result above threshold.

    When character-based fuzzy is close but below threshold (0.60–0.85),
    supplements with token-overlap check as a second opinion.  Returns
    None when no region yields a convincing match.
    """
    # 1. Extract anchors
    anchors = _extract_anchors(nc_lower)
    if len(anchors) < 2:
        return None

    # 2. Find anchor positions
    anchor_positions = _find_anchor_positions(anchors, ns_lower)
    if len(anchor_positions) < 2:
        return None

    # 3. Generate candidate regions
    regions = _best_anchor_regions(
        anchor_positions, len(ns_lower), len(nc_lower),
    )
    if not regions:
        return None

    # 4. Try fuzzy matching in each region, keep best character-based score
    best_chr: tuple[int, int, float] | None = None
    for region in regions:
        best = _fuzzy_match_in_region(ns_lower, nc_lower, region, 0.0)
        if best is not None and (
            best_chr is None or best[2] > best_chr[2]
        ):
            best_chr = best

    if best_chr is None:
        return None

    chr_score = best_chr[2]
    norm_start, norm_end = best_chr[0], best_chr[1]

    # 5. If character-based score is in the "grey zone" [0.60, threshold),
    #    verify with token overlap — paraphrased sentences may have low
    #    character similarity but high token overlap.
    if chr_score < fuzzy_threshold:
        if chr_score < 0.60:
            return None  # Too weak even for supplementary check

        # Compute token overlap against the full region (not just window)
        # because PDF noise can split the matched sentence across positions.
        # Use the region that produced the best character score.
        best_region = regions[0]  # regions[0] is the minimal-window region
        region_text = ns_lower[best_region[0]:best_region[1]]

        token_score = _token_overlap_score(nc_lower, region_text)
        if token_score < 0.65:
            return None  # Not enough token overlap — truly not a match

        # Tokens confirm the match exists in this region: accept with
        # composite score (average of character + token, capped at 0.94)
        composite = min((chr_score + token_score) / 2, 0.94)
        if composite < fuzzy_threshold:
            return None
        chr_score = composite

    norm_start, norm_end = _expand_to_sentence(ns_lower, norm_start, norm_end)
    src_start, src_end = get_src_span(norm_start, norm_end)
    return LocateResult(
        status="located",
        verbatim_quote=source_text[src_start:src_end],
        page=_get_page(src_start, page_map),
        char_span=(src_start, src_end),
        score=chr_score,
    )


# Stop words for token overlap filtering (common function words are uninformative)
_TOKEN_STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "of", "to", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "under", "and", "but",
    "or", "not", "no", "if", "then", "than", "that", "this", "these",
    "those", "it", "its", "we", "they", "their", "our", "also", "both",
    "such", "only", "more", "most", "each", "all", "some", "any", "very",
    "just", "about", "other", "which", "who", "whom", "been", "being",
    "found", "show", "shown", "suggest", "suggests", "indicates", "including",
}


def _token_overlap_score(candidate: str, region: str) -> float:
    """Compute what fraction of candidate's meaningful tokens appear in region.

    Strips function words and measures substantive content overlap.
    Returns 0.0–1.0.
    """
    cand_tokens = {
        t for t in candidate.split()
        if t not in _TOKEN_STOP_WORDS and len(t) > 1
    }
    region_tokens = set(region.split())

    if not cand_tokens:
        return 0.0

    overlap = cand_tokens & region_tokens
    return len(overlap) / len(cand_tokens)


def _fuzzy_match_in_region(
    norm_source: str,
    norm_candidate: str,
    region: tuple[int, int],
    min_score: float,
) -> tuple[int, int, float] | None:
    """Run sliding-window fuzzy matching *only* within the given region.

    Same algorithm as _fuzzy_locate but constrained to region boundaries.
    """
    c_len = len(norm_candidate)
    region_start, region_end = region
    search_space = norm_source[region_start:region_end]
    s_len = len(search_space)
    if c_len == 0 or s_len == 0 or c_len > s_len * 2:
        return None

    window_sizes: list[int] = []
    for ratio in (0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5):
        w = int(c_len * ratio)
        if 5 <= w <= s_len and w not in window_sizes:
            window_sizes.append(w)
    if not window_sizes:
        window_sizes = [c_len]

    step = max(1, c_len // 10)
    best_start, best_end, best_score = 0, 0, 0.0

    for start in range(0, s_len, step):
        for w in window_sizes:
            end = start + w
            if end > s_len:
                continue
            window = search_space[start:end]
            score = _fuzz.ratio(norm_candidate, window) / 100.0
            if score > best_score:
                best_score = score
                best_start = start
                best_end = end

    if best_score >= min_score:
        # Map back to global coordinates
        return (region_start + best_start, region_start + best_end, best_score)
    return None


def locate_quote_anchored(
    candidate_quote: str,
    source_text: str,
    page_map: Optional[PageMap] = None,
    fuzzy_threshold: float = 0.85,
) -> LocateResult:
    """Locate a quote using hard-anchor guidance.

    Same API as `locate_quote`, but constrains fuzzy matching to the
    region where key domain entities cluster.  Falls back to global
    fuzzy matching when anchors are insufficient or ambiguous.

    Use this directly when you want explicit anchored-only behaviour;
    otherwise `locate_quote` auto-routes internally.
    """
    # ── guards ──
    if not candidate_quote.strip() or not source_text.strip():
        return LocateResult(status="not_found")

    # ── Step 1: normalise both sides ──
    norm_source, get_src_span = _build_normalised(source_text)
    norm_candidate = _normalise(candidate_quote)

    ns_lower = norm_source.lower()
    nc_lower = norm_candidate.lower()

    if not nc_lower or not ns_lower:
        return LocateResult(status="not_found")

    # ── Step 2: exact substring (fast path, unchanged) ──
    exact_idx = ns_lower.find(nc_lower)
    if exact_idx != -1:
        norm_end = exact_idx + len(nc_lower)
        src_start, src_end = get_src_span(exact_idx, norm_end)
        return LocateResult(
            status="located",
            verbatim_quote=source_text[src_start:src_end],
            page=_get_page(src_start, page_map),
            char_span=(src_start, src_end),
            score=1.0,
        )

    if not HAS_RAPIDFUZZ:
        return LocateResult(status="not_found")

    # ── Step 3a: try multiple anchor-guided regions ──
    anchored_result = _try_anchored_match(
        ns_lower, nc_lower, get_src_span, source_text, page_map, fuzzy_threshold,
    )
    if anchored_result is not None:
        return anchored_result

    # ── Step 3b: fallback — global fuzzy matching ──
    best = _fuzzy_locate(ns_lower, nc_lower, min_score=0.0)
    if best is None or best[2] < fuzzy_threshold:
        return LocateResult(
            status="not_found",
            score=best[2] if best else 0.0,
        )

    norm_start, norm_end, score = best
    norm_start, norm_end = _expand_to_sentence(ns_lower, norm_start, norm_end)
    src_start, src_end = get_src_span(norm_start, norm_end)
    return LocateResult(
        status="located",
        verbatim_quote=source_text[src_start:src_end],
        page=_get_page(src_start, page_map),
        char_span=(src_start, src_end),
        score=score,
    )
