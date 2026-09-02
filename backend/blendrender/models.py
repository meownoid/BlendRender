from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

WORKSPACE_SCHEMA_VERSION: Final = 2


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    INTERRUPTED = "interrupted"


class UploadStatus(StrEnum):
    UPLOADING = "uploading"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"


class Backend(StrEnum):
    OPTIX = "OPTIX"
    CUDA = "CUDA"
    CPU = "CPU"


TERMINAL_STATUSES = {
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.CANCELED,
    JobStatus.INTERRUPTED,
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class WorkspaceManifest(BaseModel):
    schema_version: Literal[2] = WORKSPACE_SCHEMA_VERSION
    created_at: str


class Scene(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    name: str = ""
    source_kind: Literal["blend", "zip"]
    entrypoint: str
    created_at: str
    size_bytes: int = Field(ge=0)
    job_count: int = Field(default=0, ge=0)
    result_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def use_filename_as_legacy_name(self) -> Self:
        if not self.name:
            self.name = self.filename
        return self


class SceneManifest(Scene):
    schema_version: Literal[2] = WORKSPACE_SCHEMA_VERSION
    job_count: int = 0
    result_count: int = 0


class CreateUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    name: str | None = Field(default=None, max_length=512)
    size_bytes: int = Field(gt=0)


class UploadManifest(BaseModel):
    """Durable state for an upload while it lives in staging or its completed scene."""

    schema_version: Literal[2] = WORKSPACE_SCHEMA_VERSION
    id: str
    filename: str
    name: str
    size_bytes: int = Field(gt=0)
    uploaded_bytes: int = Field(default=0, ge=0)
    status: UploadStatus = UploadStatus.UPLOADING
    created_at: str
    updated_at: str
    expires_at: str
    error: str | None = None
    source_kind: Literal["blend", "zip"] | None = None
    entrypoint: str | None = None


class UploadSession(UploadManifest):
    chunk_size_bytes: int = Field(gt=0)
    scene: Scene | None = None


class CreateJobRequest(BaseModel):
    scene_id: str
    mode: Literal["still", "range"]
    backend: Backend
    frame: int | None = None
    start: int | None = None
    end: int | None = None
    samples: int | None = Field(default=None, ge=1, le=1_000_000)
    tile_size: int | None = Field(default=None, ge=8, le=8_192)
    resolution_x: int | None = Field(default=None, ge=4, le=65_536)
    resolution_y: int | None = Field(default=None, ge=4, le=65_536)
    resolution_percentage: int | None = Field(default=None, ge=1, le=100)

    def frame_bounds(self) -> tuple[int, int]:
        if self.mode == "still":
            if self.frame is None:
                raise ValueError("A frame is required for a still render")
            return self.frame, self.frame
        if self.start is None or self.end is None:
            raise ValueError("Start and end frames are required")
        if self.start > self.end:
            raise ValueError("Start frame must not exceed end frame")
        return self.start, self.end

    def validate_render_settings(self) -> tuple[int, int]:
        start, end = self.frame_bounds()
        if end - start + 1 > 100_000:
            raise ValueError("Frame range is too large")
        if (self.resolution_x is None) != (self.resolution_y is None):
            raise ValueError("Resolution width and height must be provided together")
        return start, end


class JobManifest(BaseModel):
    schema_version: Literal[2] = WORKSPACE_SCHEMA_VERSION
    id: str
    scene_id: str
    filename: str
    owner_pod_id: str
    mode: Literal["still", "range"]
    frame_start: int
    frame_end: int
    backend: Backend
    samples: int | None = None
    tile_size: int | None = None
    resolution_x: int | None = None
    resolution_y: int | None = None
    resolution_percentage: int | None = None
    created_at: str


class JobStatusSnapshot(BaseModel):
    schema_version: Literal[2] = WORKSPACE_SCHEMA_VERSION
    status: JobStatus = JobStatus.QUEUED
    progress: float = Field(default=0, ge=0, le=100)
    current_frame: int | None = None
    sample_current: int | None = Field(default=None, ge=0)
    sample_total: int | None = Field(default=None, gt=0)
    completed_frames: list[int] = Field(default_factory=list)
    error: str | None = None
    log_tail: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_seconds: float = Field(default=0, ge=0)
    eta_seconds: float | None = Field(default=None, ge=0)
    cancel_requested: bool = False
    updated_at: str


class Job(JobManifest, JobStatusSnapshot):
    owner_online: bool = False

    @property
    def total_frames(self) -> int:
        return self.frame_end - self.frame_start + 1


class FrameResult(BaseModel):
    schema_version: Literal[2] = WORKSPACE_SCHEMA_VERSION
    id: str
    scene_id: str
    job_id: str
    frame: int
    pod_id: str
    backend: Backend
    hardware: list[str] = Field(default_factory=list)
    samples: int = Field(ge=1)
    render_seconds: float = Field(ge=0)
    completed_at: str


class RenderConfig(BaseModel):
    schema_version: Literal[2] = WORKSPACE_SCHEMA_VERSION
    backend: Backend
    frames: list[int] = Field(min_length=1)
    output_dir: str
    project_root: str
    samples: int | None = Field(default=None, ge=1, le=1_000_000)
    tile_size: int | None = Field(default=None, ge=8, le=8_192)
    resolution_x: int | None = Field(default=None, ge=4, le=65_536)
    resolution_y: int | None = Field(default=None, ge=4, le=65_536)
    resolution_percentage: int | None = Field(default=None, ge=1, le=100)


class FrameGroup(BaseModel):
    frame: int
    results: list[FrameResult]


class FramesPage(BaseModel):
    items: list[FrameGroup]
    next_cursor: int | None = None


class NodeStatus(BaseModel):
    schema_version: Literal[2] = WORKSPACE_SCHEMA_VERSION
    pod_id: str
    available_backends: list[Backend]
    hardware: list[str]
    last_seen: str


class TelemetrySample(BaseModel):
    captured_at: str
    cpu_utilization: float = Field(ge=0, le=100)
    gpu_utilization: float | None = Field(default=None, ge=0, le=100)
    memory_used_bytes: int = Field(ge=0)
    memory_total_bytes: int = Field(gt=0)
    vram_used_mb: int | None = Field(default=None, ge=0)
    vram_total_mb: int | None = Field(default=None, ge=0)


class TelemetrySnapshot(BaseModel):
    schema_version: Literal[2] = WORKSPACE_SCHEMA_VERSION
    samples: list[TelemetrySample]


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class SessionResponse(BaseModel):
    authenticated: bool


class ArchiveRequest(BaseModel):
    result_ids: list[str] | None = None


class ArchiveDownload(BaseModel):
    download_url: str


class GPUInfo(BaseModel):
    name: str
    utilization: int = Field(ge=0, le=100)
    memory_used_mb: int = Field(ge=0)
    memory_total_mb: int = Field(ge=0)


class SystemInfo(BaseModel):
    pod_id: str
    blender_version: str | None
    gpus: list[GPUInfo]
    available_backends: list[Backend]
    cpu_utilization: float = Field(ge=0, le=100)
    memory_used_bytes: int = Field(ge=0)
    memory_total_bytes: int = Field(gt=0)
    disk_free_bytes: int
    disk_total_bytes: int
