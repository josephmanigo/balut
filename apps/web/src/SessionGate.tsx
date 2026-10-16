import { useEffect, useState } from "react";
import { ArrowRight, Eye, EyeOff, Languages, LoaderCircle, LockKeyhole } from "lucide-react";
import { Brand, Workspace } from "./Workspace";

class AuthError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function authRequest(action: string, body?: object) {
  const response = await fetch(`/api/v1/auth/${action}`, {
    method: action === "session" ? "GET" : "POST",
    credentials: "same-origin", signal: AbortSignal.timeout(10_000),
    headers: { "Content-Type": "application/json", "X-Balut-Origin": "local" },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (!response.ok) {
    if (response.status === 401) throw new AuthError(401, "Username or password is incorrect.");
    if (response.status === 429) throw new AuthError(429, "Too many attempts. Wait one minute.");
    if ([400, 409].includes(response.status)) {
      const error = await response.json();
      throw new AuthError(response.status, typeof error.detail === "string" ? error.detail : "Check your details and try again.");
    }
    if (response.status === 422) throw new AuthError(422, "Check your details. Passwords need 12–128 characters.");
    throw new Error("Cannot connect. Check the Balut service and try again.");
  }
  return response.json() as Promise<{ authenticated: boolean; setupRequired?: boolean; username?: string; cloudDemo?: boolean }>;
}

export function SessionGate() {
  const [state, setState] = useState<"checking" | "login" | "ready">("checking");
  const [locale, setLocale] = useState<"en" | "fil">("en");
  const [notice, setNotice] = useState("");
  const [signingOut, setSigningOut] = useState(false);
  const [setupRequired, setSetupRequired] = useState(false);
  const [cloudDemo, setCloudDemo] = useState(false);
  useEffect(() => {
    let active = true;
    const expired = () => { setState("login"); setNotice("Session ended. Sign in again."); };
    window.addEventListener("balut:session-expired", expired);
    authRequest("session").then(value => { if (active) { setCloudDemo(!!value.cloudDemo); setSetupRequired(!!value.setupRequired); setState(value.authenticated ? "ready" : "login"); } })
      .catch(() => { if (active) { setState("login"); setNotice("Cannot connect. Check the Balut service and try again."); } });
    return () => { active = false; window.removeEventListener("balut:session-expired", expired); };
  }, []);

  async function signOut() {
    setSigningOut(true);
    try { await authRequest("logout"); setNotice(""); setState("login"); }
    catch { setNotice("Sign-out failed. Check your connection and try again."); }
    finally { setSigningOut(false); }
  }
  if (state === "checking") return <div className="session-loading" role="status"><Brand /><LoaderCircle className="spin" size={22} /><p>Opening your workspace…</p></div>;
  if (state === "ready") return <Workspace locale={locale} setLocale={setLocale} onSignOut={() => void signOut()} signingOut={signingOut} notice={notice} cloudDemo={cloudDemo} />;
  return <Login locale={locale} setLocale={setLocale} notice={notice} setupRequired={setupRequired} cloudDemo={cloudDemo} onLogin={() => { setSetupRequired(false); setNotice(""); setState("ready"); }} />;
}

export function Login({ locale = "en", setLocale, notice = "", setupRequired = false, cloudDemo = false, onLogin }: {
  locale?: "en" | "fil"; setLocale?: (value: "en" | "fil") => void; notice?: string; setupRequired?: boolean; onLogin: () => void;
  cloudDemo?: boolean;
}) {
  const t = (en: string, fil: string) => locale === "en" ? en : fil;
  const [creating, setCreating] = useState(setupRequired);
  const [canRegister, setCanRegister] = useState(setupRequired);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { document.title = `${creating ? "Create account" : "Sign in"} · Balut AIoT`; document.documentElement.lang = locale; }, [locale, creating]);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (creating && password !== confirmation) { setError(t("Passwords do not match.", "Hindi magkapareho ang mga password.")); return; }
    setBusy(true); setError("");
    try { await authRequest(creating ? "register" : "login", { username: username.trim(), password, ...(creating ? { confirmPassword: confirmation } : {}) }); setPassword(""); setConfirmation(""); onLogin(); }
    catch (failure) {
      if (failure instanceof AuthError && failure.status === 409) { setCreating(false); setCanRegister(false); setPassword(""); setConfirmation(""); }
      setError(failure instanceof Error && failure.name === "Error" ? failure.message : "Cannot connect. Check the Balut service and try again.");
    }
    finally { setBusy(false); }
  }
  return <div className="login-page">
    <section className="login-story" aria-label="Balut workspace">
      <Brand />
      <div className="login-story-body">
        <div className="candling-symbol" aria-hidden="true"><span /><span /><span /></div>
        <h2>{t("A closer look.", "Mas malinaw na kuha.")}<br /><em>{t("A clearer record.", "Mas maayos na tala.")}</em></h2>
        <p>{t("Your candling workspace, all in one place.", "Isang lugar para sa iyong mga candling image.")}</p>
        <div className="login-workflow"><span>{t("Place an egg", "Ilagay ang itlog")}</span><ArrowRight size={16} /><span>{t("See the result", "Tingnan ang resulta")}</span><ArrowRight size={16} /><span>{t("Keep a record", "Itala")}</span></div>
      </div>
      <p className="login-story-foot">{t("Built for a more considered inspection.", "Para sa mas maingat na pagsusuri.")}</p>
    </section>
    <main className="login-panel">
      <div className="login-panel-top"><span>{cloudDemo ? "Cloud demo" : t("Local workspace", "Lokal na workspace")}</span><button className="quiet-button" onClick={() => setLocale?.(locale === "en" ? "fil" : "en")} type="button"><Languages size={16} />{locale === "en" ? "Filipino" : "English"}</button></div>
      <div className="login-form-wrap">
        <LockKeyhole className="login-lock" size={26} strokeWidth={1.4} aria-hidden="true" />
        <h1>{creating ? t("Create your account.", "Gumawa ng account.") : t("Welcome back.", "Maligayang pagbabalik.")}</h1>
        <p>{creating ? t("Your username. Your password. Your workbench.", "Iyong username, password, at workbench.") : t("Sign in to your Balut workbench.", "Mag-sign in sa iyong Balut workbench.")}</p>
        <form className="login-form" onSubmit={event => void submit(event)}>
          <div className="field-group"><label htmlFor="username">Username</label><input id="username" name="username" autoComplete="username" autoCapitalize="none" spellCheck={false} placeholder={creating ? t("Choose a username", "Pumili ng username") : t("Enter your username", "Ilagay ang username")} required minLength={creating ? 3 : undefined} maxLength={creating ? 32 : 80} pattern={creating ? "[a-zA-Z0-9][a-zA-Z0-9_.\\-]{2,31}" : undefined} title={creating ? t("3–32 letters, numbers, dots, underscores or hyphens", "3–32 letra, numero, tuldok, underscore o gitling") : undefined} value={username} onChange={event => setUsername(event.target.value)} disabled={busy} /></div>
          <div className="field-group"><label htmlFor="password">Password</label><div className="password-field"><input id="password" name="password" type={visible ? "text" : "password"} autoComplete={creating ? "new-password" : "current-password"} placeholder={creating ? t("Choose a password", "Pumili ng password") : t("Enter your password", "Ilagay ang password")} required minLength={creating ? 12 : undefined} maxLength={128} value={password} onChange={event => setPassword(event.target.value)} disabled={busy} aria-describedby={[creating ? "password-hint" : "", error ? "login-error" : ""].filter(Boolean).join(" ") || undefined} aria-invalid={!!error} /><button type="button" aria-label={visible ? "Hide password" : "Show password"} aria-pressed={visible} onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={19} /> : <Eye size={19} />}</button></div>{creating && <small className="field-hint" id="password-hint">{t("At least 12 characters. A short phrase works well.", "12 character pataas. Maaaring maikling parirala.")}</small>}</div>
          {creating && <div className="field-group"><label htmlFor="confirm-password">{t("Confirm password", "Ulitin ang password")}</label><input id="confirm-password" name="confirmPassword" type={visible ? "text" : "password"} autoComplete="new-password" placeholder={t("Enter it again", "Ilagay muli")} required minLength={12} maxLength={128} value={confirmation} onChange={event => setConfirmation(event.target.value)} disabled={busy} aria-describedby={error ? "login-error" : undefined} /></div>}
          {(error || notice) && <p className="inline-error" id="login-error" role="alert">{error || notice}</p>}
          <button className="solid-button" type="submit" disabled={busy}>{busy ? <><LoaderCircle className="spin" size={18} />{creating ? t("Creating account…", "Ginagawa ang account…") : t("Signing in…", "Nagsa-sign in…")}</> : <>{creating ? t("Create account", "Gumawa ng account") : t("Sign in", "Mag-sign in")}<ArrowRight size={18} /></>}</button>
        </form>
        {canRegister && <p className="auth-switch">{creating ? t("Already set up?", "May account na?") : t("New to this laptop?", "Bago sa laptop na ito?")} <button type="button" disabled={busy} onClick={() => { setCreating(!creating); setError(""); setPassword(""); setConfirmation(""); setVisible(false); }}>{creating ? t("Sign in", "Mag-sign in") : t("Create account", "Gumawa ng account")}</button></p>}
        <p className="account-note">{cloudDemo ? t("Use the account prepared for this cloud demo.", "Gamitin ang account para sa cloud demo na ito.") : creating ? t("One account for this laptop. Your existing records stay here.", "Isang account para sa laptop. Mananatili ang mga tala.") : t("Use the account you created on this laptop.", "Gamitin ang account na ginawa sa laptop na ito.")}</p>
      </div>
      <footer className="login-panel-foot"><LockKeyhole size={14} aria-hidden="true" />{cloudDemo ? t("Temporary cloud history · resets on server restart.", "Pansamantalang tala · mawawala kapag nag-restart ang server.") : t("Images and records stay on this laptop.", "Naka-save sa laptop na ito ang mga larawan at tala.")}</footer>
    </main>
  </div>;
}
