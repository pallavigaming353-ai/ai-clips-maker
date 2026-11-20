import { NextRequest, NextResponse } from "next/server";

export function middleware(request: NextRequest) {
  const user = process.env.CLIPPER_SITE_USER;
  const password = process.env.CLIPPER_SITE_PASSWORD;
  if (!user || !password) {
    return new NextResponse("Site access is not configured", { status: 503 });
  }
  const authorization = request.headers.get("authorization") || "";
  let valid = false;
  if (authorization.startsWith("Basic ")) {
    try {
      const decoded = atob(authorization.slice(6));
      const separator = decoded.indexOf(":");
      valid = separator >= 0 && decoded.slice(0, separator) === user &&
        decoded.slice(separator + 1) === password;
    } catch { valid = false; }
  }
  if (!valid) {
    return new NextResponse("Authentication required", {
      status: 401,
      headers: { "WWW-Authenticate": 'Basic realm="AI Clips Maker", charset="UTF-8"', "Cache-Control": "no-store" },
    });
  }
  return NextResponse.next();
}

export const config = { matcher: ["/", "/api/:path*"] };
