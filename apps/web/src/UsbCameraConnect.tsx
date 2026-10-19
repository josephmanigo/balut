import { useEffect, useRef, useState } from "react";
import { UsbCamera, usbCameraSupported, watchUsbCamera } from "./usbCamera";
import type { CameraPort, UsbCameraState } from "./usbCamera";

export function UsbCameraConnect({ locale, onPreview }: { locale: "en" | "fil"; onPreview?: (url: string | null) => void }) {
  const t = (en: string, fil: string) => locale === "en" ? en : fil;
  const [state, setState] = useState<UsbCameraState>("disconnected");
  const [error, setError] = useState("");
  const connection = useRef<UsbCamera | null>(null);
  const phase = useRef<UsbCameraState>("disconnected");
  const paused = useRef(false);
  const alive = useRef(true);
  const preview = useRef<string | null>(null);
  function clearPreview() {
    onPreview?.(null);
    if (preview.current) URL.revokeObjectURL(preview.current);
    preview.current = null;
  }
  useEffect(() => {
    alive.current = true;
    const unwatch = watchUsbCamera(port => {
      if (!paused.current && phase.current === "disconnected") void connect(port);
    });
    return () => { alive.current = false; unwatch(); clearPreview(); void connection.current?.close(); };
  }, []);
  const supported = usbCameraSupported();
  async function connect(port?: CameraPort) {
    phase.current = "connecting"; paused.current = false; setState("connecting"); setError("");
    if (connection.current) { await connection.current.close(); connection.current = null; }
    const camera = new UsbCamera((value, message) => {
      if (alive.current) {
        phase.current = value; setState(value); setError(message ?? "");
        if (value === "connecting" || value === "disconnected") clearPreview();
      }
    }, frame => {
      if (!alive.current) return;
      const previous = preview.current;
      preview.current = URL.createObjectURL(new Blob([frame], { type: "image/jpeg" }));
      onPreview?.(preview.current);
      if (previous) URL.revokeObjectURL(previous);
    });
    connection.current = camera;
    await camera.connect(port);
  }
  async function disconnect() {
    phase.current = "disconnected"; paused.current = true; setState("disconnected"); setError("");
    const camera = connection.current; connection.current = null;
    clearPreview();
    await camera?.close();
  }
  const live = state === "connected" || state === "retrying";
  return <div className="usb-camera-connect">
    <button type="button" className={live ? "outline-button" : "solid-button"} disabled={!supported}
      onClick={() => void (live || state === "connecting" ? disconnect() : connect())}>
      {live || state === "connecting" ? t("Disconnect USB camera", "Idiskonekta ang USB camera") : t("Connect USB camera", "Ikonekta ang USB camera")}
    </button>
    {(!supported || state !== "disconnected") && <p role="status">{!supported ? t("Use Chrome or Edge on a computer for USB capture. You can still view this workspace on your phone.", "Gumamit ng Chrome o Edge sa computer para sa USB camera. Maaari pa ring tingnan ang workspace sa phone.")
      : state === "connecting" ? t("Choose the camera port. Waiting for its first image…", "Piliin ang port ng camera. Hinihintay ang unang larawan…")
      : state === "retrying" ? t("Camera connected. Cloud connection is retrying; keep this tab open.", "Konektado ang camera. Kumokonekta muli sa cloud; panatilihing bukas ang tab.")
      : t("USB camera connected. Keep this tab open and this computer awake.", "Konektado ang USB camera. Panatilihing bukas ang tab at gising ang computer.")}</p>}
    {error && <p className="inline-error" role="alert">{error}</p>}
  </div>;
}
