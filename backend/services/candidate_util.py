"""Shared helpers for discover candidates (limitation clusters + contradictions)."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]+", flags=re.UNICODE)
_ARTICLES = ("the ", "a ", "an ")


def one_liner(text: str | None, max_len: int = 80) -> str:
    """Collapse whitespace/newlines into a single-line title, truncated."""
    line = _WS_RE.sub(" ", (text or "").strip())
    if not line:
        return ""
    if len(line) <= max_len:
        return line
    ellipsis = "..."
    keep = max(1, max_len - len(ellipsis))
    return line[:keep].rstrip() + ellipsis


def has_quote_evidence(quote: str | None, page: int | None) -> bool:
    """Primary evidence requires a non-empty quote and a real page number."""
    return bool((quote or "").strip()) and int(page or 0) > 0


def normalize_subject(subject: str | None) -> str:
    """Light subject normalization for alignment (not embeddings / NLI)."""
    text = (subject or "").strip().lower()
    if not text:
        return ""
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    for article in _ARTICLES:
        if text.startswith(article):
            text = text[len(article):].strip()
            break
    return text


def evidence_paper_ids(evidence: list[dict]) -> set[str]:
    return {str(ev.get("paper_id") or "") for ev in evidence if ev.get("paper_id")}


def candidate_fingerprint(candidate_type: str, claim_ids: Iterable[str]) -> str:
    """Stable identity for a candidate across discover/clustering re-runs.

    Same project-level type + claim set → same fingerprint, independent of
    run_id / group_label wording. Used to mark previously_rejected groups
    without mutating existing Signals (ADR-7).
    """
    ids = ",".join(sorted({str(cid).strip() for cid in claim_ids if cid}))
    payload = f"{(candidate_type or '').strip()}|{ids}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "one_liner",
    "has_quote_evidence",
    "normalize_subject",
    "evidence_paper_ids",
    "candidate_fingerprint",
]
