import { test } from "node:test";
import assert from "node:assert/strict";
import { proxy } from "../api/box.mjs";

const env = { BALUT_BOX_URL: "https://test-box.trycloudflare.com", BALUT_BOX_KEY: "k".repeat(48) };
const request = (path, body, headers = {}) => new Request("https://balut.example" + path, body === undefined ? { headers } : {
  method: "POST", headers: { Origin: "https://balut.example", "X-Balut-Origin": "local", "Content-Type": "application/json", ...headers },
  body: JSON.stringify(body),
});

test("proxy preserves status, secure session, query and JSON; hides key from browser", async () => {
  const calls = [];
  const response = await proxy(request("/api/box?route=auth/login", { username: "operator", password: "test" }, {
    Cookie: "other=secret; balut_session=" + "s".repeat(43), Authorization: "Bearer forbidden",
  }), env, async (url, options) => {
    calls.push([url, options]);
    return Response.json({ authenticated: true }, { headers: { "Set-Cookie": "balut_session=" + "t".repeat(43) + "; Secure; HttpOnly; SameSite=strict; Path=/" } });
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.match(response.headers.get("set-cookie"), /Secure/);
  assert.doesNotMatch(await response.text(), new RegExp(env.BALUT_BOX_KEY));
  const [url, options] = calls[0];
  assert.equal(url.href, env.BALUT_BOX_URL + "/api/v1/auth/login");
  assert.equal(options.headers.Cookie, "balut_session=" + "s".repeat(43));
  assert.equal(options.headers["X-Balut-Box-Key"], env.BALUT_BOX_KEY);
  assert.equal(options.redirect, "manual");
  assert.equal(options.headers.Authorization, undefined);
  assert.equal(options.headers.Origin, undefined);
});

test("only required routes, same-origin JSON writes and USB connection are accepted", async () => {
  for (const [input, status] of [
    [request("/api/v1/auth/register", {}), 404], [request("/api/v1/egg-analysis", {}), 404],
    [request("/api/v1/auth/login", {}, { Origin: "https://evil.example" }), 403],
    [request("/api/v1/auth/login", {}, { "Sec-Fetch-Site": "cross-site" }), 403],
    [request("/api/v1/auth/login", {}, { "Content-Type": "text/plain" }), 415],
    [request("/api/v1/box/connect", { cameraUrl: "http://192.168.1.1" }), 400],
    [request("/api/v1/box/status?extra=1"), 400],
    [request("/api/v1/box/status?preview=false&preview=true"), 400],
    [request("/api/v1/box/status?preview=invalid"), 400],
    [request("/api/v1/model-predictions?limit=0"), 400],
    [request("/api/box?route=box/status&route=models"), 400],
    [request("/api/v1/auth/login", { x: "a".repeat(17000) }), 400],
  ]) {
    assert.equal((await proxy(input, env, () => assert.fail("must not forward"))).status, status);
  }
});

test("invalid server configuration and offline/redirect/oversized upstream fail closed", async () => {
  for (const origin of ["http://test.trycloudflare.com", "https://evil.example", "https://test.trycloudflare.com/secret", "https://user@test.trycloudflare.com"]) {
    assert.equal((await proxy(request("/api/v1/auth/session"), { ...env, BALUT_BOX_URL: origin })).status, 503);
  }
  for (const fake of [async () => { throw new Error("secret"); }, async () => new Response(null, { status: 302, headers: { Location: "https://evil.example" } }),
    async () => new Response("a".repeat(2 * 1024 * 1024 + 1), { headers: { "Content-Type": "application/json" } })]) {
    const response = await proxy(request("/api/v1/auth/session"), env, fake);
    assert.ok([502, 503].includes(response.status));
    assert.doesNotMatch(await response.text(), /secret/);
  }
});

test("original API path forwards bounded history query", async () => {
  const response = await proxy(request("/api/v1/model-predictions?limit=50"), env, async url => {
    assert.equal(url.href, env.BALUT_BOX_URL + "/api/v1/model-predictions?limit=50");
    return Response.json({ items: [] });
  });
  assert.equal(response.status, 200);
});

test("proxy forwards status without preview for the capture computer", async () => {
  const response = await proxy(request("/api/v1/box/status?preview=false"), env, async url => {
    assert.equal(url.href, env.BALUT_BOX_URL + "/api/v1/box/status?preview=false");
    return Response.json({ preview: null });
  });
  assert.equal(response.status, 200);
});

test("sign-out accepts the app's empty POST body", async () => {
  const input = new Request("https://balut.example/api/v1/auth/logout", { method: "POST",
    headers: { Origin: "https://balut.example", "X-Balut-Origin": "local", "Content-Type": "application/json" } });
  assert.equal((await proxy(input, env, async (_url, options) => {
    assert.equal(options.body.toString(), "{}");
    return Response.json({ authenticated: false });
  })).status, 200);
});

test("stable assigned ngrok origins work without allowing arbitrary destinations", async () => {
  for (const origin of ["https://box.ngrok-free.dev", "https://box.ngrok-free.app", "https://box.ngrok.app"]) {
    const response = await proxy(request("/api/v1/auth/session"), { ...env, BALUT_BOX_URL: origin }, async (url, options) => {
      assert.equal(url.origin, origin);
      assert.equal(options.headers["ngrok-skip-browser-warning"], "true");
      return Response.json({ authenticated: false });
    });
    assert.equal(response.status, 200);
  }
  for (const origin of ["https://evil.ngrok-free.dev.example.com", "http://127.0.0.1:8768", "https://ngrok-free.dev", "https://localhost"]) {
    assert.equal((await proxy(request("/api/v1/auth/session"), { ...env, BALUT_BOX_URL: origin })).status, 503);
  }
});
