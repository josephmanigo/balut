import type {
  DashboardSummary,
  InspectionDetail,
  InspectionSummary,
  SimulatorRunResponse,
  SimulatorScenario,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? "http://127.0.0.1:8000/api/v1" : "/api/v1");
const LOCAL_TOKEN =
  import.meta.env.DEV ? "dev-local-token" : "";

async function apiFetch(url: string, options?: RequestInit): Promise<Response> {
  const response = await fetch(url, { credentials: "same-origin", ...options });
  if (response.status === 401 && !import.meta.env.DEV) window.dispatchEvent(new Event("balut:session-expired"));
  return response;
}

export async function getPredictionHistory(): Promise<SourcePrediction[]> {
  const value = await parse<{ items: SourcePrediction[] }>(await apiFetch(`${API_BASE}/model-predictions?limit=50`));
  return value.items;
}

type JsonObject = Record<string, unknown>;

export interface SourceModelCatalog {
  releaseId: string | null;
  analysisModelId: string | null;
  models: Array<{ id: string; classOrder: string[]; input: string }>;
}

export interface SourcePrediction {
  predictionId: string;
  sourcePrediction: string | null;
  modelId: string;
  operationalOutcome: "NOT_AUTHORIZED";
  analysisOutcome: "CLASSIFIED" | "RECAPTURE_REQUIRED";
  recaptureRequested: boolean;
  recaptureReasons: string[];
  reviewRequired: false;
  operationalUseAuthorized: false;
  createdAt: string;
}

export interface BoxStatus {
  cloudCapture?: boolean;
  cameraUrl: string;
  enabled: boolean;
  connected: boolean;
  calibrated: boolean;
  state: string;
  error: string | null;
  preview: string | null;
  result: SourcePrediction | null;
}

