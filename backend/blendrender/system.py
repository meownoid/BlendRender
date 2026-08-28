from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path

import psutil

from .models import Backend, GPUInfo, SystemInfo

BACKEND_MARKER = "BLENDRENDER_BACKENDS="


async def _run_command(*args: str, timeout: float = 15) -> tuple[int, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        return process.returncode or 0, output.decode(errors="replace")
    except (FileNotFoundError, TimeoutError):
        return 127, ""


class SystemProbe:
    def __init__(self, blender_bin: Path, data_root: Path, override: tuple[str, ...] = ()):
        self.blender_bin = blender_bin
        self.data_root = data_root
        self.override = override
        self.blender_version: str | None = None
        self.available_backends: list[Backend] = []

    async def initialize(self) -> None:
        psutil.cpu_percent(interval=None)
        version_code, version_output = await _run_command(str(self.blender_bin), "--version")
        if version_code == 0 and version_output:
            first_line = version_output.splitlines()[0]
            self.blender_version = first_line.removeprefix("Blender ").strip()
        if self.blender_version is None:
            return
        if self.override:
            self.available_backends = list(dict.fromkeys(Backend(item) for item in self.override))
            return
        self.available_backends = [Backend.CPU]
        if not await self.gpus():
            return
        expression = (
            "import bpy; p=bpy.context.preferences.addons['cycles'].preferences; "
            "types=[]; "
            "[(setattr(p,'compute_device_type',t),p.get_devices(),types.append(t)) "
            "for t in ('OPTIX','CUDA') if t in "
            "[x[0] for x in p.bl_rna.properties['compute_device_type'].enum_items]]; "
            f"print('{BACKEND_MARKER}'+','.join(types))"
        )
        code, output = await _run_command(
            str(self.blender_bin),
            "--background",
            "--factory-startup",
            "--python-expr",
            expression,
            timeout=45,
        )
        if code == 0:
            marker_line = next(
                (line for line in output.splitlines() if line.startswith(BACKEND_MARKER)), ""
            )
            names = marker_line.removeprefix(BACKEND_MARKER).split(",")
            gpu_names = {Backend.OPTIX.value, Backend.CUDA.value}
            self.available_backends.extend(Backend(name) for name in names if name in gpu_names)

    async def gpus(self) -> list[GPUInfo]:
        code, output = await _run_command(
            "nvidia-smi",
            "--query-gpu=name,utilization.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits",
            timeout=5,
        )
        if code != 0:
            return []
        gpus: list[GPUInfo] = []
        for line in output.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) != 4:
                continue
            try:
                gpus.append(
                    GPUInfo(
                        name=parts[0],
                        utilization=max(0, min(100, int(re.sub(r"\D", "", parts[1]) or 0))),
                        memory_used_mb=max(0, int(re.sub(r"\D", "", parts[2]) or 0)),
                        memory_total_mb=max(0, int(re.sub(r"\D", "", parts[3]) or 0)),
                    )
                )
            except ValueError:
                continue
        return gpus

    async def info(self) -> SystemInfo:
        self.data_root.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(self.data_root)
        memory = psutil.virtual_memory()
        return SystemInfo(
            blender_version=self.blender_version,
            gpus=await self.gpus(),
            available_backends=self.available_backends,
            cpu_utilization=psutil.cpu_percent(interval=None),
            memory_used_bytes=memory.total - memory.available,
            memory_total_bytes=memory.total,
            disk_free_bytes=usage.free,
            disk_total_bytes=usage.total,
        )

    @property
    def ready(self) -> bool:
        return self.blender_version is not None and bool(self.available_backends)
