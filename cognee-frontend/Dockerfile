# =============================================================================
# Cognee dashboard UI (Next.js) — production image.
#
# Based on the upstream cognee frontend. 
# Upstream's own Dockerfile
# only supports `next dev` (no production build) — this one replaces it with
# a proper multi-stage build using Next.js "standalone" output (enabled in
# next.config.mjs) and a non-root runtime, so it doesn't ship node_modules,
# devDependencies, or source in the final image.
#
# The browser reaches the cognee API same-origin (relative /api/v1/... URLs,
# path-split to the API Service by the k8s router — see
# argocd-deployment/*/cognee), so NO backend URL is baked into the JS bundle
# and ONE image serves every environment. The server-side route handlers
# (src/app/api/*) read BACKEND_API_URL at RUNTIME from the Deployment env
# (default http://localhost:8000).
#
# Remaining NEXT_PUBLIC_* build args below are still inlined at `next build`
# time — runtime env vars have no effect on them.
# =============================================================================

FROM node:22-alpine AS deps

WORKDIR /app

RUN apk upgrade --no-cache

COPY package.json package-lock.json ./
RUN npm ci
# Cross-arch/platform native binding mismatch fix (matches upstream Dockerfile).
RUN npm rebuild lightningcss

# -----------------------------------------------------------------------------
# Build stage — produces the standalone server in /app/.next/standalone
# -----------------------------------------------------------------------------
FROM deps AS builder

COPY next.config.mjs postcss.config.mjs tsconfig.json ./
COPY src ./src
COPY public ./public
COPY types ./types

ARG NEXT_PUBLIC_IS_CLOUD_ENVIRONMENT=false
# Optional: only needed if the Cognee API requires an API key (it doesn't
# when ENABLE_BACKEND_ACCESS_CONTROL=false, the default in this deployment).
# WARNING: baked into the publicly served JS bundle — never pass a secret.
ARG NEXT_PUBLIC_COGWIT_API_KEY=""
# Proxy target for the /api/v1 (+ /health, /docs, /openapi.json) rewrites in
# next.config.mjs — Next.js resolves rewrite destinations at BUILD time. Only
# reached when no router path-splits those paths in front of this server:
# in Kubernetes the router handles them, so the default is irrelevant there;
# docker-compose (no router) overrides this with http://cognee-api:8000.
ARG BACKEND_API_URL=http://localhost:8000

ENV NEXT_PUBLIC_IS_CLOUD_ENVIRONMENT=${NEXT_PUBLIC_IS_CLOUD_ENVIRONMENT}
ENV NEXT_PUBLIC_COGWIT_API_KEY=${NEXT_PUBLIC_COGWIT_API_KEY}
ENV BACKEND_API_URL=${BACKEND_API_URL}
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# -----------------------------------------------------------------------------
# Production stage — minimal standalone Next.js server, non-root
# -----------------------------------------------------------------------------
FROM node:22-alpine AS production

RUN apk upgrade --no-cache

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

# Grant the root group (GID 0, assigned by OpenShift SCCs to all containers)
# write access, mirroring the other images in this fork. The
# standalone server itself only needs to read these files, but Next.js writes
# an on-disk cache under .next/cache at runtime.
RUN chown -R node:0 /app && chmod -R g=u /app

# node:*-alpine ships a built-in non-root "node" user (UID 1000). OpenShift
# will override the UID with an arbitrary value but keeps GID 0, so the group
# permissions above apply either way.
USER node

EXPOSE 3000

CMD ["node", "server.js"]
