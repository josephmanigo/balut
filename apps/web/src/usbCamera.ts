import { uploadBoxFrame } from "./api";

export interface CameraPort {
  readable: ReadableStream<Uint8Array> | null;
  writable: WritableStream<Uint8Array> | null;
  getInfo(): { usbVendorId?: number; usbProductId?: number };
  open(options: { baudRate: number; bufferSize: number }): Promise<void>;
  setSignals(signals: { dataTerminalReady: boolean; requestToSend: boolean }): Promise<void>;
  close(): Promise<void>;
}
interface CameraSerial extends EventTarget {
  getPorts(): Promise<CameraPort[]>;
  requestPort(options: { filters: { usbVendorId: number; usbProductId: number }[] }): Promise<CameraPort>;
}

export function usbCameraSupported() {
  return !!(navigator as Navigator & { serial?: CameraSerial }).serial;
}

export function watchUsbCamera(found: (port: CameraPort) => void) {
  const serial = (navigator as Navigator & { serial?: CameraSerial }).serial;
  let stopped = false;
  function check() {
    void serial?.getPorts().then(ports => {
      const cameras = ports.filter(port => {
        const info = port.getInfo();
        return info.usbVendorId === 0x0403 && info.usbProductId === 0x6001;
      });
      if (!stopped && cameras.length === 1) found(cameras[0]);
    }).catch(() => { });
  }
  serial?.addEventListener("connect", check);
  check();
  return () => { stopped = true; serial?.removeEventListener("connect", check); };
}

export class UsbFrameParser {
  private buffer: Uint8Array<ArrayBuffer> = new Uint8Array();
  private length = 0;
  private checksum = 0;
  private noise = 0;

  push(chunk: Uint8Array): Uint8Array<ArrayBuffer> | null {
    if (this.buffer.length + chunk.length > 128 * 1024 + 4096) throw new Error("Camera frame is too large.");
    const combined = new Uint8Array(this.buffer.length + chunk.length);
    combined.set(this.buffer); combined.set(chunk, this.buffer.length); this.buffer = combined;
    while (!this.length) {
      const end = this.buffer.indexOf(10);
      if (end < 0) {
        if (this.buffer.length > 512) throw new Error("Camera sent an invalid frame header.");
        return null;
      }
      const line = new TextDecoder().decode(this.buffer.slice(0, end)).trim();
      this.buffer = this.buffer.slice(end + 1);
      if (line.startsWith("BALUT_ERROR")) throw new Error("Camera could not capture. Check its power and reconnect.");
      const header = /^BALUT_JPEG (\d+) ([0-9a-fA-F]{8})$/.exec(line);
      if (!header) {
        this.noise += end + 1;
        if (line.startsWith("BALUT_JPEG") || this.noise > 4096) throw new Error("Camera sent an invalid frame header.");
        continue;
      }
      this.length = Number(header[1]); this.checksum = Number.parseInt(header[2], 16);
      if (this.length <= 4 || this.length > 128 * 1024) throw new Error("Camera frame is too large or incomplete.");
    }
    if (this.buffer.length < this.length) return null;
    const frame = this.buffer.slice(0, this.length);
    let crc = 0xffffffff;
    for (const byte of frame) {
      crc ^= byte;
      for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
    }
    if (((crc ^ 0xffffffff) >>> 0) !== this.checksum || frame[0] !== 255 || frame[1] !== 216
      || frame.at(-2) !== 255 || frame.at(-1) !== 217) throw new Error("Camera image was incomplete. Check the USB cable and reconnect.");
    return frame;
  }
}

export type UsbCameraState = "connecting" | "connected" | "retrying" | "disconnected";

export class UsbCamera {
  private port?: CameraPort;
  private reader?: ReadableStreamDefaultReader<Uint8Array>;
  private writer?: WritableStreamDefaultWriter<Uint8Array>;
  private stopped = false;
  private abort = new AbortController();
  private running?: Promise<void>;
  private uploading?: Promise<void>;
  private pending?: { body: Uint8Array<ArrayBuffer>; key: string; session: string };
  private uploadError?: unknown;

  constructor(private changed: (state: UsbCameraState, error?: string) => void,
    private preview?: (frame: Uint8Array<ArrayBuffer>) => void) { }

  async connect(grantedPort?: CameraPort) {
    const serial = (navigator as Navigator & { serial?: CameraSerial }).serial;
    if (!serial) throw new Error("Use Chrome or Edge on a computer to connect the USB camera.");
    this.changed("connecting");
    try {
      const port = grantedPort ?? await serial.requestPort({ filters: [{ usbVendorId: 0x0403, usbProductId: 0x6001 }] });
      if (this.stopped) return;
      const info = port.getInfo();
      if (info.usbVendorId !== 0x0403 || info.usbProductId !== 0x6001) throw new Error("Select the box camera's FTDI USB adapter.");
      await port.open({ baudRate: 921600, bufferSize: 256 * 1024 });
      this.port = port;
      if (!port.readable || !port.writable) throw new Error("USB camera is unavailable.");
      this.reader = port.readable.getReader(); this.writer = port.writable.getWriter();
      this.running = this.run();
    } catch (error) {
      await this.release();
      if (!this.stopped) this.changed("disconnected", error instanceof DOMException && error.name === "NotFoundError" ? undefined
        : error instanceof Error && error.name !== "NetworkError" ? error.message : "Close other camera programs, check the USB cable, and connect again.");
    }
  }

