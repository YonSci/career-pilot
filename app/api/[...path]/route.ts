import { env } from "cloudflare:workers";
import { getChatGPTUser } from "@/app/chatgpt-auth";
export const dynamic = "force-dynamic";
async function proxy(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  const user = await getChatGPTUser();
  if (!user)
    return Response.json(
      { detail: "Sign in to your private workspace." },
      { status: 401 },
    );
  const config = env as unknown as Record<string, string | undefined>;
  const base = config.CAREER_API_URL,
    token = config.CAREER_API_TOKEN;
  // An explicit owner identity is required before server credentials are used.
  // This keeps a later audience change from sharing the single-user backend.
  if (!base || !token || !config.CAREER_OWNER_EMAIL)
    return Response.json(
      {
        detail:
          "The dashboard is ready. Connect your Python service to start using your CV and job feeds.",
      },
      { status: 503 },
    );
  if (user.email.toLowerCase() !== config.CAREER_OWNER_EMAIL.toLowerCase())
    return Response.json(
      { detail: "This is a personal workspace." },
      { status: 403 },
    );
  const { path } = await context.params;
  if (path.some((p) => !/^[-a-zA-Z0-9_]+$/.test(p)))
    return Response.json({ detail: "Invalid route." }, { status: 400 });
  const target = new URL(base);
  if (target.protocol !== "https:")
    return Response.json(
      { detail: "The backend requires an HTTPS URL." },
      { status: 503 },
    );
  const incomingOrigin = request.headers.get("origin");
  if (
    !["GET", "HEAD"].includes(request.method) &&
    incomingOrigin &&
    incomingOrigin !== new URL(request.url).origin
  )
    return Response.json(
      { detail: "Cross-origin request rejected." },
      { status: 403 },
    );
  const bytes = !["GET", "HEAD"].includes(request.method)
    ? await request.arrayBuffer()
    : undefined;
  if (bytes && bytes.byteLength > 5_100_000)
    return Response.json({ detail: "Request too large." }, { status: 413 });
  try {
    const r = await fetch(base.replace(/\/$/, "") + "/api/" + path.join("/"), {
      method: request.method,
      headers: {
        Authorization: "Bearer " + token,
        ...(request.headers.get("content-type")
          ? { "Content-Type": request.headers.get("content-type")! }
          : {}),
      },
      body: bytes,
      redirect: "error",
      signal: AbortSignal.timeout(120000),
    });
    return new Response(r.body, {
      status: r.status,
      headers: {
        "Content-Type": r.headers.get("content-type") || "application/json",
        "Cache-Control": "no-store",
        ...(r.headers.get("content-disposition")
          ? { "Content-Disposition": r.headers.get("content-disposition")! }
          : {}),
      },
    });
  } catch {
    return Response.json(
      {
        detail: "Your service could not be reached. Check that it is running.",
      },
      { status: 502 },
    );
  }
}
export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const DELETE = proxy;
