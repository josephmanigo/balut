import { useEffect, useRef, useState } from "react";
import { Camera, Check, LoaderCircle, Pause, Play, Radio, Settings2 } from "lucide-react";
import { boxRequest, getSourceModels } from "./api";
import type { BoxStatus, SourceModelCatalog } from "./api";
import { UsbCameraConnect } from "./UsbCameraConnect";

const states: Record<string, [string, string, string, string]> = {
  not_connected: ["Connect your box.", "Ikonekta ang kahon.", "Set up the camera once. Then place an egg.", "I-setup ang camera. Ilagay ang itlog pagkatapos."],
  connecting: ["Finding your camera…", "Hinahanap ang camera…", "Keep the box powered on.", "Panatilihing nakabukas ang kahon."],
  needs_reference: ["Start with an empty box.", "Magsimula sa bakanteng kahon.", "Remove the egg. Keep normal candling light on.", "Alisin ang itlog. Gamitin ang karaniwang ilaw."],
  calibrating: ["Saving the empty view.", "Sine-save ang bakanteng kuha.", "Leave the box empty. Waiting up to 45 seconds for a steady image.", "Panatilihing bakante ang kahon. Maghihintay nang hanggang 45 segundo para sa hindi gumagalaw na kuha."],
  checking_empty: ["Waiting for an empty view.", "Hinihintay ang bakanteng kuha.", "The camera has not matched the saved empty view. Remove the egg and keep your hands clear.", "Hindi pa tumutugma ang camera sa naka-save na bakanteng kuha. Alisin ang itlog at ilayo ang mga kamay."],
  waiting: ["Ready for an egg.", "Handa para sa itlog.", "Box is empty. Place one egg and keep your hands clear.", "Bakante ang kahon. Maglagay ng isang itlog at ilayo ang mga kamay."],
  settling: ["Scanning egg.", "Ini-scan ang itlog.", "Keep your hands clear. The camera analyzes the egg automatically.", "Ilayo ang mga kamay. Awtomatikong sinusuri ng camera ang itlog."],
  analyzing: ["Analyzing egg.", "Sinusuri ang itlog.", "Your result saves automatically.", "Awtomatikong mase-save ang resulta."],
  capturing_views: ["Scanning egg.", "Ini-scan ang itlog.", "Keep your hands clear until the result appears.", "Ilayo ang mga kamay hanggang lumabas ang resulta."],
  remove_egg: ["Result saved.", "Nai-save ang resulta.", "Remove the egg before placing the next one.", "Alisin ang itlog bago ilagay ang susunod."],
  recapture: ["Another view needed.", "Kailangan ng ibang kuha.", "Remove the egg, adjust it, then place it again.", "Alisin, ayusin, at ilagay muli ang itlog."],
  paused: ["Automatic mode paused.", "Naka-pause ang awtomatikong mode.", "Live view continues. Resume when the box is ready.", "Tuloy ang live na kuha. Ituloy ang pagsusuri kapag handa na ang kahon."],
  offline: ["Camera disconnected.", "Hindi konektado ang camera.", "Check camera power and connection. We’ll reconnect.", "Suriin ang kuryente at koneksyon ng camera. Kokonekta muli."],
  error: ["Capture saved. Retrying…", "Nai-save ang kuha. Inuulit…", "The same capture will be retried without duplicate records.", "Uulitin ang parehong kuha nang walang dobleng tala."],
};

