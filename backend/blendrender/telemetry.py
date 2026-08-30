from __future__ import annotations

import asyncio
import logging
import platform
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from .models import NodeStatus, SystemInfo, TelemetrySample, utc_now
from .system import SystemProbe
from .workspace import WorkspaceStore

ACTIVE_SAMPLE_SECONDS = 5
IDLE_SAMPLE_SECONDS = 10
TELEMETRY_RETENTION = timedelta(minutes=15)

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
    def __init__(self, store: WorkspaceStore, probe: SystemProbe):
        self.store = store
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

    async def samples(self) -> list[TelemetrySample]:
        return await asyncio.to_thread(self.store.read_telemetry, self.probe.pod_id)

    async def _capture(self) -> None:
        try:
            info = await self.probe.info()
            sample = sample_system(info)
            existing = await asyncio.to_thread(self.store.read_telemetry, self.probe.pod_id)
            cutoff = datetime.now(UTC) - TELEMETRY_RETENTION
            retained = [
                item
                for item in existing + [sample]
                if datetime.fromisoformat(item.captured_at).astimezone(UTC) >= cutoff
            ]
            hardware = [gpu.name for gpu in info.gpus] or [platform.processor() or "CPU"]
            await asyncio.to_thread(
                self.store.write_node_status,
                NodeStatus(
                    pod_id=self.probe.pod_id,
                    available_backends=info.available_backends,
                    hardware=hardware,
                    last_seen=sample.captured_at,
                ),
            )
            await asyncio.to_thread(self.store.write_telemetry, self.probe.pod_id, retained)
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
            jobs = await asyncio.to_thread(
                self.store.list_jobs, owner_pod_id=self.probe.pod_id
            )
            if any(job.status.value in {"queued", "running"} for job in jobs):
                return ACTIVE_SAMPLE_SECONDS
        except Exception:
            logger.exception("Unable to determine telemetry sampling interval")
        return IDLE_SAMPLE_SECONDS
