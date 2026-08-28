# BlendRender

BlendRender is a self-contained Blender render node for RunPod Pods. One container serves a
React dashboard and FastAPI API, queues one Cycles render at a time, invokes Blender 5.2.1 with
OptiX, CUDA, or CPU, creates WebP previews, and provides PNG or ZIP downloads.

The dashboard exposes OptiX, CUDA, and CPU rendering. Its system control reports live CPU, GPU,
host-memory, and GPU-VRAM telemetry; CPU is also used by the container end-to-end test.

## RunPod quick start

1. Build and push the `linux/amd64` image:

   ```bash
   docker buildx build --platform linux/amd64 \
     -t YOUR_REGISTRY/blendrender:0.1.0 --push .
   ```

2. Create a RunPod **Pod** template with:

   - the image tag built above;
   - HTTP port `8000`;
   - at least 20 GB of container disk;
   - `APP_PASSWORD` set to a long random password; and
   - no volume mount if job data should remain ephemeral.

3. Open `https://POD_ID-8000.proxy.runpod.net` and sign in with `APP_PASSWORD`.

Use an RTX-class NVIDIA GPU for OptiX. The dashboard disables backends that Blender cannot detect.
`GET /healthz` checks the web process; `GET /readyz` succeeds once Blender and at least one render
backend are available.

See [Deployment and operations](docs/deployment.md) for configuration, storage, health checks,
and platform constraints.

## Render contract

- Upload one `.blend` file with all external assets packed into it.
- The active scene and camera are used.
- Resolution, samples, denoising, compositor, and color management are preserved unless an API
  render override is supplied.
- The worker overrides the engine, selected compute backend, requested frames, output location,
  and output format (PNG).
- Embedded Python auto-execution is disabled.
- A single worker renders one job at a time. Verified completed PNGs are skipped on retry.
- Job data lives below `/var/lib/blendrender` and lasts only as long as that filesystem.

Read [Security and rendering](docs/security-and-rendering.md) before exposing a node or accepting
files from other people.

## Local development

Requirements: Python 3.12+, [`uv`](https://docs.astral.sh/uv/), Node.js 24+, and npm. Blender
5.2.1 is optional for ordinary unit tests and required for a real render smoke test.

```bash
cp .env.example .env
just install
```

Run these in separate terminals:

```bash
just dev-backend
just dev-frontend
```

Open `http://localhost:5173`. Add `?demo=1` for the visual QA dataset without starting a render.
Run the normal verification suite with:

```bash
just test
just check
```

Detailed setup, commands, and test boundaries are in
[Development and testing](docs/development.md).

## Documentation

- [Documentation index](docs/README.md)
- [Architecture](docs/architecture.md) — components, data flow, persistence, and job lifecycle
- [API](docs/api.md) — authentication, endpoints, request fields, and examples
- [Development and testing](docs/development.md) — setup, workflows, test layers, and project map
- [Deployment and operations](docs/deployment.md) — RunPod, Docker, configuration, and health
- [Security and rendering](docs/security-and-rendering.md) — trust boundary and scene behavior
- [Design specification](docs/design/design-spec.md) — accepted UI concepts and visual tokens

Contributor and coding-agent guidance is in [AGENTS.md](AGENTS.md).

## API summary

All `/api` routes except the login, logout, and session-inspection routes require the signed session
cookie.

- `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/session`
- `GET /api/system`
- `POST /api/jobs`, `GET /api/jobs`, `GET /api/jobs/{id}`
- `POST /api/jobs/{id}/cancel`, `POST /api/jobs/{id}/retry`, `DELETE /api/jobs/{id}`
- `GET /api/jobs/{id}/frames/{frame}` (`?preview=true` for WebP)
- `POST /api/jobs/{id}/archive`

`POST /api/jobs` accepts `backend=OPTIX|CUDA|CPU` and optional `samples`, `resolution_x`,
`resolution_y`, and `resolution_percentage` multipart fields. See the [API reference](docs/api.md)
for validation rules and curl examples.
