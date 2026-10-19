export const SPINNER_VENDOR_ID = 0x10c4;
export const SPINNER_PRODUCT_ID = 0xea60;
export const SPINNER_MAC = "3c:8a:1f:09:88:8c";
const HOLD_DURATION_MS = 12000;
const HOLD_REFRESH_MS = 6000;
const RESPONSE_TIMEOUT_MS = 2000;

export type HolderState = "connecting" | "connected" | "disconnected";

export interface SpinnerPort {
  readable: ReadableStream<Uint8Array> | null;
  writable: WritableStream<Uint8Array> | null;
  getInfo(): { usbVendorId?: number; usbProductId?: number };
  open(options: { baudRate: number }): Promise<void>;
  setSignals?(signals: { dataTerminalReady: boolean; requestToSend: boolean }): Promise<void>;
  close(): Promise<void>;
}
interface SpinnerSerial extends EventTarget {
  getPorts(): Promise<SpinnerPort[]>;
  requestPort(options: { filters: { usbVendorId: number; usbProductId: number }[] }): Promise<SpinnerPort>;
}
interface Reply { state: string; steps: number }
interface Pending { nonce: string; resolve: (reply: Reply) => void; reject: (error: Error) => void }

function spinnerSerial() {
  return (navigator as Navigator & { serial?: SpinnerSerial }).serial;
}

export function usbSpinnerSupported() {
  return !!spinnerSerial();
}

export function watchUsbSpinner(found: (port: SpinnerPort) => void) {
  const serial = spinnerSerial();
  let stopped = false;
  function check() {
    void serial?.getPorts().then(ports => {
      const holders = ports.filter(port => {
        const info = port.getInfo();
        return info.usbVendorId === SPINNER_VENDOR_ID && info.usbProductId === SPINNER_PRODUCT_ID;
      });
      if (!stopped && holders.length === 1) found(holders[0]);
    }).catch(() => {});
  }
  serial?.addEventListener("connect", check);
  check();
  return () => { stopped = true; serial?.removeEventListener("connect", check); };
}

export class UsbSpinner {
  private port?: SpinnerPort;
  private reader?: ReadableStreamDefaultReader<Uint8Array>;
  private writer?: WritableStreamDefaultWriter<Uint8Array>;
  private stopped = false;
  private ready = false;
  private running?: Promise<void>;
  private queue: Promise<unknown> = Promise.resolve();
  private pending: Pending | null = null;
  private scanning = false;
  private holding = false;
  private refresh?: number;

  constructor(private changed: (state: HolderState, error?: string) => void) {}

  async connect(grantedPort?: SpinnerPort) {
    const serial = spinnerSerial();
    if (!serial) { this.changed("disconnected", "Use Chrome or Edge on a computer to connect the holder."); return; }
    this.stopped = false;
    this.changed("connecting");
    try {
      const port = grantedPort ?? await serial.requestPort({ filters: [{ usbVendorId: SPINNER_VENDOR_ID, usbProductId: SPINNER_PRODUCT_ID }] });
      if (this.stopped) return;
      const info = port.getInfo();
      if (info.usbVendorId !== SPINNER_VENDOR_ID || info.usbProductId !== SPINNER_PRODUCT_ID) throw new Error("Select the holder's CP210x USB adapter.");
      await port.open({ baudRate: 115200 });
      this.port = port;
      if (!port.readable || !port.writable) throw new Error("Holder serial port is unavailable.");
      this.reader = port.readable.getReader(); this.writer = port.writable.getWriter();
      // Release the ESP32 auto-program lines so opening the port does not reset the motor controller.
      await port.setSignals?.({ dataTerminalReady: false, requestToSend: false }).catch(() => {});
      this.running = this.pump();
      await this.command("STATUS");
      this.ready = true;
      this.changed("connected");
    } catch (error) {
      if (this.stopped) return;
      await this.halt();
      this.changed("disconnected", error instanceof DOMException && error.name === "NotFoundError" ? undefined
        : error instanceof Error && error.name !== "NetworkError" ? error.message : "Close the box connector program on this computer, check the USB cable, and connect again.");
    }
  }

  async close() {
    if (this.holding && !this.stopped) { try { await this.command("RUN"); } catch { /* the firmware resumes on its own */ } }
    await this.halt();
  }

