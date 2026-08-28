# BlendQueue

BlendQueue is a self-contained Blender GPU render node for RunPod Pods. A single container serves the web interface and API, queues one Cycles render at a time, invokes Blender 5.2.1 LTS with OptiX or CUDA, previews completed PNG frames, and provides individual or ZIP downloads.

## RunPod deployment

1. Build and push the `linux/amd64` image to a registry:

   ```bash
   docker buildx build --platform linux/amd64 -t YOUR_REGISTRY/blendqueue:0.1.0 --push .
   ```

2. Create a **Pod** template in RunPod with:

   - Container image: the tag pushed above.
   - HTTP port: `8000`.
   - Container disk: at least 20 GB, increased for large projects or frame ranges.
   - Environment variable `APP_PASSWORD`: a long random password.
   - No volume mount. Job data is deliberately ephemeral and disappears when the Pod is reset.

3. Open `https://POD_ID-8000.proxy.runpod.net` and sign in with `APP_PASSWORD`.

Use an RTX-class NVIDIA GPU for OptiX. The UI disables render backends that Blender cannot detect. `/healthz` reports process health; `/readyz` returns 200 only after Blender and at least one GPU backend are ready.

## Render behavior

- Inputs must be one `.blend` file with external assets packed into it.
- Embedded Python auto-execution is disabled.
- The active scene and camera are used. Resolution, samples, denoising, compositor, and color management are preserved.
- The engine, GPU backend, requested frames, output directory, and PNG format are overridden.
- One job runs at a time. Completed frames survive cancel or an in-place application restart and are skipped on retry.
- Files live under `/var/lib/blendqueue` only for the lifetime of the Pod filesystem.

## Local development

Requirements: Python 3.12+, `uv`, Node 24+, npm, and optionally Blender 5.2.1.

```bash
cp .env.example .env
just install
just dev-backend
just dev-frontend
```

The Vite development server is at `http://localhost:5173`. Add `?demo=1` for the visual QA dataset without starting a GPU render. `COOKIE_SECURE=false` is intentionally used only for local HTTP development.

Run all checks with:

```bash
just test
just check
```

Local Docker GPU execution requires Linux, Docker Compose 2.30+, an NVIDIA driver, and NVIDIA Container Toolkit:

```bash
APP_PASSWORD='replace-me' docker compose up --build
```

Apple Silicon can build the target image with Buildx and run the frontend/backend tests, but cannot validate NVIDIA passthrough. Final OptiX and CUDA smoke tests must run on a RunPod RTX Pod.

## API

All `/api` routes except login/session require the signed session cookie.

- `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/session`
- `GET /api/system`
- `POST /api/jobs`, `GET /api/jobs`, `GET /api/jobs/{id}`
- `POST /api/jobs/{id}/cancel`, `POST /api/jobs/{id}/retry`, `DELETE /api/jobs/{id}`
- `GET /api/jobs/{id}/frames/{frame}` (`?preview=true` for WebP)
- `POST /api/jobs/{id}/archive` with `{ "frames": [1, 2] }` or `{ "frames": null }`

This project is intended for trusted operators. Disabling Blender auto-execution and constraining paths reduces risk, but a Blender process is not a strong hostile multi-tenant sandbox.
