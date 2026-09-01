from __future__ import annotations

import asyncio
import os
import tempfile
import unicodedata
import uuid
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from starlette.requests import ClientDisconnect

from .auth import SessionManager
from .config import Settings
from .models import (
    ArchiveRequest,
    CreateJobRequest,
    CreateUploadRequest,
    FrameResult,
    FramesPage,
    Job,
    JobManifest,
    JobStatus,
    LoginRequest,
    Scene,
    SessionResponse,
    SystemInfo,
    TelemetrySample,
    UploadManifest,
    UploadSession,
    UploadStatus,
    utc_now,
)
from .project_archive import ProjectArchiveError
from .system import SystemProbe
from .telemetry import TelemetryCollector
from .worker import RenderWorker
from .workspace import (
    UPLOAD_TTL,
    ConflictError,
    NotFoundError,
    WorkspaceError,
    WorkspaceStore,
)


def create_app(settings: Settings | None = None, *, start_worker: bool = True) -> FastAPI:
    resolved = settings or Settings.from_env()
    store = WorkspaceStore(resolved)
    sessions = SessionManager(
        resolved.app_password,
        secure=resolved.cookie_secure,
        max_age=resolved.session_ttl_seconds,
    )
    probe = SystemProbe(
        resolved.blender_bin,
        resolved.workspace_root,
        resolved.pod_id,
        resolved.available_backends_override,
    )
    worker = RenderWorker(resolved, store)
    telemetry = TelemetryCollector(store, probe)
    finalization_tasks: set[asyncio.Task[None]] = set()

    async def finalize_upload(upload_id: str) -> None:
        try:
            await asyncio.to_thread(store.finalize_upload, upload_id)
        except ProjectArchiveError as exc:
            await _mark_upload_failed(store, upload_id, str(exc))
        except (ConflictError, NotFoundError):
            return
        except (OSError, WorkspaceError):
            await _mark_upload_failed(
                store,
                upload_id,
                "The uploaded project could not be finalized. Try again after checking disk space.",
            )

    def schedule_finalization(upload_id: str) -> None:
        task = asyncio.create_task(finalize_upload(upload_id))
        finalization_tasks.add(task)
        task.add_done_callback(finalization_tasks.discard)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await asyncio.to_thread(store.initialize)
        await asyncio.to_thread(store.cleanup_expired_uploads)
        await probe.initialize()
        await telemetry.start()
        if start_worker:
            await worker.start()
        app.state.settings = resolved
        app.state.store = store
        app.state.sessions = sessions
        app.state.probe = probe
        app.state.telemetry = telemetry
        app.state.worker = worker
        for upload_id in await asyncio.to_thread(store.list_recoverable_uploads):
            schedule_finalization(upload_id)
        yield
        if finalization_tasks:
            await asyncio.gather(*finalization_tasks, return_exceptions=True)
        if start_worker:
            await worker.stop()
        await telemetry.stop()

    app = FastAPI(
        title="BlendRender",
        version="2.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        return response

    def require_auth(request: Request) -> None:
        sessions.require(request)

    @app.get("/healthz", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def ready() -> Response:
        if probe.ready:
            return JSONResponse({"status": "ready"})
        return JSONResponse({"status": "not_ready"}, status_code=503)

    @app.post("/api/auth/login", response_model=SessionResponse)
    async def login(payload: LoginRequest, response: Response) -> SessionResponse:
        if not sessions.verify_password(payload.password):
            await asyncio.sleep(0.5)
            raise HTTPException(status_code=401, detail="Incorrect password")
        sessions.set_cookie(response)
        return SessionResponse(authenticated=True)

    @app.post("/api/auth/logout", response_model=SessionResponse)
    async def logout(response: Response) -> SessionResponse:
        sessions.clear_cookie(response)
        return SessionResponse(authenticated=False)

    @app.get("/api/auth/session", response_model=SessionResponse)
    async def session(request: Request) -> SessionResponse:
        return SessionResponse(authenticated=sessions.is_authenticated(request))

    @app.get("/api/system", response_model=SystemInfo)
    async def system_info(_: None = Depends(require_auth)) -> SystemInfo:
        return telemetry.latest or await probe.info()

    @app.get("/api/system/telemetry", response_model=list[TelemetrySample])
    async def system_telemetry(_: None = Depends(require_auth)) -> list[TelemetrySample]:
        return await telemetry.samples()

    @app.post("/api/uploads", response_model=UploadSession, status_code=201)
    async def create_upload(
        payload: CreateUploadRequest, _: None = Depends(require_auth)
    ) -> UploadSession:
        filename = _sanitize_scene_name(payload.filename)
        if Path(filename).suffix.lower() not in {".blend", ".zip"}:
            raise HTTPException(
                status_code=422, detail="Only .blend files and project ZIP archives are accepted"
            )
        if payload.size_bytes > resolved.max_upload_bytes:
            raise HTTPException(status_code=413, detail="Upload exceeds the configured limit")
        now = datetime.now(UTC)
        upload = UploadManifest(
            id=str(uuid.uuid4()),
            filename=filename,
            name=_sanitize_scene_name(payload.name or "") or filename,
            size_bytes=payload.size_bytes,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
            expires_at=(now + UPLOAD_TTL).isoformat(),
        )
        try:
            created = await asyncio.to_thread(store.create_upload, upload)
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except WorkspaceError as exc:
            raise HTTPException(status_code=507, detail=str(exc)) from exc
        return await _upload_session(store, created, resolved.upload_chunk_bytes)

    @app.get("/api/uploads/{upload_id}", response_model=UploadSession)
    async def get_upload(upload_id: str, _: None = Depends(require_auth)) -> UploadSession:
        try:
            upload = await asyncio.to_thread(store.get_upload, upload_id)
        except (NotFoundError, WorkspaceError) as exc:
            raise HTTPException(status_code=404, detail="Upload not found") from exc
        return await _upload_session(store, upload, resolved.upload_chunk_bytes)

    @app.patch("/api/uploads/{upload_id}", response_model=UploadSession)
    async def append_upload(
        upload_id: str, request: Request, _: None = Depends(require_auth)
    ) -> UploadSession:
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/octet-stream":
            raise HTTPException(status_code=415, detail="Upload chunks must be binary data")
        try:
            offset = int(request.headers["upload-offset"])
        except (KeyError, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail="Upload-Offset must be a non-negative integer"
            ) from exc
        if offset < 0:
            raise HTTPException(
                status_code=422, detail="Upload-Offset must be a non-negative integer"
            )
        try:
            declared_length = int(request.headers.get("content-length", "0"))
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail="Content-Length must be an integer"
            ) from exc
        if declared_length <= 0:
            raise HTTPException(status_code=422, detail="Upload chunks must not be empty")

        try:
            with store.upload_lock(upload_id):
                upload = store.get_upload(upload_id)
                if upload.status != UploadStatus.UPLOADING:
                    raise HTTPException(
                        status_code=409, detail="This upload is not accepting chunks"
                    )
                if offset != upload.uploaded_bytes:
                    raise HTTPException(
                        status_code=409,
                        detail="Upload offset does not match the committed bytes",
                        headers={"Upload-Offset": str(upload.uploaded_bytes)},
                    )
                remaining_bytes = upload.size_bytes - upload.uploaded_bytes
                allowed = min(resolved.upload_chunk_bytes, remaining_bytes)
                if declared_length > allowed:
                    raise HTTPException(
                        status_code=413, detail="Upload chunk exceeds the allowed size"
                    )
                paths = store.upload_paths(upload_id)
                written = 0
                try:
                    with paths["part"].open("ab") as destination:
                        async for chunk in request.stream():
                            if not chunk:
                                continue
                            written += len(chunk)
                            if written > allowed:
                                raise HTTPException(
                                    status_code=413, detail="Upload chunk exceeds the allowed size"
                                )
                            destination.write(chunk)
                        destination.flush()
                        os.fsync(destination.fileno())
                    if written != declared_length:
                        raise HTTPException(
                            status_code=422, detail="Upload chunk length did not match"
                        )
                    if written == 0:
                        raise HTTPException(
                            status_code=422, detail="Upload chunks must not be empty"
                        )
                except (ClientDisconnect, HTTPException, OSError):
                    if paths["part"].exists():
                        with paths["part"].open("r+b") as destination:
                            destination.truncate(offset)
                    raise
                updated = store.update_upload(
                    upload_id,
                    uploaded_bytes=upload.uploaded_bytes + written,
                    error=None,
                )
        except ClientDisconnect as exc:
            raise HTTPException(status_code=499, detail="Upload connection closed") from exc
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="Upload not found") from exc
        except OSError as exc:
            raise HTTPException(status_code=507, detail="Unable to store the upload chunk") from exc
        return await _upload_session(store, updated, resolved.upload_chunk_bytes)

    @app.post("/api/uploads/{upload_id}/complete", response_model=UploadSession, status_code=202)
    async def complete_upload(upload_id: str, _: None = Depends(require_auth)) -> UploadSession:
        try:
            upload, should_start = await asyncio.to_thread(
                store.prepare_upload_finalization, upload_id
            )
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="Upload not found") from exc
        except WorkspaceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if should_start:
            schedule_finalization(upload_id)
        return await _upload_session(store, upload, resolved.upload_chunk_bytes)

    @app.delete("/api/uploads/{upload_id}", status_code=204)
    async def delete_upload(upload_id: str, _: None = Depends(require_auth)) -> Response:
        try:
            await asyncio.to_thread(store.delete_upload, upload_id)
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="Upload not found") from exc
        return Response(status_code=204)

    @app.get("/api/scenes", response_model=list[Scene])
    async def list_scenes(_: None = Depends(require_auth)) -> list[Scene]:
        return await asyncio.to_thread(store.list_scenes)

    @app.get("/api/scenes/{scene_id}", response_model=Scene)
    async def get_scene(scene_id: str, _: None = Depends(require_auth)) -> Scene:
        return await _require_scene(store, scene_id)

    @app.delete("/api/scenes/{scene_id}", status_code=204)
    async def delete_scene(scene_id: str, _: None = Depends(require_auth)) -> Response:
        try:
            await asyncio.to_thread(store.delete_scene, scene_id)
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="Scene not found") from exc
        return Response(status_code=204)

    @app.post("/api/jobs", response_model=Job, status_code=201)
    async def create_job(payload: CreateJobRequest, _: None = Depends(require_auth)) -> Job:
        if payload.backend not in probe.available_backends:
            raise HTTPException(
                status_code=422,
                detail=f"{payload.backend.value} is not available on this Pod",
            )
        try:
            frame_start, frame_end = payload.validate_render_settings()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        scene = await _require_scene(store, payload.scene_id)
        job = JobManifest(
            id=str(uuid.uuid4()),
            scene_id=scene.id,
            filename=scene.name,
            owner_pod_id=resolved.pod_id,
            mode=payload.mode,
            frame_start=frame_start,
            frame_end=frame_end,
            backend=payload.backend,
            samples=payload.samples,
            tile_size=payload.tile_size,
            resolution_x=payload.resolution_x,
            resolution_y=payload.resolution_y,
            resolution_percentage=payload.resolution_percentage,
            created_at=utc_now(),
        )
        try:
            created = await asyncio.to_thread(store.create_job, job)
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        worker.notify()
        telemetry.notify()
        return created

    @app.get("/api/jobs", response_model=list[Job])
    async def list_jobs(
        scene_id: str | None = None,
        status: JobStatus | None = None,
        _: None = Depends(require_auth),
    ) -> list[Job]:
        return await asyncio.to_thread(store.list_jobs, scene_id=scene_id, status=status)

    @app.get("/api/jobs/{job_id}", response_model=Job)
    async def get_job(job_id: str, _: None = Depends(require_auth)) -> Job:
        return await _require_job(store, job_id)

    @app.post("/api/jobs/{job_id}/cancel", response_model=Job)
    async def cancel_job(job_id: str, _: None = Depends(require_auth)) -> Job:
        job = await _require_owned_job(store, job_id, resolved.pod_id)
        if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            raise HTTPException(
                status_code=409, detail="Only queued or running jobs can be canceled"
            )
        updated = await worker.cancel(job)
        telemetry.notify()
        return updated

    @app.post("/api/jobs/{job_id}/retry", response_model=Job)
    async def retry_job(job_id: str, _: None = Depends(require_auth)) -> Job:
        job = await _require_owned_job(store, job_id, resolved.pod_id)
        if job.status not in {JobStatus.FAILED, JobStatus.CANCELED, JobStatus.INTERRUPTED}:
            raise HTTPException(status_code=409, detail="This job cannot be retried")
        results = await asyncio.to_thread(store.results_for_job, job.id)
        completed = sorted({result.frame for result in results})
        updated = await asyncio.to_thread(
            store.update_job,
            job.id,
            status=JobStatus.QUEUED,
            progress=len(completed) / job.total_frames * 100,
            current_frame=None,
            sample_current=None,
            sample_total=None,
            completed_frames=completed,
            error=None,
            finished_at=None,
            eta_seconds=None,
            cancel_requested=False,
        )
        worker.notify()
        telemetry.notify()
        return updated

    @app.delete("/api/jobs/{job_id}", status_code=204)
    async def delete_job(job_id: str, _: None = Depends(require_auth)) -> Response:
        await _require_owned_job(store, job_id, resolved.pod_id)
        try:
            await asyncio.to_thread(store.delete_job, job_id)
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Response(status_code=204)

    @app.get("/api/scenes/{scene_id}/frames", response_model=FramesPage)
    async def list_frames(
        scene_id: str,
        cursor: int | None = None,
        limit: int = 50,
        _: None = Depends(require_auth),
    ) -> FramesPage:
        await _require_scene(store, scene_id)
        if not 1 <= limit <= 200:
            raise HTTPException(status_code=422, detail="Limit must be between 1 and 200")
        return await asyncio.to_thread(store.list_frame_groups, scene_id, cursor, limit)

    @app.get("/api/scenes/{scene_id}/results/{result_id}", response_model=FrameResult)
    async def get_result(
        scene_id: str, result_id: str, _: None = Depends(require_auth)
    ) -> FrameResult:
        for result in await asyncio.to_thread(store.list_results, scene_id):
            if result.id == result_id:
                return result
        raise HTTPException(status_code=404, detail="Result not found")

    @app.get("/api/scenes/{scene_id}/results/{result_id}/image")
    async def get_result_image(
        scene_id: str,
        result_id: str,
        preview: bool = False,
        _: None = Depends(require_auth),
    ) -> FileResponse:
        result = await get_result(scene_id, result_id)
        result_paths = store.result_paths(scene_id, result.frame, result.id)
        path = result_paths["preview" if preview else "image"]
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Result image is not available")
        return FileResponse(
            path,
            media_type="image/webp" if preview else "image/png",
            filename=None if preview else f"frame_{result.frame:06d}-{result.id[:8]}.png",
            content_disposition_type="inline" if preview else "attachment",
        )

    @app.post("/api/scenes/{scene_id}/archive")
    async def archive_scene(
        scene_id: str, payload: ArchiveRequest, _: None = Depends(require_auth)
    ) -> FileResponse:
        scene = await _require_scene(store, scene_id)
        available = await asyncio.to_thread(store.list_results, scene_id)
        selected = available if payload.result_ids is None else [
            result for result in available if result.id in set(payload.result_ids)
        ]
        requested_count = len(set(payload.result_ids or []))
        if not selected or (payload.result_ids is not None and len(selected) != requested_count):
            raise HTTPException(
                status_code=422, detail="One or more requested results are unavailable"
            )
        archive_path = await asyncio.to_thread(_create_archive, store, selected, scene.name)
        return FileResponse(
            archive_path,
            media_type="application/zip",
            filename=f"{Path(scene.name).stem}-results.zip",
            background=BackgroundTask(archive_path.unlink, missing_ok=True),
        )

    @app.post("/api/jobs/{job_id}/archive")
    async def archive_job(job_id: str, _: None = Depends(require_auth)) -> FileResponse:
        job = await _require_job(store, job_id)
        results = await asyncio.to_thread(store.results_for_job, job.id)
        if not results:
            raise HTTPException(status_code=422, detail="This job has no completed results")
        archive_path = await asyncio.to_thread(_create_archive, store, results, job.filename)
        return FileResponse(
            archive_path,
            media_type="application/zip",
            filename=f"{Path(job.filename).stem}-job-{job.id[:8]}.zip",
            background=BackgroundTask(archive_path.unlink, missing_ok=True),
        )

    if resolved.frontend_dist.is_dir():
        assets = resolved.frontend_dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def frontend(path: str) -> FileResponse:
            candidate = (resolved.frontend_dist / path).resolve()
            if (
                path
                and candidate.is_file()
                and candidate.is_relative_to(resolved.frontend_dist.resolve())
            ):
                return FileResponse(candidate)
            return FileResponse(resolved.frontend_dist / "index.html")

    return app


