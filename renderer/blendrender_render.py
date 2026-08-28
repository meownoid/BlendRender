"""Executed inside Blender to configure and render a BlendRender job."""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

import bpy

PREFIX = "BLENDRENDER_EVENT "


def emit(event_type: str, **payload: object) -> None:
    print(PREFIX + json.dumps({"type": event_type, **payload}), flush=True)


def config_path() -> Path:
    if "--" not in sys.argv:
        raise RuntimeError("Missing BlendRender render configuration")
    arguments = sys.argv[sys.argv.index("--") + 1 :]
    if len(arguments) != 1:
        raise RuntimeError("Expected exactly one render configuration path")
    return Path(arguments[0]).resolve()


def missing_external_assets() -> list[str]:
    missing: list[str] = []
    for image in bpy.data.images:
        if image.source == "FILE" and not image.packed_file and image.filepath:
            path = bpy.path.abspath(image.filepath)
            if not os.path.exists(path):
                missing.append(path)
    for library in bpy.data.libraries:
        path = bpy.path.abspath(library.filepath)
        if path and not os.path.exists(path):
            missing.append(path)
    for sound in bpy.data.sounds:
        if not sound.packed_file and sound.filepath:
            path = bpy.path.abspath(sound.filepath)
            if not os.path.exists(path):
                missing.append(path)
    return sorted(set(missing))


def enable_backend(backend: str) -> list[str]:
    preferences = bpy.context.preferences.addons["cycles"].preferences
    preferences.compute_device_type = backend
    preferences.get_devices()
    enabled: list[str] = []
    for device in preferences.devices:
        device.use = device.type == backend
        if device.use:
            enabled.append(device.name)
    if not enabled:
        raise RuntimeError(f"No {backend} render device is available")
    return enabled


def run() -> None:
    config = json.loads(config_path().read_text(encoding="utf-8"))
    backend = str(config["backend"])
    frames = [int(frame) for frame in config["frames"]]
    output_dir = Path(config["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    scene = bpy.context.scene
    if scene.camera is None:
        raise RuntimeError("The active scene does not have an active camera")
    missing = missing_external_assets()
    if missing:
        sample = ", ".join(missing[:5])
        suffix = "" if len(missing) <= 5 else f" and {len(missing) - 5} more"
        raise RuntimeError(f"Project contains missing unpacked assets: {sample}{suffix}")

    cpu_render = backend == "CPU"
    devices = ["CPU"] if cpu_render else enable_backend(backend)
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU" if cpu_render else "GPU"
    if "samples" in config:
        scene.cycles.samples = int(config["samples"])
    if "resolution_x" in config:
        scene.render.resolution_x = int(config["resolution_x"])
    if "resolution_y" in config:
        scene.render.resolution_y = int(config["resolution_y"])
    if "resolution_percentage" in config:
        scene.render.resolution_percentage = int(config["resolution_percentage"])
    scene.render.image_settings.file_format = "PNG"
    scene.render.use_file_extension = True
    emit("job_started", backend=backend, devices=devices, frame_count=len(frames))

    for frame in frames:
        started = time.monotonic()
        scene.frame_set(frame)
        scene.render.filepath = str(output_dir / f"frame_{frame:06d}.png")
        emit("frame_started", frame=frame)
        bpy.ops.render.render(write_still=True)
        emit("frame_completed", frame=frame, seconds=time.monotonic() - started)
    if report_path := config.get("diagnostic_report"):
        Path(str(report_path)).write_text(
            json.dumps(
                {
                    "camera": scene.camera.name,
                    "resolution_x": scene.render.resolution_x,
                    "resolution_y": scene.render.resolution_y,
                    "resolution_percentage": scene.render.resolution_percentage,
                    "samples": scene.cycles.samples,
                    "denoising": scene.cycles.use_denoising,
                    "view_transform": scene.view_settings.look,
                    "compositor_nodes": scene.use_nodes,
                    "engine": scene.render.engine,
                    "file_format": scene.render.image_settings.file_format,
                }
            ),
            encoding="utf-8",
        )
    emit("job_completed", rendered_frames=frames)


try:
    run()
except Exception as exc:
    emit("error", message=str(exc))
    traceback.print_exc()
    raise
