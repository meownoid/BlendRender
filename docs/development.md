# Development and testing

## Prerequisites

- Python 3.12+, `uv`, and `just`.
- Node.js 24+ and npm.
- Blender 5.2.1 for real renders and smoke tests.
- Docker and Colima for the container E2E workflow.

## Local setup

```bash
git submodule update --init --recursive
cp .env.example .env
just install
```

Edit `.env`: set `APP_PASSWORD` and change `WORKSPACE_ROOT` to `./workspace` for local development.
Set `BLENDER_BIN` if Blender is not available as `blender` on your `PATH`.

Start the servers in separate terminals:

```bash
just dev-backend
```

```bash
just dev-frontend
```

Open `http://localhost:5173` and sign in with the password from `.env`. The frontend proxies API
requests to `http://localhost:8000`. The backend recipe uses Pod ID `local`, enables CPU rendering,
and disables secure cookies for local HTTP. It advertises CPU availability even if Blender is not
installed; actual renders still require Blender.

The FLIP Fluids submodule is compiled by the Dockerfiles. Local Blender needs a compatible add-on
installed separately to render FLIP caches; see [Rendering](rendering.md#flip-fluids).

## Checks

| Command | Coverage |
| --- | --- |
| `just test` | Python pytest and frontend Vitest suites |
| `just check` | Ruff, strict mypy, ESLint, TypeScript, and production frontend build |
| `just docker-build` | Production `linux/amd64` image, loaded as `blendrender:local` |
| `just e2e-backend` | Real Blender CPU render through the API in a Colima container |

For targeted checks, run from the repository root:

```bash
uv run pytest tests/test_api.py
npm test --prefix frontend -- NewJobPanel.test.tsx
```

API and workspace tests use temporary directories and do not need Blender. Blender smoke tests
skip when no binary is configured or found on `PATH`. The container E2E test checks a CPU render and PNG,
WebP, and ZIP downloads. OptiX and CUDA need verification on an NVIDIA host or RTX RunPod Pod.

Run the smallest relevant checks while editing, then `just test` and `just check` for behavioral
changes. For documentation-only edits, check local links and accuracy against the code.

## Project layout

| Path | Contents |
| --- | --- |
| `backend/blendrender/` | API, authentication, workspace, and render worker |
| `frontend/src/` | React dashboard and API client |
| `renderer/` | Scripts executed in Blender's bundled Python |
| `scripts/` | S3 utilities, container entrypoint, and E2E tools |
| `tests/` | Backend and Blender tests; frontend tests live beside components |
| `docs/` | User guides and technical reference |
| `Justfile` | Development and verification commands |

Keep dependency lockfiles synchronized. Use typed boundary models, strict mypy, and Ruff's
100-character line length for Python; keep shared frontend API types in `frontend/src/types.ts`.
Do not import application-only dependencies into Blender scripts.

See [Architecture](architecture.md) before changing storage or process control, and
[AGENTS.md](../AGENTS.md) for contribution guidance. CI and image publishing are described in
[Deployment](deployment.md#automated-publishing).
