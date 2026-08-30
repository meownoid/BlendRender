# Deployment and operations

## Shared RunPod deployment

Deploy the same image to every peer Pod and attach the same Secure Cloud network volume during Pod
creation. RunPod mounts that volume at `/workspace`; BlendRender stores its v2 workspace in
`/workspace/blendrender` by default. All peer Pods must run the same BlendRender version and have a
common `APP_PASSWORD` for a consistent operator experience.

Each Pod is a complete dashboard/API instance and renders only jobs created through its own URL.
Use multiple Pod dashboards to run multiple jobs for the same scene in parallel. A network-volume
Pod cannot be stopped, only terminated; terminated-owner jobs remain shared read-only history.

## Production image

The production `Dockerfile` builds the Vite frontend, creates a locked Python environment, and
downloads the pinned Blender 5.2.1 Linux x64 archive with SHA-256 verification. It creates the
shared workspace subdirectory before dropping to UID/GID `10001` under `tini`.

Build and push the required platform explicitly:

```bash
docker buildx build --platform linux/amd64 \
  -t YOUR_REGISTRY/blendrender:2.0.0 --push .
```

Blender 5.2.1 is published for Linux x64 in this build, so the production target is
`linux/amd64` even when the build host is Apple Silicon.

## GitHub Actions and GHCR

The `Test and publish image` workflow runs the unit tests, static checks, and frontend production
build for pull requests, pushes to `main`, and tags beginning with `v`. Pull requests receive only
read access and stop after verification. For trusted pushes, a production container build then
publishes after verification succeeds:

- a push to `main` publishes `ghcr.io/OWNER/REPOSITORY:main`, `:latest`, and `:sha-COMMIT`;
- a version tag publishes `ghcr.io/OWNER/REPOSITORY:TAG` and `:sha-COMMIT`.

Repository and owner names are normalized to lowercase for GHCR. The workflow uses its scoped
`GITHUB_TOKEN`, so no publishing secret is required.

## RunPod configuration

Create a RunPod **Pod**, not a serverless endpoint, with:

- the pushed image;
- configured GHCR credentials if the image is private;
- an RTX-class NVIDIA GPU for OptiX;
- HTTP port `8000`;
- at least 20 GB of container disk, with more for large projects or frame ranges;
- a long, random `APP_PASSWORD`; and
- the same Secure Cloud network volume mounted at `/workspace` as its peer Pods.

Open the node through `https://POD_ID-8000.proxy.runpod.net`. Keep `COOKIE_SECURE=true` behind the
RunPod HTTPS proxy.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_PASSWORD` | required | Operator password and cookie-signing source |
| `WORKSPACE_ROOT` | `/workspace/blendrender` | Shared scenes, jobs, results, node heartbeats, and telemetry |
| `BLENDRENDER_POD_ID` | `RUNPOD_POD_ID`, then hostname | Development override for Pod ownership |
| `BLENDER_BIN` | `/opt/blender/blender` | Blender executable |
| `RENDERER_SCRIPT` | bundled renderer | Blender-side runner |
| `MAX_UPLOAD_GB` | `5` | Upload and extracted ZIP limit |
| `COOKIE_SECURE` | `true` | Restrict cookies to HTTPS |
| `AVAILABLE_BACKENDS` | probe | Development/test backend override |

The container starts as root only long enough to create and own its workspace subdirectory, then
drops to UID/GID `10001`. Preserve `/workspace/blendrender`; container disk is suitable only for
temporary files and archive responses.

## Health and verification

`/healthz` checks the web process. `/readyz` requires Blender and at least one usable backend.
`/api/system` and `/api/system/telemetry` describe the Pod serving that URL, not a fleet aggregate.

Build with `just docker-build`. Before release, attach one network volume to two real Pods, upload a
scene once, create same-frame jobs through both dashboards, and confirm both distinct result
variants appear from each Pod URL.
