import { useEffect, useRef, useState } from "react";
import { ArrowRight, Check, ImagePlus, LoaderCircle, RefreshCw, ScanLine, Upload, X } from "lucide-react";
import { getSourceModels, analyzeEgg } from "./api";
import type { SourceModelCatalog, SourcePrediction } from "./api";

const results: Record<string, { title: string; description: string }> = {
  DAY_16: { title: "Day 16", description: "Appearance matches Day 16 examples." },
  DAY_18: { title: "Day 18", description: "Appearance matches Day 18 examples." },
  REJECT: { title: "Reject — suspected", description: "Appearance matches reject examples. Not a food-safety verdict." },
};
const recaptureHelp: Record<string, [string, string]> = {
  IMAGE_TOO_SMALL: ["Use a larger image.", "Gumamit ng mas malaking larawan."],
  LOW_CONTRAST: ["Adjust the candling light.", "Ayusin ang ilaw ng candling."],
  IMAGE_TOO_BLURRY: ["Hold steady. Focus on the egg.", "Huwag igalaw. Ituon sa itlog."],
  EXPOSURE_CLIPPED: ["Adjust exposure. Keep shell details visible.", "Ayusin ang exposure. Panatilihing malinaw ang detalye."],
  AMBIGUOUS_APPEARANCE: ["Take another view of the same egg.", "Kunan muli sa ibang anggulo ang itlog."],
  UNFAMILIAR_APPEARANCE: ["Center one egg. Use consistent lighting.", "Igitna ang itlog. Gumamit ng pantay na ilaw."],
  INSUFFICIENT_VALIDATION_SUPPORT: ["Too few matching examples. Try another view.", "Kulang ang katugmang halimbawa. Kunan sa ibang anggulo."],
};

