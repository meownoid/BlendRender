set dotenv-load := true

install:
    uv sync
    cd frontend && npm ci

dev-backend:
    APP_PASSWORD=${APP_PASSWORD:-password} \
    COOKIE_SECURE=false \
    BLENDER_BIN=${BLENDER_BIN:-blender} \
    AVAILABLE_BACKENDS=CPU \
    BLENDRENDER_POD_ID=local \
    WORKSPACE_ROOT=${WORKSPACE_ROOT:-/tmp/workspace/} \
    UPLOAD_CHUNK_MB=${UPLOAD_CHUNK_MB:-32} \
    uv run uvicorn blendrender.main:app --reload --port 8000

dev-frontend:
    cd frontend && npm run dev

test:
    uv run pytest
    cd frontend && npm test

check:
    uv run ruff check backend tests renderer scripts
    uv run mypy backend/blendrender
    cd frontend && npm run lint && npm run build

docker-build:
    git submodule update --init --recursive
    docker buildx build --platform linux/amd64 --load -t blendrender:local .

e2e-backend:
    ./scripts/e2e_backend_colima.sh
