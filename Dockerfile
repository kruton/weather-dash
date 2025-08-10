# syntax=docker.io/docker/dockerfile:1.17-labs
# An example using multi-stage image builds to create a final image without uv.

# First, build the application in the `/app` directory.
# See `Dockerfile` for details.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Install Node.js and pnpm
RUN apt-get update && apt-get install -y nodejs npm
RUN npm install -g pnpm

COPY ./frontend /frontend
# Build the frontend
WORKDIR /frontend
RUN pnpm install
RUN pnpm run build

# Disable Python downloads, because we want to use the system interpreter
# across both images. If using a managed Python version, it needs to be
# copied from the build image into the final image; see `standalone.Dockerfile`
# for an example.
ENV UV_PYTHON_DOWNLOADS=0

WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev
COPY --exclude=frontend . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


# Then, use a final image without uv
FROM python:3.12-slim-bookworm
# It is important to use the image that matches the builder, as the path to the
# Python executable must be the same, e.g., using `python:3.11-slim-bookworm`

ARG BUILDTIME
ARG VERSION
ARG REVISION

LABEL org.opencontainers.image.title="Weather Dashboard for e-Ink displays"
LABEL org.opencontainers.image.description="Docker container for deploying Weather Dashboard on e-Ink displays"
LABEL org.opencontainers.image.url="https://github.com/kruton/weather-dash"
LABEL org.opencontainers.image.source="https://github.com/kruton/weather-dash"
LABEL org.opencontainers.image.created="${BUILDTIME}"
LABEL org.opencontainers.image.version="${VERSION}"
LABEL org.opencontainers.image.revision="${REVISION}"

# Prerequisites for Chromium playwright
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxcb1 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2

# Copy the application from the builder
COPY --from=builder --chown=app:app /app /app
COPY --from=builder --chown=app:app /frontend/dist /app/frontend/dist

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Install Chromium for Playwright
RUN playwright install chromium

# Run the FastAPI application by default
WORKDIR /app
CMD ["uvicorn", "--host", "0.0.0.0", "weather_dash:app", "--log-config=log_conf.yaml"]
