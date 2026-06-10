"""projects API 测试."""
from __future__ import annotations

import io

import pytest

PROJECTS = "/api/v1/projects"
LITERATURE = "/api/v1/literature"


class TestCreateProject:
    def test_create_ok(self, client):
        resp = client.post(PROJECTS + "/", json={"name": "课题 A", "description": "测试"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "课题 A"
        assert data["is_default"] is False
        assert data["paper_count"] == 0


class TestListProjects:
    def test_list_includes_default(self, client):
        resp = client.get(PROJECTS + "/")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert any(p["name"] == "未分类" and p["is_default"] for p in items)


class TestGetProject:
    def test_get_detail(self, client, sample_project):
        resp = client.get(f"{PROJECTS}/{sample_project.id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test Project"
        assert resp.json()["paper_ids"] == []


class TestUpdateProject:
    def test_update_name(self, client, sample_project):
        resp = client.put(
            f"{PROJECTS}/{sample_project.id}",
            json={"name": "Updated Project"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Project"

    def test_cannot_rename_default(self, client, db_session):
        from backend.services.project_service import get_default_project

        default = get_default_project(db_session)
        resp = client.put(
            f"{PROJECTS}/{default.id}",
            json={"name": "其他名称"},
        )
        assert resp.status_code == 400


class TestDeleteProject:
    def test_delete_moves_papers_to_default(self, client, sample_project, db_session):
        from backend.services.project_service import get_default_project

        default = get_default_project(db_session)

        pdf = io.BytesIO(b"%PDF-1.4 minimal")
        r1 = client.post(
            f"{LITERATURE}/upload",
            files=[("files[]", ("t.pdf", pdf, "application/pdf"))],
            data={"project_id": sample_project.id},
        )
        assert r1.status_code == 200
        paper_id = r1.json()["uploaded"][0]["id"]

        r2 = client.delete(f"{PROJECTS}/{sample_project.id}")
        assert r2.status_code == 200
        assert r2.json()["moved_count"] == 1

        r3 = client.get(f"{LITERATURE}/{paper_id}")
        assert r3.json()["project_id"] == default.id

    def test_cannot_delete_default(self, client, db_session):
        from backend.services.project_service import get_default_project

        default = get_default_project(db_session)
        resp = client.delete(f"{PROJECTS}/{default.id}")
        assert resp.status_code == 400


class TestMovePapers:
    def test_move_papers(self, client, sample_project, db_session):
        from backend.services.project_service import get_default_project

        default = get_default_project(db_session)
        pdf = io.BytesIO(b"%PDF-1.4 minimal")
        r1 = client.post(
            f"{LITERATURE}/upload",
            files=[("files[]", ("t.pdf", pdf, "application/pdf"))],
        )
        paper_id = r1.json()["uploaded"][0]["id"]
        assert r1.json()["uploaded"][0]["id"]

        r2 = client.post(
            f"{PROJECTS}/{sample_project.id}/move-papers",
            json={"paper_ids": [paper_id]},
        )
        assert r2.status_code == 200
        assert r2.json()["moved_count"] == 1

        r3 = client.get(f"{LITERATURE}/{paper_id}")
        assert r3.json()["project_id"] == sample_project.id


class TestLiteratureProjectFeatures:
    def test_filter_by_project_id(self, client, sample_project):
        pdf = io.BytesIO(b"%PDF-1.4 minimal")
        client.post(
            f"{LITERATURE}/upload",
            files=[("files[]", ("t.pdf", pdf, "application/pdf"))],
            data={"project_id": sample_project.id},
        )
        resp = client.get(f"{LITERATURE}/", params={"project_id": sample_project.id})
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1
        assert all(i["project_id"] == sample_project.id for i in resp.json()["items"])

    def test_batch_delete(self, client, sample_project):
        pdf = io.BytesIO(b"%PDF-1.4 minimal")
        r1 = client.post(
            f"{LITERATURE}/upload",
            files=[("files[]", ("t.pdf", pdf, "application/pdf"))],
            data={"project_id": sample_project.id},
        )
        paper_id = r1.json()["uploaded"][0]["id"]
        r2 = client.post(f"{LITERATURE}/batch-delete", json={"paper_ids": [paper_id]})
        assert r2.status_code == 200
        assert r2.json()["deleted_count"] == 1
        assert client.get(f"{LITERATURE}/{paper_id}").status_code == 404

    def test_update_paper_project(self, client, sample_project):
        pdf = io.BytesIO(b"%PDF-1.4 minimal")
        r1 = client.post(
            f"{LITERATURE}/upload",
            files=[("files[]", ("t.pdf", pdf, "application/pdf"))],
        )
        paper_id = r1.json()["uploaded"][0]["id"]
        r2 = client.put(
            f"{LITERATURE}/{paper_id}/project",
            json={"project_id": sample_project.id},
        )
        assert r2.status_code == 200
        assert r2.json()["project_name"] == "Test Project"
