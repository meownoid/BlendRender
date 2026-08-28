from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    INTERRUPTED = "interrupted"


class Backend(StrEnum):
    OPTIX = "OPTIX"
    CUDA = "CUDA"


TERMINAL_STATUSES = {
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.CANCELED,
    JobStatus.INTERRUPTED,
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Job(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    status: JobStatus
    mode: Literal["still", "range"]
    frame_start: int
    frame_end: int
    backend: Backend
    progress: float = Field(ge=0, le=100)
    current_frame: int | None = None
    completed_frames: list[int] = Field(default_factory=list)
    error: str | None = None
    log_tail: str = ""
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_seconds: float = 0
    eta_seconds: float | None = None
    cancel_requested: bool = False

    @property
    def total_frames(self) -> int:
        return self.frame_end - self.frame_start + 1


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class SessionResponse(BaseModel):
    authenticated: bool


class ArchiveRequest(BaseModel):
    frames: list[int] | None = None


class GPUInfo(BaseModel):
    name: str
    utilization: int = Field(ge=0, le=100)
    memory_used_mb: int = Field(ge=0)
    memory_total_mb: int = Field(ge=0)


class SystemInfo(BaseModel):
    blender_version: str | None
    gpus: list[GPUInfo]
    available_backends: list[Backend]
    disk_free_bytes: int
    disk_total_bytes: int

