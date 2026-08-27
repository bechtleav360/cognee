import { NextResponse, type NextRequest } from "next/server";

// Local mode — no Auth0 middleware. The one exception: redirect a
// never-onboarded user straight to /onboarding at the server level, before
// any HTML is sent. This closes a gap a client-side check can't: React has
// to mount at least once before an effect can call router.replace, which
// produces a millisecond-scale flash of the dashboard tree (and anything it
// renders) even when the decision itself is fast. Reading a cookie here
// happens before the React tree exists at all.
const ONBOARDING_COOKIE = "cognee-onboarding-complete";

export function middleware(request: NextRequest) {
  if (request.nextUrl.pathname === "/" && !request.cookies.has(ONBOARDING_COOKIE)) {
    return NextResponse.redirect(new URL("/onboarding", request.url));
  }
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
