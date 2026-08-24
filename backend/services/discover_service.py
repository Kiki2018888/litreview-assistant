"""Unified discover orchestration (S1).

One job, two phases:
  1. limitation clustering
  2. rule-based contradiction detection

Persist both candidate types in a single run. Failures mark the job failed
and are re-raised so HTTP callers see a non-200 status.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from typing import Any, Optional

from backend.models.tables import ExtractJob, JobStatus, JobType, Project
from backend.services.cluster_writer import save_clustering_result
from backend.services.contradiction_detector import detect_contradictions
from backend.services import db as db_mod
from backend.services.limitation_clusterer import run_clustering

logger = logging.getLogger(__name__)

DISCOVER_PHASES = ("limitation_cluster", "contradiction")


def _uuid4() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


def create_discover_job(project_id: str) -> ExtractJob:
    """Insert a running discover job (two phases)."""
    db = db_mod.SessionLocal()
    try:
        job = ExtractJob(
            id=_uuid4(),
            project_id=project_id,
            job_type=JobType.DISCOVER.value,
            status=JobStatus.RUNNING.value,
            total=len(DISCOVER_PHASES),
            current=0,
            succeeded=0,
            failed=0,
            error_summary={"phase": DISCOVER_PHASES[0]},
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job
    finally:
        db.close()


def update_discover_job(job_id: str, **kwargs: Any) -> Optional[ExtractJob]:
    db = db_mod.SessionLocal()
    try:
        job = db.query(ExtractJob).filter(ExtractJob.id == job_id).first()
        if not job:
            return None
        for key, value in kwargs.items():
            setattr(job, key, value)
        job.updated_at = _now()
        db.commit()
        db.refresh(job)
        return job
    finally:
        db.close()


def fail_discover_job(job_id: str, *, phase: str, error: str) -> None:
    update_discover_job(
        job_id,
        status=JobStatus.FAILED.value,
        failed=1,
        error_summary={"phase": phase, "error": error[:500]},
    )


def get_in_progress_discover_job(project_id: str) -> Optional[ExtractJob]:
    db = db_mod.SessionLocal()
    try:
        return (
            db.query(ExtractJob)
            .filter(
                ExtractJob.project_id == project_id,
                ExtractJob.job_type == JobType.DISCOVER.value,
                ExtractJob.status.in_([
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                    JobStatus.PAUSED.value,
                ]),
            )
            .order_by(ExtractJob.created_at.desc())
            .first()
        )
    finally:
        db.close()


def project_exists(project_id: str) -> bool:
    db = db_mod.SessionLocal()
    try:
        return db.query(Project).filter(Project.id == project_id).first() is not None
    finally:
        db.close()


async def run_discover(project_id: str, job_id: str) -> dict[str, Any]:
    """Run both discover phases and persist one run of candidates.

    Raises on clustering / persist failure (caller maps to HTTP). Contradiction
    detection is rule-based and should not fail; if it does, the job fails too.
    """
    t0 = time.perf_counter()

    # Phase 1 — limitation clustering
    update_discover_job(
        job_id,
        current=1,
        error_summary={"phase": "limitation_cluster"},
    )
    try:
        cluster_result = await run_clustering(project_id)
    except Exception as exc:
        logger.exception("discover clustering failed: project_id=%s", project_id)
        fail_discover_job(job_id, phase="limitation_cluster", error=str(exc))
        raise

    update_discover_job(job_id, succeeded=1)

    # Phase 2 — contradiction detection
    update_discover_job(
        job_id,
        current=2,
        error_summary={"phase": "contradiction"},
    )
    try:
        contradiction_groups = detect_contradictions(project_id)
    except Exception as exc:
        logger.exception("discover contradiction failed: project_id=%s", project_id)
        fail_discover_job(job_id, phase="contradiction", error=str(exc))
        raise

    limitation_groups = list(cluster_result.get("groups") or [])
    all_groups = limitation_groups + contradiction_groups
    run_id = ""
    if all_groups:
        try:
            run_id = save_clustering_result(
                {
                    "project_id": project_id,
                    "groups": all_groups,
                },
                project_id=project_id,
            )
            if not run_id:
                raise RuntimeError("未获得 run_id")
        except Exception as exc:
            logger.exception("discover persist failed: project_id=%s", project_id)
            fail_discover_job(job_id, phase="persist", error=str(exc))
            raise RuntimeError(f"发现任务落库失败: {exc}") from exc

    weak_count = sum(1 for g in all_groups if g.get("is_weak"))
    primary_count = len(all_groups) - weak_count
    elapsed = round(time.perf_counter() - t0, 2)

    update_discover_job(
        job_id,
        status=JobStatus.COMPLETED.value,
        current=2,
        succeeded=2,
        failed=0,
        error_summary={
            "phase": "done",
            "run_id": run_id,
            "limitation_groups": len(limitation_groups),
            "contradiction_groups": len(contradiction_groups),
            "weak_count": weak_count,
        },
    )

    return {
        "job_id": job_id,
        "project_id": project_id,
        "status": JobStatus.COMPLETED.value,
        "run_id": run_id,
        "limitation_groups": len(limitation_groups),
        "contradiction_groups": len(contradiction_groups),
        "weak_count": weak_count,
        "primary_count": primary_count,
        "total_candidate_groups": len(all_groups),
        "wall_time_seconds": elapsed,
    }


__all__ = [
    "create_discover_job",
    "update_discover_job",
    "fail_discover_job",
    "get_in_progress_discover_job",
    "project_exists",
    "run_discover",
    "DISCOVER_PHASES",
]