export async function boxRequest(action = "status", body?: Record<string, unknown>): Promise<BoxStatus> {
  const response = await apiFetch(`${API_BASE}/box/${action}`, {
    method: body ? "POST" : "GET", signal: AbortSignal.timeout(45_000),
    headers: { "X-Balut-Origin": "local", ...(body ? { "Content-Type": "application/json" } : {}),
      ...(LOCAL_TOKEN ? { Authorization: `Bearer ${LOCAL_TOKEN}` } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (!response.ok) {
    const value = await response.json().catch(() => null);
    throw new Error(typeof value?.detail === "string" ? value.detail : "Cannot reach the box service. Try again.");
  }
  const value = await response.json() as BoxStatus;
  const result = value.result;
  if (result && (result.operationalOutcome !== "NOT_AUTHORIZED" || result.operationalUseAuthorized !== false || result.reviewRequired !== false || !Array.isArray(result.recaptureReasons)
    || !(result.analysisOutcome === "CLASSIFIED" && !result.recaptureRequested && ["DAY_16", "DAY_18", "REJECT"].includes(result.sourcePrediction ?? "")
      || result.analysisOutcome === "RECAPTURE_REQUIRED" && result.recaptureRequested && result.sourcePrediction === null))) {
    throw new Error("Unsupported box result. No class has been assigned.");
  }
  return value;
}

export async function uploadBoxFrame(body: Uint8Array<ArrayBuffer>, key: string, session: string, signal: AbortSignal): Promise<boolean> {
  const response = await apiFetch(`${API_BASE}/box/frame`, {
    method: "POST", body: new Blob([body], { type: "image/jpeg" }),
    signal: AbortSignal.any([signal, AbortSignal.timeout(130_000)]),
    headers: { "Content-Type": "image/jpeg", "X-Balut-Origin": "local", "Idempotency-Key": key, "X-Balut-Camera-Session": session },
  });
  if (response.status === 409 || response.status === 429 || response.status >= 500) return false;
  const value = await response.json().catch(() => null);
  if (!response.ok || value?.accepted !== true) throw new Error(
    response.status === 401 ? "Sign in again to connect the camera." : typeof value?.detail === "string" ? value.detail : "Camera upload was not accepted. Reconnect and try again.",
  );
  return true;
}

export async function getSourceModels(signal?: AbortSignal): Promise<SourceModelCatalog> {
  return parse<SourceModelCatalog>(await apiFetch(`${API_BASE}/models`, { signal }));
}

export async function analyzeEgg(image: File, key: string): Promise<SourcePrediction> {
  const response = await apiFetch(`${API_BASE}/egg-analysis`, {
    method: "POST", body: image, signal: AbortSignal.timeout(30_000),
    headers: { "Content-Type": "image/jpeg", "X-Balut-Origin": "local", "Idempotency-Key": key,
      ...(LOCAL_TOKEN ? { Authorization: `Bearer ${LOCAL_TOKEN}` } : {}) },
  });
  if (response.status === 429) throw new Error("The model is busy. Wait a moment and try again; your image is still selected.");
  if (response.status === 401) throw new Error("Your local login is required. Reload this page and sign in again.");
  if (response.status === 413) throw new Error("The image is too large. Choose a JPEG under 10 MB.");
  if (response.status === 422) throw new Error("This image could not be read. Choose a valid JPEG, at least 32 pixels per side and no larger than 16 megapixels.");
  if (!response.ok) throw new Error("The result could not be confirmed. Try again with the same image; an earlier saved result will be recovered.");
  return response.json() as Promise<SourcePrediction>;
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function getDashboard(): Promise<DashboardSummary> {
  const raw = await parse<JsonObject>(await apiFetch(`${API_BASE}/dashboard`));
  const devices = raw.devices as JsonObject[];
  const device = devices[0] ?? {};
  return {
    date: new Date().toISOString().slice(0, 10),
    total: Number(raw.totalInspections ?? 0),
    outcome_counts: (raw.outcomeCounts ?? {}) as Record<string, number>,
    review_required: Number(raw.pendingReview ?? 0),
    pending_sync: Number(raw.pendingSync ?? 0),
    device: {
      device_id: String(device.deviceId ?? "UNREGISTERED"),
      display_name: String(device.displayName ?? "No registered device"),
      registered: devices.length > 0,
      hardware_connected: Boolean(device.hardwareValidated),
      model_release_id:
        device.modelReleaseId && device.modelReleaseId !== "SIMULATOR_NO_CNN"
          ? String(device.modelReleaseId)
          : null,
    },
    evidence_mode: Boolean(raw.isSimulated) ? "SYNTHETIC_DEMO_ONLY" : "PHYSICAL_DEVICE",
  };
}

export async function getInspections(): Promise<InspectionSummary[]> {
  const raw = await parse<{ items: JsonObject[] }>(await apiFetch(`${API_BASE}/inspections?limit=50`));
  return raw.items.map(normalizeSummary);
}

export async function getInspection(inspectionId: string): Promise<InspectionDetail> {
  const raw = await parse<JsonObject>(await apiFetch(`${API_BASE}/inspections/${inspectionId}`));
  const summary = normalizeSummary(raw);
  const probabilities = raw.meanProbabilities as JsonObject;
  return {
    ...summary,
    recorded_age_label:
      raw.recordedElapsedHours == null
        ? null
        : `${Math.floor(Number(raw.recordedElapsedHours) / 24)} days ${Math.round(Number(raw.recordedElapsedHours) % 24)} hours`,
    machine_result: {
      outcome: summary.outcome,
      confidence: summary.confidence,
      class_margin: Number(raw.margin ?? 0),
      view_agreement: Number(raw.agreement ?? 0),
      valid_view_count: summary.valid_view_count,
      aggregate_probabilities: normalizeProbabilities(probabilities),
      machine_flags: (raw.flags ?? []) as string[],
      explanation: String(raw.explanation ?? "No explanation was stored."),
      threshold_version: String(raw.thresholdProfileId ?? "UNKNOWN"),
      quality_gate_version: "quality-gates-0.1.0",
      decision_authority: String(raw.authority ?? "UNKNOWN"),
    },
    view_frames: ((raw.views ?? []) as JsonObject[]).map((frame) => ({
      frame_id: `${summary.inspection_id}-${frame.viewIndex}`,
      view_index: Number(frame.viewIndex),
      angle_degrees: Number(frame.angleDegrees),
      image_sha256: String(frame.imageSha256 ?? "NO_IMAGE_CAPTURED"),
      quality_flags: (frame.flags ?? []) as string[],
      probabilities: normalizeProbabilities(frame.probabilities as JsonObject),
      valid: Boolean(frame.qualityValid),
      capture_authority: summary.evidence_mode === "SYNTHETIC_DEMO_ONLY"
        ? "SIMULATOR_NO_CAMERA"
        : "PHYSICAL_DEVICE",
    })),
    reviews: ((raw.reviews ?? []) as JsonObject[]).map((review) => ({
      review_id: String(review.reviewId),
      reviewer_id: String(review.reviewerId),
      disposition: String(review.disposition),
      note: String(review.notes ?? ""),
      created_at: String(review.createdAt),
    })),
  };
}

export async function runSimulator(
  scenario: SimulatorScenario,
  recordedElapsedHours: number | null,
): Promise<SimulatorRunResponse> {
  const stored = await parse<JsonObject>(
    await apiFetch(`${API_BASE}/simulator/run`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(LOCAL_TOKEN ? { Authorization: `Bearer ${LOCAL_TOKEN}` } : {}),
        "X-Balut-Origin": "local",
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify({
        scenario,
        recorded_elapsed_hours: recordedElapsedHours,
      }),
    }),
  );
  return {
    repeated: false,
    inspection: await getInspection(String(stored.inspectionId)),
  };
}

function normalizeProbabilities(raw: JsonObject | undefined): InspectionDetail["machine_result"]["aggregate_probabilities"] {
  return {
    DAY_16_LIKE: Number(raw?.DAY_16_LIKE ?? raw?.day_16_like ?? 0),
    DAY_18_LIKE: Number(raw?.DAY_18_LIKE ?? raw?.day_18_like ?? 0),
    REJECT_SUSPECT: Number(raw?.REJECT_SUSPECT ?? raw?.reject_suspect ?? 0),
  };
}

function normalizeSummary(raw: JsonObject): InspectionSummary {
  return {
    inspection_id: String(raw.inspectionId),
    device_id: String(raw.deviceId),
    batch_id: raw.batchId == null ? null : String(raw.batchId),
    physical_egg_id: raw.eggId == null ? null : String(raw.eggId),
    started_at: String(raw.capturedAt),
    recorded_elapsed_hours: raw.recordedElapsedHours == null ? null : Number(raw.recordedElapsedHours),
    state: String(raw.state),
    outcome: String(raw.outcome) as InspectionSummary["outcome"],
    confidence: Number(raw.confidence),
    valid_view_count: Number(raw.validViews),
    model_release_id: String(raw.modelReleaseId),
    evidence_mode: Boolean(raw.isSimulated) ? "SYNTHETIC_DEMO_ONLY" : "PHYSICAL_DEVICE",
    review_status: Number(raw.reviewCount ?? 0) > 0 ? "REVIEWED" : "UNREVIEWED",
    created_at: String(raw.capturedAt),
  };
}
