from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("APP_PASSWORD", "test-password")
os.environ.setdefault("COOKIE_SECURE", "false")

from blendrender.config import Settings  # noqa: E402


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        app_password="test-password",
        data_root=tmp_path / "data",
        blender_bin=Path("/usr/bin/true"),
        renderer_script=tmp_path / "render.py",
        frontend_dist=tmp_path / "dist",
        max_upload_bytes=1024 * 1024,
        cookie_secure=False,
        session_ttl_seconds=3600,
        cancel_grace_seconds=0.1,
        available_backends_override=("OPTIX", "CUDA", "CPU"),
    )
