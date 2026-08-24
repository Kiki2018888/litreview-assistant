"""S1 discover: failure visibility, contradiction evidence, weak-candidate filtering."""
from __future__ import annotations

import hashlib
import uuid
from unittest.mock import AsyncMock, patch

from backend.models.tables import (
    CandidateGroup,
    CandidateType,
    Claim,
    ExtractJob,
    JobStatus,
    JobType,
    Paper,
    Project,
)
from backend.services.candidate_util import has_quote_evidence, normalize_subject, one_liner
from backend.services.contradiction_detector import _opposes, detect_contradictions
from backend.services import db as db_mod

ADJ = "/api/v1/adjudication"
PROJECTS = "/api/v1/projects"
JOBS = "/api/v1/jobs"


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
    is_limitation: bool = False,
    topic: str = "efficacy",
    subject: str = "RPE cells",
    claim_form: str = "effect",
    direction: str | None = None,
    comparison_result: str | None = None,
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
        comparison_result=comparison_result,
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


def _empty_cluster(project_id: str) -> dict:
    return {
        "project_id": project_id,
        "total_claims": 0,
        "total_candidate_groups": 0,
        "model_used": "mock-model",
        "wall_time_seconds": 0.0,
        "groups": [],
    }


def _limitation_group(project_id: str, claims: list[Claim], papers: list[Paper], *, weak: bool) -> dict:
    evidence = []
    paper_ids = set()
    for claim, paper in zip(claims, papers):
        paper_ids.add(paper.id)
        evidence.append({
            "claim_id": claim.id,
            "paper_id": paper.id,
            "paper_title": paper.title,
            "subject": claim.subject or "",
            "topic": claim.topic or "other",
            "quote": claim.quote,
            "page": claim.quote_page,
            "context": "",
        })
    paper_count = len(paper_ids)
    statement = one_liner("immune rejection after transplant")
    return {
        "candidate_group_id": 1,
        "candidate_type": CandidateType.LIMITATION_CLUSTER.value,
        "topic": "other",
        "group_label": statement,
        "statement": statement,
        "grouping_method": "topic + LLM",
        "grouping_basis": "test",
        "cross_paper": paper_count > 1,
        "paper_count": paper_count,
        "claim_count": len(claims),
        "is_weak": weak or paper_count < 2,
        "adjudication": {
            "status": "pending",
            "signal_name": None,
            "human_rationale": None,
            "reviewed_at": None,
        },
        "evidence": evidence,
    }


class TestCandidateUtil:
    def test_normalize_subject_strips_articles_and_punct(self):
        assert normalize_subject("The RPE-cells!") == "rpe cells"
        assert normalize_subject("  An hiPSC-derived RPE  ") == "hipsc derived rpe"

    def test_one_liner_collapses_newlines(self):
        assert "\n" not in one_liner("line one\nline two")
        assert len(one_liner("x" * 200)) <= 80

    def test_quote_evidence_requires_quote_and_page(self):
        assert has_quote_evidence("quoted text", 3) is True
        assert has_quote_evidence("quoted text", 0) is False
        assert has_quote_evidence("  ", 2) is False


