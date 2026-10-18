import { useEffect, useState } from "react";
import { ArrowUpRight, History, Languages, LoaderCircle, LogOut, ScanLine, RefreshCw } from "lucide-react";
import { getPredictionHistory } from "./api";
import type { SourcePrediction } from "./api";
import { AutomaticBox } from "./AutomaticBox";

export function Brand() {
  return <div className="workbench-brand"><ScanLine size={28} strokeWidth={1.5} aria-hidden="true" /><span>balut<span className="brand-suffix">AIoT</span></span></div>;
}

export function Workspace({ locale, setLocale, onSignOut, signingOut, notice, cloudDemo = false, sharedStorage = false }: {
  locale: "en" | "fil"; setLocale: (value: "en" | "fil") => void; onSignOut: () => void; signingOut: boolean; notice: string;
  cloudDemo?: boolean;
  sharedStorage?: boolean;
}) {
  const [view, setView] = useState<"analyze" | "history">("analyze");
  const [historyVersion, setHistoryVersion] = useState(0);
  const t = (en: string, fil: string) => locale === "en" ? en : fil;
  useEffect(() => { document.title = `${view === "analyze" ? "Analyze" : "History"} · Balut AIoT`; document.documentElement.lang = locale; }, [view, locale]);
  return <div className="workspace">
    <a href="#workspace-main" className="skip-link">{t("Skip to workspace", "Pumunta sa workspace")}</a>
    <header className="workspace-header">
      <Brand />
      <nav aria-label="Workspace"><button type="button" aria-current={view === "analyze" ? "page" : undefined} onClick={() => setView("analyze")}><ScanLine size={17} />{t("Analyze", "Suriin")}</button><button type="button" aria-current={view === "history" ? "page" : undefined} onClick={() => setView("history")}><History size={17} />{t("History", "Mga tala")}</button></nav>
      <div className="workspace-account"><button type="button" className="quiet-button" onClick={() => setLocale(locale === "en" ? "fil" : "en")}><Languages size={17} /><span>{locale === "en" ? "Filipino" : "English"}</span></button><span className="account-divider" /><button type="button" className="quiet-button" disabled={signingOut} onClick={onSignOut}><LogOut size={17} /><span>{t("Sign out", "Lumabas")}</span></button></div>
    </header>
    <main className="workspace-main" id="workspace-main">
      {notice && <p className="inline-error" role="alert">{notice}</p>}
      {cloudDemo && !sharedStorage && <p className="inline-error" role="note">{t("Free cloud demo · History and images reset when the server restarts. Keep a separate record of results you need.", "Libreng cloud demo · Mawawala ang mga tala at larawan kapag nag-restart ang server. Magtabi ng kopya ng mahahalagang resulta.")}</p>}
      <div hidden={view !== "analyze"}>
        <div className="workspace-heading"><div><h1>{t("A little light. A closer look.", "Mas malinaw na kuha.")}</h1><p>{t("Place one egg. Results save automatically.", "Maglagay ng isang itlog. Awtomatikong mase-save ang resulta.")}</p></div><span className="workspace-tag">{t("Candling workbench", "Candling workbench")}</span></div>
        <AutomaticBox locale={locale} active={view === "analyze"} onSaved={() => setHistoryVersion(value => value + 1)} />
      </div>
      {view === "history" && <PredictionHistory locale={locale} version={historyVersion} onAnalyze={() => setView("analyze")} />}
      <footer className="workspace-footer"><span>{sharedStorage ? t("Saved online · Shared across your devices", "Naka-save online · Para sa lahat ng iyong device") : cloudDemo ? t("Temporary demo history", "Pansamantalang mga tala") : t("Saved on this laptop", "Naka-save sa laptop na ito")}</span><span>{t("Appearance only · Not a food-safety assessment", "Batay sa hitsura · Hindi pagsusuri ng kaligtasan ng pagkain")}</span></footer>
    </main>
  </div>;
}

function PredictionHistory({ locale, onAnalyze, version }: { locale: "en" | "fil"; onAnalyze: () => void; version: number }) {
  const [items, setItems] = useState<SourcePrediction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const t = (en: string, fil: string) => locale === "en" ? en : fil;
  useEffect(() => {
    let active = true; setLoading(true); setError(false);
    getPredictionHistory().then(value => { if (active) setItems(value); }).catch(() => { if (active) setError(true); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [retry, version]);
  return <section className="history-view"><div className="workspace-heading"><div><h1>{t("Your recent results.", "Mga huling resulta.")}</h1><p>{t("The latest 50 records, kept in one place.", "Ang huling 50 tala, nasa isang lugar.")}</p></div><button type="button" className="outline-button" onClick={() => setRetry(retry + 1)} disabled={loading}><RefreshCw size={16} />{t("Refresh", "I-refresh")}</button></div>
    {loading ? <p className="history-message" role="status"><LoaderCircle className="spin" size={20} />{t("Loading records…", "Kinukuha ang mga tala…")}</p> : error ? <p role="alert" className="inline-error">{t("Records could not load. Try Refresh.", "Hindi makuha ang mga tala. Pindutin ang I-refresh.")}</p> : !items.length ? <div className="history-empty"><History size={32} strokeWidth={1.2} /><h2>{t("A fresh start.", "Bagong simula.")}</h2><p>{t("Your first analysis will appear here.", "Dito lalabas ang unang pagsusuri.")}</p><button type="button" className="solid-button" onClick={onAnalyze}>{t("Analyze an egg", "Suriin ang itlog")}<ArrowUpRight size={17} /></button></div> : <div className="history-list">{items.map(item => {
      const label = item.recaptureRequested ? t("Another image needed", "Kailangan ng ibang larawan") : ({ DAY_16: "Day 16", DAY_18: "Day 18", REJECT: t("Reject — suspected", "Posibleng reject") }[item.sourcePrediction ?? ""] ?? t("Unclassified", "Walang klasipikasyon"));
      return <details key={item.predictionId} className="history-record"><summary><span className={`result-dot ${item.sourcePrediction ?? "recapture"}`} /><strong>{label}</strong><time dateTime={item.createdAt}>{new Date(item.createdAt).toLocaleString(locale === "fil" ? "fil-PH" : "en", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</time><span className="history-expand">+</span></summary><dl><div><dt>{t("Record ID", "ID ng tala")}</dt><dd>{item.predictionId}</dd></div><div><dt>{t("Model", "Modelo")}</dt><dd>{item.modelReleaseId ?? item.modelId}</dd></div><div><dt>{t("Result type", "Uri ng resulta")}</dt><dd>{item.recaptureRequested ? t("Unclassified · new image needed", "Walang klasipikasyon · kumuha ulit") : t("Appearance estimate", "Tantiya batay sa hitsura")}</dd></div></dl></details>;
    })}</div>}
  </section>;
}
