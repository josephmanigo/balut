import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { uploadBoxFrame } from "./api";
import { Webcam, WEBCAM_DEVICE_KEY } from "./webcam";

vi.mock("./api", () => ({ uploadBoxFrame: vi.fn() }));
let clock = 0;
function cameraStream() {
  const track = Object.assign(new EventTarget(), {
    label: "EMEET SmartCam C60E 4K", muted: false, readyState: "live",
    getSettings: () => ({ deviceId: "emeet", width: 1920, height: 1080, frameRate: 60 }),
    stop: vi.fn(),
  });
  return { track, getTracks: () => [track], getVideoTracks: () => [track] };
}
function mediaDevices(stream = cameraStream()) {
  const media = Object.assign(new EventTarget(), {
    enumerateDevices: vi.fn().mockResolvedValue([{ kind: "videoinput", deviceId: "emeet", label: "EMEET C60E" }]),
    getUserMedia: vi.fn().mockResolvedValue(stream),
  });
  Object.defineProperty(navigator, "mediaDevices", { value: media, configurable: true });
  return { media, stream };
}

describe("continuous webcam scanning", () => {
  beforeEach(() => {
    vi.useFakeTimers(); clock = 0;
    const storage = new Map<string, string>();
    vi.stubGlobal("localStorage", { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value) });
    vi.mocked(uploadBoxFrame).mockReset().mockResolvedValue(true);
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    vi.spyOn(HTMLMediaElement.prototype, "readyState", "get").mockReturnValue(4);
    vi.spyOn(HTMLMediaElement.prototype, "currentTime", "get").mockImplementation(() => ++clock);
    vi.spyOn(HTMLVideoElement.prototype, "videoWidth", "get").mockReturnValue(1920);
    vi.spyOn(HTMLVideoElement.prototype, "videoHeight", "get").mockReturnValue(1080);
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage: vi.fn() } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(callback => callback({ size: 100,
      arrayBuffer: async () => new Uint8Array([255, 216, 7, 255, 217]).buffer } as Blob));
  });
  afterEach(() => {
    vi.restoreAllMocks(); vi.useRealTimers(); vi.unstubAllGlobals();
    Object.defineProperty(navigator, "mediaDevices", { value: undefined, configurable: true });
  });

  it("selects EMEET, requests 1080p60 without audio and uploads full-size fresh video frames", async () => {
    const { media, stream } = mediaDevices();
    const preview = vi.fn(), settings = vi.fn();
    const camera = new Webcam(vi.fn(), preview, settings);
    const running = camera.connect();
    await vi.advanceTimersByTimeAsync(1);
    expect(media.getUserMedia).toHaveBeenCalledWith({ audio: false, video: {
      deviceId: { exact: "emeet" }, width: { ideal: 1920, max: 1920 }, height: { ideal: 1080, max: 1080 }, frameRate: { ideal: 60, max: 60 },
    } });
    expect(preview).toHaveBeenCalledWith(stream);
    expect(settings).toHaveBeenCalledWith(stream.track.getSettings(), stream.track.label);
    expect(window.localStorage.getItem(WEBCAM_DEVICE_KEY)).toBe("emeet");
    await vi.advanceTimersByTimeAsync(1000);
    expect(uploadBoxFrame).toHaveBeenCalledTimes(3);
    expect(vi.mocked(uploadBoxFrame).mock.calls[0][1]).toMatch(/^webcam-.*-1$/);
    await camera.close(); await running;
    expect(stream.track.stop).toHaveBeenCalledOnce();
  });

  it("keeps video open during slow inference, allows only one upload and retries network failures", async () => {
    const { media, stream } = mediaDevices();
    let finish!: (value: boolean) => void;
    vi.mocked(uploadBoxFrame).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
      .mockRejectedValueOnce(new TypeError("network down")).mockResolvedValue(true);
    const changed = vi.fn();
    const camera = new Webcam(changed, vi.fn(), vi.fn());
    const running = camera.connect();
    await vi.advanceTimersByTimeAsync(3000);
    expect(uploadBoxFrame).toHaveBeenCalledOnce();
    expect(stream.track.stop).not.toHaveBeenCalled();
    finish(true); await vi.advanceTimersByTimeAsync(2500);
    expect(changed).toHaveBeenCalledWith("retrying", expect.stringMatching(/Network interrupted/));
    expect(changed).toHaveBeenLastCalledWith("connected", undefined);
    expect(media.getUserMedia).toHaveBeenCalledOnce();
    await camera.close(); await running;
  });

  it("reopens the same webcam after unplugging and never reuses the old session", async () => {
    const { media, stream } = mediaDevices();
    const second = cameraStream();
    media.getUserMedia.mockResolvedValueOnce(stream).mockResolvedValue(second);
    const changed = vi.fn(), preview = vi.fn();
    const camera = new Webcam(changed, preview, vi.fn());
    const running = camera.connect();
    await vi.advanceTimersByTimeAsync(1);
    const oldSession = vi.mocked(uploadBoxFrame).mock.calls[0][2];
    stream.track.dispatchEvent(new Event("ended"));
    await vi.advanceTimersByTimeAsync(2001);
    expect(media.getUserMedia).toHaveBeenCalledTimes(2);
    expect(preview).toHaveBeenCalledWith(null);
    expect(preview).toHaveBeenLastCalledWith(second);
    expect(vi.mocked(uploadBoxFrame).mock.lastCall![2]).not.toBe(oldSession);
    await camera.close(); await running;
  });

  it("does not upload a frozen video frame again and reconnects after eight seconds", async () => {
    const { media } = mediaDevices();
    vi.spyOn(HTMLMediaElement.prototype, "currentTime", "get").mockReturnValue(1);
    const camera = new Webcam(vi.fn(), vi.fn(), vi.fn());
    const running = camera.connect();
    await vi.advanceTimersByTimeAsync(8000);
    expect(uploadBoxFrame).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(3000);
    expect(media.getUserMedia).toHaveBeenCalledTimes(2);
    await camera.close(); await running;
  });

  it("releases a stream granted after Disconnect and uploads nothing", async () => {
    const { media, stream } = mediaDevices();
    let grant!: (value: unknown) => void;
    media.getUserMedia.mockImplementation(() => new Promise(resolve => { grant = resolve; }));
    const camera = new Webcam(vi.fn(), vi.fn(), vi.fn());
    const running = camera.connect();
    await vi.advanceTimersByTimeAsync(1);
    await camera.close(); grant(stream); await running;
    expect(stream.track.stop).toHaveBeenCalledOnce();
    expect(uploadBoxFrame).not.toHaveBeenCalled();
  });

  it("explains denied permission and stops on expired authentication", async () => {
    const { media, stream } = mediaDevices();
    const changed = vi.fn();
    media.getUserMedia.mockRejectedValueOnce(new DOMException("denied", "NotAllowedError"));
    await new Webcam(changed, vi.fn(), vi.fn()).connect();
    expect(changed).toHaveBeenLastCalledWith("disconnected", expect.stringMatching(/Allow camera access/));
    vi.mocked(uploadBoxFrame).mockRejectedValueOnce(new Error("Sign in again."));
    await new Webcam(changed, vi.fn(), vi.fn()).connect();
    expect(changed).toHaveBeenLastCalledWith("disconnected", "Sign in again.");
    expect(stream.track.stop).toHaveBeenCalledOnce();
  });
});
