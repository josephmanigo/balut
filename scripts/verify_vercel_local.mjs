// Exercise the real gateway and real local sessions without opening a public tunnel.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { proxy } from "../api/box.mjs";

const root = resolve(process.argv[2]);
assert.ok(root.includes("school-kit-check-20261017"));
const env = { BALUT_BOX_URL: "https://local-test.trycloudflare.com",
  BALUT_BOX_KEY: readFileSync(join(root, "deployment/private/cloud-key.txt"), "utf8").replace(/^\uFEFF/, "").trim() };
const localFetch = async (url, options) => {
  assert.equal(url.origin, env.BALUT_BOX_URL);
  return fetch("http://127.0.0.1:8768" + url.pathname + url.search, options);
};
const call = (route, body, cookie) => proxy(new Request("https://local-vercel-test.example/api/v1/" + route, {
  method: body === undefined ? "GET" : "POST",
  headers: { Origin: "https://local-vercel-test.example", "X-Balut-Origin": "local", "Content-Type": "application/json", ...(cookie ? { Cookie: cookie } : {}) },
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
}), env, localFetch);

assert.equal((await call("models")).status, 401);
const login = await call("auth/login", { username: "kitcheck", password: "school-verification-only-20261017" });
assert.equal(login.status, 200);
const cookie = login.headers.get("set-cookie").split(";")[0];
assert.match(login.headers.get("set-cookie"), /Secure/);
assert.match(login.headers.get("set-cookie"), /HttpOnly/);
assert.equal((await call("models", undefined, cookie)).status, 200);
assert.equal((await call("models")).status, 401, "shared HTTP client must not leak a previous visitor's cookie");
const history = await call("model-predictions?limit=50", undefined, cookie);
assert.equal(history.status, 200);
assert.equal((await history.json()).items.length, 0);
const status = await call("box/status", undefined, cookie);
assert.equal(status.status, 200);
const box = await status.json();
assert.equal(box.connected, true);
assert.equal(box.enabled, false);
assert.equal(box.calibrated, false);
assert.ok(box.preview.length > 1000);
assert.equal((await call("box/connect", { cameraUrl: "http://192.168.1.1" }, cookie)).status, 400);
assert.equal((await call("auth/logout", {}, cookie)).status, 200);
assert.equal((await call("models", undefined, cookie)).status, 401);
console.log(JSON.stringify({ realLocalGatewayAndProxy: true, cookieSignInAndSignOut: true,
  visitorsIsolated: true, usbPreview: true, analysisPaused: true, publicTunnelStarted: false, vercelDeploymentVerified: false }));
