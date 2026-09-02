"""Inspect and download completed BlendRender scenes through RunPod's S3-compatible API."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .models import TERMINAL_STATUSES, FrameResult, JobManifest, JobStatusSnapshot, SceneManifest
from .runpod_scene import ObjectUploader, RunpodS3Settings, RunpodScenePreparationError


@dataclass(frozen=True, slots=True)
class ResultFile:
    """One published file belonging to a rendered result package."""

    key: PurePosixPath
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ResultPackage:
    """A result record and the complete file package published for it."""

    result: FrameResult
    files: tuple[ResultFile, ...]


@dataclass(frozen=True, slots=True)
class CatalogJob:
    """A job manifest with its optional mutable status snapshot."""

    manifest: JobManifest
    status: JobStatusSnapshot | None


@dataclass(frozen=True, slots=True)
class CatalogScene:
    """The jobs and result packages associated with one completed scene."""

    manifest: SceneManifest
    jobs: tuple[CatalogJob, ...]
    results: tuple[ResultPackage, ...]


@dataclass(frozen=True, slots=True)
class DownloadSummary:
    """The completed local result download."""

    file_count: int
    size_bytes: int


@dataclass(frozen=True, slots=True)
class DeletionSummary:
    """The objects removed for one kind of catalog entry."""

    entity_kind: str
    entity_count: int
    object_count: int


def list_scenes(
    uploader: ObjectUploader,
    settings: RunpodS3Settings,
    *,
    scene_id: str | None = None,
) -> tuple[CatalogScene, ...]:
    """Read completed scenes, their jobs, and their published result packages."""

    uploader.ensure_volume()
    scenes_root = settings.workspace_prefix / "scenes"
    scene_objects = uploader.list_object_sizes(scenes_root)
    scene_manifests = _read_scene_manifests(uploader, scenes_root, scene_objects)
    if scene_id is not None:
        scene_manifests = tuple(scene for scene in scene_manifests if scene.id == scene_id)
        if not scene_manifests:
            raise RunpodScenePreparationError(f"Completed scene {scene_id} was not found")
    selected_ids = {scene.id for scene in scene_manifests}

    jobs_by_scene = _read_jobs(
        uploader,
        settings.workspace_prefix / "jobs",
        selected_ids,
    )
    results_by_scene = _read_results(
        uploader,
        scenes_root,
        scene_objects,
        selected_ids,
    )
    return tuple(
        CatalogScene(
            manifest=scene,
            jobs=jobs_by_scene.get(scene.id, ()),
            results=results_by_scene.get(scene.id, ()),
        )
        for scene in scene_manifests
    )


def download_results(
    uploader: ObjectUploader,
    settings: RunpodS3Settings,
    scenes: tuple[CatalogScene, ...],
    destination: Path,
) -> DownloadSummary:
    """Download complete published result packages without overwriting local files."""

    if destination.exists():
        if not destination.is_dir():
            raise RunpodScenePreparationError(
                f"Download destination {destination} is not a directory"
            )
        if any(destination.iterdir()):
            raise RunpodScenePreparationError(
                f"Refusing to write downloads into non-empty directory {destination}"
            )
    destination.mkdir(parents=True, exist_ok=True)

    source_root = settings.workspace_prefix / "scenes"
    downloads = tuple(
        (
            result_file,
            _download_destination(destination, source_root, scene.manifest.id, result_file.key),
        )
        for scene in scenes
        for result in scene.results
        for result_file in result.files
    )
    if not downloads:
        return DownloadSummary(file_count=0, size_bytes=0)

    worker_count = min(uploader.upload_workers, len(downloads))
    downloaded_size = 0
    in_flight: set[Future[int]] = set()
    remaining = iter(downloads)
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        for _ in range(worker_count):
            result_file, output_path = next(remaining)
            in_flight.add(executor.submit(uploader.download_file, result_file.key, output_path))

        try:
            while in_flight:
                completed, pending = wait(in_flight, return_when=FIRST_COMPLETED)
                in_flight = set(pending)
                for future in completed:
                    downloaded_size += future.result()
                for _ in completed:
                    next_download = next(remaining, None)
                    if next_download is not None:
                        result_file, output_path = next_download
                        in_flight.add(
                            executor.submit(uploader.download_file, result_file.key, output_path)
                        )
        except BaseException:
            for future in in_flight:
                future.cancel()
            raise

    return DownloadSummary(file_count=len(downloads), size_bytes=downloaded_size)


def delete_scenes(
    uploader: ObjectUploader,
    settings: RunpodS3Settings,
    scenes: tuple[CatalogScene, ...],
    *,
    scene_ids: frozenset[str] | None,
) -> DeletionSummary:
    """Delete selected completed scenes, their results, and their terminal jobs."""

    selected_scenes = _select_scenes(scenes, scene_ids)
    selected_jobs = tuple(job for scene in selected_scenes for job in scene.jobs)
    _require_terminal_jobs(selected_jobs, "delete scenes")
    keys = {
        key
        for scene in selected_scenes
        for key in uploader.list_object_sizes(
            settings.workspace_prefix / "scenes" / scene.manifest.id
        )
    }
    keys.update(
        key
        for job in selected_jobs
        for key in uploader.list_object_sizes(settings.workspace_prefix / "jobs" / job.manifest.id)
    )
    return _delete_objects(uploader, "scene", len(selected_scenes), keys)


def delete_jobs(
    uploader: ObjectUploader,
    settings: RunpodS3Settings,
    scenes: tuple[CatalogScene, ...],
    *,
    job_ids: frozenset[str] | None,
) -> DeletionSummary:
    """Delete selected terminal job records while preserving their published results."""

    selected_jobs = _select_jobs(scenes, job_ids)
    _require_terminal_jobs(selected_jobs, "delete jobs")
    keys = {
        key
        for job in selected_jobs
        for key in uploader.list_object_sizes(settings.workspace_prefix / "jobs" / job.manifest.id)
    }
    return _delete_objects(uploader, "job", len(selected_jobs), keys)


def delete_results(
    uploader: ObjectUploader,
    scenes: tuple[CatalogScene, ...],
    *,
    result_ids: frozenset[str] | None,
) -> DeletionSummary:
    """Delete selected published result packages while preserving their scenes and jobs."""

    selected_results = _select_results(scenes, result_ids)
    keys = {file.key for result in selected_results for file in result.files}
    return _delete_objects(uploader, "result", len(selected_results), keys)


def catalog_json(scenes: tuple[CatalogScene, ...]) -> dict[str, object]:
    """Return the catalog in a stable JSON-ready form."""

    return {
        "scenes": [
            {
                "scene": scene.manifest.model_dump(mode="json"),
                "jobs": [
                    {
                        "manifest": job.manifest.model_dump(mode="json"),
                        "status": job.status.model_dump(mode="json") if job.status else None,
                    }
                    for job in scene.jobs
                ],
                "results": [
                    {
                        "metadata": result.result.model_dump(mode="json"),
                        "files": [
                            {"key": file.key.as_posix(), "size_bytes": file.size_bytes}
                            for file in result.files
                        ],
                    }
                    for result in scene.results
                ],
            }
            for scene in scenes
        ]
    }


def format_catalog(scenes: tuple[CatalogScene, ...]) -> str:
    """Format a concise human-readable scene, job, and result inventory."""

    if not scenes:
        return "No completed scenes found."

    lines: list[str] = []
    for scene in scenes:
        manifest = scene.manifest
        lines.append(
            f"{manifest.id}  {manifest.name}  ({manifest.source_kind}, {manifest.filename})"
        )
        lines.append(f"  Jobs: {len(scene.jobs)}")
        for job in scene.jobs:
            status = job.status.status.value if job.status is not None else "status unavailable"
            lines.append(
                f"    {job.manifest.id}  {status}  frames {job.manifest.frame_start}-"
                f"{job.manifest.frame_end}  {job.manifest.backend.value}"
            )
        lines.append(f"  Results: {len(scene.results)}")
        for result in scene.results:
            size_bytes = sum(file.size_bytes for file in result.files)
            lines.append(
                f"    frame {result.result.frame}  {result.result.id}  job {result.result.job_id}  "
                f"{size_bytes} bytes"
            )
    return "\n".join(lines)


def _select_scenes(
    scenes: tuple[CatalogScene, ...], scene_ids: frozenset[str] | None
) -> tuple[CatalogScene, ...]:
    selected = tuple(
        scene for scene in scenes if scene_ids is None or scene.manifest.id in scene_ids
    )
    _require_selected_ids(
        requested_ids=scene_ids,
        found_ids={scene.manifest.id for scene in selected},
        entity_kind="scene",
    )
    return selected


def _select_jobs(
    scenes: tuple[CatalogScene, ...], job_ids: frozenset[str] | None
) -> tuple[CatalogJob, ...]:
    selected = tuple(
        job
        for scene in scenes
        for job in scene.jobs
        if job_ids is None or job.manifest.id in job_ids
    )
    _require_selected_ids(
        requested_ids=job_ids,
        found_ids={job.manifest.id for job in selected},
        entity_kind="job",
    )
    return selected


def _select_results(
    scenes: tuple[CatalogScene, ...], result_ids: frozenset[str] | None
) -> tuple[ResultPackage, ...]:
    selected = tuple(
        result
        for scene in scenes
        for result in scene.results
        if result_ids is None or result.result.id in result_ids
    )
    _require_selected_ids(
        requested_ids=result_ids,
        found_ids={result.result.id for result in selected},
        entity_kind="result",
    )
    return selected


def _require_selected_ids(
    *, requested_ids: frozenset[str] | None, found_ids: set[str], entity_kind: str
) -> None:
    if requested_ids is None:
        return
    missing_ids = sorted(requested_ids.difference(found_ids))
    if missing_ids:
        raise RunpodScenePreparationError(
            f"Completed {entity_kind} {missing_ids[0]} was not found"
        )


def _require_terminal_jobs(jobs: tuple[CatalogJob, ...], action: str) -> None:
    for job in jobs:
        if job.status is None:
            raise RunpodScenePreparationError(
                f"Cannot {action}: job {job.manifest.id} has no status snapshot"
            )
        if job.status.status not in TERMINAL_STATUSES:
            raise RunpodScenePreparationError(
                f"Cannot {action}: job {job.manifest.id} is {job.status.status.value}"
            )


def _delete_objects(
    uploader: ObjectUploader,
    entity_kind: str,
    entity_count: int,
    keys: set[PurePosixPath],
) -> DeletionSummary:
    selected_keys = tuple(sorted(keys, key=PurePosixPath.as_posix))
    uploader.delete_objects(selected_keys)
    return DeletionSummary(
        entity_kind=entity_kind,
        entity_count=entity_count,
        object_count=len(selected_keys),
    )


def _read_scene_manifests(
    uploader: ObjectUploader,
    scenes_root: PurePosixPath,
    objects: dict[PurePosixPath, int],
) -> tuple[SceneManifest, ...]:
    manifests: list[SceneManifest] = []
    for key in _direct_manifest_keys(objects, scenes_root):
        manifest = _read_model(uploader, key, SceneManifest, "scene")
        if manifest.id != key.parent.name:
            raise RunpodScenePreparationError(
                f"Scene manifest {key} does not match its scene directory"
            )
        manifests.append(manifest)
    return tuple(sorted(manifests, key=lambda scene: (scene.created_at, scene.id), reverse=True))


def _read_jobs(
    uploader: ObjectUploader,
    jobs_root: PurePosixPath,
    scene_ids: set[str],
) -> dict[str, tuple[CatalogJob, ...]]:
    objects = uploader.list_object_sizes(jobs_root)
    jobs_by_scene: dict[str, list[CatalogJob]] = {scene_id: [] for scene_id in scene_ids}
    for key in _direct_manifest_keys(objects, jobs_root):
        manifest = _read_model(uploader, key, JobManifest, "job")
        if manifest.id != key.parent.name:
            raise RunpodScenePreparationError(
                f"Job manifest {key} does not match its job directory"
            )
        if manifest.scene_id not in scene_ids:
            continue
        status_key = key.parent / "status.json"
        status = (
            _read_model(uploader, status_key, JobStatusSnapshot, "job status")
            if status_key in objects
            else None
        )
        jobs_by_scene[manifest.scene_id].append(CatalogJob(manifest=manifest, status=status))
    return {
        scene_id: tuple(sorted(jobs, key=lambda job: (job.manifest.created_at, job.manifest.id)))
        for scene_id, jobs in jobs_by_scene.items()
    }


def _read_results(
    uploader: ObjectUploader,
    scenes_root: PurePosixPath,
    objects: dict[PurePosixPath, int],
    scene_ids: set[str],
) -> dict[str, tuple[ResultPackage, ...]]:
    results_by_scene: dict[str, list[ResultPackage]] = {scene_id: [] for scene_id in scene_ids}
    for key in sorted(objects, key=PurePosixPath.as_posix):
        relative = key.relative_to(scenes_root)
        if (
            len(relative.parts) != 5
            or relative.parts[1] != "results"
            or key.name != "metadata.json"
        ):
            continue
        scene_id, _, frame_directory, result_id, _ = relative.parts
        if scene_id not in scene_ids:
            continue
        result = _read_model(uploader, key, FrameResult, "result")
        if (
            result.scene_id != scene_id
            or result.id != result_id
            or f"{result.frame:06d}" != frame_directory
        ):
            raise RunpodScenePreparationError(
                f"Result metadata {key} does not match its result directory"
            )
        result_root = key.parent
        files = tuple(
            ResultFile(key=file_key, size_bytes=size_bytes)
            for file_key, size_bytes in sorted(objects.items(), key=lambda item: item[0].as_posix())
            if file_key.is_relative_to(result_root)
        )
        results_by_scene[scene_id].append(ResultPackage(result=result, files=files))
    return {
        scene_id: tuple(
            sorted(
                results,
                key=lambda package: (
                    package.result.frame,
                    package.result.completed_at,
                    package.result.id,
                ),
            )
        )
        for scene_id, results in results_by_scene.items()
    }


def _direct_manifest_keys(
    objects: dict[PurePosixPath, int], root: PurePosixPath
) -> tuple[PurePosixPath, ...]:
    return tuple(
        sorted(
            (
                key
                for key in objects
                if key.name == "manifest.json"
                and key.is_relative_to(root)
                and len(key.relative_to(root).parts) == 2
            ),
            key=PurePosixPath.as_posix,
        )
    )


def _read_model[Model: (SceneManifest, JobManifest, JobStatusSnapshot, FrameResult)](
    uploader: ObjectUploader,
    key: PurePosixPath,
    model: type[Model],
    name: str,
) -> Model:
    try:
        return model.model_validate(uploader.read_json(key))
    except ValueError as exc:
        raise RunpodScenePreparationError(f"Invalid {name} metadata at {key}") from exc


def _download_destination(
    destination: Path,
    scenes_root: PurePosixPath,
    scene_id: str,
    key: PurePosixPath,
) -> Path:
    scene_root = scenes_root / scene_id
    if not key.is_relative_to(scene_root):
        raise RunpodScenePreparationError(f"Result file {key} is outside scene {scene_id}")
    relative = key.relative_to(scenes_root)
    if relative.is_absolute() or ".." in relative.parts:
        raise RunpodScenePreparationError(f"Result file {key} has an unsafe path")
    return destination / "scenes" / Path(relative.as_posix())
