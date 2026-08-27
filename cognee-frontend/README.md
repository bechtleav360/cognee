# cognee-frontend (fork)

Next.js dashboard UI for this cognee fork. It replaces the upstream
`create-next-app` boilerplate README. The full set of deviations lives in the
`fork/*` branches, one concern each, with the reason in each commit body.

## Development

```bash
npm install
npm run dev            # http://localhost:3000, proxies /api/v1/* to localhost:8000
```

`next dev` uses the rewrites in `next.config.mjs` to reach a locally running
cognee API (`BACKEND_API_URL`, default `http://localhost:8000`).

## Production build / Docker

Upstream only supports `next dev`; this fork ships a production multi-stage
image (see `Dockerfile`) using Next.js `standalone` output with a non-root
runtime:

```bash
# from the repo root
docker build -t cognee-frontend cognee-frontend/
```

In `docker compose` and Kubernetes the browser calls the API same-origin
(`/api/v1/...` on the frontend host) -- no backend URL is baked into the JS
bundle. In k8s the router path-splits API routes to the API Service; in
compose/`next dev` the Next.js rewrites proxy them.

## Fork-specific gotchas

- **Proxied body size**: `experimental.proxyClientMaxBodySize` in
  `next.config.mjs` raises the Next.js proxy's 10MB default body buffer --
  without it, uploads over 10MB are silently truncated. Note the documented
  `middlewareClientMaxBodySize` spelling is ignored by the runtime.
- **Middleware**: `src/middleware.ts` only handles the `/` onboarding
  redirect; its matcher is deliberately narrowed to `/`.
- Server-side route handlers (`src/app/api/...`) read `BACKEND_API_URL` at
  runtime.
