import { uploadBoxFrame } from "./api";
import type { UsbCameraState } from "./usbCamera";

export const WEBCAM_DEVICE_KEY = "balut.webcam.device";
export const webcamSupported = () => !!navigator.mediaDevices?.getUserMedia;
export function rememberedWebcam() {
  try { return window.localStorage.getItem(WEBCAM_DEVICE_KEY) ?? ""; } catch { return ""; }
}

export class Webcam {
  private stopped = false;
  private abort = new AbortController();
  private frameAbort = new AbortController();
  private stream?: MediaStream;
  private video = document.createElement("video");
  private canvas = document.createElement("canvas");
  private deviceId = "";
  private session = crypto.randomUUID();
  private sequence = 0;
  private wake?: () => void;

  constructor(private changed: (state: UsbCameraState, error?: string) => void,
    private preview: (stream: MediaStream | null) => void,
    private settings: (settings: MediaTrackSettings, label: string) => void) {
    this.video.muted = true;
    this.video.playsInline = true;
  }

  async connect(deviceId = "") {
    this.deviceId = deviceId;
    this.changed("connecting");
    navigator.mediaDevices?.addEventListener("devicechange", this.deviceChanged);
    await this.run();
  }

  async close() {
    this.stopped = true;
    this.abort.abort();
    this.frameAbort.abort();
    this.wake?.();
    navigator.mediaDevices?.removeEventListener("devicechange", this.deviceChanged);
    this.release();
  }

  private deviceChanged = () => { if (!this.stream) this.wake?.(); };

  private wait(ms: number) {
    return new Promise<void>(resolve => {
      const done = () => { window.clearTimeout(timer); this.wake = undefined; resolve(); };
      const timer = window.setTimeout(done, ms);
      this.wake = done;
      if (this.stopped) done();
    });
  }

  private release() {
    this.stream?.getTracks().forEach(track => track.stop());
    this.stream = undefined;
    this.video.srcObject = null;
    this.preview(null);
  }

  private async open() {
    const media = navigator.mediaDevices;
    if (!this.deviceId) {
      const devices = await media.enumerateDevices();
      this.deviceId = devices.find(device => device.kind === "videoinput" && /emeet/i.test(device.label))?.deviceId ?? "";
    }
    const constraints: MediaTrackConstraints = {
      width: { ideal: 1920, max: 1920 }, height: { ideal: 1080, max: 1080 }, frameRate: { ideal: 60, max: 60 },
      ...(this.deviceId ? { deviceId: { exact: this.deviceId } } : {}),
    };
    let stream = await media.getUserMedia({ video: constraints, audio: false });
    if (this.stopped) { stream.getTracks().forEach(track => track.stop()); return; }
    // Permission reveals device labels; prefer EMEET over a laptop or virtual webcam.
    if (!this.deviceId) {
      const devices = await media.enumerateDevices().catch(() => []);
      const emeet = devices.find(device => device.kind === "videoinput" && /emeet/i.test(device.label));
      if (emeet && stream.getVideoTracks()[0].getSettings().deviceId !== emeet.deviceId) {
        stream.getTracks().forEach(track => track.stop());
        stream = await media.getUserMedia({ video: { ...constraints, deviceId: { exact: emeet.deviceId } }, audio: false });
      }
    }
    if (this.stopped) { stream.getTracks().forEach(track => track.stop()); return; }
    this.stream = stream;
    const track = stream.getVideoTracks()[0];
    this.deviceId = track.getSettings().deviceId ?? this.deviceId;
    this.session = crypto.randomUUID();
    this.frameAbort = new AbortController();
    track.addEventListener("ended", () => { this.frameAbort.abort(); this.wake?.(); }, { once: true });
    this.video.srcObject = stream;
    await this.video.play();
    if (this.stopped) return;
    try { window.localStorage.setItem(WEBCAM_DEVICE_KEY, this.deviceId); } catch { /* Permissions still work without persistence. */ }
    this.settings(track.getSettings(), track.label);
    this.preview(stream);
    this.changed("connected");
  }

  private async frame() {
    const { videoWidth: width, videoHeight: height } = this.video;
    if (!width || !height || this.video.readyState < 2) return null;
    if (![[1920, 1080], [1280, 720], [640, 480]].some(([w, h]) => w === width && h === height)) {
      throw new Error(`Camera supplied ${width} × ${height}. Set the webcam to 1080p, 720p or VGA.`);
    }
    this.canvas.width = width; this.canvas.height = height;
    const context = this.canvas.getContext("2d");
    if (!context) throw new Error("This browser cannot read webcam video frames.");
    context.drawImage(this.video, 0, 0, width, height);
    for (const quality of [.9, .8, .7]) {
      const blob = await new Promise<Blob | null>(resolve => this.canvas.toBlob(resolve, "image/jpeg", quality));
      if (blob && blob.size <= 512 * 1024) return new Uint8Array(await blob.arrayBuffer());
    }
    throw new Error("Webcam frame exceeds 512 KB. Reduce background detail or select 720p in the webcam utility.");
  }

  private async run() {
    try {
      while (!this.stopped) {
        try {
          await this.open();
          if (this.stopped) break;
          let lastTime = -1;
          let lastFresh = performance.now();
          while (!this.stopped && !this.frameAbort.signal.aborted) {
            const track = this.stream!.getVideoTracks()[0];
            if (!track.muted && this.video.currentTime !== lastTime) {
              lastTime = this.video.currentTime;
              const body = await this.frame();
              if (this.stopped || this.frameAbort.signal.aborted) break;
              if (body) {
                lastFresh = performance.now();
                try {
                  // One upload at a time; always sample again after it finishes.
                  const accepted = await uploadBoxFrame(body, `webcam-${this.session}-${++this.sequence}`, this.session,
                    AbortSignal.any([this.abort.signal, this.frameAbort.signal]));
                  if (!this.stopped && !this.frameAbort.signal.aborted) this.changed(accepted ? "connected" : "retrying",
                    accepted ? undefined : "Live camera continues. Scan service is reconnecting.");
                  if (!accepted) await this.wait(1000);
                } catch (error) {
                  if (this.stopped || this.frameAbort.signal.aborted) break;
                  if (!(error instanceof TypeError) && !(error instanceof DOMException && error.name === "TimeoutError")) throw error;
                  this.changed("retrying", "Live camera continues. Network interrupted; retrying automatically.");
                  await this.wait(1000);
                }
              }
            } else if (performance.now() - lastFresh > 8000) {
              break;
            }
            await this.wait(500);
          }
        } catch (error) {
          if (this.stopped) break;
          if (!(error instanceof DOMException) || !["NotReadableError", "NotFoundError", "AbortError"].includes(error.name)) throw error;
        }
        this.release();
        if (!this.stopped) {
          this.changed("retrying", "Webcam unavailable. Reconnecting automatically; check USB and close other camera apps.");
          await this.wait(2000);
        }
      }
    } catch (error) {
      if (!this.stopped) this.changed("disconnected", error instanceof DOMException && error.name === "NotAllowedError"
        ? "Allow camera access for this website, then connect again."
        : error instanceof Error ? error.message : "Webcam could not start.");
    } finally { await this.close(); }
  }
}
