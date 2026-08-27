import { NextResponse, type NextRequest } from "next/server";

// Local mode — no Auth0 middleware, just pass through
export function middleware(_request: NextRequest) {
  return NextResponse.next();
}

export const config = {
  // Vendoring deviation from upstream: match only "/" — the sole path this
  // middleware acts on — so it no longer runs for API/asset requests.
  // NOTE: this does NOT exempt proxied bodies from the router's 10MB buffer
  // cap (that applies whenever a middleware file exists, matcher or not);
  // the cap itself is raised via experimental.proxyClientMaxBodySize in
  // next.config.mjs.
  matcher: ["/"],
};