  setScanning(scanning: boolean) {
    if (this.stopped || !this.ready || scanning === this.scanning) return;
    this.scanning = scanning;
    if (scanning) {
      this.refresh = window.setInterval(() => { void this.hold(); }, HOLD_REFRESH_MS);
      void this.hold();
    } else {
      this.stopRefresh();
      void this.resume();
    }
  }

  private hold() {
    return this.command("HOLD").then(() => { this.holding = true; },
      error => { this.lost(error instanceof Error ? error.message : "The holder did not answer."); });
  }

  private resume() {
    return this.command("RUN").then(() => { this.holding = false; },
      error => { this.lost(error instanceof Error ? error.message : "The holder did not answer."); });
  }

  private command(verb: "STATUS" | "HOLD" | "RUN"): Promise<Reply> {
    return this.enqueue(() => this.send(verb));
  }

  private enqueue<T>(task: () => Promise<T>): Promise<T> {
    const next = this.queue.then(task, task);
    this.queue = next.catch(() => {});
    return next;
  }

  private async send(verb: "STATUS" | "HOLD" | "RUN"): Promise<Reply> {
    if (!this.writer) throw new Error("Connect the holder first.");
    const nonce = crypto.randomUUID().replace(/-/g, "").slice(0, 16);
    let settle!: Pending;
    const response = new Promise<Reply>((resolve, reject) => { settle = this.pending = { nonce, resolve, reject }; });
    const timer = window.setTimeout(() => {
      if (this.pending === settle) { this.pending = null; settle.reject(new Error("The holder did not answer. Check its USB cable and reconnect.")); }
    }, RESPONSE_TIMEOUT_MS);
    try {
      await this.writer.write(new TextEncoder().encode(verb === "HOLD" ? `HOLD ${nonce} ${HOLD_DURATION_MS}\n` : `${verb} ${nonce}\n`));
      const reply = await response;
      if (verb === "HOLD" && reply.state !== "HELD" || verb === "RUN" && reply.state !== "RUNNING") throw new Error("The holder did not acknowledge its capture state.");
      return reply;
    } finally {
      window.clearTimeout(timer);
      if (this.pending === settle) this.pending = null;
    }
  }

  private async pump() {
    const decoder = new TextDecoder();
    let text = "";
    try {
      while (!this.stopped) {
        const { value, done } = await this.reader!.read();
        if (done) throw new Error("The holder stopped responding. Check its USB cable and reconnect.");
        if (!value) continue;
        text = (text + decoder.decode(value, { stream: true })).slice(-4096);
        let end: number;
        while ((end = text.indexOf("\n")) >= 0) {
          const line = text.slice(0, end).trim();
          text = text.slice(end + 1);
          const match = /^BALUT_MOTOR_V1 ([0-9a-f]{16}) (HELD|RUNNING) steps=(\d+) mac=([0-9a-f:]{17})$/.exec(line);
          const pending = this.pending;
          if (!match || !pending || match[1] !== pending.nonce) continue;
          this.pending = null;
          if (match[4] !== SPINNER_MAC) pending.reject(new Error("This serial device is not the box holder. Connect the identified holder adapter."));
          else pending.resolve({ state: match[2], steps: Number(match[3]) });
        }
      }
    } catch (error) {
      this.lost(error instanceof Error ? error.message : "Holder disconnected. Connect again.");
    } finally {
      this.stopRefresh();
      await this.release();
    }
  }

  private lost(message?: string) {
    if (this.stopped) return;
    this.changed("disconnected", message);
    void this.halt();
  }

  private async halt() {
    this.stopRefresh();
    this.stopped = true;
    const pending = this.pending; this.pending = null;
    pending?.reject(new Error("Holder connection closed."));
    await this.reader?.cancel().catch(() => {});
    if (this.running) { await this.running.catch(() => {}); this.running = undefined; }
    else await this.release();
  }

  private stopRefresh() {
    if (this.refresh !== undefined) { window.clearInterval(this.refresh); this.refresh = undefined; }
  }

  private async release() {
    this.reader?.releaseLock(); this.writer?.releaseLock();
    this.reader = undefined; this.writer = undefined;
    await this.port?.close().catch(() => {}); this.port = undefined;
    this.ready = false; this.scanning = false; this.holding = false;
  }
}
