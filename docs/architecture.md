# Architecture

BlendRender packages the browser UI, HTTP API, persistent queue, and Blender subprocess runner in
one container. The production process intentionally uses one Uvicorn worker so that one in-process
render worker owns the queue.

## Components

| Area | Location | Responsibility |
| --- | --- | --- |
| React frontend | `frontend/src/` | Authentication screen, node status, job creation, polling, previews, and downloads |
| FastAPI application | `backend/blendrender/main.py` | HTTP routes, validation, security headers, upload/download handling, and static frontend serving |
| Session handling | `backend/blendrender/auth.py` | Password verification, signed cookies, rate limiting, and cross-origin mutation checks |
| SQLite store | `backend/blendrender/db.py` | Job state, queue ordering, progress, errors, restart recovery, and telemetry history |
| Render worker | `backend/blendrender/worker.py` | Single-job scheduling, Blender process control, log parsing, preview generation, cancel, and retry |
| System probe | `backend/blendrender/system.py` | Blender version, host CPU/RAM and NVIDIA telemetry, render backend detection, disk usage, and readiness |
| Telemetry collector | `backend/blendrender/telemetry.py` | Server-owned CPU, GPU, memory, and VRAM sampling with rolling SQLite retention |
| Blender-side runner | `renderer/blendrender_render.py` | Scene validation, Cycles/device configuration, frame rendering, and structured progress events |
| Production image | `Dockerfile` | Frontend build, Python environment, pinned Blender runtime, non-root user, and process entrypoint |

## Request and render flow

1. The browser authenticates with `APP_PASSWORD`; the API returns a signed, HTTP-only session
   cookie.
2. A job submission streams a `.blend` upload into `DATA_ROOT/jobs/{job-id}/input.blend`, validates
   its request fields, and inserts a queued SQLite row.
3. `RenderWorker` atomically claims the oldest queued job and writes `render-config.json`.
4. Blender starts in background mode with `--disable-autoexec` and executes the Blender-side
   runner against the uploaded scene.
5. The runner emits `BLENDRENDER_EVENT` JSON lines. The worker also parses Blender sample output,
   stores progress, current/total frame samples, and a bounded log tail, and appends the complete
   output to `render.log`.
6. Each frame-completion event causes the PNG to be checked with Pillow. A maximum 720×480 WebP
   preview is generated for a valid output frame.
7. The telemetry collector samples the node every 5 seconds while jobs are queued or running and
   every 10 seconds otherwise, retaining the latest 15 minutes in SQLite. The frontend polls jobs,
   system information, and that server-owned history every 1.5 seconds while work is active and
   every 8 seconds while idle.

## Job lifecycle

Jobs move through these states:

- `queued` → `running` → `completed`
- `queued` or `running` → `canceled`
- `running` → `failed` when Blender or post-processing fails
- `running` → `interrupted` when the application stops or restarts
- `failed`, `canceled`, or `interrupted` → `queued` on retry

Canceling a running job sends `SIGTERM` to its process group. If it has not stopped within
`CANCEL_GRACE_SECONDS`, the worker sends `SIGKILL`. Retry scans and verifies existing PNGs, records
them as complete, and renders only missing or invalid frames.

Deleting is allowed only in a terminal state. It removes both the database row and the job's files.

## Persistence layout

The default data root is `/var/lib/blendrender`:

```text
/var/lib/blendrender/
├── blendrender.sqlite3
└── jobs/
    └── {job-id}/
        ├── input.blend
        ├── render-config.json
        ├── render.log
        ├── outputs/frame_000001.png
        └── previews/frame_000001.webp
```

SQLite uses WAL mode. During application startup, database rows left in `running` are marked
`interrupted`. The database also retains the most recent 15 minutes of node telemetry. Files remain
available, allowing a later retry to reuse valid frames.

The RunPod setup deliberately does not require a persistent volume. Mount or preserve `DATA_ROOT`
only if job history and rendered files must survive replacement of the Pod filesystem.

## Important scaling boundary

The queue is designed for one application process and one Blender subprocess at a time. Do not
increase Uvicorn's worker count or run multiple application replicas against the same data root:
each process would create its own render worker, cancel ownership is in memory, and the filesystem
layout is not a distributed coordination mechanism.

To scale, run independent BlendRender nodes with separate data roots and route work to them outside
this application.
