# AGENTS.md

This file contains repository-specific guidance for coding agents and contributors working on
BlendRender. Keep changes narrow, preserve unrelated work, and follow the existing Python,
TypeScript, Docker, and Just conventions.

## Read the relevant documentation first

- [Architecture](docs/architecture.md) for queue ownership, process control, state transitions, and
  persistent data.
- [API](docs/api.md) for routes, validation limits, authentication, and response behavior.
- [Development and testing](docs/development.md) for setup, project layout, and verification.
- [Deployment and operations](docs/deployment.md) for the image, environment variables, RunPod,
  health checks, and platform constraints.
- [Security and rendering](docs/security-and-rendering.md) for the trust boundary, Blender launch
  contract, retained settings, and output behavior.

The [documentation index](docs/README.md) and root [README](README.md) should remain synchronized
when a user-facing capability, prerequisite, command, endpoint, or operational behavior changes.

## Architectural invariants

- Production runs one Uvicorn process with one in-process `RenderWorker`; it renders one Blender
  job at a time. Do not increase worker/replica counts without redesigning queue, cancellation, and
  filesystem coordination.
- Job state is stored in SQLite; source projects, configs, logs, outputs, and previews are stored
  under `DATA_ROOT/jobs/{uuid}`.
- Retriable jobs reuse only output files that pass PNG verification. Preserve completed frames on
  cancel, interruption, and retry.
- Blender must continue to launch with background mode, disabled embedded-script auto-execution,
  and a separate process group so cancellation reaches descendants.
- The frontend and API are same-origin in production. Preserve signed HTTP-only cookies,
  cross-origin mutation checks, and existing response security headers.
- The UI intentionally exposes OptiX and CUDA; CPU is supported through the API and test workflow.
- The Blender-side renderer runs in Blender's bundled Python. Do not import application-only
  dependencies there.

## Change locations

| Concern | Primary files |
| --- | --- |
| HTTP validation/routes/static serving | `backend/blendrender/main.py`, `models.py` |
| Queue/state/persistence | `backend/blendrender/db.py`, `worker.py` |
| Authentication/security headers | `backend/blendrender/auth.py`, `main.py` |
| GPU and Blender discovery | `backend/blendrender/system.py` |
| Blender scene/render behavior | `renderer/blendrender_render.py` |
| Browser API types and calls | `frontend/src/types.ts`, `frontend/src/lib/api.ts` |
| Dashboard UI | `frontend/src/components/`, `frontend/src/styles.css` |
| Build/runtime | `Dockerfile`, `Dockerfile.e2e`, `compose.yaml`, `Justfile` |
| Documentation | `README.md`, `docs/` |

When changing an API model, update backend models and validation, frontend types/client behavior,
tests, and `docs/api.md` together. When adding configuration, update `.env.example`,
`docs/deployment.md`, and the appropriate test settings fixture.

## Implementation conventions

- Python targets 3.12 with strict mypy and Ruff's 100-character line length. Prefer explicit types
  and domain models at HTTP, database, environment, and subprocess-output boundaries.
- React code uses TypeScript. Keep shared server shapes in `frontend/src/types.ts` and HTTP details
  in `frontend/src/lib/api.ts`; avoid duplicating request logic in components.
- Keep the Blender event prefix and payload contract compatible with
  `backend/blendrender/progress.py` and `worker.py`, or change producer, parser, and tests together.
- Preserve deterministic frame names and path-safety checks. Never construct destructive targets
  from an unvalidated request value.
- Avoid unrelated dependency, lockfile, formatting, or visual changes.
- Do not commit, push, publish an image, deploy a Pod, or act on external data unless explicitly
  requested.

## Verification

Use the smallest targeted checks while iterating, then broaden in proportion to risk:

```bash
just test
just check
```

- Backend-only changes: run the relevant `uv run pytest ...`, Ruff, and strict mypy.
- Frontend-only changes: run the relevant Vitest file, ESLint, and the production build.
- Renderer changes: run unit tests plus the Blender smoke test when Blender is available; use
  `just e2e-backend` for a production-shaped CPU render when warranted.
- Docker/runtime changes: build the production image; GPU backend validation must occur on an
  NVIDIA host or RunPod RTX Pod.
- Docs-only changes: check local Markdown links and review terminology against the implementation.

Before handoff, review `git diff` for unintended changes and report the checks that ran, checks that
were skipped, and any remaining platform-specific risk.
