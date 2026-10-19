import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ModelWorkbench } from "./ModelWorkbench";
import { analyzeEgg, getSourceModels } from "./api";

vi.mock("./api", () => ({ getSourceModels: vi.fn(), analyzeEgg: vi.fn() }));

describe("automatic egg analysis", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:test"), revokeObjectURL: vi.fn() });
    vi.mocked(getSourceModels).mockResolvedValue({ releaseId: "test-release", analysisModelId: "egg-grade", models: [{ id: "egg-grade", classOrder: ["DAY_16", "DAY_18", "REJECT"], input: "one egg" }] });
  });

  it.each([["DAY_16", "Day 16"], ["DAY_18", "Day 18"], ["REJECT", "Reject"], ["UNFERTILIZED", "Reject"]])("automatically displays %s with no model selector", async (prediction, heading) => {
    const user = userEvent.setup();
    vi.mocked(analyzeEgg).mockResolvedValue({ predictionId: "saved-001", sourcePrediction: prediction, modelId: "egg-grade", operationalOutcome: "NOT_AUTHORIZED", operationalUseAuthorized: false, analysisOutcome: "CLASSIFIED", recaptureRequested: false, recaptureReasons: [], reviewRequired: false, createdAt: "2026-09-12T10:00:00Z" });
    render(<ModelWorkbench />);
    const input = await screen.findByLabelText("Candling JPEG");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Analyze egg" })).toBeDisabled();
    const file = new File(["image"], "egg.jpg", { type: "image/jpeg" });
    await user.upload(input, file);
    await user.click(screen.getByRole("button", { name: "Analyze egg" }));
    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
    expect(screen.getByText("Research estimate")).toBeInTheDocument();
    expect(screen.queryByText(/human confirmation required/)).not.toBeInTheDocument();
    expect(analyzeEgg).toHaveBeenCalledWith(file, expect.any(String));
    const key = vi.mocked(analyzeEgg).mock.calls[0][1];
    await user.click(screen.getByRole("button", { name: "Analyze egg" }));
    await waitFor(() => expect(analyzeEgg).toHaveBeenLastCalledWith(file, key));
    await user.upload(input, new File(["new image"], "another.jpg", { type: "image/jpeg" }));
    expect(screen.queryByRole("heading", { name: heading })).not.toBeInTheDocument();
  });

  it("leaves unclear images unclassified and requests a replacement without a review step", async () => {
    const user = userEvent.setup();
    vi.mocked(analyzeEgg).mockResolvedValue({ predictionId: "recapture-001", sourcePrediction: null, modelId: "egg-grade", operationalOutcome: "NOT_AUTHORIZED", operationalUseAuthorized: false, analysisOutcome: "RECAPTURE_REQUIRED", recaptureRequested: true, recaptureReasons: ["AMBIGUOUS_APPEARANCE"], reviewRequired: false, createdAt: "2026-09-12T10:00:00Z" });
    render(<ModelWorkbench />);
    const input = await screen.findByLabelText("Candling JPEG");
    await user.upload(input, new File(["unclear"], "unclear.jpg", { type: "image/jpeg" }));
    await user.click(screen.getByRole("button", { name: "Analyze egg" }));
    expect(await screen.findByRole("heading", { name: "Another image needed" })).toBeInTheDocument();
    expect(screen.getByText("Unclassified · research mode")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Day 16|Day 18|Reject/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/human confirmation required/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Analyze egg" })).toBeDisabled();
    expect(analyzeEgg).toHaveBeenCalledTimes(1);
    const previousKey = vi.mocked(analyzeEgg).mock.calls[0][1];
    await user.upload(input, new File(["new view"], "new-view.jpg", { type: "image/jpeg" }));
    expect(screen.queryByRole("heading", { name: "Another image needed" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Analyze egg" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Analyze egg" }));
    await screen.findByRole("heading", { name: "Another image needed" });
    expect(vi.mocked(analyzeEgg).mock.calls[1][1]).not.toBe(previousKey);
  });

  it("does not display a class when recapture and classification fields conflict", async () => {
    const user = userEvent.setup();
    vi.mocked(analyzeEgg).mockResolvedValue({ predictionId: "bad-contract", sourcePrediction: "DAY_16", modelId: "egg-grade", operationalOutcome: "NOT_AUTHORIZED", operationalUseAuthorized: false, analysisOutcome: "RECAPTURE_REQUIRED", recaptureRequested: true, recaptureReasons: ["LOW_CONTRAST"], reviewRequired: false, createdAt: "2026-09-12T10:00:00Z" });
    render(<ModelWorkbench />);
    await user.upload(await screen.findByLabelText("Candling JPEG"), new File(["unclear"], "egg.jpg", { type: "image/jpeg" }));
    await user.click(screen.getByRole("button", { name: "Analyze egg" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No class has been assigned");
    expect(screen.queryByRole("heading", { name: "Day 16" })).not.toBeInTheDocument();
  });

  it("does not expose an arbitrary model fallback when automatic analysis is unavailable", async () => {
    vi.mocked(getSourceModels).mockResolvedValue({ releaseId: "legacy", analysisModelId: null, models: [{ id: "age-only", classOrder: ["16", "18"], input: "one egg" }] });
    render(<ModelWorkbench />);
    expect(await screen.findByText(/Egg analysis is unavailable/)).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Analyze egg" })).not.toBeInTheDocument();
  });
});
