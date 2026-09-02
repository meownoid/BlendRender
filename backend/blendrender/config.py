from __future__ import annotations

import os
import re
import socket
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _positive_integer_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive whole number") from exc
    if parsed <= 0:
        raise RuntimeError(f"{name} must be a positive whole number")
    return parsed


@dataclass(frozen=True, slots=True)
class Settings:
    app_password: str
    workspace_root: Path
    pod_id: str
    blender_bin: Path
    renderer_script: Path
    frontend_dist: Path
    max_upload_bytes: int
    upload_chunk_bytes: int
    cookie_secure: bool
    session_ttl_seconds: int
    cancel_grace_seconds: float
    available_backends_override: tuple[str, ...]
    flip_fluids_addon: str | None = None
    flip_fluids_bootstrap_script: Path | None = None

    @classmethod
    def from_env(cls) -> Settings:
        password = os.getenv("APP_PASSWORD", "")
        if not password:
            raise RuntimeError("APP_PASSWORD is required and must not be empty")

        project_root = Path(__file__).resolve().parents[2]
        override = tuple(
            item.strip().upper()
            for item in os.getenv("AVAILABLE_BACKENDS", "").split(",")
            if item.strip().upper() in {"OPTIX", "CUDA", "CPU"}
        )
        flip_fluids_addon = _addon_module_env("FLIP_FLUIDS_ADDON")
        return cls(
            app_password=password,
            workspace_root=Path(
                os.getenv("WORKSPACE_ROOT", "/workspace/blendrender")
            ).resolve(),
            pod_id=_pod_id(),
            blender_bin=Path(os.getenv("BLENDER_BIN", "/opt/blender/blender")),
            renderer_script=Path(
                os.getenv("RENDERER_SCRIPT", str(project_root / "renderer/blendrender_render.py"))
            ).resolve(),
            frontend_dist=Path(
                os.getenv("FRONTEND_DIST", str(project_root / "frontend/dist"))
            ).resolve(),
            max_upload_bytes=int(float(os.getenv("MAX_UPLOAD_GB", "20")) * 1024**3),
            upload_chunk_bytes=_positive_integer_env("UPLOAD_CHUNK_MB", 32) * 1024**2,
            cookie_secure=_bool_env("COOKIE_SECURE", True),
            session_ttl_seconds=int(os.getenv("SESSION_TTL_SECONDS", str(7 * 24 * 3600))),
            cancel_grace_seconds=float(os.getenv("CANCEL_GRACE_SECONDS", "8")),
            available_backends_override=override,
            flip_fluids_addon=flip_fluids_addon,
            flip_fluids_bootstrap_script=(
                Path(
                    os.getenv(
                        "FLIP_FLUIDS_BOOTSTRAP_SCRIPT",
                        str(project_root / "renderer/blendrender_enable_flip_fluids.py"),
                    )
                ).resolve()
                if flip_fluids_addon is not None
                else None
            ),
        )

    @property
    def scenes_root(self) -> Path:
        return self.workspace_root / "scenes"

    @property
    def jobs_root(self) -> Path:
        return self.workspace_root / "jobs"

    @property
    def nodes_root(self) -> Path:
        return self.workspace_root / "nodes"


def _pod_id() -> str:
    configured = os.getenv("BLENDRENDER_POD_ID") or os.getenv("RUNPOD_POD_ID")
    value = (configured or re.sub(r"[^A-Za-z0-9_-]", "-", socket.gethostname())).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise RuntimeError(
            "BLENDRENDER_POD_ID must contain only letters, digits, underscores, or hyphens"
        )
    return value


def _addon_module_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise RuntimeError(f"{name} must be a valid Python module name")
    return value
