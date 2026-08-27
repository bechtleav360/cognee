import { NextResponse } from "next/server";

// Server-side only, so read at RUNTIME (no NEXT_PUBLIC_ prefix = not inlined
// at build). In Kubernetes this points at the in-cluster Service.
const localApiUrl = process.env.BACKEND_API_URL || "http://localhost:8000";

export async function GET(request: Request) {
  // Call the local backend's logout endpoint to invalidate the session
  try {
    await fetch(`${localApiUrl}/api/v1/auth/logout`, {
      method: "POST",
      headers: {
        cookie: request.headers.get("cookie") || "",
      },
    });
  } catch {
    // Backend might be down — still clear cookies and redirect
  }

  // Clear the fastapiusersauth cookie and redirect to local login
  const response = NextResponse.redirect(new URL("/local-login", request.url));
  response.cookies.set("fastapiusersauth", "", {
    maxAge: 0,
    path: "/",
  });
  return response;
}
