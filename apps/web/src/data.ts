import type { DashboardSummary, InspectionDetail, SimulatorScenario } from "./types";

export const fallbackDashboard: DashboardSummary = {
  date: new Date().toISOString().slice(0, 10),
  total: 0,
  outcome_counts: {
    DAY_16_LIKE: 0,
    DAY_18_LIKE: 0,
    REJECT_SUSPECT: 0,
    REVIEW_RECAPTURE: 0,
  },
  review_required: 0,
  pending_sync: 0,
  device: {
    device_id: "SIM-ESP32-S3-01",
    display_name: "Synthetic ESP32-S3 stand-in",
    registered: true,
    hardware_connected: false,
    model_release_id: null,
  },
  evidence_mode: "SYNTHETIC_DEMO_ONLY",
};

export const emptyFrames: InspectionDetail["view_frames"] = Array.from(
  { length: 8 },
  (_, index) => ({
    frame_id: `EMPTY-${index}`,
    view_index: index,
    angle_degrees: index * 45,
    image_sha256: "NO_IMAGE_CAPTURED",
    quality_flags: [],
    probabilities: {
      DAY_16_LIKE: 0,
      DAY_18_LIKE: 0,
      REJECT_SUSPECT: 0,
    },
    valid: false,
    capture_authority: "NO_HARDWARE_EVIDENCE",
  }),
);

export const scenarios: Array<{
  value: SimulatorScenario;
  label: string;
  hours: number | null;
  intent: string;
}> = [
  { value: "day16", label: "Day 16-like", hours: 384, intent: "Clear synthetic agreement" },
  { value: "day18", label: "Day 18-like", hours: 432, intent: "Clear synthetic agreement" },
  { value: "reject", label: "Reject suspect", hours: null, intent: "Model anomaly only" },
  { value: "low_confidence", label: "Low confidence", hours: 384, intent: "Must abstain" },
  { value: "bad_capture", label: "Bad capture", hours: 384, intent: "Too few valid views" },
  { value: "age_mismatch", label: "Age mismatch", hours: 432, intent: "Timestamp conflict" },
  { value: "device_fault", label: "Device fault", hours: 384, intent: "Safety-first stop" },
];
