import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { Workspace } from "./Workspace";
import { boxRequest } from "./api";

vi.mock("./api", () => ({ boxRequest: vi.fn(), getPredictionHistory: vi.fn() }));

beforeEach(() => vi.mocked(boxRequest).mockResolvedValue({ cameraUrl: "http://192.168.2.2:8767", enabled: true, connected: true, calibrated: true, state: "waiting", error: null, preview: null, result: null }));

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
});

it("shows shared history only when the backend confirms shared storage", () => {
  render(<Workspace locale="en" setLocale={() => {}} onSignOut={() => {}} signingOut={false} notice="" cloudDemo sharedStorage />);
  expect(screen.getByText("Saved online · Shared across your devices")).toBeInTheDocument();
  expect(screen.queryByRole("note")).not.toBeInTheDocument();
});
