from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import uuid
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from .auth import SessionManager
from .config import Settings
from .db import Database
from .models import (
    TERMINAL_STATUSES,
    ArchiveRequest,
    Backend,
    Job,
    JobStatus,
    LoginRequest,
    SessionResponse,
    SystemInfo,
    TelemetrySample,
)
from .system import SystemProbe
from .telemetry import TelemetryCollector
from .worker import (
    RenderWorker,
    completed_output_frames,
    delete_job_files,
    frame_filename,
    job_paths,
    preview_filename,
)


def create_app(settings: Settings | None = None, *, start_worker: bool = True) -> FastAPI:
    resolved = settings or Settings.from_env()
    database = Database(resolved.database_path)
    sessions = SessionManager(
        resolved.app_password,
        secure=resolved.cookie_secure,
        max_age=resolved.session_ttl_seconds,
    )
    probe = SystemProbe(
        resolved.blender_bin,
        resolved.data_root,
        resolved.available_backends_override,
    )
    worker = RenderWorker(resolved, database)
    telemetry = TelemetryCollector(database, probe)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved.jobs_root.mkdir(parents=True, exist_ok=True)
        await database.initialize()
        await probe.initialize()
        await telemetry.start()
        if start_worker:
            await worker.start()
        app.state.settings = resolved
        app.state.database = database
        app.state.sessions = sessions
        app.state.probe = probe
        app.state.telemetry = telemetry
        app.state.worker = worker
        yield
        if start_worker:
            await worker.stop()
        await telemetry.stop()

    app = FastAPI(
        title="BlendRender",
        version="0.1.0",
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
        return JSONResponse(
            {"status": "not_ready", "detail": "Blender or an NVIDIA backend is unavailable"},
            status_code=503,
        )

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
        return await database.list_telemetry()

    @app.post("/api/jobs", response_model=Job, status_code=201)
    async def create_job(
        file: Annotated[UploadFile, File()],
        mode: Annotated[Literal["still", "range"], Form()],
        backend: Annotated[Backend, Form()],
        frame: Annotated[int | None, Form()] = None,
        start: Annotated[int | None, Form()] = None,
        end: Annotated[int | None, Form()] = None,
        samples: Annotated[int | None, Form()] = None,
        resolution_x: Annotated[int | None, Form()] = None,
        resolution_y: Annotated[int | None, Form()] = None,
        resolution_percentage: Annotated[int | None, Form()] = None,
        _: None = Depends(require_auth),
    ) -> Job:
        if backend not in probe.available_backends:
            raise HTTPException(
                status_code=422,
                detail=f"{backend.value} is not available on this Pod",
            )
        original_name = Path(file.filename or "").name
        if not original_name.lower().endswith(".blend"):
            raise HTTPException(status_code=422, detail="Only .blend files are accepted")
        if mode == "still":
            if frame is None:
                raise HTTPException(
                    status_code=422,
                    detail="A frame is required for a still render",
                )
            frame_start = frame_end = frame
        else:
            if start is None or end is None:
                raise HTTPException(status_code=422, detail="Start and end frames are required")
            if start > end:
                raise HTTPException(status_code=422, detail="Start frame must not exceed end frame")
            frame_start, frame_end = start, end
        if frame_end - frame_start + 1 > 100_000:
            raise HTTPException(status_code=422, detail="Frame range is too large")
        if samples is not None and not 1 <= samples <= 1_000_000:
            raise HTTPException(status_code=422, detail="Samples must be between 1 and 1000000")
        if (resolution_x is None) != (resolution_y is None):
            raise HTTPException(
                status_code=422,
                detail="Resolution width and height must be provided together",
            )
        if resolution_x is not None and not 4 <= resolution_x <= 65_536:
            raise HTTPException(status_code=422, detail="Resolution width is out of range")
        if resolution_y is not None and not 4 <= resolution_y <= 65_536:
            raise HTTPException(status_code=422, detail="Resolution height is out of range")
        if resolution_percentage is not None and not 1 <= resolution_percentage <= 100:
            raise HTTPException(
                status_code=422,
                detail="Resolution percentage must be between 1 and 100",
            )

        usage = shutil.disk_usage(resolved.data_root)
        if usage.free < 1024**3:
            raise HTTPException(status_code=507, detail="Less than 1 GB of disk space remains")
        job_id = str(uuid.uuid4())
        paths = job_paths(resolved, job_id)
        paths["root"].mkdir(parents=True)
        size = 0
        try:
            with paths["input"].open("wb") as destination:
                while chunk := await file.read(8 * 1024 * 1024):
                    size += len(chunk)
                    if size > resolved.max_upload_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail="Upload exceeds the configured limit",
                        )
                    destination.write(chunk)
            if size == 0:
                raise HTTPException(status_code=422, detail="The uploaded .blend file is empty")
            job = await database.create_job(
                job_id=job_id,
                filename=original_name,
                mode=mode,
                frame_start=frame_start,
                frame_end=frame_end,
                backend=backend,
                samples=samples,
                resolution_x=resolution_x,
                resolution_y=resolution_y,
                resolution_percentage=resolution_percentage,
            )
        except Exception:
            shutil.rmtree(paths["root"], ignore_errors=True)
            raise
        finally:
            await file.close()
        worker.notify()
        telemetry.notify()
        return job

    @app.get("/api/jobs", response_model=list[Job])
    async def list_jobs(
        status: JobStatus | None = None, _: None = Depends(require_auth)
    ) -> list[Job]:
        return await database.list_jobs(status)

    @app.get("/api/jobs/{job_id}", response_model=Job)
    async def get_job(job_id: str, _: None = Depends(require_auth)) -> Job:
        return await _require_job(database, job_id)

    @app.post("/api/jobs/{job_id}/cancel", response_model=Job)
    async def cancel_job(job_id: str, _: None = Depends(require_auth)) -> Job:
        job = await _require_job(database, job_id)
        if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            raise HTTPException(
                status_code=409,
                detail="Only queued or running jobs can be canceled",
            )
        updated = await worker.cancel(job)
        telemetry.notify()
        return updated

    @app.post("/api/jobs/{job_id}/retry", response_model=Job)
    async def retry_job(job_id: str, _: None = Depends(require_auth)) -> Job:
        job = await _require_job(database, job_id)
        if job.status not in {
            JobStatus.FAILED,
            JobStatus.CANCELED,
            JobStatus.INTERRUPTED,
        }:
            raise HTTPException(status_code=409, detail="This job cannot be retried")
        frames = await asyncio.to_thread(completed_output_frames, resolved, job)
        updated = await database.requeue(job_id, frames)
        worker.notify()
        telemetry.notify()
        return updated

    @app.delete("/api/jobs/{job_id}", status_code=204)
    async def delete_job(job_id: str, _: None = Depends(require_auth)) -> Response:
        job = await _require_job(database, job_id)
        if job.status not in TERMINAL_STATUSES:
            raise HTTPException(status_code=409, detail="Cancel the job before deleting it")
        await database.delete_job(job_id)
        await asyncio.to_thread(delete_job_files, resolved, job_id)
        return Response(status_code=204)

    @app.get("/api/jobs/{job_id}/frames/{frame}")
    async def get_frame(
        job_id: str,
        frame: int,
        preview: bool = False,
        _: None = Depends(require_auth),
    ) -> FileResponse:
        job = await _require_job(database, job_id)
        if frame < job.frame_start or frame > job.frame_end:
            raise HTTPException(status_code=404, detail="Frame does not belong to this job")
        paths = job_paths(resolved, job_id)
        path = (
            paths["previews"] / preview_filename(frame)
            if preview
            else paths["outputs"] / frame_filename(frame)
        )
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Frame is not available")
        return FileResponse(
            path,
            media_type="image/webp" if preview else "image/png",
            filename=None if preview else frame_filename(frame),
            content_disposition_type="inline" if preview else "attachment",
        )

    @app.post("/api/jobs/{job_id}/archive")
    async def archive(
        job_id: str, payload: ArchiveRequest, _: None = Depends(require_auth)
    ) -> FileResponse:
        job = await _require_job(database, job_id)
        available = set(completed_output_frames(resolved, job))
        requested = sorted(available if payload.frames is None else set(payload.frames))
        if not requested or not set(requested).issubset(available):
            raise HTTPException(
                status_code=422,
                detail="One or more requested frames are unavailable",
            )
        archive_path = await asyncio.to_thread(_create_archive, resolved, job, requested)
        return FileResponse(
            archive_path,
            media_type="application/zip",
            filename=f"{Path(job.filename).stem}-frames.zip",
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


async def _require_job(database: Database, job_id: str) -> Job:
    try:
        uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    job = await database.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _create_archive(settings: Settings, job: Job, frames: list[int]) -> Path:
    handle, name = tempfile.mkstemp(prefix=f"blendrender-{job.id}-", suffix=".zip")
    os.close(handle)
    archive = Path(name)
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
            outputs = job_paths(settings, job.id)["outputs"]
            for frame in frames:
                path = outputs / frame_filename(frame)
                bundle.write(path, arcname=path.name)
        return archive
    except Exception:
        archive.unlink(missing_ok=True)
        raise


app = create_app()
