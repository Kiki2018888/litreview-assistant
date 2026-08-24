"""S2: accept/reject → durable project-scoped Signals (ADR-7).

Covers:
  - Accept stamps project_id / type / statement / evidence snapshot
  - Reject records rejection (no accepted signal, no signal_claims)
  - Persistence across a new-session (restart) simulation
  - Cross-project 404
  - Re-discover does not clobber accepted Signals
  - Previously rejected candidates are re-emitted with previously_rejected=True
  - Weak candidates require accept_weak=true (else 400)
"""
from __future__ import annotations

import hashlib
import uuid
from unittest.mock import AsyncMock, patch

from backend.models.tables import (
    CandidateGroup,
    CandidateGroupClaim,
    CandidateType,
    Claim,
    Paper,
    Project,
    Signal,
    SignalClaim,
    SignalStatus,
)
from backend.services.candidate_util import candidate_fingerprint
from backend.services import db as db_mod

ADJ = "/api/v1/adjudication"
PROJECTS = "/api/v1/projects"


def _uuid() -> str:
    return str(uuid.uuid4())


def _make_project(db, name: str) -> Project:
    project = Project(id=_uuid(), name=name, description=None, paper_count=0, is_default=False)
    db.add(project)
    db.flush()
    return project


def _make_paper(db, project_id: str, title: str) -> Paper:
    paper = Paper(
        id=_uuid(),
        file_path=f"/fake/papers/{uuid.uuid4()}.pdf",
        file_size=1024,
        page_count=3,
        title=title,
        status="completed",
        project_id=project_id,
        is_scanned=False,
    )
    db.add(paper)
    db.flush()
    return paper


def _make_claim(
    db,
    paper_id: str,
    quote: str,
    *,
    is_limitation: bool = True,
    topic: str = "other",
    subject: str = "RPE cells",
    claim_form: str = "state",
    direction: str | None = None,
    quote_page: int = 1,
) -> Claim:
    quote_hash = hashlib.sha256(f"{quote}-{uuid.uuid4()}".encode("utf-8")).hexdigest()
    claim = Claim(
        id=_uuid(),
        paper_id=paper_id,
        claim_form=claim_form,
        topic=topic,
        subject=subject,
        direction=direction,
        stat_support=False,
        is_limitation=is_limitation,
        quote=quote[:300],
        quote_hash=quote_hash,
        quote_page=quote_page,
        extraction_source="model",
    )
    db.add(claim)
    db.flush()
    return claim


def _make_group(
    db,
    project_id: str,
    claims: list[Claim],
    label: str,
    *,
    candidate_type: str = CandidateType.LIMITATION_CLUSTER.value,
    is_weak: bool = False,
    paper_count: int | None = None,
) -> CandidateGroup:
    papers = {c.paper_id for c in claims}
    cg = CandidateGroup(
        id=_uuid(),
        project_id=project_id,
        run_id=_uuid(),
        candidate_type=candidate_type,
        group_label=label,
        statement=label,
        topic="other",
        grouping_method="topic only",
        grouping_basis="test",
        cross_paper=len(papers) > 1,
        claim_count=len(claims),
        paper_count=paper_count if paper_count is not None else len(papers),
        is_weak=is_weak,
        fingerprint=candidate_fingerprint(candidate_type, [c.id for c in claims]),
        previously_rejected=False,
    )
    db.add(cg)
    db.flush()
    for i, claim in enumerate(claims):
        db.add(CandidateGroupClaim(
            candidate_group_id=cg.id,
            claim_id=claim.id,
            claim_order=i,
        ))
    db.flush()
    return cg


def _empty_cluster(project_id: str) -> dict:
    return {
        "project_id": project_id,
        "total_claims": 0,
        "total_candidate_groups": 0,
        "model_used": "mock-model",
        "wall_time_seconds": 0.0,
        "groups": [],
    }


