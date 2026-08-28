from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import aiosqlite

from .models import Backend, Job, JobStatus, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    status TEXT NOT NULL,
    mode TEXT NOT NULL,
    frame_start INTEGER NOT NULL,
    frame_end INTEGER NOT NULL,
    backend TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    current_frame INTEGER,
    completed_frames TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    log_tail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    elapsed_seconds REAL NOT NULL DEFAULT 0,
    eta_seconds REAL,
    cancel_requested INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS jobs_status_created_idx ON jobs(status, created_at);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as connection:
            await connection.executescript(SCHEMA)
            await connection.execute("PRAGMA journal_mode=WAL")
            await connection.execute("PRAGMA foreign_keys=ON")
            await connection.execute(
                """
                UPDATE jobs
                SET status = ?, error = ?, finished_at = ?, cancel_requested = 0
                WHERE status = ?
                """,
                (
                    JobStatus.INTERRUPTED,
                    "The application restarted while this render was running.",
                    utc_now(),
                    JobStatus.RUNNING,
                ),
            )
            await connection.commit()

    async def create_job(
        self,
        *,
        job_id: str,
        filename: str,
        mode: str,
        frame_start: int,
        frame_end: int,
        backend: Backend,
    ) -> Job:
        created_at = utc_now()
        async with aiosqlite.connect(self.path) as connection:
            await connection.execute(
                """
                INSERT INTO jobs (
                    id, filename, status, mode, frame_start, frame_end, backend, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    filename,
                    JobStatus.QUEUED,
                    mode,
                    frame_start,
                    frame_end,
                    backend,
                    created_at,
                ),
            )
            await connection.commit()
        job = await self.get_job(job_id)
        if job is None:  # pragma: no cover - defensive invariant
            raise RuntimeError("Created job could not be read back")
        return job

    async def get_job(self, job_id: str) -> Job | None:
        async with aiosqlite.connect(self.path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = await cursor.fetchone()
        return self._to_job(row) if row is not None else None

    async def list_jobs(self, status: JobStatus | None = None) -> list[Job]:
        query = "SELECT * FROM jobs"
        params: tuple[Any, ...] = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY created_at DESC"
        async with aiosqlite.connect(self.path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(query, params)
            rows = await cursor.fetchall()
        return [self._to_job(row) for row in rows]

    async def next_queued_job(self) -> Job | None:
        async with aiosqlite.connect(self.path) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at ASC LIMIT 1",
                (JobStatus.QUEUED,),
            )
            row = await cursor.fetchone()
            if row is None:
                await connection.commit()
                return None
            await connection.execute(
                """
                UPDATE jobs
                SET status = ?, started_at = ?, finished_at = NULL, error = NULL,
                    cancel_requested = 0
                WHERE id = ? AND status = ?
                """,
                (JobStatus.RUNNING, utc_now(), row["id"], JobStatus.QUEUED),
            )
            await connection.commit()
        return await self.get_job(str(row["id"]))

    async def update(self, job_id: str, **values: Any) -> Job:
        if not values:
            job = await self.get_job(job_id)
            if job is None:
                raise KeyError(job_id)
            return job
        allowed = {
            "status",
            "progress",
            "current_frame",
            "completed_frames",
            "error",
            "log_tail",
            "started_at",
            "finished_at",
            "elapsed_seconds",
            "eta_seconds",
            "cancel_requested",
        }
        if invalid := set(values) - allowed:
            raise ValueError(f"Unsupported job fields: {sorted(invalid)}")
        normalized: dict[str, Any] = {}
        for key, value in values.items():
            if key == "completed_frames":
                value = json.dumps(sorted(set(value)))
            elif isinstance(value, JobStatus):
                value = value.value
            elif isinstance(value, bool):
                value = int(value)
            normalized[key] = value
        assignments = ", ".join(f"{key} = ?" for key in normalized)
        async with aiosqlite.connect(self.path) as connection:
            cursor = await connection.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?",  # noqa: S608 - keys are allowlisted
                (*normalized.values(), job_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(job_id)
            await connection.commit()
        job = await self.get_job(job_id)
        if job is None:  # pragma: no cover
            raise KeyError(job_id)
        return job

    async def delete_job(self, job_id: str) -> None:
        async with aiosqlite.connect(self.path) as connection:
            await connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            await connection.commit()

    async def requeue(self, job_id: str, completed_frames: Iterable[int]) -> Job:
        frames = sorted(set(completed_frames))
        job = await self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        progress = len(frames) / job.total_frames * 100
        return await self.update(
            job_id,
            status=JobStatus.QUEUED,
            progress=progress,
            current_frame=None,
            completed_frames=frames,
            error=None,
            finished_at=None,
            eta_seconds=None,
            cancel_requested=False,
        )

    @staticmethod
    def _to_job(row: aiosqlite.Row) -> Job:
        values = dict(row)
        values["completed_frames"] = json.loads(values["completed_frames"])
        values["cancel_requested"] = bool(values["cancel_requested"])
        return Job.model_validate(values)