export function ModelWorkbench({ locale = "en" }: { locale?: "en" | "fil" }) {
  const t = (en: string, fil: string) => locale === "en" ? en : fil;
  const [catalog, setCatalog] = useState<SourceModelCatalog | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [retry, setRetry] = useState(0);
  const [result, setResult] = useState<SourcePrediction | null>(null);
  const requestKey = useRef(crypto.randomUUID());
  const inFlight = useRef(false);
  const input = useRef<HTMLInputElement>(null);
  const resultPanel = useRef<HTMLElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const timer = setTimeout(() => controller.abort(), 10_000);
    setLoading(true); setNotice("");
    getSourceModels(controller.signal).then(value => { if (active) setCatalog(value); })
      .catch(() => { if (active) { setCatalog(null); setNotice("Cannot reach the model. Check the EggGrade IoT service, then retry."); } })
      .finally(() => { clearTimeout(timer); if (active) setLoading(false); });
    return () => { active = false; controller.abort(); clearTimeout(timer); };
  }, [retry]);
  useEffect(() => {
    if (!file) { setPreview(""); return; }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => {
    if (result && window.matchMedia?.("(max-width: 700px)").matches) {
      resultPanel.current?.scrollIntoView({ block: "start" });
      resultPanel.current?.focus({ preventScroll: true });
    }
  }, [result]);

  function selectFile(next: File | null) {
    if (inFlight.current) return;
    requestKey.current = crypto.randomUUID(); setResult(null); setNotice("");
    if (next && (!/\.jpe?g$/i.test(next.name) || (next.type && next.type !== "image/jpeg"))) {
      setFile(null); setNotice(t("Choose a JPEG image (.jpg or .jpeg).", "Pumili ng JPEG (.jpg o .jpeg).")); return;
    }
    if (next && (next.size === 0 || next.size > 10 * 1024 * 1024)) { setFile(null); setNotice(t("Choose a JPEG under 10 MB.", "Pumili ng JPEG na mas maliit sa 10 MB.")); return; }
    setFile(next);
  }
  async function analyze(event: React.FormEvent) {
    event.preventDefault();
    if (!file || !catalog?.analysisModelId || inFlight.current || result?.recaptureRequested) return;
    inFlight.current = true; setRunning(true); setResult(null); setNotice("");
    try {
      const value = await analyzeEgg(file, requestKey.current);
      const classified = value.analysisOutcome === "CLASSIFIED" && typeof value.sourcePrediction === "string" && Object.hasOwn(results, value.sourcePrediction) && value.recaptureRequested === false;
      const recapture = value.analysisOutcome === "RECAPTURE_REQUIRED" && value.sourcePrediction === null && value.recaptureRequested === true;
      if (value.operationalUseAuthorized !== false || value.operationalOutcome !== "NOT_AUTHORIZED" || value.reviewRequired !== false || !Array.isArray(value.recaptureReasons) || !(classified || recapture)) {
        throw new Error("Unsupported result. No class has been assigned. Restart the EggGrade IoT service.");
      }
      setResult(value);
    } catch (error) {
      setNotice(error instanceof Error && !["AbortError", "TimeoutError", "TypeError"].includes(error.name)
        ? error.message : "Connection interrupted. Retry to recover the saved result.");
    } finally { inFlight.current = false; setRunning(false); }
  }

  return <section className="analysis-workbench" aria-label={t("Egg analysis", "Pagsusuri ng itlog")}>
    <div className="analysis-toolbar"><ol className="analysis-steps" aria-label="Analysis steps"><li className="current"><span>{file ? <Check size={13} /> : "1"}</span>{t("Add image", "Mag-upload")}</li><li className={file ? "current" : ""}><span>{result ? <Check size={13} /> : "2"}</span>{t("Analyze", "Suriin")}</li><li className={result ? "current" : ""}><span>3</span>{t("See result", "Tingnan")}</li></ol><span className={`model-connection ${catalog?.analysisModelId ? "connected" : ""}`} role="status"><span />{loading ? t("Connecting…", "Kumokonekta…") : catalog?.analysisModelId ? t("Model ready", "Handa ang modelo") : t("Model offline", "Offline ang modelo")}</span></div>
    {notice && <p className="inline-error" role="alert">{notice}</p>}
    {!loading && !catalog && <button type="button" className="outline-button" onClick={() => setRetry(retry + 1)}><RefreshCw size={16} />Retry model connection</button>}
    {!loading && catalog && !catalog.analysisModelId && <p role="status">Egg analysis is unavailable. Start the verified model service.</p>}
    {(loading || !!catalog?.analysisModelId) && <form className="analysis-layout" onSubmit={event => void analyze(event)}>
      <div className="image-workspace">
        <div className="surface-heading"><h2>{t("Your image", "Iyong larawan")}</h2><span>{t("One egg per image", "Isang itlog bawat larawan")}</span></div>
        <div className={`image-drop ${dragging ? "is-dragging" : ""} ${preview ? "has-image" : ""}`} onDragOver={event => { event.preventDefault(); if (!running && !loading) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); if (!loading && !running) { if (event.dataTransfer.files.length !== 1) { setNotice(t("Choose one image at a time.", "Pumili ng isang larawan lamang.")); return; } selectFile(event.dataTransfer.files[0]); } }}>
          {preview ? <><img src={preview} alt="Selected candling image for analysis" /><button className="image-remove" type="button" aria-label="Remove selected image" disabled={running} onClick={() => { selectFile(null); if (input.current) input.current.value = ""; }}><X size={18} /></button></> : <div className="drop-prompt"><div className="upload-brackets"><ImagePlus size={34} strokeWidth={1.2} aria-hidden="true" /></div><h3>{t("Bring your egg into view.", "Ipakita ang iyong itlog.")}</h3><p>{t("Drop a candling image here", "I-drop dito ang candling image")}</p></div>}
          <label className={`choose-image ${running || loading ? "is-disabled" : ""}`} htmlFor="candling-image"><Upload size={16} />{preview ? t("Change image", "Palitan ang larawan") : t("Choose image", "Pumili ng larawan")}</label>
          <input ref={input} className="file-input" id="candling-image" aria-label="Candling JPEG" type="file" accept="image/jpeg,.jpg,.jpeg" disabled={running || loading} aria-describedby="image-requirements" onChange={event => selectFile(event.target.files?.[0] ?? null)} />
        </div>
        <div className="image-meta"><span className="selected-filename">{file ? file.name : t("Crop closely. Keep the egg in focus.", "I-crop nang malapit. Ituon sa itlog.")}</span><span id="image-requirements">JPEG · ≤10 MB</span></div>
        <button className="solid-button analyze-button" type="submit" disabled={!file || loading || running || result?.recaptureRequested}>{running ? <><LoaderCircle size={18} className="spin" />{t("Analyzing and saving…", "Sinusuri at sine-save…")}</> : <>{t("Analyze egg", "Suriin ang itlog")}<ArrowRight size={18} /></>}</button>
      </div>
      <section ref={resultPanel} tabIndex={-1} className={`result-workspace ${result ? "has-result" : ""}`} aria-labelledby="result-title" aria-busy={running}>
        <div className="surface-heading"><h2 id="result-title">{t("Your result", "Iyong resulta")}</h2>{result && <span className="saved-indicator"><Check size={14} />{t("Saved", "Nai-save")}</span>}</div>
        <div className="result-body" role="status" aria-live="polite">
          {running ? <div className="result-placeholder"><LoaderCircle className="spin" size={38} strokeWidth={1.2} /><h3>{t("Taking a closer look.", "Sinusuri ang larawan.")}</h3><p>{t("Keep this page open.", "Panatilihing bukas ang pahina.")}</p></div> : result ? <div className={`prediction-content ${result.sourcePrediction ?? "recapture"}`}>
            <span className="result-symbol" aria-hidden="true">{result.sourcePrediction === "DAY_16" ? "16" : result.sourcePrediction === "DAY_18" ? "18" : result.recaptureRequested ? <RefreshCw size={36} strokeWidth={1.2} /> : <ScanLine size={36} strokeWidth={1.2} />}</span>
            <h3>{result.sourcePrediction ? results[result.sourcePrediction].title : t("Another image needed", "Kailangan ng ibang larawan")}</h3>
            <p className="prediction-type">{result.recaptureRequested ? t("Unclassified · research mode", "Walang klasipikasyon · pananaliksik") : t("Research estimate", "Tantiya para sa pananaliksik")}</p>
            {result.sourcePrediction ? <p>{t(results[result.sourcePrediction].description, "Tantiya batay sa hitsura. Hindi pagsusuri ng kaligtasan ng pagkain.")}</p> : <>
              <p className="recapture-next">{(recaptureHelp[result.recaptureReasons[0] ?? "AMBIGUOUS_APPEARANCE"] ?? ["Take a clearer image.", "Kumuha ng mas malinaw na larawan."])[locale === "en" ? 0 : 1]}</p>
              {result.recaptureReasons.length > 1 && <details className="recapture-tips"><summary>{t("More image tips", "Iba pang tip")}</summary><ul>{result.recaptureReasons.slice(1).map(reason => <li key={reason}>{(recaptureHelp[reason] ?? ["Take a clearer image.", "Kumuha ng mas malinaw na larawan."])[locale === "en" ? 0 : 1]}</li>)}</ul></details>}
            </>}
            <button type="button" className="outline-button" onClick={() => input.current?.click()}>{result.recaptureRequested ? t("Choose another image", "Pumili ng ibang larawan") : t("Analyze next egg", "Suriin ang susunod")}<ArrowRight size={16} /></button>
            <details className="prediction-details"><summary>{t("Saved prediction record", "Nai-save na tala")}</summary><p>{result.predictionId}</p><time>{new Date(result.createdAt).toLocaleString()}</time></details>
          </div> : <div className="result-placeholder"><ScanLine size={42} strokeWidth={1} /><h3>{t("Ready when you are.", "Handa kapag handa ka na.")}</h3><p>{file ? t("Image selected. Press Analyze egg.", "Napili na. Pindutin ang Suriin ang itlog.") : t("Add an image to begin.", "Mag-upload upang magsimula.")}</p></div>}
        </div>
        <p className="result-footnote">{t("Unclear image? We’ll ask for another.", "Malabo ang larawan? Hihingi kami ng panibago.")}</p>
      </section>
    </form>}
  </section>;
}
