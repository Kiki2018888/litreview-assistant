"""局限聚类落库失败可见性 + 裁决 project_id 隔离.

覆盖:
  - 聚类有结果但落库失败 → HTTP 非 200 / 非 success
  - candidate_groups / signals 列表按 project_id 过滤
  - 跨项目查询与变更不泄漏
"""
from __future__ import annotations

import hashlib
import uuid
from unittest.mock import AsyncMock, patch

from backend.models.tables import (
    CandidateGroup,
    CandidateGroupClaim,
    Claim,
    Paper,
    Project,
    Signal,
)

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
        page_count=1,
        title=title,
        status="completed",
        project_id=project_id,
        is_scanned=False,
    )
    db.add(paper)
    db.flush()
    return paper


def _make_claim(db, paper_id: str, quote: str, *, is_limitation: bool = True) -> Claim:
    quote_hash = hashlib.sha256(quote.encode("utf-8")).hexdigest()
    claim = Claim(
        id=_uuid(),
        paper_id=paper_id,
        claim_form="state",
        topic="other",
        subject="test subject",
        stat_support=False,
        is_limitation=is_limitation,
        quote=quote[:300],
        quote_hash=quote_hash,
        quote_page=1,
        extraction_source="model",
    )
    db.add(claim)
    db.flush()
    return claim


def _make_group(db, project_id: str, claim: Claim, label: str) -> CandidateGroup:
    cg = CandidateGroup(
        id=_uuid(),
        project_id=project_id,
        run_id=_uuid(),
        group_label=label,
        topic="other",
        grouping_method="topic only",
        grouping_basis="test",
        cross_paper=False,
        claim_count=1,
    )
    db.add(cg)
    db.flush()
    db.add(CandidateGroupClaim(
        candidate_group_id=cg.id,
        claim_id=claim.id,
        claim_order=0,
    ))
    db.flush()
    return cg


def _clustering_result(project_id: str, claim: Claim, paper: Paper) -> dict:
    return {
        "project_id": project_id,
        "total_claims": 1,
        "total_candidate_groups": 1,
        "model_used": "mock-model",
        "wall_time_seconds": 0.01,
        "groups": [
            {
                "candidate_group_id": 1,
                "topic": "other",
                "group_label": "测试候选组",
                "grouping_method": "topic only",
                "grouping_basis": "solo",
                "cross_paper": False,
                "paper_count": 1,
                "claim_count": 1,
                "adjudication": {
                    "status": "pending",
                    "signal_name": None,
                    "human_rationale": None,
                    "reviewed_at": None,
                },
                "evidence": [
                    {
                        "claim_id": claim.id,
                        "paper_id": paper.id,
                        "paper_title": paper.title,
                        "subject": "test subject",
                        "topic": "other",
                        "quote": claim.quote,
                        "page": 1,
                        "context": "",
                    }
                ],
            }
        ],
    }


class TestClusterSaveFailureVisibility:
    """有候选组时落库失败不得返回 HTTP 200."""

    def test_save_failure_returns_non_success(self, client, db_session):
        project = _make_project(db_session, "Cluster Fail Project")
        paper = _make_paper(db_session, project.id, "Paper A")
        claim = _make_claim(db_session, paper.id, "Limitation quote A")
        db_session.commit()

        result = _clustering_result(project.id, claim, paper)

        with patch(
            "backend.services.limitation_clusterer.run_clustering",
            new=AsyncMock(return_value=result),
        ), patch(
            "backend.services.cluster_writer.save_clustering_result",
            side_effect=RuntimeError("db write failed"),
        ):
            resp = client.post(
                f"{PROJECTS}/{project.id}/clustering/limitation",
                json={},
            )

        assert resp.status_code != 200
        assert resp.status_code >= 400
        detail = resp.json().get("detail", "")
        assert "落库失败" in detail or "失败" in detail

    def test_empty_groups_still_200(self, client, db_session):
        """无候选组可写时不属于落库失败，仍返回 200."""
        project = _make_project(db_session, "Empty Cluster Project")
        _make_paper(db_session, project.id, "Paper empty")
        db_session.commit()

        empty = {
            "project_id": project.id,
            "total_claims": 0,
            "total_candidate_groups": 0,
            "model_used": "mock-model",
            "wall_time_seconds": 0.0,
            "groups": [],
        }
        with patch(
            "backend.services.limitation_clusterer.run_clustering",
            new=AsyncMock(return_value=empty),
        ):
            resp = client.post(
                f"{PROJECTS}/{project.id}/clustering/limitation",
                json={},
            )

        assert resp.status_code == 200
        assert resp.json()["run_id"] == ""
        assert resp.json()["total_candidate_groups"] == 0

    def test_save_persists_project_id(self, db_session):
        from backend.services.cluster_writer import save_clustering_result

        project = _make_project(db_session, "Save Project")
        paper = _make_paper(db_session, project.id, "Paper save")
        claim = _make_claim(db_session, paper.id, "Limitation quote save")
        db_session.commit()

        run_id = save_clustering_result(_clustering_result(project.id, claim, paper))
        assert run_id

        db_session.expire_all()
        stored = (
            db_session.query(CandidateGroup)
            .filter(CandidateGroup.run_id == run_id)
            .all()
        )
        assert len(stored) == 1
        assert stored[0].project_id == project.id


