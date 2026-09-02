from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from blendrender.worker import append_log_tail, blender_command


def test_append_log_tail_retains_the_latest_120_lines() -> None:
    log_tail = ""
    for line_number in range(1, 122):
        log_tail = append_log_tail(log_tail, f"line {line_number}\n")

    assert log_tail.splitlines() == [f"line {line_number}" for line_number in range(2, 122)]


def test_blender_command_omits_flip_fluids_bootstrap_when_disabled(settings) -> None:
    command = blender_command(settings, Path("/scene.blend"), Path("/render-config.json"))

    assert command == [
        str(settings.blender_bin),
        "--background",
        "--disable-autoexec",
        "--python-exit-code",
        "1",
        "/scene.blend",
        "--python",
        str(settings.renderer_script),
        "--",
        "/render-config.json",
    ]


def test_blender_command_runs_flip_fluids_bootstrap_before_opening_scene(settings) -> None:
    bootstrap = Path("/renderer/blendrender_enable_flip_fluids.py")
    configured = replace(
        settings,
        flip_fluids_addon="flip_fluids_addon",
        flip_fluids_bootstrap_script=bootstrap,
    )

    command = blender_command(configured, Path("/scene.blend"), Path("/render-config.json"))

    assert command[5:8] == ["--python", str(bootstrap), "/scene.blend"]
