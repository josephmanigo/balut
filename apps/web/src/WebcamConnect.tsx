import { useEffect, useRef, useState } from "react";
import { Webcam, rememberedWebcam, webcamSupported } from "./webcam";
import type { UsbCameraState } from "./usbCamera";

export function WebcamConnect({ locale, onStream }: { locale: "en" | "fil"; onStream: (stream: MediaStream | null) => void }) {
  const t = (en: string, fil: string) => locale === "en" ? en : fil;
  const [state, setState] = useState<UsbCameraState>("disconnected");
  const [error, setError] = useState("");
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [device, setDevice] = useState(rememberedWebcam);
  const [mode, setMode] = useState("");
  const connection = useRef<Webcam | null>(null);
  const alive = useRef(true);
  const streamCallback = useRef(onStream);
  streamCallback.current = onStream;
  const live = state !== "disconnected";

  async function refreshDevices() {
    const values = await navigator.mediaDevices?.enumerateDevices().catch(() => []);
    if (alive.current) setDevices(values?.filter(value => value.kind === "videoinput" && value.deviceId) ?? []);
  }
  function connect(id = device) {
    void connection.current?.close();
    setError(""); setMode("");
    const camera = new Webcam((value, message) => {
      if (alive.current && connection.current === camera) { setState(value); setError(message ?? ""); }
    }, stream => {
      if (alive.current && connection.current === camera) streamCallback.current(stream);
    }, (settings, label) => {
      if (!alive.current || connection.current !== camera) return;
      setDevice(settings.deviceId ?? "");
      setMode(`${label} · ${settings.width} × ${settings.height} · ${Math.round(settings.frameRate ?? 0)} fps ${t("camera mode", "camera mode")}`);
      void refreshDevices();
    });
    connection.current = camera;
    void camera.connect(id);
  }
  function disconnect() {
    const camera = connection.current;
    connection.current = null;
    void camera?.close();
    streamCallback.current(null);
    setState("disconnected"); setError(""); setMode("");
  }
  useEffect(() => {
    alive.current = true;
    void refreshDevices();
    const media = navigator.mediaDevices;
    media?.addEventListener("devicechange", refreshDevices);
    // Reopen only a previously selected camera whose permission is still visible.
    const saved = rememberedWebcam();
    if (saved) void media?.enumerateDevices().then(values => {
      if (alive.current && !connection.current && values.some(value => value.deviceId === saved && value.label)) connect(saved);
    }).catch(() => {});
    return () => {
      alive.current = false;
      media?.removeEventListener("devicechange", refreshDevices);
      void connection.current?.close();
      connection.current = null;
      streamCallback.current(null);
    };
  }, []);

  return <div className="usb-camera-connect">
    <label htmlFor="webcam-device">{t("Webcam", "Webcam")}</label>
    <select id="webcam-device" value={device} disabled={live} onChange={event => setDevice(event.target.value)}>
      <option value="">{t("Automatic · prefer EMEET", "Awtomatiko · unahin ang EMEET")}</option>
      {device && !devices.some(value => value.deviceId === device) && <option value={device}>{t("Saved webcam (unavailable)", "Naka-save na webcam (hindi available)")}</option>}
      {devices.map(value => <option key={value.deviceId} value={value.deviceId}>{value.label || t("USB webcam", "USB webcam")}</option>)}
    </select>
    <button type="button" className={live ? "outline-button" : "solid-button"} disabled={!webcamSupported()}
      onClick={() => live ? disconnect() : connect()}>{live ? t("Disconnect webcam", "Idiskonekta ang webcam") : t("Connect EMEET / webcam", "Ikonekta ang EMEET / webcam")}</button>
    <p role="status">{!webcamSupported() ? t("Open this HTTPS website in Chrome or Edge on the camera computer.", "Buksan ang HTTPS website na ito sa Chrome o Edge ng computer na may camera.")
      : state === "connecting" ? t("Allow camera access. Starting live video…", "Payagan ang camera. Sinisimulan ang live video…")
      : live ? t("Live video scanning. Keep this tab open; the egg keeps rotating.", "Live video scanning. Panatilihing bukas ang tab; tuloy ang pag-ikot ng itlog.")
      : t("Use the EMEET video stream at up to 1080p / 60 fps. Save a new empty view after changing cameras.", "Gamitin ang EMEET video hanggang 1080p / 60 fps. Mag-save ng bagong bakanteng kuha kapag nagpalit ng camera.")}</p>
    {mode && <p>{mode}</p>}
    {error && <p className={state === "disconnected" ? "inline-error" : undefined} role={state === "disconnected" ? "alert" : "status"}>{error}</p>}
  </div>;
}

export function WebcamPreview({ stream, onFps }: { stream: MediaStream; onFps: (fps: number | null) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const element = video.current!;
    element.srcObject = stream;
    void element.play().catch(() => {});
    let callback = 0, started = 0, firstFrame = 0;
    const measure: VideoFrameRequestCallback = (now, metadata) => {
      if (!started) { started = now; firstFrame = metadata.presentedFrames; }
      if (now - started >= 2000) {
        onFps((metadata.presentedFrames - firstFrame) * 1000 / (now - started));
        started = now; firstFrame = metadata.presentedFrames;
      }
      callback = element.requestVideoFrameCallback(measure);
    };
    if (element.requestVideoFrameCallback) callback = element.requestVideoFrameCallback(measure);
    return () => { element.cancelVideoFrameCallback?.(callback); element.srcObject = null; onFps(null); };
  }, [stream, onFps]);
  return <video ref={video} autoPlay muted playsInline aria-label="Live webcam view inside the candling box" />;
}
