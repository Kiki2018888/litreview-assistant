"""S4: export accepted Signals as Markdown (P0 exit).

Covers:
  - Accepted signals appear in the Markdown
  - Rejected signals are absent
  - Project isolation (no cross-project leak)
  - Empty project: valid Markdown, not 500
  - Contradiction export shows both quotes and pages
  - Missing project: 404
"""
from __future__ import annotations

from backend.models.tables import CandidateType
from backend.tests.test_discover import ADJ, _make_claim, _make_paper, _make_project
from backend.tests.test_signal_persistence import _make_group

EXPORT = f"{ADJ}/signals/export.md"


def _export(client, project_id: str):
    return client.get(EXPORT, params={"project_id": project_id})


def _accept(client, project_id: str, group_id: str, signal_name: str | None = None):
    body = {"action": "accept", "candidate_group_id": group_id}
    if signal_name is not None:
        body["signal_name"] = signal_name
    return client.post(
        f"{ADJ}/signals",
        params={"project_id": project_id},
        json=body,
    )


def _reject(client, project_id: str, group_id: str):
    return client.post(
        f"{ADJ}/signals",
        params={"project_id": project_id},
        json={"action": "reject", "candidate_group_id": group_id},
    )


def _seed_vision_contradiction(db, project_name: str):
    """Two opposing efficacy quotes used by the contradiction export cases."""
    project = _make_project(db, project_name)
    up_paper = _make_paper(db, project.id, "Vision Up Trial")
    down_paper = _make_paper(db, project.id, "Vision Down Trial")
    up = _make_claim(
        db, up_paper.id, "Vision improved at month 12.",
        is_limitation=False, claim_form="effect", direction="up",
        topic="efficacy", quote_page=5,
    )
    down = _make_claim(
        db, down_paper.id, "Vision declined at month 12.",
        is_limitation=False, claim_form="effect", direction="down",
        topic="efficacy", quote_page=11,
    )
    group = _make_group(
        db, project.id, [up, down],
        "efficacy direction conflict",
        candidate_type=CandidateType.CONTRADICTION.value,
        is_weak=False,
    )
    db.commit()
    return project, up, down, group


def _assert_contradiction_sides(body: str) -> None:
    for piece in (
        "双方证据",
        "一方",
        "另一方",
        "Vision Up Trial",
        "Vision Down Trial",
        "Vision improved at month 12.",
        "Vision declined at month 12.",
        "第 5 页",
        "第 11 页",
    ):
        assert piece in body


class TestExportAcceptedMarkdown:
    def test_accepted_present_rejected_absent(self, client, db_session):
        project = _make_project(db_session, "Export Mix")
        p1 = _make_paper(db_session, project.id, "Paper Keep")
        p2 = _make_paper(db_session, project.id, "Paper Drop")
        keep = _make_claim(
            db_session, p1.id, "Small sample size is a limitation.", quote_page=3,
        )
        keep2 = _make_claim(
            db_session, p2.id, "Cohort was underpowered.", quote_page=7,
        )
        drop = _make_claim(db_session, p2.id, "REJECTED_QUOTE_SHOULD_NOT_APPEAR")
        accepted_group = _make_group(
            db_session, project.id, [keep, keep2],
            "underpowered cohorts after transplant",
            is_weak=False,
        )
        rejected_group = _make_group(
            db_session, project.id, [drop], "noise pile", is_weak=False,
        )
        db_session.commit()

        acc = _accept(client, project.id, accepted_group.id, "Underpowered cohorts")
        rej = _reject(client, project.id, rejected_group.id)
        assert acc.status_code == 201, acc.text
        assert rej.status_code == 201, rej.text

        resp = _export(client, project.id)
        assert resp.status_code == 200, resp.text
        assert "text/markdown" in resp.headers.get("content-type", "")
        disposition = resp.headers.get("content-disposition", "")
        assert f"signals-{project.id}.md" in disposition

        body = resp.text
        assert "Underpowered cohorts" in body
        assert "局限聚类" in body
        assert "`limitation_cluster`" in body
        assert "Paper Keep" in body
        assert "Small sample size is a limitation." in body
        assert "第 3 页" in body
        assert "Cohort was underpowered." in body
        assert "第 7 页" in body
        assert "REJECTED_QUOTE_SHOULD_NOT_APPEAR" not in body
        assert "noise pile" not in body

    def test_empty_project_valid_markdown_not_500(self, client, db_session):
        project = _make_project(db_session, "Empty Export")
        db_session.commit()

        resp = _export(client, project.id)
        assert resp.status_code == 200, resp.text
        assert "text/markdown" in resp.headers.get("content-type", "")
        assert "没有已采纳" in resp.text
        assert "Empty Export" in resp.text
        assert project.id in resp.text

    def test_missing_project_404(self, client, db_session):
        resp = _export(client, "00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404
        assert "项目不存在" in resp.json()["detail"]

    def test_project_isolation(self, client, db_session):
        p1 = _make_project(db_session, "Export P1")
        p2 = _make_project(db_session, "Export P2")
        paper1 = _make_paper(db_session, p1.id, "P1 paper")
        paper2 = _make_paper(db_session, p2.id, "P2 paper")
        c1 = _make_claim(db_session, paper1.id, "P1_SECRET_LIMITATION", quote_page=2)
        c1b = _make_claim(db_session, paper1.id, "P1 other limitation", quote_page=4)
        c2 = _make_claim(db_session, paper2.id, "P2_SECRET_LIMITATION", quote_page=8)
        c2b = _make_claim(db_session, paper2.id, "P2 other limitation", quote_page=9)
        g1 = _make_group(db_session, p1.id, [c1, c1b], "p1 cluster", is_weak=False)
        g2 = _make_group(db_session, p2.id, [c2, c2b], "p2 cluster", is_weak=False)
        db_session.commit()

        assert _accept(client, p1.id, g1.id, "P1 Signal").status_code == 201
        assert _accept(client, p2.id, g2.id, "P2 Signal").status_code == 201

        out1 = _export(client, p1.id)
        out2 = _export(client, p2.id)
        assert out1.status_code == 200
        assert out2.status_code == 200
        assert "P1_SECRET_LIMITATION" in out1.text
        assert "P1 Signal" in out1.text
        assert "P2_SECRET_LIMITATION" not in out1.text
        assert "P2 Signal" not in out1.text
        assert "P2_SECRET_LIMITATION" in out2.text
        assert "P1_SECRET_LIMITATION" not in out2.text

    def test_contradiction_shows_both_quotes_and_pages(self, client, db_session):
        project, _up, _down, group = _seed_vision_contradiction(db_session, "Contra Export")
        acc = _accept(client, project.id, group.id, "Efficacy conflict")
        assert acc.status_code == 201, acc.text

        resp = _export(client, project.id)
        assert resp.status_code == 200, resp.text
        body = resp.text
        assert "Efficacy conflict" in body
        assert "矛盾" in body
        assert "`contradiction`" in body
        _assert_contradiction_sides(body)

    def test_export_keeps_snapshot_after_live_claims_deleted(self, client, db_session):
        """证据快照在采纳时冻结；删除原 claim 后导出仍含双方 quote 与页码."""
        project, up, down, group = _seed_vision_contradiction(db_session, "Snapshot Export")
        acc = _accept(client, project.id, group.id, "Efficacy conflict")
        assert acc.status_code == 201, acc.text

        db_session.delete(up)
        db_session.delete(down)
        db_session.commit()

        resp = _export(client, project.id)
        assert resp.status_code == 200, resp.text
        _assert_contradiction_sides(resp.text)