async def _upload_session(
    store: WorkspaceStore, upload: UploadManifest, chunk_size_bytes: int
) -> UploadSession:
    scene: Scene | None = None
    if upload.status == UploadStatus.COMPLETED:
        # A finalizer may have written the completion record just before atomic publication.
        with suppress(NotFoundError, WorkspaceError):
            scene = await asyncio.to_thread(store.get_scene, upload.id)
    return UploadSession.model_validate(
        {
            **upload.model_dump(),
            "chunk_size_bytes": chunk_size_bytes,
            "scene": scene,
        }
    )


async def _mark_upload_failed(store: WorkspaceStore, upload_id: str, error: str) -> None:
    try:
        await asyncio.to_thread(store.mark_upload_failed, upload_id, error)
    except (ConflictError, NotFoundError, WorkspaceError):
        return


async def _require_scene(store: WorkspaceStore, scene_id: str) -> Scene:
    try:
        return await asyncio.to_thread(store.get_scene, scene_id)
    except (NotFoundError, WorkspaceError) as exc:
        raise HTTPException(status_code=404, detail="Scene not found") from exc


def _sanitize_scene_name(value: str) -> str:
    basename = unicodedata.normalize("NFKC", value).replace("\\", "/").rsplit("/", 1)[-1]
    printable = "".join(character if character.isprintable() else " " for character in basename)
    return " ".join(printable.split()).strip(" .")[:200].rstrip()


async def _require_job(store: WorkspaceStore, job_id: str) -> Job:
    try:
        return await asyncio.to_thread(store.get_job, job_id)
    except (NotFoundError, WorkspaceError) as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc


async def _require_owned_job(store: WorkspaceStore, job_id: str, pod_id: str) -> Job:
    job = await _require_job(store, job_id)
    if job.owner_pod_id != pod_id:
        raise HTTPException(status_code=409, detail="This job is owned by another Pod")
    return job


def _create_archive(store: WorkspaceStore, results: list[FrameResult], filename: str) -> Path:
    handle, name = tempfile.mkstemp(prefix="blendrender-", suffix=".zip")
    os.close(handle)
    archive = Path(name)
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
            for result in results:
                paths = store.result_paths(result.scene_id, result.frame, result.id)
                stem = f"frame_{result.frame:06d}-{result.id}"
                bundle.write(paths["image"], arcname=f"{stem}.png")
                bundle.write(paths["metadata"], arcname=f"{stem}.json")
        return archive
    except Exception:
        archive.unlink(missing_ok=True)
        raise


app = create_app()
