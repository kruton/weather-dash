# syntax=docker.io/docker/dockerfile:1.26-labs

# Build the frontend with Node.js. Node and pnpm are not included in the final
# image.
FROM node:24-slim AS frontend-builder

WORKDIR /frontend
RUN corepack enable

# Install dependencies before copying the source so this layer remains cached
# when only application code changes.
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm run build


# Build the Python virtual environment with uv.
FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim AS python-builder

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY --exclude=frontend . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable \
    && .venv/bin/playwright install --only-shell chromium


# Run the application without the Node or uv build toolchains.
FROM python:3.14-slim-trixie AS runtime

ARG BUILDTIME
ARG VERSION
ARG REVISION

LABEL org.opencontainers.image.title="Weather Dashboard for e-Ink displays" \
      org.opencontainers.image.description="Docker container for deploying Weather Dashboard on e-Ink displays" \
      org.opencontainers.image.url="https://github.com/kruton/weather-dash" \
      org.opencontainers.image.source="https://github.com/kruton/weather-dash" \
      org.opencontainers.image.created="${BUILDTIME}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"

# Runtime libraries required by Chromium.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libasound2 \
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libatspi2.0-0 \
        libcairo2 \
        libcups2 \
        libdbus-1-3 \
        libdrm2 \
        libgbm1 \
        libglib2.0-0 \
        libnspr4 \
        libnss3 \
        libpango-1.0-0 \
        libx11-6 \
        libxcb1 \
        libxcomposite1 \
        libxdamage1 \
        libxext6 \
        libxfixes3 \
        libxkbcommon0 \
        libxrandr2 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=python-builder /app/.venv /app/.venv
COPY --from=python-builder /ms-playwright /ms-playwright
COPY --from=frontend-builder /frontend/dist /app/frontend/dist
COPY log_conf.yaml /app/log_conf.yaml

ENV PATH="/app/.venv/bin:${PATH}" \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

EXPOSE 8000
CMD ["uvicorn", "--host", "0.0.0.0", "weather_dash:app", "--log-config=log_conf.yaml"]
