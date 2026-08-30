from __future__ import annotations

import asyncio
import time
from typing import Any, cast

from blendrender.db import Database
from blendrender.worker import RenderWorker


class RecordingDatabase:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    async def update(self, _: str, **values: Any) -> None:
        self.updates.append(values)


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
