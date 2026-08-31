from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("APP_PASSWORD", "test-password")
os.environ.setdefault("COOKIE_SECURE", "false")

from blendrender.config import Settings  # noqa: E402


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    blender_bin = tmp_path / "blender"
    blender_bin.write_text("#!/bin/sh\nprintf 'Blender 5.2.1\\n'\n", encoding="utf-8")
    blender_bin.chmod(0o755)
    return Settings(
        app_password="test-password",
        workspace_root=tmp_path / "workspace",
        pod_id="pod-a",
        blender_bin=blender_bin,
        renderer_script=tmp_path / "render.py",
        frontend_dist=tmp_path / "dist",
        max_upload_bytes=1024 * 1024,
        upload_chunk_bytes=8 * 1024 * 1024,
        cookie_secure=False,
        session_ttl_seconds=3600,
        cancel_grace_seconds=0.1,
        available_backends_override=("OPTIX", "CUDA", "CPU"),
    )
