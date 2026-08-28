from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    app_password: str
    data_root: Path
    blender_bin: Path
    renderer_script: Path
    frontend_dist: Path
    max_upload_bytes: int
    cookie_secure: bool
    session_ttl_seconds: int
    cancel_grace_seconds: float
    available_backends_override: tuple[str, ...]

    @classmethod
    def from_env(cls) -> Settings:
        password = os.getenv("APP_PASSWORD", "")
        if not password:
            raise RuntimeError("APP_PASSWORD is required and must not be empty")

        project_root = Path(__file__).resolve().parents[2]
        override = tuple(
            item.strip().upper()
            for item in os.getenv("AVAILABLE_BACKENDS", "").split(",")
            if item.strip().upper() in {"OPTIX", "CUDA"}
        )
        return cls(
            app_password=password,
            data_root=Path(os.getenv("DATA_ROOT", "/var/lib/blendqueue")).resolve(),
            blender_bin=Path(os.getenv("BLENDER_BIN", "/opt/blender/blender")),
            renderer_script=Path(
                os.getenv("RENDERER_SCRIPT", str(project_root / "renderer/blendqueue_render.py"))
            ).resolve(),
            frontend_dist=Path(
                os.getenv("FRONTEND_DIST", str(project_root / "frontend/dist"))
            ).resolve(),
            max_upload_bytes=int(float(os.getenv("MAX_UPLOAD_GB", "5")) * 1024**3),
            cookie_secure=_bool_env("COOKIE_SECURE", True),
            session_ttl_seconds=int(os.getenv("SESSION_TTL_SECONDS", str(7 * 24 * 3600))),
            cancel_grace_seconds=float(os.getenv("CANCEL_GRACE_SECONDS", "8")),
            available_backends_override=override,
        )

    @property
    def database_path(self) -> Path:
        return self.data_root / "blendqueue.sqlite3"

    @property
    def jobs_root(self) -> Path:
        return self.data_root / "jobs"

