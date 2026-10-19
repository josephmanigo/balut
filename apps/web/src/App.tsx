import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Archive,
  BarChart3,
  Boxes,
  Check,
  ChevronRight,
  CircleAlert,
  ClipboardCheck,
  Database,
  FlaskConical,
  Gauge,
  History,
  Languages,
  LoaderCircle,
  LockKeyhole,
  Menu,
  Play,
  RefreshCw,
  ScanLine,
  ServerCog,
  Settings2,
  ShieldAlert,
  Users,
  WifiOff,
  X,
} from "lucide-react";
import { getDashboard, getInspection, getInspections, runSimulator } from "./api";
import { ModelWorkbench } from "./ModelWorkbench";
import { emptyFrames, fallbackDashboard, scenarios } from "./data";
import type {
  DashboardSummary,
  InspectionDetail,
  InspectionOutcome,
  InspectionSummary,
  SimulatorScenario,
} from "./types";

type ViewKey =
  | "overview"
  | "inspections"
  | "review"
  | "batches"
  | "devices"
  | "models"
  | "analytics"
  | "users"
  | "audit";
type Locale = "en" | "fil";

const navItems: Array<{ key: ViewKey; label: string; icon: typeof Gauge }> = [
  { key: "overview", label: "Workbench", icon: Gauge },
  { key: "inspections", label: "Inspections", icon: History },
  { key: "review", label: "Human review", icon: ClipboardCheck },
  { key: "batches", label: "Batches & eggs", icon: Boxes },
  { key: "devices", label: "Device health", icon: Activity },
  { key: "models", label: "Analyze egg", icon: FlaskConical },
  { key: "analytics", label: "Analytics", icon: BarChart3 },
  { key: "users", label: "Users & roles", icon: Users },
  { key: "audit", label: "Audit trail", icon: LockKeyhole },
];

const copy = {
  en: {
    evidence: "Evidence before a grade.",
    subtitle: "Eight stopped views, explicit quality gates, and a result that abstains when the evidence is weak.",
    run: "Run synthetic scan",
    recent: "Recent inspections",
  },
  fil: {
    evidence: "Ebidensiya muna bago grado.",
    subtitle: "Walong nakahintong kuha, malinaw na quality gates, at resultang umiiwas kapag kulang ang ebidensiya.",
    run: "Patakbuhin ang synthetic scan",
    recent: "Mga huling inspeksiyon",
  },
};

const outcomeLabels: Record<InspectionOutcome, string> = {
  DAY_16_LIKE: "Day 16-like",
  DAY_18_LIKE: "Day 18-like",
  REJECT_SUSPECT: "Suspect—segregate for review",
  REVIEW_RECAPTURE: "Review / recapture",
};

const mobilePrimaryViews = new Set<ViewKey>([
  "overview",
  "inspections",
  "review",
  "devices",
]);

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

