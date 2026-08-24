"""P0 rule-based contradiction detection (NOT NLI / embeddings).

Align claims in a project on topic + lightly normalized subject.
Emit type=contradiction candidates when direction or comparison_result
are opposing / mutually exclusive.

Primary path requires both sides' quote+page; missing quote → is_weak.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Optional

from backend.models.tables import CandidateType, Claim, Paper
from backend.services.candidate_util import (
    has_quote_evidence,
    normalize_subject,
    one_liner,
)
from backend.services import db as db_mod

logger = logging.getLogger(__name__)

DIRECTION_VALUES = frozenset({"up", "down"})
COMPARISON_VALUES = frozenset({"similar", "superior", "inferior"})

# Mutex pairs on the same axis (order-insensitive via frozenset)
_DIRECTION_MUTEX = frozenset({frozenset({"up", "down"})})
_COMPARISON_MUTEX = frozenset({
    frozenset({"superior", "inferior"}),
    frozenset({"similar", "superior"}),
    frozenset({"similar", "inferior"}),
})


@dataclass
class AlignableClaim:
    id: str
    paper_id: str
    paper_title: str
    subject: str
    topic: str
    claim_form: str
    direction: Optional[str]
    comparison_result: Optional[str]
    quote: str
    quote_page: int
    context_summary: str = ""

    @property
    def polarity(self) -> Optional[tuple[str, str]]:
        """(axis, value) used for mutex checks, or None if not alignable."""
        direction = (self.direction or "").strip().lower()
        comparison = (self.comparison_result or "").strip().lower()
        form = (self.claim_form or "").strip().lower()
        if form == "effect" and direction in DIRECTION_VALUES:
            return ("direction", direction)
        if form == "comparison" and comparison in COMPARISON_VALUES:
            return ("comparison", comparison)
        if direction in DIRECTION_VALUES:
            return ("direction", direction)
        if comparison in COMPARISON_VALUES:
            return ("comparison", comparison)
        return None

    @property
    def has_primary_evidence(self) -> bool:
        return has_quote_evidence(self.quote, self.quote_page)


def _opposes(left: tuple[str, str], right: tuple[str, str]) -> bool:
    if left[0] != right[0] or left[1] == right[1]:
        return False
    pair = frozenset({left[1], right[1]})
    if left[0] == "direction":
        return pair in _DIRECTION_MUTEX
    return pair in _COMPARISON_MUTEX


def fetch_alignable_claims(project_id: str) -> list[AlignableClaim]:
    """Load project claims that can participate in rule-based alignment.

    Prefer claims with quotes by sorting them first; claims without quotes
    still participate and produce weak (non-primary) candidates.
    """
    db = db_mod.SessionLocal()
    try:
        rows = (
            db.query(Claim, Paper.title)
            .join(Paper, Claim.paper_id == Paper.id)
            .filter(Paper.project_id == project_id)
            .order_by(Paper.title, Claim.id)
            .all()
        )
        records: list[AlignableClaim] = []
        for claim, paper_title in rows:
            subject = claim.subject or ""
            if not normalize_subject(subject):
                continue
            rec = AlignableClaim(
                id=claim.id,
                paper_id=claim.paper_id,
                paper_title=paper_title or "Unknown",
                subject=subject,
                topic=(claim.topic or "other"),
                claim_form=claim.claim_form or "",
                direction=claim.direction,
                comparison_result=claim.comparison_result,
                quote=claim.quote or "",
                quote_page=int(claim.quote_page or 0),
            )
            if rec.polarity is None:
                continue
            records.append(rec)
        records.sort(key=lambda c: (not c.has_primary_evidence, c.paper_title, c.id))
        return records
    finally:
        db.close()


def _evidence_item(claim: AlignableClaim) -> dict[str, Any]:
    return {
        "claim_id": claim.id,
        "paper_id": claim.paper_id,
        "paper_title": claim.paper_title,
        "subject": claim.subject,
        "topic": claim.topic,
        "quote": claim.quote,
        "page": claim.quote_page,
        "context": claim.context_summary,
        "direction": claim.direction,
        "comparison_result": claim.comparison_result,
        "claim_form": claim.claim_form,
    }


def _pair_statement(left: AlignableClaim, right: AlignableClaim) -> str:
    pol_l = left.polarity
    pol_r = right.polarity
    axis = pol_l[0] if pol_l else "value"
    val_l = pol_l[1] if pol_l else "?"
    val_r = pol_r[1] if pol_r else "?"
    subject = left.subject or right.subject or "subject"
    return one_liner(f"{subject}: {val_l} vs {val_r} ({axis})")


def detect_contradictions(project_id: str) -> list[dict[str, Any]]:
    """Return candidate-group dicts (same shape as clustering groups)."""
    claims = fetch_alignable_claims(project_id)
    buckets: dict[tuple[str, str], list[AlignableClaim]] = defaultdict(list)
    for claim in claims:
        key = (claim.topic or "other", normalize_subject(claim.subject))
        buckets[key].append(claim)

    groups: list[dict[str, Any]] = []
    for (topic, _subject_key), bucket in sorted(buckets.items()):
        n = len(bucket)
        if n < 2:
            continue
        for i in range(n):
            for j in range(i + 1, n):
                left, right = bucket[i], bucket[j]
                pol_l, pol_r = left.polarity, right.polarity
                if pol_l is None or pol_r is None or not _opposes(pol_l, pol_r):
                    continue
                evidence = [_evidence_item(left), _evidence_item(right)]
                paper_ids = {left.paper_id, right.paper_id}
                both_quoted = left.has_primary_evidence and right.has_primary_evidence
                statement = _pair_statement(left, right)
                groups.append({
                    "candidate_group_id": len(groups) + 1,
                    "candidate_type": CandidateType.CONTRADICTION.value,
                    "topic": topic[:20],
                    "group_label": statement,
                    "statement": statement,
                    "grouping_method": "rule: topic+subject mutex",
                    "grouping_basis": (
                        f"aligned topic={topic}, subject={left.subject!r}; "
                        f"{pol_l[0]} {pol_l[1]} vs {pol_r[1]}"
                    ),
                    "cross_paper": len(paper_ids) > 1,
                    "paper_count": len(paper_ids),
                    "claim_count": 2,
                    "is_weak": not both_quoted,
                    "adjudication": {
                        "status": "pending",
                        "signal_name": None,
                        "human_rationale": None,
                        "reviewed_at": None,
                    },
                    "evidence": evidence,
                })

    logger.info(
        "矛盾检测: project=%s claims=%d pairs=%d (weak=%d)",
        project_id[:12],
        len(claims),
        len(groups),
        sum(1 for g in groups if g.get("is_weak")),
    )
    return groups


__all__ = [
    "AlignableClaim",
    "fetch_alignable_claims",
    "detect_contradictions",
    "_opposes",
]