export function AutomaticBox({ locale, onSaved, active = true }: { locale: "en" | "fil"; onSaved: () => void; active?: boolean }) {
  const t = (en: string, fil: string) => locale === "en" ? en : fil;
  const [status, setStatus] = useState<BoxStatus | null>(null);
  const [catalog, setCatalog] = useState<SourceModelCatalog | null>(null);
  const [address, setAddress] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [unreachable, setUnreachable] = useState(false);
  const [localPreview, setLocalPreview] = useState<string | null>(null);
  const lastResult = useRef<string | undefined>(undefined);
  const pollDelay = useRef(250);
  const generation = useRef(0);
  const changing = useRef(false);
  const addressLoaded = useRef(false);
  const alive = useRef(true);
  const livePanel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15_000);
    getSourceModels(controller.signal).then(value => { if (!controller.signal.aborted) setCatalog(value); }).catch(() => {});
    return () => { clearTimeout(timer); controller.abort(); };
  }, []);
  useEffect(() => {
    if (active && status?.result && window.matchMedia?.("(max-width: 700px)").matches) {
      livePanel.current?.scrollIntoView({ block: "start" });
    }
  }, [status?.result?.predictionId, active]);

  function accept(value: BoxStatus) {
    pollDelay.current = value.cloudCapture ? 1500 : 250;
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
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      const current = generation.current;
      if (!changing.current && document.visibilityState !== "hidden") {
        try { const value = await boxRequest(); if (!stopped && current === generation.current) acceptRef.current(value); }
        catch { if (!stopped && current === generation.current) setUnreachable(true); }
      }
      if (!stopped) timer = setTimeout(poll, pollDelay.current);
    }
    void poll();
    return () => { stopped = true; alive.current = false; clearTimeout(timer); };
  }, []);

  async function change(action: string, body: Record<string, unknown>) {
    if (changing.current) return;
    generation.current++;
    changing.current = true; setBusy(true); setNotice("");
    try {
      const value = await boxRequest(action, body);
      if (alive.current) accept(value);
    } catch (error) {
      if (alive.current) setNotice(error instanceof Error ? error.message : "Connection interrupted. Try again.");
    } finally { changing.current = false; if (alive.current) setBusy(false); }
  }
  const copy = status?.cloudCapture && status.state === "needs_reference"
    ? ["Camera calibration needed.", "Kailangang i-calibrate ang camera.", "Remove the egg, turn on the candling light, then save a fresh empty view below.", "Alisin ang itlog, buksan ang ilaw, at mag-save ng bagong bakanteng kuha sa ibaba."]
    : states[status?.state ?? "not_connected"] ?? states.offline;
  const calibrating = status?.state === "calibrating";
  const setupError = notice || (status?.state === "needs_reference" ? status.error : null);
  const result = status?.result;
  const unfamiliar = result?.recaptureReasons.includes("UNFAMILIAR_APPEARANCE");
  const blurry = result?.recaptureReasons.includes("IMAGE_TOO_BLURRY");
  const recaptureHelp = unfamiliar
    ? t("These views are unfamiliar. The model cannot give a reliable result.", "Hindi pamilyar ang mga larawang ito. Hindi makapagbigay ng maaasahang resulta ang modelo.")
    : blurry ? t("Image too blurry · check camera focus, then replace the egg.", "Malabo ang larawan · suriin ang focus ng camera, saka ilagay muli ang itlog.")
    : t("Unclassified · adjust the view and replace the egg.", "Walang klasipikasyon · ayusin ang kuha at ilagay muli.");
  const cameraLive = !!localPreview || !!status?.connected && !unreachable;
  const label = result?.recaptureRequested ? t("Another image needed", "Kailangan ng ibang larawan")
    : ({ DAY_16: "Day 16", DAY_18: "Day 18", REJECT: t("Reject — suspected", "Posibleng reject") }[result?.sourcePrediction ?? ""]);

  return <section className="automatic-box" aria-label={t("Automatic box", "Awtomatikong kahon")}>
    {catalog?.experimental && <p className="experimental-model" role="note"><strong>{t("Camera model · experimental", "Modelo ng camera · eksperimental")}</strong><span>{t("Live test using the 30-egg dataset. Accuracy is still being evaluated.", "Live na pagsubok gamit ang dataset ng 30 itlog. Sinusuri pa ang katumpakan.")}</span></p>}
    <div className="box-status-line"><span><Radio size={17} />{cameraLive ? t("Camera connected", "Konektado ang camera") : t("Camera not connected", "Hindi konektado ang camera")}</span>
      {status?.calibrated && <button type="button" className="quiet-button" disabled={busy} onClick={() => void change("enabled", { enabled: !status.enabled })}>{status.enabled ? <Pause size={16} /> : <Play size={16} />}{status.enabled ? t("Pause", "I-pause") : t("Resume", "Ituloy")}</button>}
    </div>
    <div className="box-layout">
      <figure className="box-camera">
        <figcaption><span><Camera size={16} strokeWidth={1.5} />{t("Box camera", "Camera ng kahon")}</span><span className="box-camera-signal" data-live={cameraLive}><i aria-hidden="true" />{cameraLive ? t("Live", "Live") : status?.preview ? t("Last image", "Huling larawan") : t("Offline", "Offline")}</span></figcaption>
        <div className="box-camera-stage">
          {localPreview ? <div className="box-camera-direct"><img src={localPreview} alt={t("Latest view inside the candling box", "Huling kuha sa loob ng kahon")} /></div>
            : status?.preview ? <img src={`data:image/jpeg;base64,${status.preview}`} alt={t("Latest view inside the candling box", "Huling kuha sa loob ng kahon")} />
            : <div className="box-camera-empty"><Camera size={40} strokeWidth={1} /><span>{t("Waiting for camera", "Hinihintay ang camera")}</span></div>}
        </div>
      </figure>
      <div ref={livePanel} className="box-live" role="status" aria-live="polite" aria-atomic="true">
        <h2>{unreachable ? t("Connection interrupted.", "Naputol ang koneksyon.") : copy[locale === "en" ? 0 : 1]}</h2>
        <p>{unreachable ? t("Check the EggGrade IoT server. Reconnecting automatically.", "Suriin ang EggGrade IoT server. Kokonekta muli.") : copy[locale === "en" ? 2 : 3]}</p>
        {status?.cloudCapture && <UsbCameraConnect locale={locale} onPreview={setLocalPreview} />}
        {(status?.state === "analyzing" || status?.state === "capturing_views" || calibrating) && <LoaderCircle className="spin" size={24} />}
        {result && <div className="box-result"><span><Check size={15} />{t("Latest saved result", "Huling nai-save na resulta")}</span><h3>{label}</h3><p>{result.recaptureRequested ? recaptureHelp : t("Research estimate · appearance only", "Tantiya para sa pananaliksik · hitsura lamang")}</p>{catalog?.experimental && <p>{result.modelReleaseId === catalog.releaseId ? t("Current experimental camera model", "Kasalukuyang eksperimental na modelo") : t("Earlier model result · place a new egg to test the camera model.", "Resulta ng dating modelo · maglagay ng bagong itlog upang subukan.")}</p>}{result.recaptureRequested && unfamiliar && blurry && <p>{t("Some views also have low detail. Check lens focus and reduce vibration.", "Kulang din sa detalye ang ilang kuha. Suriin ang focus ng lens at bawasan ang pagyanig.")}</p>}<time dateTime={result.createdAt}>{new Date(result.createdAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time></div>}
      </div>
    </div>
    {setupError && <p className="inline-error" role="alert">{setupError}</p>}
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
