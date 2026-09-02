# Deployment and operations

## Build the image

The production image includes the dashboard, API, Blender 5.2.1, and FLIP Fluids Demo v1.8.8.
Build for `linux/amd64`, including when building on Apple Silicon:

```bash
git submodule update --init --recursive
docker buildx build --platform linux/amd64 -t YOUR_REGISTRY/blendrender:2.1.0 --push .
```

To build locally without publishing, use `just docker-build`.

## Configure RunPod

Create a Secure Cloud Pod with:

- Your published image and registry credentials if the image is private.
- An RTX-class NVIDIA GPU for OptiX and HTTP port `8000` exposed.
- At least 20 GB of container disk for the image and temporary downloads.
- A network volume mounted at `/workspace`.
- A long, random `APP_PASSWORD` and `COOKIE_SECURE=true`.

Open `https://POD_ID-8000.proxy.runpod.net` and sign in with `APP_PASSWORD`.

For multiple Pods, use the same image version, network volume, workspace path, and password.
Create jobs through each Pod's dashboard to render in parallel. Each Pod runs one application
process and one render at a time; jobs are never reassigned to another Pod.

## Storage

Keep `/workspace/blendrender` on persistent storage. It contains scenes, jobs, results, and Pod
status. Container disk holds temporary files and prepared download archives; allow free space at
least as large as the largest ZIP users may download.

A project ZIP is staged before extraction. At the default upload limit, allow at least 41 GiB free
on the volume for a 20 GiB ZIP and 20 GiB of extracted files, plus space for render results.
Interrupted browser uploads can resume for 24 hours.

The container creates the workspace directory, then runs as UID/GID `10001`. It does not change
volume ownership; the mounted workspace must already permit that user to write.

For direct uploads, downloads, source replacement, and cleanup, use the
[RunPod S3 scripts guide](s3-guide.md).

## Configuration

See [.env.example](../.env.example) for a starting configuration.

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_PASSWORD` | Required | Sign-in password and cookie-signing source |
| `WORKSPACE_ROOT` | `/workspace/blendrender` | Persistent workspace path |
| `COOKIE_SECURE` | `true` | Require HTTPS for session cookies; use `false` only for local HTTP |
| `MAX_UPLOAD_GB` | `20` | Upload and extracted ZIP limit, in GiB |
| `UPLOAD_CHUNK_MB` | `32` | Maximum upload chunk in whole MiB; lower for unreliable connections |

Advanced settings usually need no changes:

| Variable | Default | Purpose |
| --- | --- | --- |
| `BLENDRENDER_POD_ID` | `RUNPOD_POD_ID`, then hostname | Override the job owner ID; keep unique per Pod |
| `BLENDER_BIN` | `/opt/blender/blender` | Blender executable |
| `RENDERER_SCRIPT` | Bundled renderer | Blender render script |
| `FRONTEND_DIST` | Bundled `frontend/dist` | Built dashboard directory |
| `FLIP_FLUIDS_ADDON` | `flip_fluids_addon` in the image | Add-on enabled before opening a scene; unset for local development |
| `FLIP_FLUIDS_BOOTSTRAP_SCRIPT` | Bundled bootstrap | Script that enables the configured add-on |
| `SESSION_TTL_SECONDS` | `604800` | Session lifetime: seven days |
| `CANCEL_GRACE_SECONDS` | `8` | Wait before force-killing a canceled Blender process |
| `AVAILABLE_BACKENDS` | Auto-detected | Development/test override, such as `CPU` |

## Health checks

| Endpoint | Meaning |
| --- | --- |
| `/healthz` | Web process is running |
| `/readyz` | Blender and a render backend are available; otherwise returns `503` |
| `/api/system` | Current Pod's hardware, backends, and storage; requires sign-in |
| `/api/system/telemetry` | Current Pod's recent performance samples; requires sign-in |

Before release, validate OptiX and CUDA on an NVIDIA host. For shared storage, render the same
scene and frame from two Pods and confirm both results appear in both dashboards.

## Automated publishing

The [GitHub Actions workflow](../.github/workflows/ci.yml) runs tests, static checks, and the frontend
build. Pull requests only verify changes. After successful checks, pushes publish to
`ghcr.io/owner/repository`:

- `main` publishes `:main`, `:latest`, and `:sha-COMMIT`.
- Tags beginning with `v` publish `:TAG` and `:sha-COMMIT`.

Publishing uses the repository's scoped `GITHUB_TOKEN`; no separate publishing secret is required.
