# =============================================================================
# Cognee MCP server -- built from this repository's own cognee source.
#
# Fork deviations from upstream (topoteretes/cognee cognee-mcp/Dockerfile):
#   * cognee is installed from the LOCAL source tree at the repo root instead
#     of PyPI (see [tool.uv.sources] in cognee-mcp/pyproject.toml and the
#     re-locked cognee-mcp/uv.lock), so local patches to cognee/** reach this
#     image and it embeds the same cognee code as the API image. Upstream still
#     resolves cognee from PyPI, so its MCP image can silently drift from its
#     API image.
#   * The build context is therefore the REPO ROOT, not cognee-mcp/ alone, and
#     the repo layout is mirrored under /app so the relative path dependency
#     ("..") resolves identically at build and run time:
#         /app/pyproject.toml, /app/cognee/, ...    <- cognee library source
#         /app/cognee-mcp/                          <- this MCP server
#     The venv lives at /app/cognee-mcp/.venv in BOTH stages so venv shebangs
#     stay valid after the copy into the runtime stage.
#   * Runtime files are owned 1000:0 with `chmod g=u` rather than upstream's
#     cognee:cognee, so an OpenShift arbitrary-UID SCC (random UID, group 0)
#     can write them. Plain docker-compose still matches by owner uid 1000.
#
# Build from the repo root:
#   docker build -f cognee-mcp/Dockerfile -t cognee-mcp .
# =============================================================================

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS uv

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Tolerate slow registries/mirrors: cognee[docs] pulls torch + multi-GB
# NVIDIA CUDA wheels, which abort under uv's default 30s timeout on slow
# networks.
ENV UV_HTTP_TIMEOUT=300

# Set build argument
ARG DEBUG

# Set environment variable based on the build argument
ENV DEBUG=${DEBUG}

# Needed when psycopg2 is built from source via cognee[postgres] in linux images.
# libpq-dev provides pg_config; build-essential provides libc headers and toolchain.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# --- cognee library source (the ".." path dependency) ------------------------
# Metadata first: pyproject.toml + README.md are what hatchling needs to build
# the cognee wheel; the package sources follow.
COPY README.md pyproject.toml LICENSE NOTICE.md /app/
COPY ./cognee /app/cognee
COPY ./distributed /app/distributed
COPY ./cognee_db_workers /app/cognee_db_workers
# Compatibility shim that re-exports ladybug under the legacy `kuzu` module
# name (listed in cognee's [tool.hatch.build.targets.wheel] packages).
COPY ./kuzu /app/kuzu

# --- MCP server ---------------------------------------------------------------
WORKDIR /app/cognee-mcp

# Copy pyproject.toml and lockfile first for better caching
COPY ./cognee-mcp/pyproject.toml ./cognee-mcp/uv.lock ./cognee-mcp/entrypoint.sh ./

# Install the project's dependencies using the lockfile and settings
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --no-editable

# Then, add the rest of the project source code and install it
# Installing separately from its dependencies allows layer caching
COPY ./cognee-mcp /app/cognee-mcp
# Drop in the workspace bundle built by the node stage. Order matters: the
# COPY above brings in `cognee-mcp/src/app_bundles/` (empty in CI/clean clones
# because the bundle is gitignored, or stale on a developer's machine), and
# this COPY then *shadows* it with the freshly-built bundle. uv sync below
# packages this into the wheel installed into the venv; visualize_graph_ui
# reads the bundle from its own neighbor directory inside site-packages.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# Prepare the tree for the runtime stage HERE, so the final image gets it in
# a single COPY layer (a runtime-stage `RUN chown/chmod -R` would re-store
# the whole venv -- torch + CUDA wheels included -- in an extra layer,
# ~doubling an already large image):
#   * strip Windows carriage returns from entrypoint.sh
#   * group-0 gets owner-equal rights (OpenShift arbitrary-UID SCCs)
RUN sed -i 's/\r$//' /app/cognee-mcp/entrypoint.sh && chmod +x /app/cognee-mcp/entrypoint.sh \
    && chmod -R g=u /app

FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user; ownership is applied by COPY --chown below (uid 1000, gid 0).
RUN groupadd --system --gid 1000 cognee \
    && useradd --system --uid 1000 --gid cognee --no-create-home --shell /usr/sbin/nologin cognee

WORKDIR /app/cognee-mcp

# Copy the virtual environment from the uv stage
COPY --from=uv /usr/local /usr/local
# Storage root, matching the API image so both containers share the volumes.
# Owned 1000:0 with g=u for the same arbitrary-UID reason as the tree itself.
RUN mkdir -p /cognee-storage/system /cognee-storage/data \
    && chown -R 1000:0 /cognee-storage \
    && chmod -R g=u /cognee-storage

COPY --from=uv --chown=1000:0 /app /app

# Place executables in the environment at the front of the path
ENV PATH="/app/cognee-mcp/.venv/bin:$PATH"

# Set environment variables for MCP server
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/cognee-mcp
# Give the non-root user a stable, writable HOME so Kuzu/Ladybug caches its
# downloaded extensions in a consistent location across build and runtime.
ENV HOME=/app
ENV SYSTEM_ROOT_DIRECTORY=/cognee-storage/system
ENV DATA_ROOT_DIRECTORY=/cognee-storage/data

# Add labels for API mode usage
LABEL org.opencontainers.image.description="Cognee MCP Server with API mode support (from-source build)"

USER cognee

# Pre-install Kuzu/Ladybug's JSON extension at build time (network is available
# here) so it is baked into the image. Runs the same install path the app uses,
# as the same user with the same HOME, so the cached extension lands exactly
# where the running server looks for it — avoiding the "Extension: json ... has
# not been installed" Binder error when recall runs in a network-restricted
# container. Best-effort: a failed download must not break the image build.
# (Not exercised when GRAPH_DATABASE_PROVIDER=postgres, but kept so the image
# also works with the embedded Ladybug/Kuzu graph store.)
RUN python -c "from cognee_db_workers._kuzu_helpers import install_json_extension_local; install_json_extension_local(buffer_pool_size=268435456)" \
    || echo "WARNING: JSON extension pre-install skipped (no network at build time); it will be installed on first run if the container has network access."

# Use the application name from pyproject.toml for normal operation
# For testing, we'll override this with a direct command
ENTRYPOINT ["/app/cognee-mcp/entrypoint.sh"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD [ "${TRANSPORT_MODE:-stdio}" = "stdio" ] || python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)"
