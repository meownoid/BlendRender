from __future__ import annotations

from pathlib import Path

import blendrender.system as system_module
from blendrender.models import Backend
from blendrender.system import SystemProbe
from blendrender.telemetry import (
    ACTIVE_SAMPLE_SECONDS,
    IDLE_SAMPLE_SECONDS,
    TelemetryCollector,
    sample_system,
)


async def test_system_info_includes_host_metrics(tmp_path: Path, monkeypatch) -> None:
    class Memory:
        total = 16 * 1024**3
        available = 6 * 1024**3

    async def no_gpus() -> list:
        return []

    monkeypatch.setattr(system_module.psutil, "cpu_percent", lambda interval=None: 37.5)
    monkeypatch.setattr(system_module.psutil, "virtual_memory", lambda: Memory())
    probe = SystemProbe(Path("/usr/bin/true"), tmp_path)
    probe.blender_version = "5.2.1"
    probe.available_backends = [Backend.CPU]
    monkeypatch.setattr(probe, "gpus", no_gpus)

    info = await probe.info()

    assert info.cpu_utilization == 37.5
    assert info.memory_used_bytes == 10 * 1024**3
    assert info.memory_total_bytes == 16 * 1024**3
    assert info.gpus == []


async def test_backend_override_requires_a_working_blender_binary(tmp_path: Path) -> None:
    probe = SystemProbe(tmp_path / "missing-blender", tmp_path, ("CPU",))

    await probe.initialize()

    assert probe.blender_version is None
    assert probe.available_backends == []


def test_telemetry_sample_aggregates_gpus() -> None:
    info = system_module.SystemInfo.model_validate(
        {
            "blender_version": "5.2.1",
            "gpus": [
                {
                    "name": "GPU 0",
                    "utilization": 22,
                    "memory_used_mb": 1000,
                    "memory_total_mb": 4000,
                },
                {
                    "name": "GPU 1",
                    "utilization": 81,
                    "memory_used_mb": 3000,
                    "memory_total_mb": 8000,
                },
            ],
            "available_backends": ["CPU"],
            "cpu_utilization": 45,
            "memory_used_bytes": 6 * 1024**3,
            "memory_total_bytes": 16 * 1024**3,
            "disk_free_bytes": 1,
            "disk_total_bytes": 2,
        }
    )

    sample = sample_system(info, "2026-08-29T12:00:00+00:00")

    assert sample.gpu_utilization == 81
    assert sample.vram_used_mb == 4000
    assert sample.vram_total_mb == 12000


async def test_telemetry_collector_recovers_and_stops_promptly() -> None:
    class Database:
        def __init__(self) -> None:
            self.samples = []
            self.active = False

        async def record_telemetry(self, sample) -> None:
            self.samples.append(sample)

        async def has_active_jobs(self) -> bool:
            return self.active

    class Probe:
        def __init__(self) -> None:
            self.calls = 0

        async def info(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary failure")
            return system_module.SystemInfo.model_validate(
                {
                    "blender_version": "5.2.1",
                    "gpus": [],
                    "available_backends": ["CPU"],
                    "cpu_utilization": 20,
                    "memory_used_bytes": 1,
                    "memory_total_bytes": 2,
                    "disk_free_bytes": 1,
                    "disk_total_bytes": 2,
                }
            )

    database = Database()
    collector = TelemetryCollector(database, Probe())
    await collector._capture()
    assert collector.latest is None
    await collector._capture()
    assert collector.latest is not None
    assert len(database.samples) == 1
    assert await collector._sampling_interval() == IDLE_SAMPLE_SECONDS
    database.active = True
    assert await collector._sampling_interval() == ACTIVE_SAMPLE_SECONDS

    await collector.start()
    await collector.stop()
