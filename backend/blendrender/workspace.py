from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from .config import Settings
from .models import (
    TERMINAL_STATUSES,
    WORKSPACE_SCHEMA_VERSION,
    FrameGroup,
    FrameResult,
    FramesPage,
    Job,
    JobManifest,
    JobStatus,
    JobStatusSnapshot,
    NodeStatus,
    RenderConfig,
    Scene,
    SceneManifest,
    TelemetrySample,
    TelemetrySnapshot,
    UploadManifest,
    UploadStatus,
    WorkspaceManifest,
    utc_now,
)
from .project_archive import (
    ProjectArchiveCapacityError,
    ProjectArchiveError,
    extract_project_archive,
    inspect_project_archive,
)

T = TypeVar("T", bound=BaseModel)
NODE_ONLINE_FOR = timedelta(seconds=30)
LOCK_STALE_AFTER_SECONDS = 300
UPLOAD_TTL = timedelta(hours=24)
UPLOAD_CAPACITY_HEADROOM_BYTES = 1024**3


class WorkspaceError(RuntimeError):
    pass


class NotFoundError(WorkspaceError):
    pass


class ConflictError(WorkspaceError):
    pass


class WorkspaceStore:
    """A shared-volume catalog with one writer per mutable document."""

    def __init__(self, settings: Settings):
        self.settings = settings
        # A pod is the only writer for its own job status documents, but several
        # asyncio.to_thread calls can still overlap inside that one process.
        self._status_lock = threading.RLock()

    def initialize(self) -> None:
        root = self.settings.workspace_root
        root.mkdir(parents=True, exist_ok=True)
        for path in (
            self.settings.scenes_root,
            self.settings.jobs_root,
            self.settings.nodes_root,
            root / "staging",
            root / "locks" / "scenes",
            root / "locks" / "uploads",
            root / "tombstones" / "scenes",
            root / "trash",
        ):
            path.mkdir(parents=True, exist_ok=True)
        manifest_path = root / "workspace.json"
        if not manifest_path.exists():
            with suppress(FileExistsError):
                _atomic_write_model(
                    manifest_path,
                    WorkspaceManifest(created_at=utc_now()),
                    create_only=True,
                )
        manifest = _read_model(manifest_path, WorkspaceManifest)
        if manifest.schema_version != WORKSPACE_SCHEMA_VERSION:  # pragma: no cover - Literal guard
            raise WorkspaceError("Workspace schema version is not supported")

    def staging_path(self, identifier: str) -> Path:
        return self.settings.workspace_root / "staging" / identifier

    def upload_paths(self, upload_id: str, *, completed: bool = False) -> dict[str, Path]:
        _require_uuid(upload_id, "Upload")
        root = self.scene_paths(upload_id)["root"] if completed else self.staging_path(upload_id)
        return {
            "root": root,
            "manifest": root / "upload.json",
            "part": root / "upload.part",
            "source": root / "source",
        }

    def create_upload(self, upload: UploadManifest) -> UploadManifest:
        if upload.size_bytes > self.settings.max_upload_bytes:
            raise WorkspaceError("Upload exceeds the configured limit")
        with self.upload_admission_lock():
            self.cleanup_expired_uploads()
            available = shutil.disk_usage(self.settings.workspace_root).free
            reserved = self._reserved_upload_bytes()
            if available - reserved < upload.size_bytes + UPLOAD_CAPACITY_HEADROOM_BYTES:
                raise WorkspaceError("Insufficient disk space for the requested upload")
            paths = self.upload_paths(upload.id)
            try:
                paths["root"].mkdir(parents=True)
                _atomic_write_model(paths["manifest"], upload, create_only=True)
            except FileExistsError as exc:
                raise ConflictError("Upload already exists") from exc
        return upload

    def get_upload(self, upload_id: str) -> UploadManifest:
        paths = self.upload_paths(upload_id)
        if paths["manifest"].is_file():
            return _read_model_required(paths["manifest"], UploadManifest, "Upload")
        completed_paths = self.upload_paths(upload_id, completed=True)
        return _read_model_required(completed_paths["manifest"], UploadManifest, "Upload")

    def list_recoverable_uploads(self) -> list[str]:
        uploads: list[str] = []
        for root in _directory_children(self.settings.workspace_root / "staging"):
            try:
                upload = _read_model_required(root / "upload.json", UploadManifest, "Upload")
            except (WorkspaceError, ValidationError, OSError):
                continue
            if upload.status in {UploadStatus.FINALIZING, UploadStatus.COMPLETED}:
                uploads.append(upload.id)
        return uploads

    def cleanup_expired_uploads(self) -> None:
        cutoff = datetime.now(UTC) - UPLOAD_TTL
        for root in _directory_children(self.settings.workspace_root / "staging"):
            try:
                upload = _read_model_required(root / "upload.json", UploadManifest, "Upload")
                updated_at = datetime.fromisoformat(upload.updated_at).astimezone(UTC)
            except (WorkspaceError, ValidationError, OSError, ValueError):
                continue
            if updated_at > cutoff:
                continue
            try:
                with self.upload_lock(upload.id):
                    if root.exists():
                        shutil.rmtree(root)
            except ConflictError:
                continue

    def delete_upload(self, upload_id: str) -> None:
        with self.upload_lock(upload_id):
            paths = self.upload_paths(upload_id)
            upload = _read_model_required(paths["manifest"], UploadManifest, "Upload")
            if upload.status == UploadStatus.FINALIZING:
                raise ConflictError("The upload is being finalized")
            if upload.status == UploadStatus.COMPLETED:
                raise ConflictError("The upload has already created a scene")
            shutil.rmtree(paths["root"])

    def update_upload(self, upload_id: str, **values: Any) -> UploadManifest:
        paths = self.upload_paths(upload_id)
        upload = _read_model_required(paths["manifest"], UploadManifest, "Upload")
        now = datetime.now(UTC)
        updated = UploadManifest.model_validate(
            {
                **upload.model_dump(),
                **values,
                "updated_at": now.isoformat(),
                "expires_at": (now + UPLOAD_TTL).isoformat(),
            }
        )
        _atomic_write_model(paths["manifest"], updated)
        return updated

    def mark_upload_failed(self, upload_id: str, error: str) -> UploadManifest:
        with self.upload_lock(upload_id):
            return self.update_upload(upload_id, status=UploadStatus.FAILED, error=error)

    def prepare_upload_finalization(self, upload_id: str) -> tuple[UploadManifest, bool]:
        with self.upload_lock(upload_id):
            upload = self.get_upload(upload_id)
            if upload.status == UploadStatus.COMPLETED:
                return upload, False
            if upload.uploaded_bytes != upload.size_bytes:
                raise WorkspaceError("The upload is incomplete")
            if upload.status not in {
                UploadStatus.UPLOADING,
                UploadStatus.FAILED,
                UploadStatus.FINALIZING,
            }:
                raise ConflictError("The upload cannot be finalized")
            should_start = upload.status != UploadStatus.FINALIZING
            if should_start:
                upload = self.update_upload(upload_id, status=UploadStatus.FINALIZING, error=None)
            return upload, should_start

    def finalize_upload(self, upload_id: str) -> UploadManifest:
        with self.upload_lock(upload_id) as lock:
            upload = self.get_upload(upload_id)
            if upload.status == UploadStatus.COMPLETED:
                return self._publish_completed_upload(upload, self.upload_paths(upload_id))
            if upload.status != UploadStatus.FINALIZING:
                raise ConflictError("The upload is not ready to be finalized")
            paths = self.upload_paths(upload_id)
            source = paths["source"]
            part = paths["part"]
            if not part.is_file() and not source.is_dir():
                raise WorkspaceError("The uploaded file is unavailable")

            def heartbeat() -> None:
                os.utime(lock)

            if source.is_dir() and not part.exists():
                if upload.source_kind is None or upload.entrypoint is None:
                    raise WorkspaceError("The upload source is incomplete")
            else:
                shutil.rmtree(source, ignore_errors=True)
                suffix = Path(upload.filename).suffix.lower()
                if suffix == ".blend":
                    source.mkdir()
                    os.replace(part, source / "input.blend")
                    upload = self.update_upload(
                        upload_id,
                        source_kind="blend",
                        entrypoint="input.blend",
                    )
                elif suffix == ".zip":
                    manifest = inspect_project_archive(
                        part,
                        source,
                        self.settings.max_upload_bytes,
                        heartbeat,
                    )
                    if (
                        shutil.disk_usage(self.settings.workspace_root).free
                        < manifest.total_size + UPLOAD_CAPACITY_HEADROOM_BYTES
                    ):
                        raise ProjectArchiveCapacityError(
                            "Insufficient disk space to extract the uploaded ZIP archive"
                        )
                    extract_project_archive(
                        part,
                        source,
                        manifest,
                        self.settings.max_upload_bytes,
                        heartbeat,
                    )
                    part.unlink()
                    upload = self.update_upload(
                        upload_id,
                        source_kind="zip",
                        entrypoint=manifest.scene_relative_path.as_posix(),
                    )
                else:
                    raise ProjectArchiveError(
                        "Only .blend files and project ZIP archives are accepted"
                    )

            if upload.source_kind is None or upload.entrypoint is None:
                raise WorkspaceError("The upload source is incomplete")
            completed = self.update_upload(upload_id, status=UploadStatus.COMPLETED, error=None)
            return self._publish_completed_upload(completed, paths)

    def _publish_completed_upload(
        self, upload: UploadManifest, paths: dict[str, Path]
    ) -> UploadManifest:
        if upload.source_kind is None or upload.entrypoint is None:
            raise WorkspaceError("The upload source is incomplete")
        scene = SceneManifest(
            id=upload.id,
            filename=Path(upload.entrypoint).name,
            name=upload.name,
            source_kind=upload.source_kind,
            entrypoint=upload.entrypoint,
            created_at=upload.created_at,
            size_bytes=upload.size_bytes,
        )
        try:
            self.create_scene(scene, paths["root"])
        except ConflictError:
            if not self.scene_paths(upload.id)["root"].is_dir():
                raise
        return upload

    def _reserved_upload_bytes(self) -> int:
        reserved = 0
        for root in _directory_children(self.settings.workspace_root / "staging"):
            try:
                upload = _read_model_required(root / "upload.json", UploadManifest, "Upload")
            except (WorkspaceError, ValidationError, OSError):
                continue
            if upload.status == UploadStatus.UPLOADING:
                reserved += upload.size_bytes - upload.uploaded_bytes
        return reserved

    def scene_paths(self, scene_id: str) -> dict[str, Path]:
        _require_uuid(scene_id, "Scene")
        root = self.settings.scenes_root / scene_id
        return {
            "root": root,
            "manifest": root / "manifest.json",
            "source": root / "source",
            "results": root / "results",
        }

    def job_paths(self, job_id: str) -> dict[str, Path]:
        _require_uuid(job_id, "Job")
        root = self.settings.jobs_root / job_id
        return {
            "root": root,
            "manifest": root / "manifest.json",
            "status": root / "status.json",
            "config": root / "render-config.json",
            "log": root / "render.log",
            "pending": root / "pending",
        }

    def create_scene(self, scene: SceneManifest, staged_root: Path) -> Scene:
        paths = self.scene_paths(scene.id)
        if paths["root"].exists():
            raise ConflictError("Scene already exists")
        if not staged_root.is_dir() or not (staged_root / "source").is_dir():
            raise WorkspaceError("Scene upload staging directory is incomplete")
        _atomic_write_model(staged_root / "manifest.json", scene)
        try:
            os.replace(staged_root, paths["root"])
        except FileExistsError as exc:
            raise ConflictError("Scene already exists") from exc
        return Scene.model_validate(scene.model_dump())

    def get_scene(self, scene_id: str) -> Scene:
        paths = self.scene_paths(scene_id)
        manifest = _read_model_required(paths["manifest"], SceneManifest, "Scene")
        jobs = self.list_jobs(scene_id=scene_id)
        values = manifest.model_dump()
        values.update(job_count=len(jobs), result_count=len(self.list_results(scene_id)))
        return Scene.model_validate(values)

    def list_scenes(self) -> list[Scene]:
        scenes: list[Scene] = []
        for root in _directory_children(self.settings.scenes_root):
            try:
                scenes.append(self.get_scene(root.name))
            except (WorkspaceError, ValidationError, OSError):
                continue
        return sorted(scenes, key=lambda scene: scene.created_at, reverse=True)

    def scene_entrypoint(self, scene_id: str) -> tuple[Path, Path]:
        scene = self.get_scene(scene_id)
        paths = self.scene_paths(scene_id)
        relative = Path(scene.entrypoint)
        source = paths["source"].resolve()
        entrypoint = (source / relative).resolve()
        if not entrypoint.is_relative_to(source) or not entrypoint.is_file():
            raise WorkspaceError("Scene entrypoint is unavailable")
        return entrypoint, source

    def create_job(self, manifest: JobManifest) -> Job:
        paths = self.job_paths(manifest.id)
        self.get_scene(manifest.scene_id)
        with self.scene_lock(manifest.scene_id):
            if self.scene_tombstone(manifest.scene_id).exists():
                raise ConflictError("Scene is being deleted")
            paths["root"].mkdir(parents=True, exist_ok=False)
            _atomic_write_model(paths["manifest"], manifest)
            _atomic_write_model(paths["status"], JobStatusSnapshot(updated_at=utc_now()))
            paths["pending"].mkdir()
        return self.get_job(manifest.id)

    def get_job(self, job_id: str) -> Job:
        paths = self.job_paths(job_id)
        manifest = _read_model_required(paths["manifest"], JobManifest, "Job")
        snapshot = _read_model_required(paths["status"], JobStatusSnapshot, "Job status")
        return Job.model_validate(
            {
                **manifest.model_dump(),
                **snapshot.model_dump(),
                "owner_online": self.owner_online(manifest.owner_pod_id),
            }
        )

    def list_jobs(
        self,
        *,
        scene_id: str | None = None,
        status: JobStatus | None = None,
        owner_pod_id: str | None = None,
    ) -> list[Job]:
        jobs: list[Job] = []
        for root in _directory_children(self.settings.jobs_root):
            try:
                job = self.get_job(root.name)
            except (WorkspaceError, ValidationError, OSError):
                continue
            if scene_id is not None and job.scene_id != scene_id:
                continue
            if status is not None and job.status != status:
                continue
            if owner_pod_id is not None and job.owner_pod_id != owner_pod_id:
                continue
            jobs.append(job)
        return sorted(jobs, key=lambda job: job.created_at, reverse=True)

    def update_job(self, job_id: str, **values: Any) -> Job:
        with self._status_lock:
            job = self.get_job(job_id)
            snapshot = JobStatusSnapshot.model_validate(
                {
                    **job.model_dump(include=set(JobStatusSnapshot.model_fields)),
                    **values,
                    "updated_at": utc_now(),
                }
            )
            _atomic_write_model(self.job_paths(job_id)["status"], snapshot)
            return self.get_job(job_id)

    def next_queued_job(self, pod_id: str) -> Job | None:
        for job in sorted(
            self.list_jobs(owner_pod_id=pod_id), key=lambda candidate: candidate.created_at
        ):
            if job.status != JobStatus.QUEUED:
                continue
            return self.update_job(
                job.id,
                status=JobStatus.RUNNING,
                started_at=utc_now(),
                finished_at=None,
                error=None,
                cancel_requested=False,
                sample_current=None,
                sample_total=None,
            )
        return None

    def recover_owner_jobs(self, pod_id: str) -> None:
        for job in self.list_jobs(owner_pod_id=pod_id):
            if job.status == JobStatus.RUNNING:
                self.update_job(
                    job.id,
                    status=JobStatus.INTERRUPTED,
                    error="The application restarted while this render was running.",
                    finished_at=utc_now(),
                    cancel_requested=False,
                    current_frame=None,
                    sample_current=None,
                    sample_total=None,
                )

    def delete_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job.status not in TERMINAL_STATUSES:
            raise ConflictError("Cancel the job before deleting it")
        with self.scene_lock(job.scene_id):
            shutil.rmtree(self.job_paths(job_id)["root"])

    def delete_scene(self, scene_id: str) -> None:
        with self.scene_lock(scene_id):
            scene = self.get_scene(scene_id)
            tombstone = self.scene_tombstone(scene_id)
            _atomic_write_json(tombstone, {"scene_id": scene_id, "created_at": utc_now()})
            jobs = self.list_jobs(scene_id=scene_id)
            if any(job.status not in TERMINAL_STATUSES for job in jobs):
                tombstone.unlink(missing_ok=True)
                raise ConflictError("Cancel active scene jobs before deleting the scene")
            trash = self.settings.workspace_root / "trash" / f"{int(time.time())}-{scene.id}"
            trash.mkdir(parents=True, exist_ok=False)
            scene_root = self.scene_paths(scene_id)["root"]
            if scene_root.exists():
                os.replace(scene_root, trash / "scene")
            jobs_root = trash / "jobs"
            jobs_root.mkdir()
            for job in jobs:
                root = self.job_paths(job.id)["root"]
                if root.exists():
                    os.replace(root, jobs_root / job.id)

    def scene_tombstone(self, scene_id: str) -> Path:
        _require_uuid(scene_id, "Scene")
        return self.settings.workspace_root / "tombstones" / "scenes" / f"{scene_id}.json"

    @contextmanager
    def upload_lock(self, upload_id: str) -> Iterator[Path]:
        _require_uuid(upload_id, "Upload")
        path = self.settings.workspace_root / "locks" / "uploads" / upload_id
        with self._directory_lock(path, "Upload is busy"):
            yield path

    @contextmanager
    def upload_admission_lock(self) -> Iterator[None]:
        path = self.settings.workspace_root / "locks" / "uploads" / "admission"
        with self._directory_lock(path, "Another upload is being prepared"):
            yield

    @contextmanager
    def _directory_lock(self, path: Path, conflict_message: str) -> Iterator[None]:
        for _ in range(100):
            try:
                path.mkdir()
                break
            except FileExistsError:
                try:
                    age = time.time() - path.stat().st_mtime
                    if age > LOCK_STALE_AFTER_SECONDS:
                        path.rmdir()
                        continue
                except (FileNotFoundError, OSError):
                    continue
                time.sleep(0.05)
        else:
            raise ConflictError(conflict_message)
        try:
            yield
        finally:
            with suppress(FileNotFoundError):
                path.rmdir()

    @contextmanager
    def scene_lock(self, scene_id: str) -> Iterator[None]:
        _require_uuid(scene_id, "Scene")
        path = self.settings.workspace_root / "locks" / "scenes" / scene_id
        with self._directory_lock(path, "Scene is busy"):
            yield

    def result_paths(self, scene_id: str, frame: int, result_id: str) -> dict[str, Path]:
        _require_uuid(scene_id, "Scene")
        _require_uuid(result_id, "Result")
        root = self.scene_paths(scene_id)["results"] / f"{frame:06d}" / result_id
        return {
            "root": root,
            "image": root / "frame.png",
            "preview": root / "preview.webp",
            "metadata": root / "metadata.json",
        }

    def publish_result(self, result: FrameResult, pending: Path) -> FrameResult:
        paths = self.result_paths(result.scene_id, result.frame, result.id)
        if paths["root"].exists():
            return _read_model_required(paths["metadata"], FrameResult, "Result")
        if not (pending / "frame.png").is_file() or not (pending / "preview.webp").is_file():
            raise WorkspaceError("Result staging files are incomplete")
        _atomic_write_model(pending / "metadata.json", result)
        paths["root"].parent.mkdir(parents=True, exist_ok=True)
        os.replace(pending, paths["root"])
        return result

    def write_render_config(self, job_id: str, config: RenderConfig) -> None:
        _atomic_write_model(self.job_paths(job_id)["config"], config)

    def list_results(self, scene_id: str, *, frame: int | None = None) -> list[FrameResult]:
        base = self.scene_paths(scene_id)["results"]
        if not base.is_dir():
            return []
        frame_roots = [base / f"{frame:06d}"] if frame is not None else _directory_children(base)
        results: list[FrameResult] = []
        for frame_root in frame_roots:
            for root in _directory_children(frame_root):
                try:
                    results.append(
                        _read_model_required(root / "metadata.json", FrameResult, "Result")
                    )
                except (WorkspaceError, ValidationError, OSError):
                    continue
        return sorted(results, key=lambda result: (result.frame, result.completed_at), reverse=True)

    def list_frame_groups(self, scene_id: str, cursor: int | None, limit: int) -> FramesPage:
        base = self.scene_paths(scene_id)["results"]
        frame_roots = sorted(
            (
                (int(root.name), root)
                for root in _directory_children(base)
                if root.name.isdecimal() and _directory_children(root)
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        if cursor is not None:
            frame_roots = [item for item in frame_roots if item[0] < cursor]
        page_roots = frame_roots[:limit]
        next_cursor = page_roots[-1][0] if len(frame_roots) > limit else None
        return FramesPage(
            items=[
                FrameGroup(frame=frame, results=self.list_results(scene_id, frame=frame))
                for frame, _ in page_roots
            ],
            next_cursor=next_cursor,
        )

    def results_for_job(self, job_id: str) -> list[FrameResult]:
        job = self.get_job(job_id)
        return [result for result in self.list_results(job.scene_id) if result.job_id == job_id]

    def write_node_status(self, status: NodeStatus) -> None:
        root = self.settings.nodes_root / status.pod_id
        root.mkdir(parents=True, exist_ok=True)
        _atomic_write_model(root / "status.json", status)

    def write_telemetry(self, pod_id: str, samples: Sequence[TelemetrySample]) -> None:
        root = self.settings.nodes_root / pod_id
        root.mkdir(parents=True, exist_ok=True)
        _atomic_write_model(root / "telemetry.json", TelemetrySnapshot(samples=list(samples)))

    def read_telemetry(self, pod_id: str) -> list[TelemetrySample]:
        path = self.settings.nodes_root / pod_id / "telemetry.json"
        try:
            return _read_model(path, TelemetrySnapshot).samples
        except (WorkspaceError, OSError, ValidationError):
            return []

    def read_node_status(self, pod_id: str) -> NodeStatus | None:
        try:
            return _read_model(self.settings.nodes_root / pod_id / "status.json", NodeStatus)
        except (WorkspaceError, ValidationError, OSError):
            return None

    def owner_online(self, pod_id: str) -> bool:
        status = self.read_node_status(pod_id)
        if status is None:
            return False
        try:
            seen = datetime.fromisoformat(status.last_seen).astimezone(UTC)
        except ValueError:
            return False
        return datetime.now(UTC) - seen <= NODE_ONLINE_FOR


def _read_model(path: Path, model: type[T]) -> T:  # noqa: UP047
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceError(f"Unable to read {path.name}") from exc
    return model.model_validate(payload)


def _read_model_required(path: Path, model: type[T], name: str) -> T:  # noqa: UP047
    if not path.is_file():
        raise NotFoundError(f"{name} not found")
    return _read_model(path, model)


def _atomic_write_model(path: Path, model: BaseModel, *, create_only: bool = False) -> None:
    _atomic_write_json(path, model.model_dump(mode="json"), create_only=create_only)


def _atomic_write_json(path: Path, payload: dict[str, Any], *, create_only: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if create_only:
        with path.open("x", encoding="utf-8") as destination:
            destination.write(content)
            destination.flush()
            os.fsync(destination.fileno())
        return
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as destination:
            destination.write(content)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _directory_children(path: Path) -> list[Path]:
    if not path.is_dir():
        return []
    return [child for child in path.iterdir() if child.is_dir()]


def _require_uuid(value: str, name: str) -> None:
    try:
        uuid.UUID(value)
    except ValueError as exc:
        raise NotFoundError(f"{name} not found") from exc
