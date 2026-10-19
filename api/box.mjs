// Only the server sees the connector key; browser sessions stay on the Vercel origin.
const routes = {
  "auth/session": "GET", "auth/login": "POST", "auth/logout": "POST",
  models: "GET", "model-predictions": "GET", "box/status": "GET",
  "box/connect": "POST", "box/reference": "POST", "box/enabled": "POST",
};
const error = (status, detail) => Response.json({ detail }, { status, headers: { "Cache-Control": "no-store" } });

async function bounded(stream, limit) {
  if (!stream) return new Uint8Array();
  const reader = stream.getReader();
  const chunks = [];
  let length = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.length;
      if (length > limit) throw new Error("Body too large");
      chunks.push(value);
    }
  } finally { await reader.cancel(); }
  return Buffer.concat(chunks, length);
}

export async function proxy(request, env = process.env, fetchBox = fetch) {
  const url = new URL(request.url);
  const route = url.pathname.startsWith("/api/v1/") ? url.pathname.slice(8) : url.searchParams.get("route");
  if (!Object.hasOwn(routes, route)) return error(404, "Route unavailable");
  if (request.method !== routes[route]) return error(405, "Method unavailable");
  const query = [...url.searchParams].filter(([name]) => name !== "route");
  const historyQuery = route === "model-predictions" && query.length === 1
    && query[0][0] === "limit" && /^[0-9]{1,3}$/.test(query[0][1]) && +query[0][1] >= 1 && +query[0][1] <= 100;
  const previewQuery = route === "box/status" && query.length === 1 && query[0][0] === "preview" && ["true", "false"].includes(query[0][1]);
  if (url.searchParams.getAll("route").length > 1 || query.length && !(historyQuery || previewQuery)) {
    return error(400, "Invalid query");
  }
  if (request.headers.get("sec-fetch-site") === "cross-site") return error(403, "Open the Balut website directly");
  let body;
  if (request.method === "POST") {
    if (request.headers.get("origin") !== url.origin || request.headers.get("X-Balut-Origin") !== "local") {
      return error(403, "Use the Balut page to make changes");
    }
    if (request.headers.get("content-type")?.split(";")[0] !== "application/json") return error(415, "Use JSON");
    try {
      body = await bounded(request.body, 16384);
      if (route === "auth/logout" && !body.length) body = Buffer.from("{}");
      const value = JSON.parse(new TextDecoder().decode(body));
      if (!value || Array.isArray(value) || typeof value !== "object") throw new Error();
      if (route === "box/connect" && (Object.keys(value).length !== 1 || value.cameraUrl !== "http://127.0.0.1:8767")) {
        return error(400, "Use the school USB camera address: http://127.0.0.1:8767");
      }
    } catch { return error(400, "Invalid or oversized JSON"); }
  }
  let origin;
  try {
    origin = new URL(env.BALUT_BOX_URL);
    if (origin.protocol !== "https:" || !/^[a-z0-9-]+\.(trycloudflare\.com|ngrok-free\.(app|dev)|ngrok\.app)$/.test(origin.hostname)
        || origin.username || origin.password || origin.port || origin.pathname !== "/" || origin.search || origin.hash
        || !/^[A-Za-z0-9_=-]{32,128}$/.test(env.BALUT_BOX_KEY ?? "")) throw new Error();
  } catch { return error(503, "Box connector is not configured in Vercel yet."); }
  const target = new URL("/api/v1/" + route, origin);
  target.search = new URLSearchParams(query).toString();
  const headers = { "X-Balut-Box-Key": env.BALUT_BOX_KEY, "Content-Type": "application/json" };
  if (origin.hostname.includes("ngrok")) headers["ngrok-skip-browser-warning"] = "true";
  const cookie = request.headers.get("cookie")?.split(";").map(x => x.trim()).find(x => /^balut_session=[A-Za-z0-9_-]{20,100}$/.test(x));
  if (cookie) headers.Cookie = cookie;
  try {
    const upstream = await fetchBox(target, { method: request.method, headers, body, redirect: "manual", signal: AbortSignal.timeout(45_000) });
    if (upstream.status >= 300 && upstream.status < 400 || upstream.headers.get("content-type")?.split(";")[0] !== "application/json") {
      await upstream.body?.cancel();
      return error(502, "Unexpected box connector response");
    }
    const responseHeaders = new Headers({ "Content-Type": "application/json", "Cache-Control": "no-store", Vary: "Cookie" });
    for (const value of upstream.headers.getSetCookie()) responseHeaders.append("Set-Cookie", value);
    if (upstream.headers.has("retry-after")) responseHeaders.set("Retry-After", upstream.headers.get("retry-after"));
    return new Response(await bounded(upstream.body, 2 * 1024 * 1024), { status: upstream.status, headers: responseHeaders });
  } catch { return error(503, "Box offline. Start the connector on the school laptop and check its internet."); }
}

export default { fetch: request => proxy(request) };
