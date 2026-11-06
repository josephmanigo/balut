import { afterEach, expect, it, vi } from "vitest";
import { UsbSpinner, SPINNER_MAC } from "./usbSpinner";

afterEach(() => { Object.defineProperty(navigator, "serial", { value: undefined, configurable: true }); });

it.each(["RUNNING", "HELD"])("keeps rotation running when holder starts %s and never sends HOLD", async initial => {
  const commands: string[] = [];
  let incoming!: ReadableStreamDefaultController<Uint8Array>;
  const port = {
    readable: new ReadableStream<Uint8Array>({ start(controller) { incoming = controller; } }),
    writable: new WritableStream<Uint8Array>({ write(bytes) {
      const [verb, nonce] = new TextDecoder().decode(bytes).trim().split(" ");
      commands.push(verb);
      incoming.enqueue(new TextEncoder().encode(`BALUT_MOTOR_V1 ${nonce} ${verb === "RUN" ? "RUNNING" : initial} steps=42 mac=${SPINNER_MAC}\n`));
    } }),
    getInfo: () => ({ usbVendorId: 0x10c4, usbProductId: 0xea60 }),
    open: vi.fn(), close: vi.fn(),
  };
  Object.defineProperty(navigator, "serial", { value: { requestPort: async () => port }, configurable: true });
  const changed = vi.fn();
  const spinner = new UsbSpinner(changed);
  await spinner.connect();
  expect(changed).toHaveBeenLastCalledWith("connected");
  await spinner.close();
  expect(commands).toEqual(initial === "HELD" ? ["STATUS", "RUN"] : ["STATUS"]);
});
