import { useEffect, useRef, useState } from "react";
import { UsbCamera, usbCameraSupported, watchUsbCamera } from "./usbCamera";
import type { CameraPort, UsbCameraState } from "./usbCamera";
import { UsbSpinner, usbSpinnerSupported, watchUsbSpinner } from "./usbSpinner";
import type { SpinnerPort, HolderState } from "./usbSpinner";

export function UsbCameraConnect({ locale, onPreview, scanning = false }: { locale: "en" | "fil"; onPreview?: (url: string | null) => void; scanning?: boolean }) {
  const t = (en: string, fil: string) => locale === "en" ? en : fil;
  const [state, setState] = useState<UsbCameraState>("disconnected");
  const [holderState, setHolderState] = useState<HolderState>("disconnected");
  const [error, setError] = useState("");
  const connection = useRef<UsbCamera | null>(null);
  const spinner = useRef<UsbSpinner | null>(null);
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
    const unwatchCamera = watchUsbCamera(port => {
      if (!paused.current && phase.current === "disconnected") void connect(port);
    });
    const unwatchSpinner = watchUsbSpinner(port => {
      if (alive.current && !spinner.current) void connectSpinner(port);
    });
    return () => {
      alive.current = false;
      unwatchCamera();
      unwatchSpinner();
      clearPreview();
      void connection.current?.close();
      void spinner.current?.close();
    };
  }, []);

  // Wire the scanning prop to the spinner's hold/run state.
  useEffect(() => {
    spinner.current?.setScanning(scanning);
  }, [scanning, holderState]);

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
  async function connectSpinner(port?: SpinnerPort) {
    if (spinner.current) { await spinner.current.close(); spinner.current = null; }
    const holder = new UsbSpinner((value, _message) => {
      if (alive.current) setHolderState(value);
    });
    spinner.current = holder;
    await holder.connect(port);
    // Apply the current scanning state after connecting.
    if (scanning) holder.setScanning(true);
  }
  async function disconnect() {
    phase.current = "disconnected"; paused.current = true; setState("disconnected"); setError("");
    const camera = connection.current; connection.current = null;
    const holder = spinner.current; spinner.current = null;
    clearPreview();
    await camera?.close();
    await holder?.close();
    setHolderState("disconnected");
  }
  const live = state === "connected" || state === "retrying";
  const holderLive = holderState === "connected";
  return <div className="usb-camera-connect">
    <button type="button" className={live ? "outline-button" : "solid-button"} disabled={!supported}
      onClick={() => void (live || state === "connecting" ? disconnect() : connect())}>
      {live || state === "connecting" ? t("Disconnect USB camera", "Idiskonekta ang USB camera") : t("Connect USB camera", "Ikonekta ang USB camera")}
    </button>
    {(!supported || state !== "disconnected") && <p role="status">{!supported ? t("Use Chrome or Edge on a computer for USB capture. You can still view this workspace on your phone.", "Gumamit ng Chrome o Edge sa computer para sa USB camera. Maaari pa ring tingnan ang workspace sa phone.")
      : state === "connecting" ? t("Choose the camera port. Waiting for its first image…", "Piliin ang port ng camera. Hinihintay ang unang larawan…")
        : state === "retrying" ? t("Camera connected. Cloud connection is retrying; keep this tab open.", "Konektado ang camera. Kumokonekta muli sa cloud; panatilihing bukas ang tab.")
          : t("USB camera connected. Keep this tab open and this computer awake.", "Konektado ang USB camera. Panatilihing bukas ang tab at gising ang computer.")}</p>}
    {live && usbSpinnerSupported() && <p role="status">{holderLive
      ? t("Holder connected. It pauses automatically during capture.", "Konektado ang holder. Awtomatikong humihinto habang kinukuha ang larawan.")
      : t("Holder not detected. Connect its USB adapter for automatic pausing.", "Hindi nahanap ang holder. Ikonekta ang USB adapter nito para awtomatikong huminto.")}</p>}
    {error && <p className="inline-error" role="alert">{error}</p>}
  </div>;
}
