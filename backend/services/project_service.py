"""项目（原批次）领域逻辑."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.models.tables import Paper, Project

DEFAULT_UNCATEGORIZED_PROJECT_ID = "00000000-0000-4000-a000-000000000001"
DEFAULT_UNCATEGORIZED_PROJECT_NAME = "未分类"


def get_default_project(db: Session) -> Project:
    """获取默认「未分类」项目，不存在则创建."""
    project = (
        db.query(Project)
        .filter(Project.is_default.is_(True))
        .first()
    )
    if project:
        return project

    project = Project(
        id=DEFAULT_UNCATEGORIZED_PROJECT_ID,
        name=DEFAULT_UNCATEGORIZED_PROJECT_NAME,
        description=None,
        paper_count=0,
        is_default=True,
    )
    db.add(project)
    db.flush()
    return project


def resolve_project_id(db: Session, project_id: Optional[str]) -> str:
    """解析上传/归属项目 ID，空则使用默认项目."""
    if project_id:
        project = db.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")
        return project.id
    return get_default_project(db).id


def adjust_project_paper_count(db: Session, project_id: str, delta: int) -> None:
    """增减项目文献计数."""
    if not project_id or delta == 0:
        return
    db.execute(
        text(
            "UPDATE projects SET paper_count = MAX(0, paper_count + :delta), "
            "updated_at = datetime('now') WHERE id = :pid"
        ),
        {"delta": delta, "pid": project_id},
    )


def recalculate_project_paper_count(db: Session, project_id: str) -> None:
    """按实际文献数重算项目 paper_count."""
    count = db.scalar(
        select(func.count(Paper.id)).where(Paper.project_id == project_id)
    ) or 0
    db.execute(
        text(
            "UPDATE projects SET paper_count = :c, updated_at = datetime('now') "
            "WHERE id = :pid"
        ),
        {"c": count, "pid": project_id},
    )


def move_paper_between_projects(
    db: Session,
    paper: Paper,
    new_project_id: str,
) -> None:
    """将文献从一个项目移动到另一个项目."""
    old_project_id = paper.project_id
    if old_project_id == new_project_id:
        return
    paper.project_id = new_project_id
    if old_project_id:
        adjust_project_paper_count(db, old_project_id, -1)
    adjust_project_paper_count(db, new_project_id, 1)


__all__ = [
    "DEFAULT_UNCATEGORIZED_PROJECT_ID",
    "DEFAULT_UNCATEGORIZED_PROJECT_NAME",
    "adjust_project_paper_count",
    "get_default_project",
    "move_paper_between_projects",
    "recalculate_project_paper_count",
    "resolve_project_id",
]
