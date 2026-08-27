# =============================================================================
# Cognee API backend -- built from this repository's own cognee source.
#
# Based on upstream topoteretes/cognee Dockerfile (commit 252f2c3, v1.3.0).
# Fork deviations:
#   * A dedicated non-root user + group-0 permissions (chmod g=u) so the image
#     runs under OpenShift's arbitrary-UID SCCs and plain docker-compose alike,
#     mirroring the frontend image.
#   * /app/cognee-storage is pre-created as the writable data root (the k8s
#     deployment mounts a PVC there; docker-compose mounts a named volume).
#
# Build from the repo root:
#   docker build -t cognee-api .
# =============================================================================

# Use a Python image with uv pre-installed
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS uv

# Install the project into `/app`
WORKDIR /app

# Enable bytecode compilation: without it the venv ships no .pyc files, so
# every container cold start recompiles the entire dependency tree from
# source (measured upstream: ~8s of a ~13s import, halving startup).
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Tolerate slow registries/mirrors (default 30s aborts large wheels on
# flaky networks).
ENV UV_HTTP_TIMEOUT=120

# Set build argument
ARG DEBUG

# Set environment variable based on the build argument
ENV DEBUG=${DEBUG}

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    git \
    curl \
    cmake \
    clang \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml and lockfile first for better caching
COPY README.md pyproject.toml uv.lock entrypoint.sh LICENSE NOTICE.md ./

# Install the project's dependencies using the lockfile and settings
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --extra debug --extra api --extra postgres --extra neo4j --extra llama-index --extra ollama --extra mistral --extra groq --extra anthropic --frozen --no-install-project --no-dev --no-editable

# Then, add the rest of the project source code and install it
# Installing separately from its dependencies allows optimal layer caching
COPY ./cognee /app/cognee
COPY ./distributed /app/distributed
COPY ./cognee_db_workers /app/cognee_db_workers
# Compatibility shim that re-exports ladybug under the legacy `kuzu`
# module name. Listed in [tool.hatch.build.targets.wheel] packages, and
# imported at module load by alembic/versions/b9274c27a25a_kuzu_11_migration.py.
COPY ./kuzu /app/kuzu
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --extra debug --extra api --extra postgres --extra neo4j --extra llama-index --extra ollama --extra mistral --extra groq --extra anthropic --frozen --no-dev --no-editable

# Prepare the tree for the runtime stage HERE, so the final image gets it in
# a single COPY layer (a runtime-stage `RUN chown/chmod -R` would re-store
# the whole venv in an extra layer, ~doubling the image):
#   * strip Windows carriage returns from entrypoint.sh
#   * group-0 gets owner-equal rights (OpenShift arbitrary-UID SCCs)
#   * /app/cognee-storage pre-created as the data-root mount point
#     (PVC in k8s, named volume in docker-compose)
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh \
    && mkdir -p /app/cognee-storage \
    && chmod -R g=u /app

FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user; ownership is applied by COPY --chown below (uid 1000, gid 0).
RUN groupadd --system --gid 1000 cognee \
    && useradd --system --uid 1000 --gid cognee --no-create-home --shell /usr/sbin/nologin cognee

WORKDIR /app

COPY --from=uv --chown=1000:0 /app /app

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

USER cognee

ENTRYPOINT ["/app/entrypoint.sh"]
