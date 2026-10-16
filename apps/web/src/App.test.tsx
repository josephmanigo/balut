import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

describe("Balut evidence workbench", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  });

  it("fails closed when the local API is unavailable", async () => {
    render(<App />);
    expect(screen.getByText("SYNTHETIC DEMONSTRATION")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/Local API unavailable/)).toBeInTheDocument());
    expect(screen.getByText("No result yet")).toBeInTheDocument();
    expect(screen.getByText(/Automatic grading is unavailable/)).toBeInTheDocument();
  });

  it("makes unsupported model activation visibly blocked", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: "Analyze egg" }));
    expect(screen.getByText(/Unclear images request another view/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Retry model connection" })).toBeInTheDocument());
  });
});
