# syntax=docker/dockerfile:1.7

FROM node:24-bookworm-slim AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.8.14 AS uv

FROM ubuntu:24.04 AS python-builder
ENV DEBIAN_FRONTEND=noninteractive UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY backend/ ./backend/
RUN uv sync --frozen --no-dev --no-editable

FROM ubuntu:24.04 AS runtime
ARG BLENDER_VERSION=5.2.1
ARG BLENDER_SHA256=a31f524fa99a527d3d52b7f5aaa68c34e1a19d5a1c9473f79c5cc610fd5b10e9
ENV DEBIAN_FRONTEND=noninteractive \
    PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    WORKSPACE_ROOT=/workspace/blendrender \
    BLENDER_BIN=/opt/blender/blender \
    RENDERER_SCRIPT=/app/renderer/blendrender_render.py \
    FRONTEND_DIST=/app/frontend/dist

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl xz-utils tini python3 util-linux \
      libegl1 libgl1 libsm6 libx11-6 libxext6 libxfixes3 libxi6 libxkbcommon0 libxrender1 \
      libxxf86vm1 libwayland-client0 \
    && curl -fsSLo /tmp/blender.tar.xz \
      "https://download.blender.org/release/Blender5.2/blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
    && echo "${BLENDER_SHA256}  /tmp/blender.tar.xz" | sha256sum -c - \
    && mkdir -p /opt/blender \
    && tar -xJf /tmp/blender.tar.xz --strip-components=1 -C /opt/blender \
    && rm /tmp/blender.tar.xz \
    && find /opt/blender -type f -name '*.a' -delete \
    && rm -rf /opt/blender/5.2/datafiles/locale \
    && apt-get purge -y --auto-remove curl xz-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=python-builder /app/.venv /app/.venv
COPY backend/ ./backend/
COPY renderer/ ./renderer/
COPY scripts/container-entrypoint.sh ./scripts/container-entrypoint.sh
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist

RUN groupadd --gid 10001 blendrender \
    && useradd --uid 10001 --gid blendrender --no-create-home --shell /usr/sbin/nologin blendrender \
    && chmod 755 /app/scripts/container-entrypoint.sh \
    && chown -R blendrender:blendrender /app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]
ENTRYPOINT ["/usr/bin/tini", "--", "/app/scripts/container-entrypoint.sh"]
CMD ["uvicorn", "blendrender.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
