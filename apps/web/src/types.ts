export type InspectionOutcome =
  | "DAY_16_LIKE"
  | "DAY_18_LIKE"
  | "REJECT_SUSPECT"
  | "REVIEW_RECAPTURE";

export type SimulatorScenario =
  | "day16"
  | "day18"
  | "reject"
  | "low_confidence"
  | "bad_capture"
  | "age_mismatch"
  | "device_fault";

export interface DashboardSummary {
  date: string;
  total: number;
  outcome_counts: Record<string, number>;
  review_required: number;
  pending_sync: number;
  device: {
    device_id: string;
    display_name: string;
    registered: boolean;
    hardware_connected: boolean;
    model_release_id: string | null;
  };
  evidence_mode: string;
}

export interface InspectionSummary {
  inspection_id: string;
  device_id: string;
  batch_id: string | null;
  physical_egg_id: string | null;
  started_at: string;
  recorded_elapsed_hours: number | null;
  state: string;
  outcome: InspectionOutcome;
  confidence: number;
  valid_view_count: number;
  model_release_id: string;
  evidence_mode: string;
  review_status: string;
  created_at: string;
}

export interface ViewFrame {
  frame_id: string;
  view_index: number;
  angle_degrees: number;
  image_sha256: string;
  quality_flags: string[];
  probabilities: {
    DAY_16_LIKE: number;
    DAY_18_LIKE: number;
    REJECT_SUSPECT: number;
  };
  valid: boolean;
  capture_authority: string;
}

export interface InspectionDetail extends InspectionSummary {
  recorded_age_label: string | null;
  machine_result: {
    outcome: InspectionOutcome;
    confidence: number;
    class_margin: number;
    view_agreement: number;
    valid_view_count: number;
    aggregate_probabilities: ViewFrame["probabilities"];
    machine_flags: string[];
    explanation: string;
    threshold_version: string;
    quality_gate_version: string;
    decision_authority: string;
  };
  view_frames: ViewFrame[];
  reviews: Array<{
    review_id: string;
    reviewer_id: string;
    disposition: string;
    note: string;
    created_at: string;
  }>;
}

export interface SimulatorRunResponse {
  repeated: boolean;
  inspection: InspectionDetail;
}
