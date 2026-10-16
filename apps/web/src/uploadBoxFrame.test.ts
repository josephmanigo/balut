import { afterEach, describe, expect, it, vi } from "vitest";
import { uploadBoxFrame } from "./api";

afterEach(() => vi.unstubAllGlobals());
describe("authenticated browser camera upload", () => {
  it("uses the signed-in session without a device or database key", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ accepted: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    const bytes = new Uint8Array([255, 216, 255, 217]);
    expect(await uploadBoxFrame(bytes, "frame-001", "camera-session", new AbortController().signal)).toBe(true);
    const [url, options] = fetcher.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/box\/frame$/);
    expect(options.credentials).toBe("same-origin");
    expect(options.headers).toEqual({ "Content-Type": "image/jpeg", "X-Balut-Origin": "local", "Idempotency-Key": "frame-001", "X-Balut-Camera-Session": "camera-session" });
    expect(options.body.size).toBe(bytes.length);
  });
  it("retries cloud contention but stops on an expired sign-in", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response("", { status: 409 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "sign in" }), { status: 401 }));
    vi.stubGlobal("fetch", fetcher);
    const args = [new Uint8Array([255, 216, 255, 217]), "frame-002", "camera-session", new AbortController().signal] as const;
    expect(await uploadBoxFrame(...args)).toBe(false);
    await expect(uploadBoxFrame(...args)).rejects.toThrow("Sign in again");
  });
});
