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
  -t YOUR_REGISTRY/blendrender:2.1.0 --push .
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
- at least 20 GB of container disk for the image and temporary archive responses;
- a network volume with at least 41 GiB free when accepting the default maximum project ZIP; and
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
| `MAX_UPLOAD_GB` | `20` | Upload and extracted ZIP limit |
| `UPLOAD_CHUNK_MB` | `8` | Maximum browser upload request size in whole MiB; lower it for slower or less reliable proxies |
| `COOKIE_SECURE` | `true` | Restrict cookies to HTTPS |
| `AVAILABLE_BACKENDS` | probe | Development/test backend override |

The container starts as root only long enough to create its workspace subdirectory, then drops to
UID/GID `10001`. It does not change ownership of `/workspace/blendrender`: a RunPod network volume
can be shared by peer Pods and populated through the S3-compatible API, and its mounted filesystem
may reject ownership changes. Preserve `/workspace/blendrender`; container disk is suitable only
for temporary files and archive responses. A project ZIP is staged and then extracted on the
network volume, so a worst-case 20 GiB compressed project plus 20 GiB extracted project requires
at least 41 GiB free before upload headroom. The dashboard resumes interrupted uploads for 24 hours.

## Preload a scene through RunPod's S3 API

Use `scripts/prepare_runpod_scene.py` to make a local `.blend` or project ZIP appear as a completed
immutable BlendRender scene before starting a Pod. The script validates input using the same project
ZIP rules as normal uploads, writes all source files under the configured workspace, and uploads the
scene manifest only after every source file is present. A Pod therefore sees either no scene or a
render-ready one.

Run it while no BlendRender Pod is writing to the network volume. This direct S3 workflow bypasses
the application's shared-volume locks and must use the same `WORKSPACE_ROOT` as the future Pod. The
default maps `/workspace/blendrender` on the Pod to the `blendrender/` S3 prefix.

Run `uv sync` to install the script's Boto3 dependency, then create a separate RunPod **S3 API key**
and export its credentials along with the network-volume ID and datacenter.
`RUNPOD_NETWORK_VOLUME_ID` is the ID used as the S3 bucket, not the storage display name.
`RUNPOD_S3_REGION` builds the endpoint automatically; set `RUNPOD_S3_ENDPOINT` only to override it.

```bash
export AWS_ACCESS_KEY_ID='user_...'
export AWS_SECRET_ACCESS_KEY='rps_...'
export RUNPOD_NETWORK_VOLUME_ID='NETWORK_VOLUME_ID'
export RUNPOD_S3_REGION='EUR-IS-1'

uv run python scripts/prepare_runpod_scene.py /path/to/project.zip \
  --name 'Final exterior' \
  --upload-workers 8
```

The script logs the generated scene ID before transferring files and prints it again when complete.
If a run is interrupted, rerun the same input with that ID via `--scene-id`; the script inventories
the unfinished scene and skips source files whose paths and byte sizes already match. It refuses to
resume when an existing file differs, an unexpected object is present, or the final scene manifest
has already been published. It never overwrites a completed scene.

Source files upload concurrently, largest first, through a bounded pool of eight S3 requests by
default. Set `--upload-workers` from 1 through 16 to tune the pool for the local connection and
RunPod datacenter; all direct uploads, multipart parts, completion calls, and verification requests
share that limit. Files of at least 50 MiB use 50 MiB multipart parts with up to four part workers
per file. Transfers retain explicitly logged retries for server errors and connection/read timeouts,
completion verification after a timeout, and a final size check.

A ZIP is extracted in a local temporary directory before transfer, so leave enough local temporary
disk space for its unpacked project files. `MAX_UPLOAD_GB` has the same 20 GiB default limit as the
dashboard upload. The Boto3 transfer behavior follows RunPod's
[large-file upload helper](https://github.com/runpod/runpod-s3-examples/blob/main/upload_large_file.py).

## Clear a RunPod network volume

`scripts/clear_runpod_volume.py` removes **every object** in `RUNPOD_NETWORK_VOLUME_ID`, including
BlendRender scenes, jobs, results, and workspace metadata. It also aborts incomplete multipart
uploads left by interrupted transfers. Run it only when no Pod or preparation script is writing to
the volume.

First inspect the scope without making changes:

```bash
uv run --env-file .env -- python scripts/clear_runpod_volume.py --dry-run
```

To delete the volume contents, repeat the configured volume ID as an explicit confirmation:

```bash
uv run --env-file .env -- python scripts/clear_runpod_volume.py \
  --confirm "$RUNPOD_NETWORK_VOLUME_ID"
```

This operation is irreversible. The network volume itself remains; only its stored objects and
incomplete multipart uploads are removed. RunPod currently supports only individual object deletes,
so clearing a volume with many files can take time.

## Health and verification

`/healthz` checks the web process. `/readyz` requires Blender and at least one usable backend.
`/api/system` and `/api/system/telemetry` describe the Pod serving that URL, not a fleet aggregate.

Build with `just docker-build`. Before release, attach one network volume to two real Pods, upload a
scene once, create same-frame jobs through both dashboards, and confirm both distinct result
variants appear from each Pod URL.
