from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import time
from contextlib import suppress
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .config import Settings
from .db import Database
from .models import TERMINAL_STATUSES, Job, JobStatus, utc_now
from .progress import overall_progress, parse_renderer_line

LOG_TAIL_LIMIT = 12_000


def frame_filename(frame: int) -> str:
    return f"frame_{frame:06d}.png"


def preview_filename(frame: int) -> str:
    return f"frame_{frame:06d}.webp"


def job_paths(settings: Settings, job_id: str) -> dict[str, Path]:
    root = settings.jobs_root / job_id
    return {
        "root": root,
        "input": root / "input.blend",
        "outputs": root / "outputs",
        "previews": root / "previews",
        "log": root / "render.log",
        "config": root / "render-config.json",
    }


def verify_png(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        with Image.open(path) as image:
            return image.format == "PNG" and image.width > 0 and image.height > 0
    except (OSError, UnidentifiedImageError):
        return False


def completed_output_frames(settings: Settings, job: Job) -> list[int]:
    outputs = job_paths(settings, job.id)["outputs"]
    return [
        frame
        for frame in range(job.frame_start, job.frame_end + 1)
        if verify_png(outputs / frame_filename(frame))
    ]


def create_preview(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as opened:
        opened.thumbnail((720, 480), Image.Resampling.LANCZOS)
        preview = opened.copy() if opened.mode in {"RGB", "RGBA"} else opened.convert("RGB")
    try:
        preview.save(destination, "WEBP", quality=82, method=4)
    finally:
        preview.close()


class RenderWorker:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database
        self._wake = asyncio.Event()
        self._stopping = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._current_job_id: str | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="blendqueue-render-worker")
        self._wake.set()

    async def stop(self) -> None:
        self._stopping.set()
        await self._terminate_current()
        self._wake.set()
        if self._task is not None:
            with suppress(asyncio.CancelledError):
                await self._task

    def notify(self) -> None:
        self._wake.set()

    async def cancel(self, job: Job) -> Job:
        if job.status == JobStatus.QUEUED:
            return await self.database.update(
                job.id,
                status=JobStatus.CANCELED,
                finished_at=utc_now(),
                cancel_requested=True,
                error=None,
            )
        updated = await self.database.update(job.id, cancel_requested=True)
        if self._current_job_id == job.id:
            asyncio.create_task(self._terminate_current())
        return updated

    async def _loop(self) -> None:
        while not self._stopping.is_set():
            job = await self.database.next_queued_job()
            if job is None:
                self._wake.clear()
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=2)
                continue
            await self._run(job)

    async def _run(self, job: Job) -> None:
        paths = job_paths(self.settings, job.id)
        paths["outputs"].mkdir(parents=True, exist_ok=True)
        paths["previews"].mkdir(parents=True, exist_ok=True)
        completed = completed_output_frames(self.settings, job)
        remaining = [
            frame
            for frame in range(job.frame_start, job.frame_end + 1)
            if frame not in set(completed)
        ]
        config = {
            "backend": job.backend.value,
            "frames": remaining,
            "output_dir": str(paths["outputs"]),
        }
        paths["config"].write_text(json.dumps(config), encoding="utf-8")
        command = [
            str(self.settings.blender_bin),
            "--background",
            "--disable-autoexec",
            "--python-exit-code",
            "1",
            str(paths["input"]),
            "--python",
            str(self.settings.renderer_script),
            "--",
            str(paths["config"]),
        ]
        started = time.monotonic()
        frame_durations: list[float] = []
        log_tail = ""
        current_frame: int | None = None
        last_progress_update = 0.0
        try:
            self._current_job_id = job.id
            self._process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
            assert self._process.stdout is not None
            with paths["log"].open("a", encoding="utf-8") as log_file:
                async for raw_line in self._process.stdout:
                    line = raw_line.decode(errors="replace")
                    log_file.write(line)
                    log_file.flush()
                    log_tail = (log_tail + line)[-LOG_TAIL_LIMIT:]
                    parsed = parse_renderer_line(line)
                    if parsed.event:
                        event_type = parsed.event.get("type")
                        if event_type == "frame_started":
                            current_frame = int(parsed.event["frame"])
                            await self.database.update(
                                job.id,
                                current_frame=current_frame,
                                log_tail=log_tail,
                            )
                        elif event_type == "frame_completed":
                            frame = int(parsed.event["frame"])
                            duration = float(parsed.event.get("seconds", 0))
                            if duration > 0:
                                frame_durations.append(duration)
                            if frame not in completed:
                                completed.append(frame)
                                completed.sort()
                            output_path = paths["outputs"] / frame_filename(frame)
                            if verify_png(output_path):
                                await asyncio.to_thread(
                                    create_preview,
                                    output_path,
                                    paths["previews"] / preview_filename(frame),
                                )
                            average = (
                                sum(frame_durations) / len(frame_durations)
                                if frame_durations
                                else None
                            )
                            eta = average * (job.total_frames - len(completed)) if average else None
                            await self.database.update(
                                job.id,
                                progress=len(completed) / job.total_frames * 100,
                                completed_frames=completed,
                                elapsed_seconds=time.monotonic() - started,
                                eta_seconds=eta,
                                log_tail=log_tail,
                            )
                        elif event_type == "error":
                            await self.database.update(
                                job.id,
                                error=str(parsed.event.get("message", "Blender render failed")),
                                log_tail=log_tail,
                            )
                    elif parsed.sample_current is not None:
                        now = time.monotonic()
                        if now - last_progress_update >= 0.5:
                            last_progress_update = now
                            await self.database.update(
                                job.id,
                                current_frame=current_frame,
                                progress=overall_progress(
                                    completed_count=len(completed),
                                    total_frames=job.total_frames,
                                    sample_current=parsed.sample_current,
                                    sample_total=parsed.sample_total or 1,
                                ),
                                elapsed_seconds=now - started,
                                log_tail=log_tail,
                            )
            return_code = await self._process.wait()
            latest = await self.database.get_job(job.id)
            if latest is None:
                return
            if latest.cancel_requested:
                final_status = JobStatus.CANCELED
                error = None
            elif self._stopping.is_set():
                final_status = JobStatus.INTERRUPTED
                error = "The application stopped while this render was running."
            elif return_code == 0 and len(completed) == job.total_frames:
                final_status = JobStatus.COMPLETED
                error = None
            else:
                final_status = JobStatus.FAILED
                error = latest.error or _summarize_failure(log_tail, return_code)
            await self.database.update(
                job.id,
                status=final_status,
                progress=100 if final_status == JobStatus.COMPLETED else latest.progress,
                current_frame=None,
                completed_frames=completed,
                error=error,
                finished_at=utc_now(),
                elapsed_seconds=time.monotonic() - started,
                eta_seconds=0 if final_status == JobStatus.COMPLETED else None,
                log_tail=log_tail,
            )
        except Exception as exc:
            latest = await self.database.get_job(job.id)
            if latest is not None and latest.status not in TERMINAL_STATUSES:
                await self.database.update(
                    job.id,
                    status=JobStatus.FAILED,
                    error=f"Unable to run Blender: {exc}",
                    finished_at=utc_now(),
                    elapsed_seconds=time.monotonic() - started,
                    log_tail=log_tail,
                )
        finally:
            self._process = None
            self._current_job_id = None

    async def _terminate_current(self) -> None:
        process = self._process
        if process is None or process.returncode is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=self.settings.cancel_grace_seconds)
        except TimeoutError:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()


def delete_job_files(settings: Settings, job_id: str) -> None:
    root = job_paths(settings, job_id)["root"]
    if root.parent != settings.jobs_root or not root.name == job_id:
        raise ValueError("Unsafe job path")
    shutil.rmtree(root, ignore_errors=True)


def _summarize_failure(log_tail: str, return_code: int) -> str:
    lines = [line.strip() for line in log_tail.splitlines() if line.strip()]
    useful = next(
        (line for line in reversed(lines) if "Error" in line or "Traceback" in line),
        lines[-1] if lines else "No renderer output was produced.",
    )
    return f"Blender exited with code {return_code}: {useful}"[:1000]
