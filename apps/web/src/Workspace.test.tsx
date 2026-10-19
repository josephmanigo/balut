import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { Workspace } from "./Workspace";
import { boxRequest, getSourceModels } from "./api";

vi.mock("./api", () => ({ boxRequest: vi.fn(), getPredictionHistory: vi.fn(), getSourceModels: vi.fn() }));

beforeEach(() => {
  vi.mocked(getSourceModels).mockResolvedValue({ releaseId: "retained", analysisModelId: "egg-grade", models: [] });
  vi.mocked(boxRequest).mockResolvedValue({ cameraUrl: "http://192.168.2.2:8767", enabled: true, connected: true, calibrated: true, state: "waiting", error: null, preview: null, result: null });
});

it.each(["en", "fil"] as const)("opens directly into automatic capture in %s without a photo picker", async locale => {
  const { container } = render(<Workspace locale={locale} setLocale={() => {}} onSignOut={() => {}} signingOut={false} notice="" />);
  expect(await screen.findByRole("heading", { name: locale === "en" ? "Ready for an egg." : "Handa para sa itlog." })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Attach photo|Mag-attach/ })).not.toBeInTheDocument();
  expect(container.querySelector('input[type="file"]')).toBeNull();
  expect(screen.queryByRole("group", { name: /Image source|Pinagmulan/ })).not.toBeInTheDocument();
});

it("labels temporary Render history clearly", async () => {
  render(<Workspace locale="en" setLocale={() => {}} onSignOut={() => {}} signingOut={false} notice="" cloudDemo />);
  expect(screen.getByRole("note")).toHaveTextContent("History and images reset when the server restarts");
  expect(screen.queryByText("Saved on this laptop")).not.toBeInTheDocument();
  await screen.findByRole("heading", { name: "Ready for an egg." });
});

it.each(["en", "fil"] as const)("removes the storage footer in %s while keeping the appearance boundary", async locale => {
  render(<Workspace locale={locale} setLocale={() => {}} onSignOut={() => {}} signingOut={false} notice="" cloudDemo sharedStorage />);
  expect(screen.queryByText(/Saved online|Shared across your devices|Naka-save online|Para sa lahat ng iyong device/)).not.toBeInTheDocument();
  expect(screen.getByRole("contentinfo")).toHaveTextContent(locale === "en" ? "Appearance only · Not a food-safety assessment" : "Batay sa hitsura · Hindi pagsusuri ng kaligtasan ng pagkain");
  expect(screen.queryByRole("note")).not.toBeInTheDocument();
  await screen.findByRole("heading", { name: locale === "en" ? "Ready for an egg." : "Handa para sa itlog." });
});
