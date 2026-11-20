import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const base = process.env.CLIPPER_BACKEND_URL;
  const token = process.env.CLIPPER_API_TOKEN;
  if (!base || !token || !/^https?:\/\//.test(base)) {
    return NextResponse.json({ detail: "Processing backend is not configured" }, { status: 503 });
  }
  const { path } = await context.params;
  if (!path?.length || path.some((part) => part === "." || part === "..")) {
    return NextResponse.json({ detail: "Invalid API path" }, { status: 400 });
  }
  const allowed = path[0] === "jobs" && (
    (path.length === 1 && request.method === "POST") ||
    (path.length === 2 && path[1] === "from-link" && request.method === "POST") ||
    (path.length === 2 && /^[a-f0-9]{32}$/.test(path[1]) && request.method === "GET") ||
    (path.length === 4 && /^[a-f0-9]{32}$/.test(path[1]) && path[2] === "files" &&
      /^(?:[a-zA-Z0-9_-]+)\.(?:mp4|srt)$/.test(path[3]) && request.method === "GET")
  );
  if (!allowed) return NextResponse.json({ detail: "Not found" }, { status: 404 });
  const target = base.replace(/\/$/, "") + "/api/" + path.map(encodeURIComponent).join("/");
  try {
    const headers = new Headers({ authorization: "Bearer " + token });
    const init: RequestInit = { method: request.method, headers, cache: "no-store", redirect: "manual" };
    if (request.method === "POST") {
      const contentType = request.headers.get("content-type");
      if (contentType) headers.set("content-type", contentType);
      init.body = request.body;
      (init as RequestInit & { duplex: string }).duplex = "half";
    }
    const upstream = await fetch(target, init);
    if (upstream.status >= 300 && upstream.status < 400) {
      return NextResponse.json({ detail: "Unexpected backend redirect" }, { status: 502 });
    }
    const responseHeaders = new Headers();
    for (const name of ["content-type", "content-length", "content-disposition", "accept-ranges", "content-range"]) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    responseHeaders.set("cache-control", "private, no-store");
    return new NextResponse(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch {
    return NextResponse.json({ detail: "Processing backend unavailable" }, { status: 502 });
  }
}
export { forward as GET, forward as POST };
