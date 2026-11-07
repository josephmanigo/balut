import { useEffect, useRef, useState } from "react";
import { Camera, Check, LoaderCircle, Pause, Play, Radio, Settings2 } from "lucide-react";
import { boxRequest } from "./api";
import type { BoxStatus } from "./api";
import { UsbCameraConnect } from "./UsbCameraConnect";
import { WebcamConnect, WebcamPreview } from "./WebcamConnect";
import { webcamSupported } from "./webcam";

const states: Record<string, [string, string, string, string]> = {
  not_connected: ["Connect your box.", "Ikonekta ang kahon.", "Set up the camera once. Then place an egg.", "I-setup ang camera. Ilagay ang itlog pagkatapos."],
  connecting: ["Finding your camera…", "Hinahanap ang camera…", "Keep the box powered on.", "Panatilihing nakabukas ang kahon."],
  needs_reference: ["Start with an empty box.", "Magsimula sa bakanteng kahon.", "Remove the egg. Keep normal candling light on.", "Alisin ang itlog. Gamitin ang karaniwang ilaw."],
  calibrating: ["Saving the empty view.", "Sine-save ang bakanteng kuha.", "Leave the box empty. Waiting up to 45 seconds for a steady image.", "Panatilihing bakante ang kahon. Maghihintay nang hanggang 45 segundo para sa hindi gumagalaw na kuha."],
  checking_empty: ["Waiting for an empty view.", "Hinihintay ang bakanteng kuha.", "The camera has not matched the saved empty view. Remove the egg and keep your hands clear.", "Hindi pa tumutugma ang camera sa naka-save na bakanteng kuha. Alisin ang itlog at ilayo ang mga kamay."],
  waiting: ["Ready for an egg.", "Handa para sa itlog.", "Box is empty. Place one egg and keep your hands clear.", "Bakante ang kahon. Maglagay ng isang itlog at ilayo ang mga kamay."],
  settling: ["Scanning egg.", "Ini-scan ang itlog.", "Keep your hands clear. The camera analyzes the egg automatically.", "Ilayo ang mga kamay. Awtomatikong sinusuri ng camera ang itlog."],
  analyzing: ["Analyzing egg.", "Sinusuri ang itlog.", "Your result saves automatically.", "Awtomatikong mase-save ang resulta."],
  rescanning: ["Checking more live frames.", "Sinusuri ang mga susunod na kuha.", "Keep the egg in the holder. AI scanning continues automatically.", "Panatilihin ang itlog sa lalagyan. Awtomatikong nagpapatuloy ang AI scan."],
  capturing_views: ["Scanning egg.", "Ini-scan ang itlog.", "Keep your hands clear until the result appears.", "Ilayo ang mga kamay hanggang lumabas ang resulta."],
  remove_egg: ["Result saved.", "Nai-save ang resulta.", "Remove the egg before placing the next one.", "Alisin ang itlog bago ilagay ang susunod."],
  recapture: ["Scan inconclusive.", "Hindi malinaw ang resulta ng scan.", "Check the lighting and camera guidance below before scanning this egg again.", "Suriin ang gabay sa ilaw at camera sa ibaba bago muling i-scan ang itlog."],
  paused: ["Automatic mode paused.", "Naka-pause ang awtomatikong mode.", "Live view continues. Resume when the box is ready.", "Tuloy ang live na kuha. Ituloy ang pagsusuri kapag handa na ang kahon."],
  offline: ["Camera disconnected.", "Hindi konektado ang camera.", "Check camera power and connection. We’ll reconnect.", "Suriin ang kuryente at koneksyon ng camera. Kokonekta muli."],
  error: ["Capture saved. Retrying…", "Nai-save ang kuha. Inuulit…", "The same capture will be retried without duplicate records.", "Uulitin ang parehong kuha nang walang dobleng tala."],
};