def _reload_signal(signal_id: str) -> dict | None:
    """New session read — simulates process restart against the same DB."""
    db = db_mod.SessionLocal()
    try:
        sig = db.get(Signal, signal_id)
        if sig is None:
            return None
        return {
            "id": sig.id,
            "project_id": sig.project_id,
            "status": sig.status,
            "signal_name": sig.signal_name,
            "candidate_type": sig.candidate_type,
            "statement": sig.statement,
            "human_rationale": sig.human_rationale,
            "claim_count": sig.claim_count,
            "evidence_snapshot": list(sig.evidence_snapshot or []),
            "fingerprint": sig.fingerprint,
        }
    finally:
        db.close()


class TestFingerprint:
    def test_order_independent(self):
        a = candidate_fingerprint("contradiction", ["b", "a"])
        b = candidate_fingerprint("contradiction", ["a", "b"])
        assert a == b
        assert a != candidate_fingerprint("limitation_cluster", ["a", "b"])


class TestAcceptRejectPersistence:
    def test_accept_stamps_type_statement_and_evidence(self, client, db_session):
        project = _make_project(db_session, "Accept Stamp")
        p1 = _make_paper(db_session, project.id, "Paper 1")
        p2 = _make_paper(db_session, project.id, "Paper 2")
        c1 = _make_claim(db_session, p1.id, "Small sample size is a limitation.", quote_page=3)
        c2 = _make_claim(db_session, p2.id, "Cohort was underpowered.", quote_page=7)
        group = _make_group(
            db_session, project.id, [c1, c2],
            "underpowered cohorts after transplant",
            is_weak=False,
        )
        db_session.commit()

        resp = client.post(
            f"{ADJ}/signals",
            params={"project_id": project.id},
            json={
                "action": "accept",
                "candidate_group_id": group.id,
                "signal_name": "Underpowered cohorts",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["project_id"] == project.id
        assert body["status"] == "accepted"
        assert body["candidate_type"] == "limitation_cluster"
        assert body["type"] == "limitation_cluster"
        assert body["statement"] == "underpowered cohorts after transplant"
        assert body["claim_count"] == 2

        db_session.expire_all()
        stored = _reload_signal(body["id"])
        assert stored is not None
        assert stored["status"] == SignalStatus.ACCEPTED.value
        assert stored["project_id"] == project.id
        assert stored["candidate_type"] == "limitation_cluster"
        assert stored["statement"] == "underpowered cohorts after transplant"
        snapshot = stored["evidence_snapshot"]
        assert len(snapshot) == 2
        quotes = {(ev["quote"], ev["page"]) for ev in snapshot}
        assert ("Small sample size is a limitation.", 3) in quotes
        assert ("Cohort was underpowered.", 7) in quotes

        detail = client.get(
            f"{ADJ}/signals/{body['id']}",
            params={"project_id": project.id},
        )
        assert detail.status_code == 200
        evidence = detail.json()["evidence"]
        assert len(evidence) == 2
        for ev in evidence:
            assert ev["quote"].strip()
            assert ev["page"] > 0

    def test_reject_does_not_create_accepted_signal(self, client, db_session):
        project = _make_project(db_session, "Reject Only")
        paper = _make_paper(db_session, project.id, "Paper R")
        claim = _make_claim(db_session, paper.id, "Not a real cluster.")
        group = _make_group(
            db_session, project.id, [claim], "noise pile",
            is_weak=True,
        )
        db_session.commit()

        resp = client.post(
            f"{ADJ}/signals",
            params={"project_id": project.id},
            json={"action": "reject", "candidate_group_id": group.id},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "rejected"
        assert body["signal_name"] is None
        assert body["claim_count"] == 0
        assert body["candidate_type"] == "limitation_cluster"

        db_session.expire_all()
        stored = _reload_signal(body["id"])
        assert stored is not None
        assert stored["status"] == SignalStatus.REJECTED.value
        assert stored["status"] != SignalStatus.ACCEPTED.value
        db2 = db_mod.SessionLocal()
        try:
            claims = (
                db2.query(SignalClaim)
                .filter(SignalClaim.signal_id == stored["id"])
                .all()
            )
            assert claims == []
        finally:
            db2.close()

        listed_accepted = client.get(
            f"{ADJ}/signals",
            params={"project_id": project.id, "status": "accepted"},
        )
        assert listed_accepted.json() == []

    def test_reject_rationale_optional_and_persists(self, client, db_session):
        project = _make_project(db_session, "Reject Rationale")
        paper = _make_paper(db_session, project.id, "Paper")
        claim = _make_claim(db_session, paper.id, "Maybe a limitation.")
        g1 = _make_group(db_session, project.id, [claim], "with reason", is_weak=True)
        claim2 = _make_claim(db_session, paper.id, "Another maybe.")
        g2 = _make_group(db_session, project.id, [claim2], "no reason", is_weak=True)
        db_session.commit()

        with_reason = client.post(
            f"{ADJ}/signals",
            params={"project_id": project.id},
            json={
                "action": "reject",
                "candidate_group_id": g1.id,
                "human_rationale": "single-paper noise",
            },
        )
        without = client.post(
            f"{ADJ}/signals",
            params={"project_id": project.id},
            json={"action": "reject", "candidate_group_id": g2.id},
        )
        assert with_reason.status_code == 201
        assert without.status_code == 201
        assert with_reason.json()["human_rationale"] == "single-paper noise"
        assert without.json()["human_rationale"] is None

        db_session.expire_all()
        assert _reload_signal(with_reason.json()["id"])["human_rationale"] == "single-paper noise"
        assert _reload_signal(without.json()["id"])["human_rationale"] is None


class TestCrossProject404:
    def test_accept_and_signal_detail_404(self, client, db_session):
        p1 = _make_project(db_session, "S2 P1")
        p2 = _make_project(db_session, "S2 P2")
        paper = _make_paper(db_session, p2.id, "P2 paper")
        claim = _make_claim(db_session, paper.id, "P2 limitation")
        group = _make_group(db_session, p2.id, [claim], "p2 group", is_weak=False)
        db_session.commit()

        leaked_accept = client.post(
            f"{ADJ}/signals",
            params={"project_id": p1.id},
            json={
                "action": "accept",
                "candidate_group_id": group.id,
                "signal_name": "should-not-exist",
            },
        )
        assert leaked_accept.status_code == 404
        db_session.expire_all()
        assert (
            db_session.query(Signal).filter(Signal.candidate_group_id == group.id).first()
            is None
        )

        created = client.post(
            f"{ADJ}/signals",
            params={"project_id": p2.id},
            json={"action": "accept", "candidate_group_id": group.id, "signal_name": "ok"},
        )
        assert created.status_code == 201, created.text
        sig_id = created.json()["id"]

        leaked_detail = client.get(
            f"{ADJ}/signals/{sig_id}",
            params={"project_id": p1.id},
        )
        assert leaked_detail.status_code == 404
        leaked_list = client.get(f"{ADJ}/signals", params={"project_id": p1.id})
        assert leaked_list.json() == []


class TestWeakAcceptGate:
    def test_weak_accept_requires_explicit_flag(self, client, db_session):
        project = _make_project(db_session, "Weak Gate")
        paper = _make_paper(db_session, project.id, "Solo")
        claim = _make_claim(db_session, paper.id, "Single-paper limitation.")
        group = _make_group(
            db_session, project.id, [claim], "solo limitation",
            is_weak=True, paper_count=1,
        )
        db_session.commit()

        denied = client.post(
            f"{ADJ}/signals",
            params={"project_id": project.id},
            json={
                "action": "accept",
                "candidate_group_id": group.id,
                "signal_name": "should-400",
            },
        )
        assert denied.status_code == 400
        assert "弱候选" in denied.json()["detail"]
        db_session.expire_all()
        assert (
            db_session.query(Signal).filter(Signal.candidate_group_id == group.id).first()
            is None
        )

        allowed = client.post(
            f"{ADJ}/signals",
            params={"project_id": project.id},
            json={
                "action": "accept",
                "candidate_group_id": group.id,
                "signal_name": "explicit weak",
                "accept_weak": True,
            },
        )
        assert allowed.status_code == 201, allowed.text
        assert allowed.json()["status"] == "accepted"

    def test_primary_accept_does_not_need_flag(self, client, db_session):
        project = _make_project(db_session, "Primary Gate")
        p1 = _make_paper(db_session, project.id, "A")
        p2 = _make_paper(db_session, project.id, "B")
        c1 = _make_claim(db_session, p1.id, "Limitation in A.")
        c2 = _make_claim(db_session, p2.id, "Limitation in B.")
        group = _make_group(
            db_session, project.id, [c1, c2], "shared limitation",
            is_weak=False,
        )
        db_session.commit()

        resp = client.post(
            f"{ADJ}/signals",
            params={"project_id": project.id},
            json={"action": "accept", "candidate_group_id": group.id},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["statement"] == "shared limitation"


class TestListDetailFilters:
    def test_list_by_type_and_status_detail_evidence(self, client, db_session):
        project = _make_project(db_session, "List Filter")
        p1 = _make_paper(db_session, project.id, "Up")
        p2 = _make_paper(db_session, project.id, "Down")
        lim_p = _make_paper(db_session, project.id, "Lim1")
        lim_p2 = _make_paper(db_session, project.id, "Lim2")
        up = _make_claim(
            db_session, p1.id, "Efficacy increased.",
            is_limitation=False, claim_form="effect", direction="up",
            topic="efficacy", quote_page=4,
        )
        down = _make_claim(
            db_session, p2.id, "Efficacy decreased.",
            is_limitation=False, claim_form="effect", direction="down",
            topic="efficacy", quote_page=9,
        )
        l1 = _make_claim(db_session, lim_p.id, "Immune rejection remains.")
        l2 = _make_claim(db_session, lim_p2.id, "Immune rejection also seen.")
        contra = _make_group(
            db_session, project.id, [up, down], "efficacy direction conflict",
            candidate_type=CandidateType.CONTRADICTION.value,
            is_weak=False,
        )
        lim = _make_group(
            db_session, project.id, [l1, l2], "immune rejection",
            candidate_type=CandidateType.LIMITATION_CLUSTER.value,
            is_weak=False,
        )
        db_session.commit()

        acc = client.post(
            f"{ADJ}/signals",
            params={"project_id": project.id},
            json={"action": "accept", "candidate_group_id": contra.id, "signal_name": "conflict"},
        )
        rej = client.post(
            f"{ADJ}/signals",
            params={"project_id": project.id},
            json={"action": "reject", "candidate_group_id": lim.id, "human_rationale": "dup"},
        )
        assert acc.status_code == 201, acc.text
        assert rej.status_code == 201, rej.text

        by_type = client.get(
            f"{ADJ}/signals",
            params={"project_id": project.id, "type": "contradiction"},
        )
        assert {s["id"] for s in by_type.json()} == {acc.json()["id"]}
        assert by_type.json()[0]["candidate_type"] == "contradiction"

        by_status = client.get(
            f"{ADJ}/signals",
            params={"project_id": project.id, "status": "rejected"},
        )
        assert {s["id"] for s in by_status.json()} == {rej.json()["id"]}

        detail = client.get(
            f"{ADJ}/signals/{acc.json()['id']}",
            params={"project_id": project.id},
        )
        assert detail.status_code == 200
        body = detail.json()
        assert body["type"] == "contradiction"
        quotes = {(ev["quote"], ev["page"]) for ev in body["evidence"]}
        assert ("Efficacy increased.", 4) in quotes
        assert ("Efficacy decreased.", 9) in quotes


class TestRediscoverAdr7:
    def test_rediscover_does_not_clobber_accepted_signal(self, client, db_session):
        project = _make_project(db_session, "No Clobber")
        p1 = _make_paper(db_session, project.id, "Paper Up")
        p2 = _make_paper(db_session, project.id, "Paper Down")
        _make_claim(
            db_session, p1.id, "Vision improved at month 12.",
            is_limitation=False, claim_form="effect", direction="up",
            topic="efficacy", quote_page=5,
        )
        _make_claim(
            db_session, p2.id, "Vision declined at month 12.",
            is_limitation=False, claim_form="effect", direction="down",
            topic="efficacy", quote_page=9,
        )
        db_session.commit()

        with patch(
            "backend.services.discover_service.run_clustering",
            new=AsyncMock(return_value=_empty_cluster(project.id)),
        ):
            first = client.post(f"{PROJECTS}/{project.id}/discover", json={})
        assert first.status_code == 200, first.text

        groups = client.get(
            f"{ADJ}/candidate-groups",
            params={"project_id": project.id, "type": "contradiction"},
        ).json()
        assert len(groups) == 1
        gid = groups[0]["id"]

        accepted = client.post(
            f"{ADJ}/signals",
            params={"project_id": project.id},
            json={"action": "accept", "candidate_group_id": gid, "signal_name": "vision conflict"},
        )
        assert accepted.status_code == 201, accepted.text
        sig_id = accepted.json()["id"]
        original_snapshot = _reload_signal(sig_id)["evidence_snapshot"]

        with patch(
            "backend.services.discover_service.run_clustering",
            new=AsyncMock(return_value=_empty_cluster(project.id)),
        ):
            second = client.post(f"{PROJECTS}/{project.id}/discover", json={})
        assert second.status_code == 200, second.text
        assert second.json()["run_id"] != first.json()["run_id"]

        db_session.expire_all()
        stored = _reload_signal(sig_id)
        assert stored is not None
        assert stored["id"] == sig_id
        assert stored["status"] == SignalStatus.ACCEPTED.value
        assert stored["signal_name"] == "vision conflict"
        assert stored["evidence_snapshot"] == original_snapshot
        assert stored["candidate_type"] == "contradiction"

        accepted_rows = (
            db_session.query(Signal)
            .filter(
                Signal.project_id == project.id,
                Signal.status == SignalStatus.ACCEPTED.value,
            )
            .all()
        )
        assert any(s.id == sig_id for s in accepted_rows)

        detail = client.get(
            f"{ADJ}/signals/{sig_id}",
            params={"project_id": project.id},
        )
        assert detail.status_code == 200
        assert detail.json()["status"] == "accepted"
        assert detail.json()["id"] == sig_id

    def test_rejected_candidates_marked_previously_rejected(self, client, db_session):
        project = _make_project(db_session, "Prev Rejected")
        p1 = _make_paper(db_session, project.id, "Paper Up")
        p2 = _make_paper(db_session, project.id, "Paper Down")
        _make_claim(
            db_session, p1.id, "Safety improved.",
            is_limitation=False, claim_form="effect", direction="up",
            topic="safety", quote_page=2,
        )
        _make_claim(
            db_session, p2.id, "Safety worsened.",
            is_limitation=False, claim_form="effect", direction="down",
            topic="safety", quote_page=6,
        )
        db_session.commit()

        with patch(
            "backend.services.discover_service.run_clustering",
            new=AsyncMock(return_value=_empty_cluster(project.id)),
        ):
            first = client.post(f"{PROJECTS}/{project.id}/discover", json={})
        assert first.status_code == 200, first.text

        groups = client.get(
            f"{ADJ}/candidate-groups",
            params={"project_id": project.id, "type": "contradiction"},
        ).json()
        assert len(groups) == 1
        first_id = groups[0]["id"]
        assert groups[0]["previously_rejected"] is False

        rejected = client.post(
            f"{ADJ}/signals",
            params={"project_id": project.id},
            json={"action": "reject", "candidate_group_id": first_id, "human_rationale": "not real"},
        )
        assert rejected.status_code == 201, rejected.text
        rej_id = rejected.json()["id"]

        with patch(
            "backend.services.discover_service.run_clustering",
            new=AsyncMock(return_value=_empty_cluster(project.id)),
        ):
            second = client.post(f"{PROJECTS}/{project.id}/discover", json={})
        assert second.status_code == 200, second.text

        db_session.expire_all()
        still_rejected = _reload_signal(rej_id)
        assert still_rejected is not None
        assert still_rejected["status"] == SignalStatus.REJECTED.value
        assert still_rejected["status"] != SignalStatus.ACCEPTED.value

        listed = client.get(
            f"{ADJ}/candidate-groups",
            params={"project_id": project.id, "type": "contradiction"},
        ).json()
        new_groups = [g for g in listed if g["id"] != first_id]
        assert new_groups
        assert all(g["previously_rejected"] is True for g in new_groups)

        marked = client.get(
            f"{ADJ}/candidate-groups",
            params={
                "project_id": project.id,
                "type": "contradiction",
                "previously_rejected": True,
            },
        ).json()
        assert marked
        assert all(g["previously_rejected"] is True for g in marked)
        assert all(g["id"] != first_id for g in marked)
