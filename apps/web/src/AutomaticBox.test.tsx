import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AutomaticBox } from "./AutomaticBox";
import { boxRequest, uploadBoxFrame } from "./api";
import type { BoxStatus, SourcePrediction } from "./api";

vi.mock("./api", () => ({ boxRequest: vi.fn(), uploadBoxFrame: vi.fn() }));
const blank: BoxStatus = { cameraUrl: "", enabled: false, calibrated: false, connected: false, state: "not_connected", error: null, preview: null, result: null };
const prediction: SourcePrediction = { predictionId: "auto-test", modelId: "egg-grade", sourcePrediction: "DAY_16", analysisOutcome: "CLASSIFIED", recaptureRequested: false, recaptureReasons: [], operationalOutcome: "NOT_AUTHORIZED", operationalUseAuthorized: false, reviewRequired: false, createdAt: "2026-10-14T10:00:00Z" };

describe("automatic camera capture", () => {
  beforeEach(() => vi.resetAllMocks());
  it("shows automatic multi-view progress without a capture button", async () => {
    vi.mocked(boxRequest).mockResolvedValue({ ...blank, cloudCapture: true, calibrated: true, connected: true,
      enabled: true, state: "capturing_views", capturedViews: 2, targetViews: 3 });
    render(<AutomaticBox locale="en" onSaved={() => {}} />);
    expect(await screen.findByRole("heading", { name: "Capturing three views." })).toBeInTheDocument();
    expect(screen.getByText("Views captured · 2 / 3")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /capture|analyze|start/i })).not.toBeInTheDocument();
  });
  it("offers USB capture without a manual cloud setup or start button", async () => {
    vi.mocked(boxRequest).mockResolvedValue({ ...blank, cloudCapture: true, cameraUrl: "http://127.0.0.1:8767", state: "offline" });
    render(<AutomaticBox locale="en" onSaved={() => {}} />);
    expect(await screen.findByRole("button", { name: "Connect USB camera" })).toBeDisabled();
    expect(screen.getByText(/Use Chrome or Edge on a computer/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Camera address")).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByText("Box setup")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /empty.*start/i })).not.toBeInTheDocument();
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
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(boxRequest).not.toHaveBeenCalledWith("reference", expect.anything());
    await user.click(screen.getByRole("button", { name: "Box is empty — start" }));
    expect(await screen.findByRole("heading", { name: "Ready for an egg." })).toBeInTheDocument();
    expect(boxRequest).toHaveBeenCalledWith("reference", { emptyConfirmed: true });
    expect(screen.getByRole("button", { name: "Box is empty — start" }).closest("details")).not.toHaveAttribute("open");
    await user.click(screen.getByText("Box setup"));
    expect(screen.getByRole("button", { name: "Box is empty — start" }).closest("details")).toHaveAttribute("open");
    expect(screen.getByRole("button", { name: "Box is empty — start" })).toBeEnabled();
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
  it("shows calibration performed during box setup without sending a false empty confirmation", async () => {
    vi.useFakeTimers();
    try {
      let current: BoxStatus = { ...blank, cloudCapture: true, cameraUrl: "http://127.0.0.1:8767", connected: true, state: "calibrating" };
      vi.mocked(boxRequest).mockImplementation(async () => current);
      const saved = vi.fn();
      render(<AutomaticBox locale="en" onSaved={saved} />);
      await act(async () => { await Promise.resolve(); });
      expect(screen.getByRole("heading", { name: "Saving the empty view." })).toBeInTheDocument();
      expect(screen.getByText(/Waiting up to 20 seconds/)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /empty.*start|saving empty/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      current = { ...current, calibrated: true, enabled: true, state: "waiting" };
      await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
      expect(screen.getByRole("heading", { name: "Ready for an egg." })).toBeInTheDocument();
      expect(vi.mocked(boxRequest).mock.calls.every(args => args.length === 0)).toBe(true);
      expect(saved).not.toHaveBeenCalled();
    } finally { vi.useRealTimers(); }
  });
  it("explains missing cloud calibration instead of silently learning an egg as the empty view", async () => {
    vi.mocked(boxRequest).mockResolvedValue({ ...blank, cloudCapture: true, cameraUrl: "http://127.0.0.1:8767", connected: true,
      state: "needs_reference", error: "No steady empty view was saved. Keep the box empty, steady the camera and lighting, then save again." });
    render(<AutomaticBox locale="en" onSaved={() => {}} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("No steady empty view was saved.");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Camera calibration needed." })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /empty.*start/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Box setup")).not.toBeInTheDocument();
    expect(boxRequest).not.toHaveBeenCalledWith("reference", expect.anything());
  });
  it("shows automatic empty recognition after reconnecting without another setup click", async () => {
    vi.useFakeTimers();
    try {
      const saved = vi.fn();
      const current: BoxStatus = { ...blank, cloudCapture: true, cameraUrl: "http://127.0.0.1:8767",
        calibrated: true, enabled: true, connected: true, state: "checking_empty" };
      vi.mocked(boxRequest).mockResolvedValue(current);
      render(<AutomaticBox locale="en" onSaved={saved} />);
      await act(async () => { await Promise.resolve(); });
      expect(screen.getByRole("heading", { name: "Checking the empty box." })).toBeInTheDocument();
      expect(screen.queryByText("Box setup")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /empty.*start/i })).not.toBeInTheDocument();
      vi.mocked(boxRequest).mockResolvedValue({ ...current, state: "waiting" });
      await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
      expect(screen.getByRole("heading", { name: "Ready for an egg." })).toBeInTheDocument();
      expect(screen.getByText("Box is empty. Place one egg and keep your hands clear.")).toBeInTheDocument();
      vi.mocked(boxRequest).mockResolvedValue({ ...current, state: "remove_egg", result: prediction });
      await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
      expect(screen.getByText("Remove the egg before placing the next one.")).toBeInTheDocument();
      vi.mocked(boxRequest).mockResolvedValue({ ...current, state: "waiting", result: prediction });
      await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
      expect(screen.getByRole("heading", { name: "Ready for an egg." })).toBeInTheDocument();
      expect(vi.mocked(boxRequest).mock.calls.every(args => args.length === 0)).toBe(true);
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

  it("shows the direct USB image before a cloud upload finishes and releases its URL on disconnect", async () => {
    vi.useFakeTimers();
    const oldCreate = URL.createObjectURL, oldRevoke = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => "blob:direct-preview");
    URL.revokeObjectURL = vi.fn();
    let incoming: ReadableStreamDefaultController<Uint8Array>;
    const port = {
      readable: new ReadableStream<Uint8Array>({ start(controller) { incoming = controller; } }),
      writable: new WritableStream<Uint8Array>({ write() {
        incoming.enqueue(new Uint8Array([...new TextEncoder().encode("BALUT_JPEG 6 85e7bf70\n"), 255, 216, 0, 7, 255, 217, 10]));
      } }),
      getInfo: () => ({ usbVendorId: 0x0403, usbProductId: 0x6001 }),
      open: vi.fn(async () => {}), close: vi.fn(async () => {}),
      setSignals: async (signals: { requestToSend: boolean }) => {
        if (!signals.requestToSend) incoming.enqueue(new TextEncoder().encode("BALUT_USB_READY\n"));
      },
    };
    Object.defineProperty(navigator, "serial", { value: Object.assign(new EventTarget(), { getPorts: async () => [port] }), configurable: true });
    vi.mocked(uploadBoxFrame).mockImplementation(async () => { await new Promise(resolve => setTimeout(resolve, 600)); return true; });
    vi.mocked(boxRequest).mockResolvedValue({ ...blank, cloudCapture: true, preview: "old-cloud-image", state: "offline" });
    try {
      render(<AutomaticBox locale="en" onSaved={() => {}} />);
      await act(async () => { await Promise.resolve(); });
      await act(async () => { await vi.advanceTimersByTimeAsync(121); });
      expect(screen.getByRole("img")).toHaveAttribute("src", "blob:direct-preview");
      expect(screen.getByRole("img").parentElement).toHaveClass("box-camera-direct");
      expect(screen.getByText("Live")).toBeInTheDocument();
      expect(uploadBoxFrame).toHaveBeenCalledOnce();
      await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Disconnect USB camera" })); await vi.advanceTimersByTimeAsync(600); });
      expect(screen.getByRole("img")).toHaveAttribute("src", "data:image/jpeg;base64,old-cloud-image");
      expect(screen.getByText("Last image")).toBeInTheDocument();
      expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:direct-preview");
      expect(port.close).toHaveBeenCalledOnce();
    } finally {
      Object.defineProperty(navigator, "serial", { value: undefined, configurable: true });
      URL.createObjectURL = oldCreate; URL.revokeObjectURL = oldRevoke;
      vi.useRealTimers();
    }
  });
});