class TestAdjudicationProjectIsolation:
    """候选组 / 信号查询与变更按 project_id 隔离."""

    def test_candidate_groups_filtered_by_project_id(self, client, db_session):
        p1 = _make_project(db_session, "Iso P1")
        p2 = _make_project(db_session, "Iso P2")
        paper1 = _make_paper(db_session, p1.id, "P1 paper")
        paper2 = _make_paper(db_session, p2.id, "P2 paper")
        c1 = _make_claim(db_session, paper1.id, "lim p1")
        c2 = _make_claim(db_session, paper2.id, "lim p2")
        g1 = _make_group(db_session, p1.id, c1, "group-p1")
        g2 = _make_group(db_session, p2.id, c2, "group-p2")
        db_session.commit()

        resp = client.get(f"{ADJ}/candidate-groups", params={"project_id": p1.id})
        assert resp.status_code == 200
        ids = {g["id"] for g in resp.json()}
        assert g1.id in ids
        assert g2.id not in ids
        assert all(g.get("project_id") == p1.id for g in resp.json())

        resp2 = client.get(f"{ADJ}/candidate-groups", params={"project_id": p2.id})
        ids2 = {g["id"] for g in resp2.json()}
        assert g2.id in ids2
        assert g1.id not in ids2

    def test_signals_filtered_by_project_id(self, client, db_session):
        p1 = _make_project(db_session, "Sig P1")
        p2 = _make_project(db_session, "Sig P2")
        paper1 = _make_paper(db_session, p1.id, "P1 paper")
        paper2 = _make_paper(db_session, p2.id, "P2 paper")
        c1 = _make_claim(db_session, paper1.id, "sig lim p1")
        c2 = _make_claim(db_session, paper2.id, "sig lim p2")
        g1 = _make_group(db_session, p1.id, c1, "sig-group-p1")
        g2 = _make_group(db_session, p2.id, c2, "sig-group-p2")
        db_session.commit()

        r1 = client.post(
            f"{ADJ}/signals",
            params={"project_id": p1.id},
            json={
                "action": "accept",
                "candidate_group_id": g1.id,
                "signal_name": "signal-p1",
            },
        )
        r2 = client.post(
            f"{ADJ}/signals",
            params={"project_id": p2.id},
            json={
                "action": "reject",
                "candidate_group_id": g2.id,
            },
        )
        assert r1.status_code == 201, r1.text
        assert r2.status_code == 201, r2.text
        assert r1.json()["project_id"] == p1.id
        assert r2.json()["project_id"] == p2.id

        listed = client.get(f"{ADJ}/signals", params={"project_id": p1.id})
        assert listed.status_code == 200
        ids = {s["id"] for s in listed.json()}
        assert r1.json()["id"] in ids
        assert r2.json()["id"] not in ids

    def test_cross_project_leak_does_not_occur(self, client, db_session):
        p1 = _make_project(db_session, "Leak P1")
        p2 = _make_project(db_session, "Leak P2")
        paper2 = _make_paper(db_session, p2.id, "P2 paper")
        c2 = _make_claim(db_session, paper2.id, "leak lim p2")
        g2 = _make_group(db_session, p2.id, c2, "leak-group-p2")
        db_session.commit()

        # 列表：P1 看不到 P2 候选组
        listed = client.get(f"{ADJ}/candidate-groups", params={"project_id": p1.id})
        assert listed.status_code == 200
        assert listed.json() == []

        # 详情：用 P1 的 project_id 读 P2 候选组 → 404
        detail = client.get(
            f"{ADJ}/candidate-groups/{g2.id}",
            params={"project_id": p1.id},
        )
        assert detail.status_code == 404

        # 变更：用 P1 的 project_id 裁决 P2 候选组 → 404，且不写入 signal
        created = client.post(
            f"{ADJ}/signals",
            params={"project_id": p1.id},
            json={
                "action": "accept",
                "candidate_group_id": g2.id,
                "signal_name": "should-not-exist",
            },
        )
        assert created.status_code == 404
        db_session.expire_all()
        leaked = (
            db_session.query(Signal)
            .filter(Signal.candidate_group_id == g2.id)
            .first()
        )
        assert leaked is None

        # 真正属于 P2 的路径仍可用
        ok = client.get(
            f"{ADJ}/candidate-groups/{g2.id}",
            params={"project_id": p2.id},
        )
        assert ok.status_code == 200
        assert ok.json()["id"] == g2.id

    def test_list_requires_project_id(self, client):
        resp = client.get(f"{ADJ}/candidate-groups")
        assert resp.status_code == 422
        resp2 = client.get(f"{ADJ}/signals")
        assert resp2.status_code == 422

    def test_cross_project_signal_detail_404(self, client, db_session):
        p1 = _make_project(db_session, "Det P1")
        p2 = _make_project(db_session, "Det P2")
        paper2 = _make_paper(db_session, p2.id, "P2 paper")
        c2 = _make_claim(db_session, paper2.id, "det lim p2")
        g2 = _make_group(db_session, p2.id, c2, "det-group-p2")
        db_session.commit()

        created = client.post(
            f"{ADJ}/signals",
            params={"project_id": p2.id},
            json={"action": "reject", "candidate_group_id": g2.id},
        )
        assert created.status_code == 201
        sig_id = created.json()["id"]

        leaked = client.get(
            f"{ADJ}/signals/{sig_id}",
            params={"project_id": p1.id},
        )
        assert leaked.status_code == 404

        listed = client.get(f"{ADJ}/signals", params={"project_id": p1.id})
        assert listed.status_code == 200
        assert listed.json() == []
