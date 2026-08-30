from __future__ import annotations

from pathlib import Path

import blendrender.system as system_module
from blendrender.models import Backend
from blendrender.system import SystemProbe
from blendrender.telemetry import sample_system


async def test_system_info_includes_pod_and_host_metrics(tmp_path: Path, monkeypatch) -> None:
    class Memory:
        total = 16 * 1024**3
        available = 6 * 1024**3

    async def no_gpus() -> list:
        return []

    monkeypatch.setattr(system_module.psutil, "cpu_percent", lambda interval=None: 37.5)
    monkeypatch.setattr(system_module.psutil, "virtual_memory", lambda: Memory())
    probe = SystemProbe(Path("/usr/bin/true"), tmp_path, "pod-a")
    probe.blender_version = "5.2.1"
    probe.available_backends = [Backend.CPU]
    monkeypatch.setattr(probe, "gpus", no_gpus)
    info = await probe.info()
    assert info.pod_id == "pod-a"
    assert info.cpu_utilization == 37.5
    assert info.memory_used_bytes == 10 * 1024**3


async def test_backend_override_requires_working_blender(tmp_path: Path) -> None:
    probe = SystemProbe(tmp_path / "missing-blender", tmp_path, "pod-a", ("CPU",))
    await probe.initialize()
    assert probe.blender_version is None
    assert probe.available_backends == []


def test_telemetry_sample_aggregates_gpus() -> None:
    info = system_module.SystemInfo.model_validate(
        {
            "pod_id": "pod-a",
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
    assert (sample.gpu_utilization, sample.vram_used_mb, sample.vram_total_mb) == (81, 4000, 12000)
