set dotenv-load := true

install:
    uv sync
    cd frontend && npm ci

dev-backend:
    APP_PASSWORD=${APP_PASSWORD:-blendqueue-dev} COOKIE_SECURE=false AVAILABLE_BACKENDS=OPTIX,CUDA DATA_ROOT=./data uv run uvicorn blendqueue.main:app --reload --port 8000

dev-frontend:
    cd frontend && npm run dev

test:
    uv run pytest
    cd frontend && npm test

check:
    uv run ruff check backend tests renderer
    uv run mypy backend/blendqueue
    cd frontend && npm run lint && npm run build

docker-build:
    docker buildx build --platform linux/amd64 --load -t blendqueue:local .