  async close() {
    this.stopped = true; this.abort.abort();
    await this.reader?.cancel().catch(() => { });
    if (this.running) await this.running;
    else await this.release();
  }

  private async startCamera() {
    // Keep GPIO0 high while releasing reset so the camera boots its app, not the serial bootloader.
    await this.port!.setSignals({ dataTerminalReady: false, requestToSend: true });
    try { await new Promise(resolve => window.setTimeout(resolve, 120)); }
    finally { await this.port!.setSignals({ dataTerminalReady: false, requestToSend: false }); }
    if (this.stopped) return;
    const timer = window.setTimeout(() => { void this.reader?.cancel().catch(() => { }); }, 16000);
    const decoder = new TextDecoder();
    let text = "", received = 0;
    try {
      while (!this.stopped) {
        const { value, done } = await this.reader!.read();
        if (done) throw new Error("Camera did not finish starting. Reconnect its USB cable and try again.");
        if (!value) continue;
        received += value.length;
        if (received > 32 * 1024) throw new Error("Camera keeps restarting. Check its USB power and reconnect.");
        text = (text + decoder.decode(value, { stream: true })).slice(-1024);
        if (text.includes("Camera self-check failed") || text.includes("Camera init failed")) {
          throw new Error("Camera could not start its sensor. Check camera power and its ribbon cable, then reconnect.");
        }
        if (text.includes("BALUT_USB_READY")) return;
      }
    } finally { window.clearTimeout(timer); }
  }

  private async capture() {
    const parser = new UsbFrameParser();
    const timer = window.setTimeout(() => { void this.reader?.cancel().catch(() => { }); }, 8000);
    try {
      await this.writer!.write(new TextEncoder().encode("CAPTURE\n"));
      while (!this.stopped) {
        const { value, done } = await this.reader!.read();
        if (done) throw new Error("Camera stopped responding. Check its power and USB cable, then connect again.");
        if (value) { const frame = parser.push(value); if (frame) return frame; }
      }
      throw new DOMException("Camera disconnected", "AbortError");
    } finally { window.clearTimeout(timer); }
  }

  private async run() {
    const session = crypto.randomUUID();
    let sequence = 0;
    try {
      if (this.stopped) return;
      await this.startCamera();
      while (!this.stopped) {
        if (this.uploadError) throw this.uploadError;
        const started = performance.now();
        const body = await this.capture();
        if (this.stopped) break;
        if (sequence === 0) this.changed("connected");
        this.preview?.(body);
        // Keep one newest frame, so slow inference never freezes the local view or builds a stale queue.
        this.pending = { body, key: `web-${session}-${++sequence}`, session };
        this.uploading ??= this.uploadPending().finally(() => { this.uploading = undefined; });
        const delay = Math.max(0, 250 - (performance.now() - started));
        if (!this.stopped && delay) await new Promise(resolve => window.setTimeout(resolve, delay));
      }
    } catch (error) {
      error = this.uploadError ?? error;
      if (!this.stopped) this.changed("disconnected", error instanceof Error ? error.message : "Camera disconnected. Connect again.");
    } finally {
      this.stopped = true; this.abort.abort(); this.pending = undefined;
      await this.uploading;
      await this.release();
    }
  }

  private async uploadPending() {
    try {
      while (this.pending && !this.stopped) {
        const frame = this.pending; this.pending = undefined;
        const started = performance.now();
        let accepted = false;
        try { accepted = await uploadBoxFrame(frame.body, frame.key, frame.session, this.abort.signal); }
        catch (error) {
          if (this.stopped) break;
          if (!(error instanceof TypeError) && !(error instanceof DOMException && error.name === "TimeoutError")) throw error;
        }
        if (this.stopped) break;
        this.changed(accepted ? "connected" : "retrying");
        const delay = accepted ? Math.max(0, 250 - (performance.now() - started)) : 1000;
        if (delay) await new Promise(resolve => window.setTimeout(resolve, delay));
      }
    } catch (error) {
      this.uploadError = error;
      await this.reader?.cancel().catch(() => { });
    }
  }

  private async release() {
    this.reader?.releaseLock(); this.writer?.releaseLock();
    this.reader = undefined; this.writer = undefined;
    await this.port?.close().catch(() => { }); this.port = undefined;
  }
}
