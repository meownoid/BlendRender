from __future__ import annotations

import asyncio
import os
import signal
import time
import uuid
from contextlib import suppress
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .config import Settings
from .models import TERMINAL_STATUSES, FrameResult, Job, JobStatus, RenderConfig, utc_now
from .progress import estimate_remaining_seconds, overall_progress, parse_renderer_line
from .workspace import WorkspaceStore

LOG_TAIL_LIMIT = 12_000
ELAPSED_UPDATE_INTERVAL_SECONDS = 1.0


def frame_filename(frame: int) -> str:
    return f"frame_{frame:06d}.png"


def preview_filename(frame: int) -> str:
    return f"frame_{frame:06d}.webp"


def verify_png(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        with Image.open(path) as image:
            return image.format == "PNG" and image.width > 0 and image.height > 0
    except (OSError, UnidentifiedImageError):
        return False


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
    def __init__(self, settings: Settings, store: WorkspaceStore):
        self.settings = settings
        self.store = store
        self._wake = asyncio.Event()
        self._stopping = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._current_job_id: str | None = None

    async def start(self) -> None:
        await asyncio.to_thread(self.store.recover_owner_jobs, self.settings.pod_id)
        self._task = asyncio.create_task(self._loop(), name="blendrender-render-worker")
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
            return await asyncio.to_thread(
                self.store.update_job,
                job.id,
                status=JobStatus.CANCELED,
                finished_at=utc_now(),
                cancel_requested=True,
                error=None,
            )
        updated = await asyncio.to_thread(self.store.update_job, job.id, cancel_requested=True)
        if self._current_job_id == job.id:
            asyncio.create_task(self._terminate_current())
        return updated

    async def _loop(self) -> None:
        while not self._stopping.is_set():
            job = await asyncio.to_thread(self.store.next_queued_job, self.settings.pod_id)
            if job is None:
                self._wake.clear()
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=2)
                continue
            await self._run(job)

    async def _run(self, job: Job) -> None:
        paths = self.store.job_paths(job.id)
        output_dir = paths["pending"] / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        existing = await asyncio.to_thread(self.store.results_for_job, job.id)
        completed = sorted({result.frame for result in existing})
        completed_set = set(completed)
        remaining = [
            frame
            for frame in range(job.frame_start, job.frame_end + 1)
            if frame not in completed_set
        ]
        started = time.monotonic()
        frame_durations: list[float] = [result.render_seconds for result in existing]
        log_tail = job.log_tail
        current_frame: int | None = None
        hardware: list[str] = []
        effective_samples = job.samples or 1
        last_progress_update = 0.0
        elapsed_task: asyncio.Task[None] | None = None

        async def write_status(**values: object) -> Job:
            return await asyncio.to_thread(self.store.update_job, job.id, **values)

        async def update_sample_progress(
            sample_current: int | None,
            sample_total: int | None,
            frame_remaining_seconds: float | None = None,
        ) -> None:
            nonlocal last_progress_update
            now = time.monotonic()
            if now - last_progress_update < 0.5 and frame_remaining_seconds is None:
                return
            last_progress_update = now
            average = sum(frame_durations) / len(frame_durations) if frame_durations else None
            await write_status(
                current_frame=current_frame,
                sample_current=sample_current,
                sample_total=sample_total,
                progress=overall_progress(
                    completed_count=len(completed),
                    total_frames=job.total_frames,
                    sample_current=sample_current or 0,
                    sample_total=sample_total or 1,
                ),
                elapsed_seconds=now - started,
                eta_seconds=estimate_remaining_seconds(
                    elapsed_seconds=now - started,
                    completed_count=len(completed),
                    total_frames=job.total_frames,
                    sample_current=sample_current or 0,
                    sample_total=sample_total or 1,
                    frame_average_seconds=average,
                    frame_remaining_seconds=frame_remaining_seconds,
                ),
                log_tail=log_tail,
            )

        try:
            scene_path, project_root = await asyncio.to_thread(
                self.store.scene_entrypoint, job.scene_id
            )
            values: dict[str, object] = {
                "backend": job.backend.value,
                "frames": remaining,
                "output_dir": str(output_dir),
                "project_root": str(project_root),
            }
            for field in ("samples", "resolution_x", "resolution_y", "resolution_percentage"):
                if (value := getattr(job, field)) is not None:
                    values[field] = value
            config = RenderConfig.model_validate(values)
            await asyncio.to_thread(self.store.write_render_config, job.id, config)
            command = [
                str(self.settings.blender_bin),
                "--background",
                "--disable-autoexec",
                "--python-exit-code",
                "1",
                str(scene_path),
                "--python",
                str(self.settings.renderer_script),
                "--",
                str(paths["config"]),
            ]
            self._current_job_id = job.id
            self._process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
            assert self._process.stdout is not None
            elapsed_task = asyncio.create_task(self._record_elapsed(job.id, started))
            with paths["log"].open("a", encoding="utf-8") as log_file:
                async for raw_line in self._process.stdout:
                    line = raw_line.decode(errors="replace")
                    log_file.write(line)
                    log_file.flush()
                    log_tail = (log_tail + line)[-LOG_TAIL_LIMIT:]
                    parsed = parse_renderer_line(line)
                    if parsed.event:
                        event_type = parsed.event.get("type")
                        if event_type == "job_started":
                            devices = parsed.event.get("devices")
                            hardware = (
                                [str(item) for item in devices]
                                if isinstance(devices, list)
                                else []
                            )
                            samples = parsed.event.get("samples")
                            if (
                                isinstance(samples, int)
                                and not isinstance(samples, bool)
                                and samples > 0
                            ):
                                effective_samples = samples
                        elif event_type == "frame_started":
                            current_frame = int(parsed.event["frame"])
                            await write_status(
                                current_frame=current_frame,
                                sample_current=None,
                                sample_total=None,
                                log_tail=log_tail,
                            )
                        elif event_type == "frame_completed":
                            frame = int(parsed.event["frame"])
                            duration = float(parsed.event.get("seconds", 0))
                            source = output_dir / frame_filename(frame)
                            if duration >= 0 and verify_png(source):
                                result_id = str(uuid.uuid4())
                                result_pending = paths["pending"] / result_id
                                result_pending.mkdir()
                                os.replace(source, result_pending / "frame.png")
                                await asyncio.to_thread(
                                    create_preview,
                                    result_pending / "frame.png",
                                    result_pending / "preview.webp",
                                )
                                result = FrameResult(
                                    id=result_id,
                                    scene_id=job.scene_id,
                                    job_id=job.id,
                                    frame=frame,
                                    pod_id=self.settings.pod_id,
                                    backend=job.backend,
                                    hardware=hardware
                                    or ["CPU" if job.backend.value == "CPU" else "Unknown GPU"],
                                    samples=effective_samples,
                                    render_seconds=duration,
                                    completed_at=str(parsed.event.get("completed_at") or utc_now()),
                                )
                                await asyncio.to_thread(
                                    self.store.publish_result, result, result_pending
                                )
                                if frame not in completed:
                                    completed.append(frame)
                                    completed.sort()
                                frame_durations.append(duration)
                            average = (
                                sum(frame_durations) / len(frame_durations)
                                if frame_durations
                                else None
                            )
                            eta = average * (job.total_frames - len(completed)) if average else None
                            await write_status(
                                progress=len(completed) / job.total_frames * 100,
                                sample_current=None,
                                sample_total=None,
                                completed_frames=completed,
                                elapsed_seconds=time.monotonic() - started,
                                eta_seconds=eta,
                                log_tail=log_tail,
                            )
                        elif event_type == "frame_progress":
                            current_frame = int(parsed.event["frame"])
                            sample_current, sample_total = _event_sample_progress(parsed.event)
                            remaining_seconds = parsed.event.get("remaining_seconds")
                            await update_sample_progress(
                                sample_current,
                                sample_total,
                                float(remaining_seconds)
                                if isinstance(remaining_seconds, int | float)
                                else None,
                            )
                        elif event_type == "error":
                            await write_status(
                                error=str(parsed.event.get("message", "Blender render failed")),
                                log_tail=log_tail,
                            )
                    elif parsed.sample_current is not None:
                        await update_sample_progress(
                            parsed.sample_current, parsed.sample_total or 1
                        )
            return_code = await self._process.wait()
            latest = await asyncio.to_thread(self.store.get_job, job.id)
            if latest.cancel_requested:
                final_status, error = JobStatus.CANCELED, None
            elif self._stopping.is_set():
                final_status = JobStatus.INTERRUPTED
                error = "The application stopped while this render was running."
            elif return_code == 0 and len(completed) == job.total_frames:
                final_status, error = JobStatus.COMPLETED, None
            else:
                final_status = JobStatus.FAILED
                error = latest.error or _summarize_failure(log_tail, return_code)
            await write_status(
                status=final_status,
                progress=100 if final_status == JobStatus.COMPLETED else latest.progress,
                current_frame=None,
                sample_current=None,
                sample_total=None,
                completed_frames=completed,
                error=error,
                finished_at=utc_now(),
                elapsed_seconds=time.monotonic() - started,
                eta_seconds=0 if final_status == JobStatus.COMPLETED else None,
                log_tail=log_tail,
            )
        except Exception as exc:
            latest = await asyncio.to_thread(self.store.get_job, job.id)
            if latest.status not in TERMINAL_STATUSES:
                await write_status(
                    status=JobStatus.FAILED,
                    error=f"Unable to run Blender: {exc}",
                    finished_at=utc_now(),
                    sample_current=None,
                    sample_total=None,
                    elapsed_seconds=time.monotonic() - started,
                    log_tail=log_tail,
                )
        finally:
            if elapsed_task is not None:
                elapsed_task.cancel()
                with suppress(asyncio.CancelledError):
                    await elapsed_task
            self._process = None
            self._current_job_id = None

    async def _record_elapsed(self, job_id: str, started: float) -> None:
        while True:
            await asyncio.sleep(ELAPSED_UPDATE_INTERVAL_SECONDS)
            await asyncio.to_thread(
                self.store.update_job,
                job_id,
                elapsed_seconds=time.monotonic() - started,
            )

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


def _event_sample_progress(event: dict[str, object]) -> tuple[int | None, int | None]:
    current = event.get("sample_current")
    total = event.get("sample_total")
    if (
        not isinstance(current, int)
        or isinstance(current, bool)
        or not isinstance(total, int)
        or isinstance(total, bool)
        or current < 0
        or total <= 0
        or current > total
    ):
        return None, None
    return current, total


def _summarize_failure(log_tail: str, return_code: int) -> str:
    lines = [line.strip() for line in log_tail.splitlines() if line.strip()]
    useful = next(
        (line for line in reversed(lines) if "Error" in line or "Traceback" in line),
        lines[-1] if lines else "No renderer output was produced.",
    )
    return f"Blender exited with code {return_code}: {useful}"[:1000]
