from __future__ import annotations

import asyncio
import json
import time
from typing import Any, cast

from blendrender.db import Database
from blendrender.models import Backend, Job, JobStatus
from blendrender.worker import RenderWorker, job_paths


class RecordingDatabase:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    async def update(self, _: str, **values: Any) -> None:
        self.updates.append(values)


class WorkerDatabase(RecordingDatabase):
    def __init__(self, job: Job) -> None:
        super().__init__()
        self.job = job

    async def get_job(self, _: str) -> Job:
        return self.job

    async def update(self, _: str, **values: Any) -> Job:
        self.updates.append(values)
        self.job = self.job.model_copy(update=values)
        return self.job


class FakeProcess:
    def __init__(self, lines: list[bytes]) -> None:
        self.stdout = self._lines(lines)
        self.returncode: int | None = None

    @staticmethod
    async def _lines(lines: list[bytes]):
        for line in lines:
            yield line

    async def wait(self) -> int:
        self.returncode = 0
        return 0


async def test_elapsed_recorder_updates_while_blender_has_no_output(settings, monkeypatch) -> None:
    database = RecordingDatabase()
    worker = RenderWorker(settings, cast(Database, database))
    monkeypatch.setattr("blendrender.worker.ELAPSED_UPDATE_INTERVAL_SECONDS", 0.01)
    started = time.monotonic()
    task = asyncio.create_task(worker._record_elapsed("job-1", started))
    await asyncio.sleep(0.03)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert database.updates
    assert database.updates[-1]["elapsed_seconds"] > 0


async def test_worker_records_frame_sample_telemetry(settings, monkeypatch) -> None:
    job = Job(
        id="00000000-0000-4000-8000-000000000004",
        filename="scene.blend",
        status=JobStatus.RUNNING,
        mode="still",
        frame_start=1,
        frame_end=1,
        backend=Backend.CPU,
        progress=0,
        created_at="2026-08-30T00:00:00+00:00",
    )
    database = WorkerDatabase(job)
    worker = RenderWorker(settings, cast(Database, database))
    paths = job_paths(settings, job.id)
    scene = paths["source"] / "project/scenes/main.blend"
    scene.parent.mkdir(parents=True)
    scene.write_bytes(b"BLENDER-v1-test-data")
    paths["entrypoint"].write_text(
        json.dumps({"scene": "project/scenes/main.blend"}),
        encoding="utf-8",
    )
    invocation: list[object] = []

    async def create_process(*command: object, **_: object) -> FakeProcess:
        invocation.extend(command)
        return FakeProcess(
            [
                b'BLENDRENDER_EVENT {"type":"frame_started","frame":1}\n',
                b'BLENDRENDER_EVENT {"type":"frame_progress","frame":1,"sample_current":32,'
                b'"sample_total":64}\n',
                b'BLENDRENDER_EVENT {"type":"frame_completed","frame":1,"seconds":1}\n',
            ]
        )

    monkeypatch.setattr("blendrender.worker.asyncio.create_subprocess_exec", create_process)
    await worker._run(job)

    assert str(scene.resolve()) in invocation
    assert any(
        update.get("current_frame") == 1
        and update.get("sample_current") == 32
        and update.get("sample_total") == 64
        for update in database.updates
    )
    assert database.updates[-1]["sample_current"] is None
    assert database.updates[-1]["sample_total"] is None
