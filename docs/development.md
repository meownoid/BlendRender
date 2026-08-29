# Development and testing

## Prerequisites

- Python 3.12 or newer
- `uv`
- Node.js 24 or newer and npm
- `just`
- Blender 5.2.1 only when running a real Blender smoke test
- Docker/Colima only for container tests

## First setup

```bash
cp .env.example .env
just install
```

`just install` runs `uv sync` and `npm ci`. Keep `uv.lock` and
`frontend/package-lock.json` in sync with intentional dependency changes.

Start the two development servers in separate terminals:

```bash
just dev-backend
just dev-frontend
```

The backend listens on `http://localhost:8000`; Vite listens on
`http://localhost:5173` and proxies API requests according to `frontend/vite.config.ts`. The Just
recipe supplies a development password of `blendrender-dev`, disables secure cookies for local
HTTP, uses `./data`, invokes `blender` from your `PATH`, and exposes CPU availability. Set
`BLENDER_BIN` when Blender is installed somewhere else.

## Project map

```text
backend/blendrender/       FastAPI service, queue, worker, auth, and system probing
frontend/src/              React application and CSS
renderer/                  Python executed inside Blender
tests/                     Python unit, API, database, and Blender smoke tests
scripts/                   Container E2E driver and Colima orchestration
docs/                      Topic documentation
Dockerfile                 Production multi-stage image
Dockerfile.e2e             macOS/Colima test-only image variant
compose.yaml               Local NVIDIA Docker launch
Justfile                   Supported development commands
```

See [Architecture](architecture.md) before changing the queue, process lifecycle, or on-disk data
layout.

## Verification commands

| Command | Coverage |
| --- | --- |
| `just test` | Python pytest suite, then frontend Vitest suite |
| `just check` | Ruff, strict mypy, ESLint, TypeScript, and production Vite build |
| `just docker-build` | Production `linux/amd64` image build loaded as `blendrender:local` |
| `just e2e-backend` | Real Blender CPU render through the public API in a Colima container |

GitHub Actions runs the equivalent test and check commands for pull requests and trusted pushes.
Pushes to `main` and `v*` tags then build and publish to the repository's private GHCR package
after verification succeeds.

During iteration, narrower commands are useful:

```bash
uv run pytest tests/test_api.py
uv run pytest tests/test_progress.py
cd frontend && npm test -- Dashboard.test.tsx
cd frontend && npm run lint
```

Run the smallest relevant check while editing, then run both `just test` and `just check` before
handing off a behavioral change. A docs-only change does not require application tests, but local
Markdown links should still be checked.

## Test layers and limits

- API and database tests use temporary directories and do not require Blender.
- Progress and database tests exercise event parsing, queue ordering, restart recovery, and schema
  migration.
- Frontend tests use Vitest, Testing Library, and jsdom.
- `tests/test_blender_smoke.py` requires a compatible Blender binary and verifies scene settings
  and rendered output. It skips when Blender is unavailable.
- `just e2e-backend` builds a production-shaped container, uploads
  `tests/fixtures/test.blend`, renders one CPU sample at a reduced resolution, validates PNG, WebP,
  and ZIP downloads, then deletes the job.

Apple Silicon cannot validate NVIDIA passthrough. Run final OptiX and CUDA smoke tests on an RTX
RunPod Pod.

## Code conventions

- Backend code targets Python 3.12, uses strict mypy, and is formatted to a 100-character Ruff
  line length.
- Parse request and process output at their boundaries into the models in `models.py` or small
  typed values. Keep worker internals dependent on those validated invariants.
- The frontend uses React 19 and TypeScript. Shared API shapes belong in `frontend/src/types.ts`;
  network behavior belongs in `frontend/src/lib/api.ts`.
- Keep the Blender-side script dependency-light: it executes in Blender's bundled Python, not the
  application's virtual environment.
- Preserve the one-process, one-render-worker architecture unless the storage and cancellation
  model are deliberately redesigned.

Additional agent-oriented instructions are in [AGENTS.md](../AGENTS.md).