class TestContradictionRules:
    def test_direction_up_vs_down_opposes(self):
        assert _opposes(("direction", "up"), ("direction", "down"))
        assert not _opposes(("direction", "up"), ("direction", "up"))

    def test_comparison_mutex(self):
        assert _opposes(("comparison", "superior"), ("comparison", "inferior"))
        assert _opposes(("comparison", "similar"), ("comparison", "superior"))
        assert not _opposes(("comparison", "superior"), ("comparison", "superior"))
        assert not _opposes(("direction", "up"), ("comparison", "inferior"))

    def test_detects_paired_quotes_as_primary(self, db_session):
        project = _make_project(db_session, "Contra Primary")
        p1 = _make_paper(db_session, project.id, "Paper Up")
        p2 = _make_paper(db_session, project.id, "Paper Down")
        _make_claim(
            db_session, p1.id, "Efficacy increased significantly.",
            direction="up", quote_page=4,
        )
        _make_claim(
            db_session, p2.id, "Efficacy decreased after month 6.",
            direction="down", quote_page=12,
        )
        db_session.commit()

        groups = detect_contradictions(project.id)
        assert len(groups) == 1
        g = groups[0]
        assert g["candidate_type"] == "contradiction"
        assert g["is_weak"] is False
        assert g["claim_count"] == 2
        quotes = [(ev["quote"], ev["page"]) for ev in g["evidence"]]
        assert ("Efficacy increased significantly.", 4) in quotes
        assert ("Efficacy decreased after month 6.", 12) in quotes

    def test_missing_quote_is_weak(self, db_session):
        project = _make_project(db_session, "Contra Weak")
        p1 = _make_paper(db_session, project.id, "Paper Q")
        p2 = _make_paper(db_session, project.id, "Paper NoQ")
        _make_claim(db_session, p1.id, "Has a real quote.", direction="up", quote_page=2)
        _make_claim(db_session, p2.id, "   ", direction="down", quote_page=0)
        db_session.commit()

        groups = detect_contradictions(project.id)
        assert len(groups) == 1
        assert groups[0]["is_weak"] is True


class TestDiscoverFailureVisibility:
    def test_persist_failure_is_non_200_and_job_failed(self, client, db_session):
        project = _make_project(db_session, "Discover Fail")
        paper = _make_paper(db_session, project.id, "Paper A")
        claim = _make_claim(
            db_session, paper.id, "Limitation of sample size",
            is_limitation=True, direction="up",
        )
        db_session.commit()

        cluster = {
            "project_id": project.id,
            "total_claims": 1,
            "total_candidate_groups": 1,
            "model_used": "mock-model",
            "wall_time_seconds": 0.01,
            "groups": [_limitation_group(project.id, [claim], [paper], weak=True)],
        }

        with patch(
            "backend.services.discover_service.run_clustering",
            new=AsyncMock(return_value=cluster),
        ), patch(
            "backend.services.discover_service.detect_contradictions",
            return_value=[],
        ), patch(
            "backend.services.discover_service.save_clustering_result",
            side_effect=RuntimeError("db write failed"),
        ):
            resp = client.post(f"{PROJECTS}/{project.id}/discover", json={})

        assert resp.status_code != 200
        assert resp.status_code >= 400
        detail = resp.json().get("detail", "")
        assert "失败" in str(detail)

        db_session.expire_all()
        job = (
            db_session.query(ExtractJob)
            .filter(
                ExtractJob.project_id == project.id,
                ExtractJob.job_type == JobType.DISCOVER.value,
            )
            .one()
        )
        assert job.status == JobStatus.FAILED.value
        assert job.error_summary
        assert job.error_summary.get("phase") == "persist"

        status = client.get(f"{JOBS}/{job.id}/status")
        assert status.status_code == 200
        assert status.json()["status"] == "failed"
        assert status.json()["job_type"] == "discover"

    def test_job_is_running_during_discover(self, client, db_session):
        project = _make_project(db_session, "Discover Running")
        _make_paper(db_session, project.id, "Paper")
        db_session.commit()
        seen = {"running": False}

        async def _cluster(project_id: str):
            db = db_mod.SessionLocal()
            try:
                job = (
                    db.query(ExtractJob)
                    .filter(ExtractJob.project_id == project_id)
                    .one()
                )
                assert job.status == JobStatus.RUNNING.value
                assert job.job_type == JobType.DISCOVER.value
                seen["running"] = True
            finally:
                db.close()
            return _empty_cluster(project_id)

        with patch(
            "backend.services.discover_service.run_clustering",
            new=_cluster,
        ), patch(
            "backend.services.discover_service.detect_contradictions",
            return_value=[],
        ):
            resp = client.post(f"{PROJECTS}/{project.id}/discover", json={})

        assert resp.status_code == 200, resp.text
        assert seen["running"] is True
        assert resp.json()["status"] == "completed"
        job_status = client.get(f"{JOBS}/{resp.json()['job_id']}/status")
        assert job_status.json()["status"] == "completed"

    def test_empty_discover_still_200(self, client, db_session):
        project = _make_project(db_session, "Discover Empty")
        _make_paper(db_session, project.id, "Paper empty")
        db_session.commit()

        with patch(
            "backend.services.discover_service.run_clustering",
            new=AsyncMock(return_value=_empty_cluster(project.id)),
        ), patch(
            "backend.services.discover_service.detect_contradictions",
            return_value=[],
        ):
            resp = client.post(f"{PROJECTS}/{project.id}/discover", json={})

        assert resp.status_code == 200
        body = resp.json()
        assert body["run_id"] == ""
        assert body["total_candidate_groups"] == 0
        assert body["status"] == "completed"


