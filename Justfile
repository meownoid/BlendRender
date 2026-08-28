set dotenv-load := true

install:
    uv sync
    cd frontend && npm ci

dev-backend:
    APP_PASSWORD=${APP_PASSWORD:-blendrender-dev} COOKIE_SECURE=false AVAILABLE_BACKENDS=CPU DATA_ROOT=./data uv run uvicorn blendrender.main:app --reload --port 8000

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
    docker buildx build --platform linux/amd64 --load -t blendrender:local .

e2e-backend:
    ./scripts/e2e_backend_colima.sh
