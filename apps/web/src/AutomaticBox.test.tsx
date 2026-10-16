import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AutomaticBox } from "./AutomaticBox";
import { boxRequest } from "./api";
import type { BoxStatus, SourcePrediction } from "./api";

vi.mock("./api", () => ({ boxRequest: vi.fn(), uploadBoxFrame: vi.fn() }));
const blank: BoxStatus = { cameraUrl: "", enabled: false, calibrated: false, connected: false, state: "not_connected", error: null, preview: null, result: null };
const prediction: SourcePrediction = { predictionId: "auto-test", modelId: "egg-grade", sourcePrediction: "DAY_16", analysisOutcome: "CLASSIFIED", recaptureRequested: false, recaptureReasons: [], operationalOutcome: "NOT_AUTHORIZED", operationalUseAuthorized: false, reviewRequired: false, createdAt: "2026-10-14T10:00:00Z" };

describe("automatic camera capture", () => {
  beforeEach(() => vi.resetAllMocks());
  it("offers USB capture and requires a connected camera before calibration", async () => {
    vi.mocked(boxRequest).mockResolvedValue({ ...blank, cloudCapture: true, cameraUrl: "http://127.0.0.1:8767", state: "offline" });
    render(<AutomaticBox locale="en" onSaved={() => {}} />);
    expect(await screen.findByRole("button", { name: "Connect USB camera" })).toBeDisabled();
    expect(screen.getByText(/Use Chrome or Edge on a computer/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Camera address")).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("checkbox"));
    expect(screen.getByRole("button", { name: "Save empty view & start" })).toBeDisabled();
  });
  it("opens the browser's USB picker only after the operator clicks Connect", async () => {
    const requestPort = vi.fn().mockRejectedValue(new DOMException("Cancelled", "NotFoundError"));
    Object.defineProperty(navigator, "serial", { value: { requestPort, getPorts: async () => [], addEventListener: vi.fn(), removeEventListener: vi.fn() }, configurable: true });
    try {
      vi.mocked(boxRequest).mockResolvedValue({ ...blank, cloudCapture: true, cameraUrl: "http://127.0.0.1:8767" });
      render(<AutomaticBox locale="en" onSaved={() => {}} />);
      const button = await screen.findByRole("button", { name: "Connect USB camera" });
      expect(requestPort).not.toHaveBeenCalled();
      await userEvent.setup().click(button);
      expect(requestPort).toHaveBeenCalledOnce();
      expect(await screen.findByRole("button", { name: "Connect USB camera" })).toBeEnabled();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    } finally { Object.defineProperty(navigator, "serial", { value: undefined, configurable: true }); }
  });
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
  it("waits for a steady empty view after one confirmed save, then becomes ready through polling", async () => {
    vi.useFakeTimers();
    try {
      let current: BoxStatus = { ...blank, cloudCapture: true, cameraUrl: "http://127.0.0.1:8767", connected: true, state: "needs_reference" };
      vi.mocked(boxRequest).mockImplementation(async action => {
        if (action === "reference") current = { ...current, state: "calibrating" };
        return current;
      });
      const saved = vi.fn();
      render(<AutomaticBox locale="en" onSaved={saved} />);
      await act(async () => { await Promise.resolve(); });
      fireEvent.click(screen.getByRole("checkbox"));
      await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Save empty view & start" })); });
      expect(screen.getByRole("heading", { name: "Saving the empty view." })).toBeInTheDocument();
      expect(screen.getByText(/Waiting up to 20 seconds/)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Saving empty view…" })).toBeDisabled();
      expect(screen.getByRole("checkbox")).toBeDisabled();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      current = { ...current, calibrated: true, enabled: true, state: "waiting" };
      await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
      expect(screen.getByRole("heading", { name: "Ready for an egg." })).toBeInTheDocument();
      expect(vi.mocked(boxRequest).mock.calls.filter(([action]) => action === "reference")).toEqual([["reference", { emptyConfirmed: true }]]);
      expect(saved).not.toHaveBeenCalled();
    } finally { vi.useRealTimers(); }
  });
  it("shows calibration timeout and requires a new empty-box confirmation", async () => {
    vi.mocked(boxRequest).mockResolvedValue({ ...blank, cloudCapture: true, cameraUrl: "http://127.0.0.1:8767", connected: true,
      state: "needs_reference", error: "No steady empty view was saved. Keep the box empty, steady the camera and lighting, then save again." });
    render(<AutomaticBox locale="en" onSaved={() => {}} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("No steady empty view was saved.");
    expect(screen.getByRole("button", { name: "Save empty view & start" })).toBeDisabled();
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
