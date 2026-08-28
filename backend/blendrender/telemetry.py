from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from .db import Database
from .models import SystemInfo, TelemetrySample, utc_now
from .system import SystemProbe

ACTIVE_SAMPLE_SECONDS = 5
IDLE_SAMPLE_SECONDS = 10

logger = logging.getLogger(__name__)


def sample_system(info: SystemInfo, captured_at: str | None = None) -> TelemetrySample:
    gpus = info.gpus
    return TelemetrySample(
        captured_at=captured_at or utc_now(),
        cpu_utilization=info.cpu_utilization,
        gpu_utilization=max((gpu.utilization for gpu in gpus), default=None),
        memory_used_bytes=info.memory_used_bytes,
        memory_total_bytes=info.memory_total_bytes,
        vram_used_mb=sum(gpu.memory_used_mb for gpu in gpus) if gpus else None,
        vram_total_mb=sum(gpu.memory_total_mb for gpu in gpus) if gpus else None,
    )


class TelemetryCollector:
    def __init__(self, database: Database, probe: SystemProbe):
        self.database = database
        self.probe = probe
        self.latest: SystemInfo | None = None
        self._stopping = asyncio.Event()
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self._capture()
        self._task = asyncio.create_task(self._loop(), name="blendrender-telemetry-collector")

    async def stop(self) -> None:
        self._stopping.set()
        self._wake.set()
        if self._task is not None:
            with suppress(asyncio.CancelledError):
                await self._task

    def notify(self) -> None:
        self._wake.set()

    async def _capture(self) -> None:
        try:
            info = await self.probe.info()
            await self.database.record_telemetry(sample_system(info))
            self.latest = info
        except Exception:
            logger.exception("Unable to collect system telemetry")

    async def _loop(self) -> None:
        while not self._stopping.is_set():
            interval = await self._sampling_interval()
            with suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=interval)
            self._wake.clear()
            if not self._stopping.is_set():
                await self._capture()

    async def _sampling_interval(self) -> int:
        try:
            if await self.database.has_active_jobs():
                return ACTIVE_SAMPLE_SECONDS
            return IDLE_SAMPLE_SECONDS
        except Exception:
            logger.exception("Unable to determine telemetry sampling interval")
            return IDLE_SAMPLE_SECONDS
