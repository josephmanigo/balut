import { afterEach, expect, it, vi } from "vitest";
import { boxRequest } from "./api";

afterEach(() => vi.unstubAllGlobals());

it("skips preview downloads when requested and forwards cancellation", async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ result: null })));
  vi.stubGlobal("fetch", fetcher);
  const controller = new AbortController();
  await boxRequest("status", undefined, { preview: false, signal: controller.signal });
  const [url, options] = fetcher.mock.calls[0];
  expect(url).toMatch(/\/box\/status\?preview=false$/);
  expect(options.credentials).toBe("same-origin");
  expect(options.signal.aborted).toBe(false);
  controller.abort();
  expect(options.signal.aborted).toBe(true);
});

it("keeps existing status requests compatible and mutations free of preview query parameters", async () => {
  const fetcher = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ result: null })));
  vi.stubGlobal("fetch", fetcher);
  await boxRequest();
  expect(fetcher.mock.calls[0][0]).toMatch(/\/box\/status$/);
  await boxRequest("enabled", { enabled: false });
  expect(fetcher.mock.calls[1][0]).toMatch(/\/box\/enabled$/);
  expect(fetcher.mock.calls[1][1].method).toBe("POST");
});
