# Deployment and operations

## Production image

The production `Dockerfile` builds the Vite frontend, creates a locked Python environment, downloads
the pinned Blender 5.2.1 Linux x64 archive with SHA-256 verification, and runs the final container as
UID/GID `10001` under `tini`.

Build and push the required platform explicitly:

```bash
docker buildx build --platform linux/amd64 \
  -t YOUR_REGISTRY/blendrender:0.1.0 --push .
```

Blender 5.2.1 is published for Linux x64 in this build, so the production target is
`linux/amd64` even when the build host is Apple Silicon.

## RunPod configuration

Create a RunPod **Pod**, not a serverless endpoint, with:

- the pushed image;
- an RTX-class NVIDIA GPU for OptiX;
- HTTP port `8000`;
- at least 20 GB of container disk, with more for large projects or frame ranges;
- a long, random `APP_PASSWORD`; and
- no persistent volume when ephemeral jobs are acceptable.

Open the node through `https://POD_ID-8000.proxy.runpod.net`. Keep `COOKIE_SECURE=true` behind the
RunPod HTTPS proxy.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_PASSWORD` | None; required | Shared operator password and source material for signing sessions |
| `DATA_ROOT` | `/var/lib/blendrender` | SQLite database, uploaded projects, outputs, previews, configs, and logs |
| `BLENDER_BIN` | `/opt/blender/blender` | Blender executable |
| `RENDERER_SCRIPT` | Repository `renderer/blendrender_render.py` | Python entrypoint executed inside Blender |
| `FRONTEND_DIST` | Repository `frontend/dist` | Static frontend directory served by FastAPI |
| `MAX_UPLOAD_GB` | `5` | Maximum streamed upload size in GiB; decimal values are accepted |
| `COOKIE_SECURE` | `true` | Whether the session cookie is restricted to HTTPS |
| `SESSION_TTL_SECONDS` | `604800` | Signed session maximum age (7 days by default) |
| `CANCEL_GRACE_SECONDS` | `8` | Wait after `SIGTERM` before force-killing Blender |
| `AVAILABLE_BACKENDS` | Probe automatically | Comma-separated `OPTIX`, `CUDA`, and/or `CPU` override, mainly for development/tests |

Do not set `AVAILABLE_BACKENDS` in production merely to make the UI show an unavailable GPU. It
bypasses capability probing; Blender will still fail when the worker tries to enable that backend.

## Storage and capacity

Every job stores the original `.blend`, its full render log, output PNGs, and WebP previews below
`DATA_ROOT`. A submission is refused when less than 1 GiB is free before the upload starts, but the
application does not reserve space for the upload or render.

Use container disk for the intended ephemeral model. If data must survive Pod replacement, mount a
writable volume at `DATA_ROOT` and back it up as one unit. Do not share that directory between
multiple running BlendRender instances.

Deleting a terminal job through the dashboard or API is the supported way to reclaim its files.

## Health and diagnostics

- `GET /healthz` reports process liveness and is the image `HEALTHCHECK` target.
- `GET /readyz` reports readiness after startup probing finds Blender and at least one backend.
- `GET /api/system` reports the Blender version, host CPU/RAM, NVIDIA utilization/VRAM, available
  backends, and disk capacity; it requires authentication.
- Per-job `render.log` contains full Blender output. The API job object contains only the last
  12,000 characters as `log_tail`.

Backend probing happens at application startup. Restart the container after changing drivers,
hardware, Blender, or backend-related configuration.

The application command must remain a single Uvicorn worker. See the
[architecture scaling boundary](architecture.md#important-scaling-boundary).

## Local NVIDIA Docker

Local GPU execution requires Linux, Docker Compose 2.30 or newer, a compatible NVIDIA driver, and
NVIDIA Container Toolkit:

```bash
cp .env.example .env
# Set APP_PASSWORD in .env, then:
docker compose up --build
```

The included Compose file publishes port `8000`, requests all GPUs, and sets
`COOKIE_SECURE=false` for direct local HTTP. Do not copy that cookie setting to an HTTPS deployment.

## Container E2E on macOS

`just e2e-backend` manages a dedicated Colima profile, builds the frontend natively, builds the
production-shaped test image, runs it, performs a real CPU render, and cleans up the container. Its
main overrides are:

| Variable | Default | Purpose |
| --- | --- | --- |
| `BLENDRENDER_E2E_ARCH` | Host architecture | Colima VM architecture: `aarch64` or `x86_64` |
| `BLENDRENDER_E2E_PLATFORM` | `linux/amd64` | Image platform; currently only `linux/amd64` is supported |
| `BLENDRENDER_E2E_PORT` | `18000` | Host port used by the temporary container |
| `BLENDRENDER_E2E_TIMEOUT` | `600` | Maximum render wait in seconds |
| `BLENDRENDER_E2E_KEEP_COLIMA` | `0` | Set to `1` to keep a profile started by the script running |
| `BLENDRENDER_E2E_BLEND` | `tests/fixtures/test.blend` | Fixture uploaded by the test |

CPU container E2E does not prove CUDA or OptiX operation. Validate both desired GPU backends on the
actual RunPod GPU class before release.
