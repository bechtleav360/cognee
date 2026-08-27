/** @type {import('next').NextConfig} */
const nextConfig = {
  // Vendoring deviation from upstream: emits a minimal, self-contained
  // .next/standalone server (only the production deps actually used) so the
  // production Docker image doesn't need to ship node_modules or the
  // source tree — see Dockerfile.
  output: "standalone",
  // Vendoring deviation from upstream: while a middleware file exists, the
  // router buffers proxied (rewritten) request bodies with a 10MB default
  // cap — regardless of the middleware matcher — truncating large
  // /api/v1/remember uploads and killing them with ECONNRESET. The runtime
  // reads experimental.proxyClientMaxBodySize (resolve-routes.js); the
  // top-level/deprecated middlewareClientMaxBodySize spelling is ignored.
  experimental: {
    proxyClientMaxBodySize: "512mb",
  },
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "lh3.googleusercontent.com",
      },
    ],
  },
  // The browser reaches the cognee API same-origin (relative /api/v1/...
  // URLs). In Kubernetes the router splits those paths off to the API
  // Service before they reach this server (see argocd-deployment/*/cognee);
  // these rewrites cover whatever still lands here — chiefly `next dev`
  // against a backend on localhost:8000.
  // NOTE: BACKEND_API_URL is resolved at BUILD time here (Next.js serializes
  // rewrites into the build output). Only the route handlers under
  // src/app/api/ read it at runtime.
  async rewrites() {
    const backendApiUrl = process.env.BACKEND_API_URL || "http://localhost:8000";
    return [
      { source: "/api/v1/:path*", destination: `${backendApiUrl}/api/v1/:path*` },
      { source: "/health", destination: `${backendApiUrl}/health` },
      { source: "/docs", destination: `${backendApiUrl}/docs` },
      { source: "/openapi.json", destination: `${backendApiUrl}/openapi.json` },
    ];
  },
};

export default nextConfig;