export function AutomaticBox({ locale, onSaved, active = true }: { locale: "en" | "fil"; onSaved: () => void; active?: boolean }) {
  const t = (en: string, fil: string) => locale === "en" ? en : fil;
  const [status, setStatus] = useState<BoxStatus | null>(null);
  const [address, setAddress] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [unreachable, setUnreachable] = useState(false);
  const [localPreview, setLocalPreview] = useState<string | null>(null);
  const [webcamStream, setWebcamStream] = useState<MediaStream | null>(null);
  const [webcamFps, setWebcamFps] = useState<number | null>(null);
  const lastResult = useRef<string | undefined>(undefined);
  const pollDelay = useRef(250);
  const generation = useRef(0);
  const changing = useRef(false);
  const addressLoaded = useRef(false);
  const alive = useRef(true);
  const pollAbort = useRef<AbortController | null>(null);
  const livePanel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (active && status?.result && window.matchMedia?.("(max-width: 700px)").matches) {
      livePanel.current?.scrollIntoView({ block: "start" });
    }
  }, [status?.result?.predictionId, active]);

  function accept(value: BoxStatus) {
    pollDelay.current = value.cloudCapture || !value.connected ? 1500 : 250;
    if (value.cloudCapture && value.connected) pollDelay.current = 500;
    setStatus(value);
    setUnreachable(false);
    if (!addressLoaded.current) { setAddress(value.cameraUrl); addressLoaded.current = true; }
    if (value.result && lastResult.current !== value.result.predictionId) {
      lastResult.current = value.result.predictionId;
      onSaved();
    }
  }
  const acceptRef = useRef(accept);
  acceptRef.current = accept;
  useEffect(() => {
    alive.current = true;
    let stopped = false;
    let polling = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      clearTimeout(timer);
      if (stopped || polling || document.visibilityState === "hidden") return;
      const current = generation.current;
      if (!changing.current) {
        polling = true;
        const controller = new AbortController();
        pollAbort.current = controller;
        try {
          const value = await boxRequest("status", undefined, { signal: controller.signal, preview: active && !localPreview && !webcamStream });
          if (!stopped && !controller.signal.aborted && current === generation.current) acceptRef.current(value);
        } catch {
          if (!stopped && !controller.signal.aborted && current === generation.current) {
            pollDelay.current = Math.min(10_000, pollDelay.current * 2);
            setUnreachable(true);
          }
        } finally { polling = false; }
      }
      if (!stopped && !document.hidden) timer = setTimeout(poll, active ? pollDelay.current : 1500);
    }
    const visibilityChanged = () => {
      if (document.visibilityState === "hidden") { clearTimeout(timer); pollAbort.current?.abort(); }
      else void poll();
    };
    document.addEventListener("visibilitychange", visibilityChanged);
    void poll();
    return () => { stopped = true; alive.current = false; clearTimeout(timer); pollAbort.current?.abort(); document.removeEventListener("visibilitychange", visibilityChanged); };
  }, [active, !!localPreview, !!webcamStream]);

  async function change(action: string, body: Record<string, unknown>) {
    if (changing.current) return;
    generation.current++;
    pollAbort.current?.abort();
    changing.current = true; setBusy(true); setNotice("");
    try {
      const value = await boxRequest(action, body);
      if (alive.current) accept(value);
    } catch (error) {
      if (alive.current) setNotice(error instanceof Error ? error.message : "Connection interrupted. Try again.");
    } finally { changing.current = false; if (alive.current) setBusy(false); }
  }
  const copy = webcamStream && status?.state === "offline"
    ? ["Live camera connected.", "Konektado ang live camera.", "Waiting for the scan service. Video continues while uploads reconnect.", "Hinihintay ang scan service. Tuloy ang video habang kumokonekta muli."]
    : status?.eggPresence === "unknown" && ["checking_empty", "needs_reference", "waiting"].includes(status.state)
    ? ["Checking the holder.", "Sinusuri ang lalagyan.", "Center the holder in the camera and keep the candling light on.", "Igitna ang lalagyan sa kamera at panatilihing bukas ang ilaw."]
    : status?.eggPresence === "empty" && status.state === "waiting"
    ? ["No egg detected.", "Walang nakitang itlog.", "Place one egg in the lit holder. Scanning starts automatically.", "Maglagay ng isang itlog sa lalagyang may ilaw. Awtomatikong magsisimula ang pag-scan."]
    : status?.eggPresence === "present" && status.state === "checking_empty"
    ? ["Egg detected.", "May nakitang itlog.", "Remove this egg to reset the holder for the next scan.", "Alisin ang itlog upang maihanda ang lalagyan para sa susunod na pag-scan."]
    : status?.eggPresence === "present" && status.state === "capturing_views"
    ? ["Scanning egg.", "Ini-scan ang itlog.", "Keep the egg turning under the light while the scanner selects clear views.", "Panatilihing umiikot ang itlog sa ilaw habang pumipili ang scanner ng malilinaw na kuha."]
    : status?.cloudCapture && status.state === "needs_reference"
    ? ["Camera calibration needed.", "Kailangang i-calibrate ang camera.", "Remove the egg, turn on the candling light, then save a fresh empty view below.", "Alisin ang itlog, buksan ang ilaw, at mag-save ng bagong bakanteng kuha sa ibaba."]
    : status?.state === "settling" && status.result?.recaptureRequested ? states.rescanning
    : states[status?.state ?? "not_connected"] ?? states.offline;
  const calibrating = status?.state === "calibrating";
  const setupError = notice || (status?.state === "needs_reference" ? status.error : null);
  const result = status?.state === "waiting" || status?.eggPresence === "empty" ? null : status?.result;
  const scanning = ["settling", "capturing_views", "analyzing"].includes(status?.state ?? "");
  const unfamiliar = result?.recaptureReasons.includes("UNFAMILIAR_APPEARANCE");
  const blurry = result?.recaptureReasons.includes("IMAGE_TOO_BLURRY");
  const conflicting = result?.recaptureReasons.some(reason => ["AMBIGUOUS_APPEARANCE", "MULTIVIEW_DISAGREEMENT"].includes(reason));
  const recaptureHelp = unfamiliar
    ? t("The live view does not match what the model learned. Check that candling light reveals the egg's interior; camera-specific training may be needed.", "Hindi tugma ang live na kuha sa natutunan ng modelo. Tiyaking nakikita ang loob ng itlog sa ilaw; maaaring kailangan ng pagsasanay para sa camera na ito.")
    : blurry ? t("Video is too blurry. Check camera focus and reduce movement in the holder.", "Malabo ang video. Suriin ang focus ng camera at bawasan ang paggalaw sa lalagyan.")
    : conflicting && status?.eggPresence === "present"
    ? t("The views do not establish a grade. Remove the egg until “No egg detected” appears, then turn it a quarter turn and place it back under the light.", "Hindi matukoy ang grado sa mga kuha. Alisin ang itlog hanggang lumabas ang “Walang nakitang itlog,” saka ikutin ito nang isang-kapat at ibalik sa ilaw.")
    : t("The model could not establish a consistent result from the live video. Check candling light and keep the egg centered.", "Hindi makabuo ng magkakatugmang resulta ang modelo mula sa live video. Suriin ang ilaw at igitna ang itlog.");
  const cameraLive = !!webcamStream || !!localPreview || !!status?.connected && !unreachable;
  const label = result?.recaptureRequested ? t("Unable to classify", "Hindi matukoy ang klase")
    : ({ DAY_16: "Day 16", DAY_18: "Day 18", REJECT: "Reject", UNFERTILIZED: "Reject" }[result?.sourcePrediction ?? ""]);

  return <section className="automatic-box" aria-label={t("Automatic box", "Awtomatikong kahon")}>
    <div className="box-status-line"><span><Radio size={17} />{cameraLive ? t("Camera connected", "Konektado ang camera") : t("Camera not connected", "Hindi konektado ang camera")}</span>
      {status?.calibrated && <button type="button" className="quiet-button" disabled={busy} onClick={() => void change("enabled", { enabled: !status.enabled })}>{status.enabled ? <Pause size={16} /> : <Play size={16} />}{status.enabled ? t("Pause", "I-pause") : t("Resume", "Ituloy")}</button>}
    </div>
    <div className="box-layout">
      <figure className="box-camera">
        <figcaption><span><Camera size={16} strokeWidth={1.5} />{t("Box camera", "Camera ng kahon")}</span><span className="box-camera-signal" data-live={cameraLive}><i aria-hidden="true" />{webcamStream && webcamFps !== null && `${Math.round(webcamFps)} fps · `}{cameraLive ? t("Live", "Live") : status?.preview ? t("Last image", "Huling larawan") : t("Offline", "Offline")}</span></figcaption>
        <div className="box-camera-stage">
          {webcamStream ? <WebcamPreview stream={webcamStream} onFps={setWebcamFps} /> : localPreview ? <div className="box-camera-direct"><img src={localPreview} alt={t("Latest view inside the candling box", "Huling kuha sa loob ng kahon")} /></div>
            : status?.preview ? <img src={`data:image/jpeg;base64,${status.preview}`} alt={t("Latest view inside the candling box", "Huling kuha sa loob ng kahon")} />
            : <div className="box-camera-empty"><Camera size={40} strokeWidth={1} /><span>{t("Waiting for camera", "Hinihintay ang camera")}</span></div>}
        </div>
      </figure>
      <div ref={livePanel} className="box-live" role="status" aria-live="polite" aria-atomic="true">
        {!unreachable && status?.eggPresence === "present" && status.state !== "checking_empty" && <span>{t("Egg detected", "May nakitang itlog")}</span>}
        <h2>{unreachable ? t("Connection interrupted.", "Naputol ang koneksyon.") : copy[locale === "en" ? 0 : 1]}</h2>
        <p>{unreachable ? t("Check the EggGrade IoT server. Reconnecting automatically.", "Suriin ang EggGrade IoT server. Kokonekta muli.") : copy[locale === "en" ? 2 : 3]}</p>
        {(scanning || calibrating) && <LoaderCircle className="spin" size={24} />}
        {result && !scanning && <div className="box-result"><span>{result.recaptureRequested ? <Camera size={15} /> : <Check size={15} />}{t("Latest saved result", "Huling nai-save na resulta")}</span><h3>{label}</h3><p>{result.recaptureRequested ? recaptureHelp : t("Research estimate · appearance only", "Tantiya para sa pananaliksik · hitsura lamang")}</p>{result.recaptureRequested && unfamiliar && blurry && <p>{t("Some views also have low detail. Check lens focus and reduce vibration.", "Kulang din sa detalye ang ilang kuha. Suriin ang focus ng lens at bawasan ang pagyanig.")}</p>}<time dateTime={result.createdAt}>{new Date(result.createdAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time></div>}
      </div>
    </div>
    {setupError && <p className="inline-error" role="alert">{setupError}</p>}
    {status?.cloudCapture && <details className="box-settings">
      <summary><Settings2 size={17} />{t("Box setup", "Setup ng kahon")}</summary>
      <WebcamConnect locale={locale} onStream={setWebcamStream} />
      {!webcamStream && <details><summary>{t("Older ESP32 camera", "Lumang ESP32 camera")}</summary>
        <UsbCameraConnect locale={locale} onPreview={setLocalPreview} autoConnect={!webcamSupported()} />
      </details>}
    </details>}
    {status?.cloudCapture && ["checking_empty", "needs_reference"].includes(status.state) && <details className="box-settings">
      <summary>{t("Box is empty but still waiting?", "Bakante pero naghihintay pa rin?")}</summary>
      <p>{t("If the camera or lighting changed, update the empty view. Only continue with no egg or hands in the box. Keep the light on.", "Kung nagbago ang camera o ilaw, i-update ang bakanteng kuha. Tiyaking walang itlog o kamay sa kahon. Panatilihing bukas ang ilaw.")}</p>
      <button type="button" className="solid-button" disabled={busy || unreachable || !status.connected} onClick={() => void change("reference", { emptyConfirmed: true })}>{t("Box is empty — update reference", "Bakante ang kahon — i-update ang kuha")}</button>
    </details>}
    {status && !status.cloudCapture && <details className="box-settings" open={!status.calibrated}>
      <summary><Settings2 size={17} />{t("Box setup", "Setup ng kahon")}</summary>
      <form onSubmit={event => { event.preventDefault(); void change("connect", { cameraUrl: address }); }}>
        <label htmlFor="box-address">{t("Camera address", "Address ng camera")}</label>
        <div className="box-address-row"><input id="box-address" type="url" required value={address} disabled={busy} placeholder="http://192.168.1.50" autoComplete="off" onChange={event => setAddress(event.target.value)} /><button className="outline-button" disabled={busy || !address.trim()}>{busy ? t("Please wait…", "Sandali…") : t("Connect camera", "Ikonekta ang camera")}</button></div>
        <p>{t("Use the camera address provided during box setup.", "Gamitin ang address ng camera na ibinigay sa setup ng kahon.")}</p>
      </form>
      {status?.cameraUrl && <>
        <p>{t("Remove the egg. Keep normal candling light on, then confirm below.", "Alisin ang itlog. Panatilihing bukas ang karaniwang ilaw, saka kumpirmahin sa ibaba.")}</p>
        <div className="box-reference"><button type="button" className="solid-button" disabled={busy || calibrating || !status.connected} onClick={() => void change("reference", { emptyConfirmed: true })}>{calibrating ? t("Saving empty view…", "Sine-save ang bakanteng kuha…") : t("Box is empty — start", "Bakante ang kahon — simulan")}</button></div>
      </>}
      <p className="box-setup-note">{t("Save the empty view once. We recognize it after reconnecting and between eggs. Save again if camera position or lighting changes. This uses image comparison, not an egg-presence sensor.", "I-save nang isang beses ang bakanteng kuha. Makikilala ito sa muling pagkonekta at pagkatapos alisin ang itlog. I-save muli kapag nagbago ang posisyon ng camera o ilaw. Paghahambing ng larawan ito, hindi sensor ng itlog.")}</p>
    </details>}
  </section>;
}