export function App() {
  const [activeView, setActiveView] = useState<ViewKey>(import.meta.env.DEV ? "overview" : "models");
  const [locale, setLocale] = useState<Locale>("en");
  const [dashboard, setDashboard] = useState<DashboardSummary>(fallbackDashboard);
  const [inspections, setInspections] = useState<InspectionSummary[]>([]);
  const [selected, setSelected] = useState<InspectionDetail | null>(null);
  const [scenario, setScenario] = useState<SimulatorScenario>("day16");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [notice, setNotice] = useState("Connecting to the local evidence service…");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextDashboard, nextInspections] = await Promise.all([
        getDashboard(),
        getInspections(),
      ]);
      setDashboard(nextDashboard);
      setInspections(nextInspections);
      setNotice(
        nextDashboard.device.hardware_connected
          ? "Local device service is reachable."
          : "Local service reachable; physical hardware is not connected.",
      );
      if (!selected && nextInspections[0]) {
        setSelected(await getInspection(nextInspections[0].inspection_id));
      }
    } catch {
      setDashboard(fallbackDashboard);
      setNotice("Local API unavailable. Showing an empty, synthetic-only workbench.");
    } finally {
      setLoading(false);
    }
  }, [selected]);

  useEffect(() => {
    void refresh();
  }, []); // Refresh is intentionally run once on mount; buttons trigger later refreshes.

  const handleRun = async () => {
    setRunning(true);
    setNotice("Generating synthetic probability vectors—no camera or CNN is running.");
    try {
      const definition = scenarios.find((item) => item.value === scenario)!;
      const response = await runSimulator(scenario, definition.hours);
      setSelected(response.inspection);
      const [nextDashboard, nextInspections] = await Promise.all([
        getDashboard(),
        getInspections(),
      ]);
      setDashboard(nextDashboard);
      setInspections(nextInspections);
      setNotice(
        `Synthetic scan stored. Result: ${outcomeLabels[response.inspection.outcome]}. No camera or CNN was used.`,
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Synthetic scan failed.");
    } finally {
      setRunning(false);
    }
  };

  const openInspection = async (inspectionId: string) => {
    try {
      setSelected(await getInspection(inspectionId));
      setActiveView("overview");
    } catch {
      setNotice("That inspection could not be loaded from the local service.");
    }
  };

  const pendingReviews = inspections.filter(
    (inspection) => inspection.outcome === "REVIEW_RECAPTURE" || inspection.outcome === "REJECT_SUSPECT",
  );

  const navigate = (key: ViewKey) => {
    setActiveView(key);
    setMoreOpen(false);
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true"><ScanLine size={23} /></div>
          <div>
            <strong>EggGrade IoT</strong>
            <span>Research workbench</span>
          </div>
        </div>

        <nav aria-label="Primary navigation">
          {navItems.filter(({ key }) => import.meta.env.DEV || key !== "review").map(({ key, label, icon: Icon }) => (
            <button
              className={`${activeView === key ? "nav-item active" : "nav-item"} ${mobilePrimaryViews.has(key) ? "mobile-primary" : "mobile-secondary"}`}
              key={key}
              onClick={() => navigate(key)}
              type="button"
              title={label}
              aria-current={activeView === key ? "page" : undefined}
            >
              <Icon size={18} aria-hidden="true" />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <button
          className="mobile-more-button"
          type="button"
          aria-expanded={moreOpen}
          aria-controls="mobile-more-menu"
          onClick={() => setMoreOpen((open) => !open)}
        >
          <Menu size={19} aria-hidden="true" />
          <span>More</span>
        </button>

        {moreOpen && (
          <div className="mobile-more-menu" id="mobile-more-menu" role="menu" aria-label="More destinations">
            {navItems.filter(({ key }) => !mobilePrimaryViews.has(key) && (import.meta.env.DEV || key !== "review")).map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                type="button"
                role="menuitem"
                className={activeView === key ? "active" : ""}
                aria-current={activeView === key ? "page" : undefined}
                onClick={() => navigate(key)}
              >
                <Icon size={18} aria-hidden="true" />
                <span>{label}</span>
              </button>
            ))}
          </div>
        )}

        <div className="sidebar-foot">
          <div className="authority-stamp">
            <ShieldAlert size={18} aria-hidden="true" />
            <div><strong>Shadow mode</strong><span>No food-safety claim</span></div>
          </div>
          <button
            className="locale-control"
            onClick={() => setLocale(locale === "en" ? "fil" : "en")}
            type="button"
            aria-pressed={locale === "fil"}
            aria-label={locale === "en" ? "Enable limited Filipino preview" : "Return to English"}
            title={locale === "en" ? "Limited Filipino preview" : "Return to English"}
          >
            <Languages size={17} />
            {locale === "en" ? "Filipino preview" : "English"}
          </button>
        </div>
      </aside>

      <main>
        <header className="topline">
          <div className="status-sentence" aria-live="polite">
            {loading ? <LoaderCircle className="spin" size={17} /> : dashboard.device.hardware_connected ? <Check size={17} /> : <WifiOff size={17} />}
            <span>{notice}</span>
          </div>
          <button className="icon-button" onClick={() => void refresh()} type="button" aria-label="Refresh evidence service">
            <RefreshCw size={18} />
          </button>
        </header>

        <div className="authority-banner">
          <span>{import.meta.env.DEV ? "SYNTHETIC DEMONSTRATION" : "LOCAL IMAGE ANALYSIS"}</span>
          <p>{import.meta.env.DEV ? "Automatic grading is unavailable. Model predictions support review; synthetic scans are demonstration records." : "Unclear images stay unclassified and request another image. Candler hardware is not connected."}</p>
        </div>

        {activeView === "overview" && (
          <Overview
            dashboard={dashboard}
            inspections={inspections}
            selected={selected}
            scenario={scenario}
            setScenario={setScenario}
            running={running}
            onRun={handleRun}
            onOpenInspection={openInspection}
            locale={locale}
          />
        )}
        {activeView === "inspections" && (
          <InspectionTable inspections={inspections} onOpen={openInspection} />
        )}
        {activeView === "review" && <ReviewQueue inspections={pendingReviews} onOpen={openInspection} />}
        {activeView === "batches" && <RegistryView />}
        {activeView === "devices" && <DeviceView dashboard={dashboard} />}
        {activeView === "models" && <ModelView />}
        {activeView === "analytics" && <AnalyticsView dashboard={dashboard} />}
        {activeView === "users" && <UsersView />}
        {activeView === "audit" && <AuditView />}
      </main>
    </div>
  );
}

function Overview({
  dashboard,
  inspections,
  selected,
  scenario,
  setScenario,
  running,
  onRun,
  onOpenInspection,
  locale,
}: {
  dashboard: DashboardSummary;
  inspections: InspectionSummary[];
  selected: InspectionDetail | null;
  scenario: SimulatorScenario;
  setScenario: (value: SimulatorScenario) => void;
  running: boolean;
  onRun: () => void;
  onOpenInspection: (inspectionId: string) => void;
  locale: Locale;
}) {
  const frames = selected?.view_frames ?? emptyFrames;
  const machine = selected?.machine_result;
  const resultClass = selected ? `result ${selected.outcome.toLowerCase()}` : "result empty";

  return (
    <>
      <section className="hero-copy">
        <div>
          <h1>{copy[locale].evidence}</h1>
          <p>{copy[locale].subtitle}</p>
        </div>
        <div className="readiness-ledger" aria-label="Current readiness">
          <StatusRow label="Lid interlock" value="Not connected" state="blocked" />
          <StatusRow label="Egg presence" value="Not connected" state="blocked" />
          <StatusRow label="ESP32 model" value="No validated release" state="blocked" />
        </div>
      </section>

      <section className="capture-console" aria-labelledby="capture-title">
        <div className="section-heading">
          <div>
            <h2 id="capture-title">Eight-view evidence</h2>
            <p>Frames are ordered by target holder angle. Validity and per-view probabilities remain inspectable.</p>
          </div>
          <div className="view-count"><strong>{machine?.valid_view_count ?? 0}</strong><span>/ 8 valid</span></div>
        </div>

        <p className="frame-swipe-cue">Swipe to inspect all 8 views <span aria-hidden="true">→</span></p>

        <div className={running ? "frame-strip scanning" : "frame-strip"}>
          {frames.map((frame) => (
            <article className={frame.valid ? "frame valid" : "frame invalid"} key={frame.frame_id}>
              <div className="frame-image">
                <span>{String(frame.view_index + 1).padStart(2, "0")}</span>
                <strong>{frame.angle_degrees}°</strong>
                <small>{frame.capture_authority.includes("SIMULATOR") ? "SYNTHETIC FRAME" : "NO IMAGE"}</small>
              </div>
              <ProbabilityRows probabilities={frame.probabilities} />
              <div className="frame-state">
                {frame.valid ? <Check size={14} /> : <X size={14} />}
                {frame.quality_flags[0]?.replaceAll("_", " ") ?? (frame.valid ? "quality pass" : "not captured")}
              </div>
            </article>
          ))}
        </div>

        <div className="control-deck">
          <div className="scenario-field">
            <label htmlFor="scenario">Evidence scenario</label>
            <select id="scenario" value={scenario} onChange={(event) => setScenario(event.target.value as SimulatorScenario)}>
              {scenarios.map((item) => <option key={item.value} value={item.value}>{item.label} — {item.intent}</option>)}
            </select>
          </div>
          <button className="primary-action" onClick={onRun} type="button" disabled={running || !import.meta.env.DEV}>
            {running ? <LoaderCircle className="spin" size={19} /> : <Play size={19} fill="currentColor" />}
            {!import.meta.env.DEV ? "Simulator disabled" : running ? "Generating evidence…" : copy[locale].run}
          </button>
          <p className="control-note"><CircleAlert size={17} /> This control creates deterministic probability vectors. It does not start motion, lighting, a camera, or CNN.</p>
        </div>
      </section>

      <section className="decision-band">
        <div className={resultClass} role="status" aria-live="polite" aria-atomic="true">
          <div className="result-label">Operational result</div>
          <h2>{selected ? outcomeLabels[selected.outcome] : "No result yet"}</h2>
          <p>{machine?.explanation ?? "Run a synthetic scenario to exercise the aggregation contract."}</p>
          <dl>
            <div><dt>Aggregate confidence</dt><dd>{machine ? formatPercent(machine.confidence) : "—"}</dd></div>
            <div><dt>Class margin</dt><dd>{machine ? formatPercent(machine.class_margin) : "—"}</dd></div>
            <div><dt>View agreement</dt><dd>{machine ? formatPercent(machine.view_agreement) : "—"}</dd></div>
          </dl>
        </div>
        <div className="evidence-ledger">
          <h3>Decision ledger</h3>
          <LedgerRow label="Recorded age" value={selected?.recorded_age_label ?? "Not recorded"} />
          <LedgerRow label="Decision authority" value={machine?.decision_authority ?? "None"} />
          <LedgerRow label="Model release" value={selected?.model_release_id ?? "No validated model"} />
          <LedgerRow label="Quality gates" value={machine?.quality_gate_version ?? "Not evaluated"} />
          <LedgerRow label="Flags" value={machine?.machine_flags.join(", ").replaceAll("_", " ") || "None"} />
        </div>
      </section>

      <section className="lower-workbench">
        <div className="daily-tally">
          <div className="section-heading compact"><div><h2>Today’s operational tally</h2><p>Synthetic records remain isolated by evidence authority.</p></div><strong>{dashboard.total}</strong></div>
          <div className="tally-lines">
            {(Object.keys(outcomeLabels) as InspectionOutcome[]).map((outcome) => (
              <div key={outcome}><span>{outcomeLabels[outcome]}</span><b>{dashboard.outcome_counts[outcome] ?? 0}</b></div>
            ))}
          </div>
        </div>
        <div className="recent-list">
          <div className="section-heading compact"><div><h2>{copy[locale].recent}</h2><p>Newest immutable machine result first.</p></div></div>
          {inspections.length === 0 ? (
            <EmptyState icon={Archive} title="No inspections stored" detail="The ledger is empty; no example is presented as observed evidence." />
          ) : inspections.slice(0, 5).map((inspection) => (
            <button key={inspection.inspection_id} className="inspection-row" onClick={() => onOpenInspection(inspection.inspection_id)} type="button">
              <span className={`outcome-marker ${inspection.outcome.toLowerCase()}`} aria-hidden="true" />
              <span><strong>{outcomeLabels[inspection.outcome]}</strong><small>{formatDate(inspection.created_at)} · {inspection.valid_view_count}/8 views</small></span>
              <span className="row-confidence">{formatPercent(inspection.confidence)}</span>
              <ChevronRight size={17} />
            </button>
          ))}
        </div>
      </section>
    </>
  );
}

function ProbabilityRows({ probabilities }: { probabilities: ViewFrameProbabilities }) {
  const rows = [
    ["D16", probabilities.DAY_16_LIKE, "day16"],
    ["D18", probabilities.DAY_18_LIKE, "day18"],
    ["REJ", probabilities.REJECT_SUSPECT, "reject"],
  ] as const;
  return <div className="probability-rows">{rows.map(([label, value, className]) => (
    <div key={label}><span>{label}</span><i><b className={className} style={{ width: `${value * 100}%` }} /></i><em>{Math.round(value * 100)}</em></div>
  ))}</div>;
}

type ViewFrameProbabilities = InspectionDetail["view_frames"][number]["probabilities"];

function StatusRow({ label, value, state }: { label: string; value: string; state: "good" | "blocked" }) {
  return <div className="status-row"><span className={state} /><strong>{label}</strong><small>{value}</small></div>;
}

function LedgerRow({ label, value }: { label: string; value: string }) {
  return <div className="ledger-row"><dt>{label}</dt><dd>{value}</dd></div>;
}

function PageHeading({ title, detail }: { title: string; detail: string }) {
  return <div className="page-heading"><h1>{title}</h1><p>{detail}</p></div>;
}

function InspectionTable({ inspections, onOpen }: { inspections: InspectionSummary[]; onOpen: (id: string) => void }) {
  return <section><PageHeading title="Inspection history" detail="Machine results are immutable; reviewer dispositions append to the record." />
    {inspections.length === 0 ? <EmptyState icon={History} title="No inspection records" detail="Connect the local API or run a clearly labeled synthetic scenario." /> :
      <div className="table-wrap"><table><thead><tr><th>Created</th><th>Outcome</th><th>Evidence</th><th>Views</th><th>Confidence</th><th>Review</th><th /></tr></thead><tbody>
        {inspections.map((item) => <tr key={item.inspection_id}><td>{formatDate(item.created_at)}</td><td><span className={`table-outcome ${item.outcome.toLowerCase()}`}>{outcomeLabels[item.outcome]}</span></td><td>{item.evidence_mode.replaceAll("_", " ")}</td><td>{item.valid_view_count}/8</td><td>{formatPercent(item.confidence)}</td><td>{item.review_status.replaceAll("_", " ")}</td><td><button className="text-button" onClick={() => onOpen(item.inspection_id)}>Inspect <ChevronRight size={15} /></button></td></tr>)}
      </tbody></table></div>}
  </section>;
}

function ReviewQueue({ inspections, onOpen }: { inspections: InspectionSummary[]; onOpen: (id: string) => void }) {
  return <section><PageHeading title="Human review queue" detail="Reviewers see evidence before the machine outcome is used as a disposition." />
    <div className="protocol-callout"><ShieldAlert size={21} /><div><strong>Human-first protocol is required for research labels.</strong><p>Two independent ratings must be recorded before adjudication; unresolved cases do not enter supervised training or primary metrics.</p></div></div>
    {inspections.length === 0 ? <EmptyState icon={ClipboardCheck} title="No pending review" detail="Reject-suspect and review/recapture inspections will appear here." /> : inspections.map((item) => <button className="queue-item" key={item.inspection_id} onClick={() => onOpen(item.inspection_id)}><span>{outcomeLabels[item.outcome]}</span><strong>{item.inspection_id.slice(0, 13)}…</strong><small>{item.valid_view_count}/8 valid · {formatPercent(item.confidence)}</small><ChevronRight /></button>)}
  </section>;
}

function RegistryView() {
  return <section><PageHeading title="Batch and egg registry" detail="Incubation time is a recorded source fact, never inferred chronological truth." />
    <div className="split-ledger"><div><h2>Required batch fields</h2><p>Supplier, incubator, documented entry timestamp, breed or line when known, temperature interruptions, and collection protocol version.</p></div><div><h2>Required egg identity</h2><p>A durable physical-egg ID keeps every angle, recapture, and Day 16/Day 18 session in one leakage-safe partition.</p></div></div>
    <EmptyState icon={Boxes} title="No production registry loaded" detail="The API includes batch and physical-egg contracts; operator forms remain a subsequent implementation slice." />
  </section>;
}

function DeviceView({ dashboard }: { dashboard: DashboardSummary }) {
  const checks = [
    ["Physical connection", dashboard.device.hardware_connected ? "Connected" : "Not demonstrated"],
    ["Validated model", dashboard.device.model_release_id ?? "No release installed"],
    ["Interlock telemetry", "Unavailable without hardware"],
    ["Synchronization", `${dashboard.pending_sync} outbox record(s) pending`],
  ];
  return <section><PageHeading title="Device health" detail="Cloud and laptop status cannot override the hard-wired safety boundary." />
    <div className="device-plate"><div><ServerCog size={30} /><h2>{dashboard.device.display_name}</h2><code>{dashboard.device.device_id}</code></div><span className="connection-state blocked"><WifiOff size={17} /> Hardware not connected</span></div>
    <dl className="health-list">{checks.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
  </section>;
}

function ModelView() {
  return <section><PageHeading title="Analyze egg" detail="Automatic appearance analysis. Unclear images request another view." />
    <ModelWorkbench />
  </section>;
}

function AnalyticsView({ dashboard }: { dashboard: DashboardSummary }) {
  const max = Math.max(1, ...Object.values(dashboard.outcome_counts));
  return <section><PageHeading title="Analytics" detail="Current counts describe synthetic workflow records only; they are not model performance metrics." />
    <div className="analytic-plot" role="img" aria-label="Outcome counts for today's synthetic workflow records">
      {(Object.keys(outcomeLabels) as InspectionOutcome[]).map((outcome) => <div key={outcome}><span>{outcomeLabels[outcome]}</span><i><b className={outcome.toLowerCase()} style={{ width: `${((dashboard.outcome_counts[outcome] ?? 0) / max) * 100}%` }} /></i><strong>{dashboard.outcome_counts[outcome] ?? 0}</strong></div>)}
    </div>
    <div className="protocol-callout"><CircleAlert size={21} /><div><strong>Performance panel intentionally withheld.</strong><p>Balanced accuracy, class recall, selective coverage, calibration, and confidence intervals require the frozen prospective physical-egg test set.</p></div></div>
  </section>;
}

function UsersView() {
  return <section><PageHeading title="Users and roles" detail="Operational authority is local; cloud users never send motor or illumination commands." />
    <div className="role-matrix"><div><strong>Operator</strong><p>Run local scans and view assigned operational records.</p></div><div><strong>Reviewer</strong><p>Append evidence-backed dispositions without overwriting machine output.</p></div><div><strong>Admin</strong><p>Manage users, devices, batches, exports, releases, and audit access.</p></div></div>
  </section>;
}

function AuditView() {
  return <section><PageHeading title="Immutable audit trail" detail="Each local audit event includes its predecessor hash and a canonical context hash." />
    <div className="audit-explainer"><Database size={34} /><div><h2>Append, verify, synchronize</h2><p>The local SQLite transaction stores the inspection, eight frame records, machine result, audit event, and sync-outbox entry together. Cloud upserts key on immutable UUIDs.</p></div></div>
    <EmptyState icon={LockKeyhole} title="Use the API audit endpoint" detail="The viewer shell is present; filtering, pagination, and chain verification UI remain to be completed." />
  </section>;
}

function EmptyState({ icon: Icon, title, detail }: { icon: typeof Archive; title: string; detail: string }) {
  return <div className="empty-state"><Icon size={27} /><div><strong>{title}</strong><p>{detail}</p></div></div>;
}
