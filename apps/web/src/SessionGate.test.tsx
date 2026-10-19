import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Login, SessionGate } from "./SessionGate";

vi.mock("./Workspace", () => ({ Brand: () => <span>EggGrade IoT</span>, Workspace: ({ onSignOut }: { onSignOut: () => void }) => <button onClick={onSignOut}>Sign out</button> }));

describe("browser sign-in", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  it("keeps sign up available after the workspace is configured", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockResolvedValue(new Response('{"authenticated":false,"setupRequired":false}'));
    render(<SessionGate />);
    await user.click(await screen.findByRole("button", { name: "Sign up" }));
    expect(screen.getByRole("heading", { name: "Create your account." })).toBeInTheDocument();
    expect(screen.getByLabelText("Confirm password")).toBeInTheDocument();
  });
  it("identifies shared storage without the temporary-history warning", () => {
    render(<Login cloudDemo sharedStorage onLogin={() => {}} />);
    expect(screen.getByText("Shared workspace")).toBeInTheDocument();
    expect(screen.getByText(/private history, on your laptops and phones/)).toBeInTheDocument();
    expect(screen.queryByText(/Temporary cloud history/)).not.toBeInTheDocument();
  });
  it("identifies the cloud account and temporary storage before sign-in", () => {
    render(<Login cloudDemo onLogin={() => {}} />);
    expect(screen.getByText("Cloud demo")).toBeInTheDocument();
    expect(screen.getByText(/Temporary cloud history/)).toBeInTheDocument();
    expect(screen.queryByText("Images and records stay on this laptop.")).not.toBeInTheDocument();
  });
  it("reveals the password, reports rejection, and sends credentials only in the login body", async () => {
    const user = userEvent.setup();
    const done = vi.fn();
    const storePassword = vi.fn();
    vi.stubGlobal("localStorage", { setItem: storePassword });
    vi.mocked(fetch).mockResolvedValueOnce(new Response("{}", { status: 401 })).mockResolvedValueOnce(new Response('{"authenticated":true}'));
    render(<Login onLogin={done} />);
    await user.type(screen.getByLabelText("Username"), "operator");
    const password = screen.getByLabelText("Password");
    await user.type(password, "test-password");
    await user.click(screen.getByRole("button", { name: "Show password" }));
    expect(password).toHaveAttribute("type", "text");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Username or password is incorrect.");
    expect(done).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(done).toHaveBeenCalledOnce());
    expect(fetch).toHaveBeenLastCalledWith("/api/v1/auth/login", expect.objectContaining({ method: "POST", credentials: "same-origin", body: JSON.stringify({ username: "operator", password: "test-password" }) }));
    expect(password).toHaveValue("");
    expect(storePassword).not.toHaveBeenCalled();
  });
  it("restores an existing session and returns to login after sign-out", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockResolvedValueOnce(new Response('{"authenticated":true}')).mockResolvedValueOnce(new Response('{"authenticated":false}'));
    render(<SessionGate />);
    await user.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Welcome back." })).toBeInTheDocument();
    expect(fetch).toHaveBeenLastCalledWith("/api/v1/auth/logout", expect.objectContaining({ method: "POST" }));
  });
  it("creates an account using chosen credentials without shell instructions", async () => {
    const user = userEvent.setup();
    const done = vi.fn();
    vi.mocked(fetch).mockResolvedValue(new Response('{"authenticated":true,"setupRequired":false}', { status: 201 }));
    render(<Login setupRequired onLogin={done} />);
    expect(screen.getByRole("heading", { name: "Create your account." })).toBeInTheDocument();
    expect(screen.queryByText(/PowerShell|Copy-Balut/)).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Username"), "myaccount");
    await user.type(screen.getByLabelText("Password", { exact: true }), "my chosen passphrase");
    await user.type(screen.getByLabelText("Confirm password"), "different passphrase");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Passwords do not match.");
    expect(fetch).not.toHaveBeenCalled();
    await user.clear(screen.getByLabelText("Confirm password"));
    await user.type(screen.getByLabelText("Confirm password"), "my chosen passphrase");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(done).toHaveBeenCalledOnce());
    expect(fetch).toHaveBeenCalledWith("/api/v1/auth/register", expect.objectContaining({ body: JSON.stringify({ username: "myaccount", password: "my chosen passphrase", confirmPassword: "my chosen passphrase" }) }));
  });
  it("shows account setup automatically for an unconfigured laptop", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response('{"authenticated":false,"setupRequired":true}'));
    render(<SessionGate />);
    expect(await screen.findByRole("heading", { name: "Create your account." })).toBeInTheDocument();
  });
  it("keeps signup open after a duplicate username so another name can be chosen", async () => {
    const user = userEvent.setup();
    const done = vi.fn();
    vi.mocked(fetch).mockResolvedValueOnce(new Response('{"detail":"That username is already taken. Choose another or sign in."}', { status: 409 }))
      .mockResolvedValueOnce(new Response('{"authenticated":true}', { status: 201 }));
    render(<Login onLogin={done} />);
    await user.click(screen.getByRole("button", { name: "Sign up" }));
    await user.type(screen.getByLabelText("Username"), "operator");
    await user.type(screen.getByLabelText("Password", { exact: true }), "my chosen passphrase");
    await user.type(screen.getByLabelText("Confirm password"), "my chosen passphrase");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That username is already taken.");
    expect(screen.getByRole("heading", { name: "Create your account." })).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Username"));
    await user.type(screen.getByLabelText("Username"), "another-user");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(done).toHaveBeenCalledOnce());
  });
});