class TestDiscoverCandidates:
    def test_contradiction_paired_evidence_on_detail(self, client, db_session):
        project = _make_project(db_session, "Pair Evidence")
        p1 = _make_paper(db_session, project.id, "Paper Up")
        p2 = _make_paper(db_session, project.id, "Paper Down")
        _make_claim(
            db_session, p1.id, "Vision improved at month 12.",
            direction="up", quote_page=5,
        )
        _make_claim(
            db_session, p2.id, "Vision declined at month 12.",
            direction="down", quote_page=9,
        )
        db_session.commit()

        with patch(
            "backend.services.discover_service.run_clustering",
            new=AsyncMock(return_value=_empty_cluster(project.id)),
        ):
            resp = client.post(f"{PROJECTS}/{project.id}/discover", json={})

        assert resp.status_code == 200, resp.text
        assert resp.json()["contradiction_groups"] == 1
        assert resp.json()["weak_count"] == 0

        listed = client.get(
            f"{ADJ}/candidate-groups",
            params={"project_id": project.id, "type": "contradiction"},
        )
        assert listed.status_code == 200
        items = listed.json()
        assert len(items) == 1
        assert items[0]["type"] == "contradiction"
        assert items[0]["is_weak"] is False
        assert items[0]["statement"]

        detail = client.get(
            f"{ADJ}/candidate-groups/{items[0]['id']}",
            params={"project_id": project.id},
        )
        assert detail.status_code == 200
        body = detail.json()
        assert body["type"] == "contradiction"
        assert body["statement"]
        assert len(body["papers"]) == 2
        evidence = body["evidence"]
        assert len(evidence) == 2
        quotes = {(ev["quote"], ev["page"]) for ev in evidence}
        assert ("Vision improved at month 12.", 5) in quotes
        assert ("Vision declined at month 12.", 9) in quotes
        for ev in evidence:
            assert ev["quote"].strip()
            assert ev["page"] > 0

    def test_weak_candidate_filtering(self, client, db_session):
        project = _make_project(db_session, "Weak Filter")
        p1 = _make_paper(db_session, project.id, "Paper 1")
        p2 = _make_paper(db_session, project.id, "Paper 2")
        # Primary contradiction (quoted both sides)
        _make_claim(db_session, p1.id, "Safety signal up.", direction="up", quote_page=3)
        _make_claim(db_session, p2.id, "Safety signal down.", direction="down", quote_page=8)
        # Weak contradiction (missing page/quote on one side)
        p3 = _make_paper(db_session, project.id, "Paper 3")
        p4 = _make_paper(db_session, project.id, "Paper 4")
        _make_claim(
            db_session, p3.id, "Different subject improved.",
            subject="photoreceptors", direction="up", quote_page=2,
        )
        _make_claim(
            db_session, p4.id, "",
            subject="photoreceptors", direction="down", quote_page=0,
        )
        # Weak limitation cluster: 1 paper
        lim = _make_claim(
            db_session, p1.id, "Small cohort is a limitation.",
            is_limitation=True, subject="cohort size", claim_form="state",
        )
        db_session.commit()

        cluster = {
            "project_id": project.id,
            "total_claims": 1,
            "total_candidate_groups": 1,
            "model_used": "mock-model",
            "wall_time_seconds": 0.01,
            "groups": [_limitation_group(project.id, [lim], [p1], weak=True)],
        }

        with patch(
            "backend.services.discover_service.run_clustering",
            new=AsyncMock(return_value=cluster),
        ):
            resp = client.post(f"{PROJECTS}/{project.id}/discover", json={})

        assert resp.status_code == 200, resp.text
        assert resp.json()["weak_count"] >= 2

        primary = client.get(
            f"{ADJ}/candidate-groups",
            params={"project_id": project.id, "is_weak": False},
        )
        assert primary.status_code == 200
        primary_items = primary.json()
        assert primary_items
        assert all(item["is_weak"] is False for item in primary_items)
        assert all(item["type"] == "contradiction" for item in primary_items)

        weak = client.get(
            f"{ADJ}/candidate-groups",
            params={"project_id": project.id, "is_weak": True},
        )
        weak_items = weak.json()
        assert weak_items
        assert all(item["is_weak"] is True for item in weak_items)
        types = {item["type"] for item in weak_items}
        assert "limitation_cluster" in types
        assert "contradiction" in types

        lim_only = client.get(
            f"{ADJ}/candidate-groups",
            params={
                "project_id": project.id,
                "type": "limitation_cluster",
                "is_weak": False,
            },
        )
        assert lim_only.json() == []

    def test_limitation_cluster_stamps_type_and_weak(self, client, db_session):
        project = _make_project(db_session, "Cluster Type")
        paper = _make_paper(db_session, project.id, "Solo paper")
        claim = _make_claim(
            db_session, paper.id, "Only one paper limitation",
            is_limitation=True, claim_form="state",
        )
        db_session.commit()

        result = {
            "project_id": project.id,
            "total_claims": 1,
            "total_candidate_groups": 1,
            "model_used": "mock-model",
            "wall_time_seconds": 0.01,
            "groups": [_limitation_group(project.id, [claim], [paper], weak=True)],
        }
        with patch(
            "backend.services.limitation_clusterer.run_clustering",
            new=AsyncMock(return_value=result),
        ):
            resp = client.post(f"{PROJECTS}/{project.id}/clustering/limitation", json={})

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["groups"][0]["candidate_type"] == "limitation_cluster"
        assert body["groups"][0]["is_weak"] is True
        assert "\n" not in body["groups"][0]["statement"]

        db_session.expire_all()
        stored = db_session.query(CandidateGroup).filter(
            CandidateGroup.project_id == project.id,
        ).one()
        assert stored.candidate_type == "limitation_cluster"
        assert stored.is_weak is True
        assert stored.paper_count < 2

    def test_contradiction_project_isolation(self, client, db_session):
        p1 = _make_project(db_session, "Iso A")
        p2 = _make_project(db_session, "Iso B")
        a1 = _make_paper(db_session, p1.id, "A1")
        a2 = _make_paper(db_session, p1.id, "A2")
        b1 = _make_paper(db_session, p2.id, "B1")
        b2 = _make_paper(db_session, p2.id, "B2")
        _make_claim(db_session, a1.id, "A up", direction="up", quote_page=1)
        _make_claim(db_session, a2.id, "A down", direction="down", quote_page=2)
        _make_claim(db_session, b1.id, "B up", direction="up", quote_page=1)
        _make_claim(db_session, b2.id, "B down", direction="down", quote_page=2)
        db_session.commit()

        with patch(
            "backend.services.discover_service.run_clustering",
            new=AsyncMock(return_value=_empty_cluster(p1.id)),
        ):
            r1 = client.post(f"{PROJECTS}/{p1.id}/discover", json={})
        with patch(
            "backend.services.discover_service.run_clustering",
            new=AsyncMock(return_value=_empty_cluster(p2.id)),
        ):
            r2 = client.post(f"{PROJECTS}/{p2.id}/discover", json={})
        assert r1.status_code == 200, r1.text
        assert r2.status_code == 200, r2.text

        listed = client.get(
            f"{ADJ}/candidate-groups",
            params={"project_id": p1.id, "type": "contradiction"},
        )
        ids = {g["id"] for g in listed.json()}
        listed_b = client.get(
            f"{ADJ}/candidate-groups",
            params={"project_id": p2.id, "type": "contradiction"},
        )
        ids_b = {g["id"] for g in listed_b.json()}
        assert ids
        assert ids_b
        assert ids.isdisjoint(ids_b)
        assert all(g["project_id"] == p1.id for g in listed.json())
