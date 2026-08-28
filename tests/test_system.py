from __future__ import annotations

from pathlib import Path

import blendrender.system as system_module
from blendrender.models import Backend
from blendrender.system import SystemProbe


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
