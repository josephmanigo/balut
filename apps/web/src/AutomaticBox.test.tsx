import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AutomaticBox } from "./AutomaticBox";
import { boxRequest } from "./api";
import type { BoxStatus, SourcePrediction } from "./api";

vi.mock("./api", () => ({ boxRequest: vi.fn() }));
const blank: BoxStatus = { cameraUrl: "", enabled: false, calibrated: false, connected: false, state: "not_connected", error: null, preview: null, result: null };
const prediction: SourcePrediction = { predictionId: "auto-test", modelId: "egg-grade", sourcePrediction: "DAY_16", analysisOutcome: "CLASSIFIED", recaptureRequested: false, recaptureReasons: [], operationalOutcome: "NOT_AUTHORIZED", operationalUseAuthorized: false, reviewRequired: false, createdAt: "2026-10-14T10:00:00Z" };

describe("automatic camera capture", () => {
  beforeEach(() => vi.resetAllMocks());
  it("requires an empty-box confirmation before starting and keeps capture automatic", async () => {
    const user = userEvent.setup();
    let current = blank;
    vi.mocked(boxRequest).mockImplementation(async action => {
      if (action === "connect") current = { ...blank, cameraUrl: "http://192.168.1.50", connected: true, state: "needs_reference" };
      if (action === "reference") current = { ...current, calibrated: true, enabled: true, state: "waiting" };
      return current;
    });
    render(<AutomaticBox locale="en" onSaved={() => {}} />);
    await screen.findByRole("heading", { name: "Connect your box." });
    await user.type(screen.getByLabelText("Camera address"), "http://192.168.1.50");
    await user.click(screen.getByRole("button", { name: "Connect camera" }));
    expect(await screen.findByRole("heading", { name: "Start with an empty box." })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save empty view & start" })).toBeDisabled();
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Save empty view & start" }));
    expect(await screen.findByRole("heading", { name: "Ready for an egg." })).toBeInTheDocument();
    expect(boxRequest).toHaveBeenCalledWith("reference", { emptyConfirmed: true });
    expect(screen.queryByRole("button", { name: "Analyze egg" })).not.toBeInTheDocument();
  });
  it("receives a saved result through polling without an upload or click", async () => {
    vi.useFakeTimers();
    try {
      const saved = vi.fn();
      vi.mocked(boxRequest).mockResolvedValue({ ...blank, enabled: true, calibrated: true, state: "waiting" });
      render(<AutomaticBox locale="en" onSaved={saved} />);
      await act(async () => { await Promise.resolve(); });
      vi.mocked(boxRequest).mockResolvedValue({ ...blank, calibrated: true, enabled: true, state: "remove_egg", result: prediction });
      await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
      expect(screen.getByRole("heading", { name: "Day 16" })).toBeInTheDocument();
      expect(screen.getByText("Remove the egg before placing the next one.")).toBeInTheDocument();
      await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
      expect(saved).toHaveBeenCalledOnce();
    } finally { vi.useRealTimers(); }
  });
  it("shows disconnection rather than a ready-to-capture state", async () => {
    vi.mocked(boxRequest).mockRejectedValue(new Error("offline"));
    render(<AutomaticBox locale="en" onSaved={() => {}} />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Connection interrupted." })).toBeInTheDocument());
    expect(screen.queryByText("Ready for an egg.")).not.toBeInTheDocument();
  });
  it("updates the live preview while automatic analysis is paused", async () => {
    vi.useFakeTimers();
    try {
      const paused = { ...blank, connected: true, calibrated: true, state: "paused", preview: "first-frame" };
      vi.mocked(boxRequest).mockResolvedValue(paused);
      render(<AutomaticBox locale="en" onSaved={() => {}} />);
      await act(async () => { await Promise.resolve(); });
      expect(screen.getByRole("img")).toHaveAttribute("src", "data:image/jpeg;base64,first-frame");
      vi.mocked(boxRequest).mockResolvedValue({ ...paused, preview: "next-frame" });
      await act(async () => { await vi.advanceTimersByTimeAsync(250); });
      expect(screen.getByRole("img")).toHaveAttribute("src", "data:image/jpeg;base64,next-frame");
      expect(screen.getByRole("heading", { name: "Automatic mode paused." })).toBeInTheDocument();
      expect(boxRequest).not.toHaveBeenCalledWith("enabled", expect.anything());
    } finally { vi.useRealTimers(); }
  });
});
