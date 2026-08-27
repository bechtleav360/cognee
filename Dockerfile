# =============================================================================
# Cognee API backend -- built from this repository's own cognee source.
#
# Based on upstream topoteretes/cognee Dockerfile.
# Fork deviation, now a single concern:
#   * Upstream already ships a non-root user and a pre-created /cognee-storage,
#     but owns both as cognee:cognee (gid 1000). An OpenShift arbitrary-UID SCC
#     assigns a random UID whose only group is 0, so that ownership is not
#     writable. This image owns the tree and the storage root 1000:0 with
#     `chmod g=u` instead, which works under both: plain docker-compose matches
#     by owner (uid 1000), OpenShift matches by group.
#   * Storage lives at upstream's /cognee-storage (system/ and data/), NOT the
#     /app/cognee-storage this fork used before v1.5 -- the k8s PVC mountPath
#     and the compose volume must follow when this branch reaches deploy.
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

# Additional optional-dependency groups to install, separated by spaces.
# Example: docker build --build-arg COGNEE_EXTRAS="aws langchain" .
# Keep this applied to both sync steps: the second exact sync would otherwise
# remove extras installed only in the dependency-cache layer.
ARG COGNEE_EXTRAS=""

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
    set -eu; \
    set -f; \
    set --; \
    for extra in ${COGNEE_EXTRAS}; do \
        set -- "$@" --extra "$extra"; \
    done; \
    uv sync "$@" --extra fastembed --extra debug --extra api --extra postgres --extra neo4j --extra llama-index --extra aws --extra ollama --extra mistral --extra groq --extra anthropic --frozen --no-install-project --no-dev --no-editable

# Then, add the rest of the project source code and install it
# Installing separately from its dependencies allows optimal layer caching
COPY ./cognee /app/cognee
COPY ./cognee_db_workers /app/cognee_db_workers
# Compatibility shim that re-exports ladybug under the legacy `kuzu`
# module name. Listed in [tool.hatch.build.targets.wheel] packages, and
# imported at module load by alembic/versions/b9274c27a25a_kuzu_11_migration.py.
COPY ./kuzu /app/kuzu
RUN --mount=type=cache,target=/root/.cache/uv \
    set -eu; \
    set -f; \
    set --; \
    for extra in ${COGNEE_EXTRAS}; do \
        set -- "$@" --extra "$extra"; \
    done; \
    uv sync "$@" --extra fastembed --extra debug --extra aws --extra api --extra postgres --extra neo4j --extra llama-index --extra ollama --extra mistral --extra groq --extra anthropic --frozen --no-dev --no-editable

# Fork deviation: grant group 0 owner-equal rights across the tree HERE, in the
# builder, so the runtime picks it up in the single COPY layer below. Doing it in
# the runtime stage would re-store the whole venv in an extra layer, roughly
# doubling the image. Group 0 is what OpenShift arbitrary-UID SCCs run as.
RUN chmod -R g=u /app

FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user; ownership is applied by COPY --chown below (uid 1000, gid 0).
RUN groupadd --system --gid 1000 cognee \
    && useradd --system --uid 1000 --gid cognee --no-create-home --shell /usr/sbin/nologin cognee

WORKDIR /app

# Fork deviation from upstream: upstream owns these cognee:cognee (gid 1000),
# which an OpenShift arbitrary-UID SCC cannot write -- it assigns a random UID
# whose only group is 0. Owning them 1000:0 with g=u satisfies both runtimes:
# plain Docker runs as uid 1000 and matches by owner, OpenShift matches by group.
# The user itself is created above, before WORKDIR -- do not re-create it here.
# ``chown 1000:0 /app`` (the directory inode only): WORKDIR created /app as root,
# and ``COPY --chown`` sets ownership on the copied content, not the pre-existing
# target dir -- without this the non-root user cannot create ``$HOME/.lbdb`` and
# the build-time extension pre-install silently fails.
RUN mkdir -p /cognee-storage/system /cognee-storage/data \
    && chown -R 1000:0 /cognee-storage \
    && chmod -R g=u /cognee-storage \
    && chown 1000:0 /app \
    && chmod g=u /app

COPY --from=uv --chown=1000:0 /app /app

# Strip Windows carriage returns (fixes "no such file" on Windows Docker)
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
# Writable HOME for the non-root user (~/.cognee logs, tool caches).
ENV HOME=/app
# Default storage OUTSIDE the source tree: the ./cognee bind mount exists for
# dev reload and must not double as the persistence location (host-uid
# sensitive, pollutes the checkout, and was shared with the MCP container by
# accident rather than by design). docker-compose mounts named volumes here.
ENV SYSTEM_ROOT_DIRECTORY=/cognee-storage/system
ENV DATA_ROOT_DIRECTORY=/cognee-storage/data

USER cognee

# Pre-install Kuzu/Ladybug's JSON extension at build time (network is available
# here) so it is baked into the image — same mechanism as the cognee-mcp
# image. As root the server used to INSTALL it at runtime into /root/.lbdb on
# every boot; as the non-root user that runtime install races between graph
# workers and fails ("Directory ... cannot be created"). Best-effort: a failed
# download must not break the image build.
RUN python -c "from cognee_db_workers._kuzu_helpers import install_json_extension_local; install_json_extension_local(buffer_pool_size=268435456)" \
    || echo "WARNING: JSON extension pre-install skipped (no network at build time); it will be installed on first run if the container has network access."

ENTRYPOINT ["/app/entrypoint.sh"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1
