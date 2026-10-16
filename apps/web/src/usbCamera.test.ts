import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { UsbCamera, UsbFrameParser, watchUsbCamera } from "./usbCamera";
import { uploadBoxFrame } from "./api";

vi.mock("./api", () => ({ uploadBoxFrame: vi.fn() }));
const jpeg = new Uint8Array([255, 216, 0, 7, 255, 217]);
const header = new TextEncoder().encode("Boot message\r\nBALUT_JPEG 6 85e7bf70\r\n");
function frame() { return new Uint8Array([...header, ...jpeg, 10]); }

function cameraPort(send = true) {
  let incoming: ReadableStreamDefaultController<Uint8Array>;
  const readable = new ReadableStream<Uint8Array>({ start(controller) { incoming = controller; } });
  const write = vi.fn(async (command: Uint8Array) => {
    expect(new TextDecoder().decode(command)).toBe("CAPTURE\n");
    if (send) incoming.enqueue(frame());
  });
  return { readable, writable: new WritableStream<Uint8Array>({ write }), write,
    getInfo: () => ({ usbVendorId: 0x0403, usbProductId: 0x6001 }),
    open: vi.fn(async () => {}), setSignals: vi.fn(async () => {}), close: vi.fn(async () => {}) };
}

describe("USB camera protocol", () => {
  beforeEach(() => { vi.useFakeTimers(); vi.mocked(uploadBoxFrame).mockReset().mockResolvedValue(true); });
  afterEach(() => { vi.useRealTimers(); Object.defineProperty(navigator, "serial", { value: undefined, configurable: true }); });

  it("reads fragmented headers and JPEG bytes and rejects corrupted or oversized frames", () => {
    const parser = new UsbFrameParser();
    expect(parser.push(header.slice(0, 8))).toBeNull();
    expect(parser.push(new Uint8Array([...header.slice(8), ...jpeg.slice(0, 3)]))).toBeNull();
    expect(parser.push(jpeg.slice(3))).toEqual(jpeg);
    const corrupt = frame(); corrupt[header.length + 2] ^= 1;
    expect(() => new UsbFrameParser().push(corrupt)).toThrow(/incomplete/);
    expect(() => new UsbFrameParser().push(new TextEncoder().encode("BALUT_JPEG 131073 00000000\n"))).toThrow(/large/);
    expect(() => new UsbFrameParser().push(new TextEncoder().encode("BALUT_ERROR Capture failed\n"))).toThrow(/could not capture/);
  });

  it("requests the camera adapter and sends fresh captures after a lost cloud response", async () => {
    const port = cameraPort();
    const requestPort = vi.fn(async () => port);
    Object.defineProperty(navigator, "serial", { value: { requestPort }, configurable: true });
    vi.mocked(uploadBoxFrame).mockRejectedValueOnce(new TypeError("network unavailable")).mockResolvedValue(true);
    const changed = vi.fn(); const connection = new UsbCamera(changed);
    await connection.connect(); await vi.advanceTimersByTimeAsync(0);
    expect(requestPort).toHaveBeenCalledWith({ filters: [{ usbVendorId: 0x0403, usbProductId: 0x6001 }] });
    expect(port.open).toHaveBeenCalledWith({ baudRate: 921600, bufferSize: 262144 });
    expect(port.setSignals).toHaveBeenCalledWith({ dataTerminalReady: false, requestToSend: false });
    expect(changed).toHaveBeenCalledWith("retrying");
    await vi.advanceTimersByTimeAsync(1000);
    expect(port.write).toHaveBeenCalledTimes(2);
    expect(uploadBoxFrame).toHaveBeenCalledTimes(2);
    expect(vi.mocked(uploadBoxFrame).mock.calls[0][1]).not.toBe(vi.mocked(uploadBoxFrame).mock.calls[1][1]);
    expect(changed).toHaveBeenCalledWith("connected");
    const closing = connection.close(); await vi.advanceTimersByTimeAsync(1000); await closing;
    expect(port.close).toHaveBeenCalledOnce();
    expect(port.readable.locked || port.writable.locked).toBe(false);
    expect(vi.mocked(uploadBoxFrame).mock.calls[0][3].aborted).toBe(true);
  });

  it("times out a silent camera and releases both stream locks", async () => {
    const port = cameraPort(false);
    Object.defineProperty(navigator, "serial", { value: { requestPort: async () => port }, configurable: true });
    const changed = vi.fn(); const connection = new UsbCamera(changed);
    await connection.connect(); await vi.advanceTimersByTimeAsync(8001);
    expect(changed).toHaveBeenCalledWith("disconnected", expect.stringMatching(/stopped responding/));
    expect(port.close).toHaveBeenCalledOnce();
    expect(port.readable.locked || port.writable.locked).toBe(false);
    expect(uploadBoxFrame).not.toHaveBeenCalled();
  });

  it("allows cancelling the port picker without an error or upload", async () => {
    Object.defineProperty(navigator, "serial", { value: { requestPort: async () => { throw new DOMException("No port", "NotFoundError"); } }, configurable: true });
    const changed = vi.fn(); await new UsbCamera(changed).connect();
    expect(changed).toHaveBeenLastCalledWith("disconnected", undefined);
    expect(uploadBoxFrame).not.toHaveBeenCalled();
  });

  it("automatically finds a previously allowed camera on page load and USB reconnect, without prompting", async () => {
    const port = cameraPort();
    const serial = Object.assign(new EventTarget(), { getPorts: vi.fn().mockResolvedValue([port]), requestPort: vi.fn() });
    Object.defineProperty(navigator, "serial", { value: serial, configurable: true });
    const found = vi.fn(); const stop = watchUsbCamera(found);
    await vi.advanceTimersByTimeAsync(0);
    expect(found).toHaveBeenCalledWith(port);
    serial.dispatchEvent(new Event("connect")); await vi.advanceTimersByTimeAsync(0);
    expect(found).toHaveBeenCalledTimes(2);
    expect(serial.requestPort).not.toHaveBeenCalled();
    stop(); serial.dispatchEvent(new Event("connect")); await vi.advanceTimersByTimeAsync(0);
    expect(found).toHaveBeenCalledTimes(2);
    serial.getPorts.mockResolvedValue([port, cameraPort()]);
    const stopAmbiguous = watchUsbCamera(found); await vi.advanceTimersByTimeAsync(0);
    expect(found).toHaveBeenCalledTimes(2);
    stopAmbiguous();
  });
});
