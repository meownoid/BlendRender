from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from blendrender.worker import frame_filename
from PIL import Image


def test_blender_driver_renders_tiny_scene_and_preserves_settings(tmp_path: Path) -> None:
    blender = os.getenv("BLENDER_BIN") or shutil.which("blender")
    if blender is None:
        pytest.skip("Blender is not installed")

    project_root = tmp_path / "project"
    scene_path = project_root / "scenes" / "smoke.blend"
    texture_path = project_root / "textures" / "albedo.png"
    output_dir = tmp_path / "outputs"
    report_path = tmp_path / "report.json"
    generator = tmp_path / "create_scene.py"
    scene_path.parent.mkdir(parents=True)
    texture_path.parent.mkdir(parents=True)
    Image.new("RGB", (2, 2), (240, 60, 40)).save(texture_path, "PNG")
    generator.write_text(
        """
import bpy
import math
import sys

scene = bpy.context.scene
scene.render.resolution_x = 32
scene.render.resolution_y = 24
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "JPEG"
scene.cycles.samples = 1
scene.cycles.use_denoising = False
scene.use_nodes = True

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))
cube = bpy.context.object
bpy.ops.object.camera_add(location=(4, -4, 3), rotation=(math.radians(67), 0, math.radians(46)))
scene.camera = bpy.context.object
scene.camera.name = "SmokeCamera"
bpy.ops.object.light_add(type="AREA", location=(2, -2, 4))
bpy.context.object.data.energy = 800
bpy.context.object.data.shape = "DISK"
bpy.context.object.data.size = 5
arguments = sys.argv[sys.argv.index("--") + 1:]
image = bpy.data.images.load(arguments[0])
image.name = "Albedo"
image.filepath = "//../textures/albedo.png"
material = bpy.data.materials.new("SmokeMaterial")
material.use_nodes = True
texture_node = material.node_tree.nodes.new("ShaderNodeTexImage")
texture_node.image = image
cube.data.materials.append(material)
bpy.ops.wm.save_as_mainfile(filepath=arguments[1])
""",
        encoding="utf-8",
    )
    subprocess.run(
        [
            blender,
            "--background",
            "--factory-startup",
            "--python",
            str(generator),
            "--",
            str(texture_path),
            str(scene_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )

    config_path = tmp_path / "render-config.json"
    config_path.write_text(
        json.dumps(
            {
                "backend": "CPU",
                "frames": [1],
                "output_dir": str(output_dir),
                "project_root": str(project_root),
                "diagnostic_report": str(report_path),
            }
        ),
        encoding="utf-8",
    )
    renderer = Path(__file__).resolve().parents[1] / "renderer" / "blendrender_render.py"
    completed = subprocess.run(
        [
            blender,
            "--background",
            "--disable-autoexec",
            "--python-exit-code",
            "1",
            str(scene_path),
            "--python",
            str(renderer),
            "--",
            str(config_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert 'BLENDRENDER_EVENT {"type": "frame_started", "frame": 1}' in completed.stdout
    assert 'BLENDRENDER_EVENT {"type": "frame_progress", "frame": 1' in completed.stdout
    assert 'BLENDRENDER_EVENT {"type": "frame_completed", "frame": 1' in completed.stdout
    output = output_dir / frame_filename(1)
    with Image.open(output) as image:
        assert image.format == "PNG"
        assert image.size == (32, 24)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report == {
        "camera": "SmokeCamera",
        "resolution_x": 32,
        "resolution_y": 24,
        "resolution_percentage": 100,
        "samples": 1,
        "denoising": False,
        "view_transform": "None",
        "compositor_nodes": True,
        "engine": "CYCLES",
        "file_format": "PNG",
    }

    outside_texture = tmp_path / "outside.png"
    Image.new("RGB", (2, 2), (20, 40, 220)).save(outside_texture, "PNG")
    rewrite = tmp_path / "rewrite_asset_path.py"
    rewrite.write_text(
        """
import bpy
import sys

bpy.data.images["Albedo"].filepath = sys.argv[sys.argv.index("--") + 1]
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
""",
        encoding="utf-8",
    )
    subprocess.run(
        [
            blender,
            "--background",
            "--disable-autoexec",
            str(scene_path),
            "--python",
            str(rewrite),
            "--",
            str(outside_texture),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    rejected = subprocess.run(
        [
            blender,
            "--background",
            "--disable-autoexec",
            "--python-exit-code",
            "1",
            str(scene_path),
            "--python",
            str(renderer),
            "--",
            str(config_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert rejected.returncode != 0
    assert "image uses an absolute path" in rejected.stdout
