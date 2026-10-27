import { useEffect, useState } from "react";
import { api, signIn } from "./api";
import type { Session } from "./types";

const ROLE_HINTS: Record<string, string> = {
  operator: "chats with the agent and requests actions",
  reviewer: "approves or rejects risky actions",
  admin: "everything, plus resetting demo data",
};

export default function Login({ onSignedIn }: { onSignedIn: (session: Session) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [demoUsers, setDemoUsers] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<{ demo_users: string[] }>("/auth/config").then((c) => setDemoUsers(c.demo_users)).catch(() => {});
  }, []);

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      onSignedIn(await signIn(username.trim(), password));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-page">
      <form className="login card" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <h1>SafeOps Agent</h1>
        <p className="hint">Sign in. Risky actions need a second person with the reviewer role.</p>
        <label>
          Username
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus />
        </label>
        <label>
          Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                 autoComplete="current-password" />
        </label>
        {error && <div className="error">{error}</div>}
        <button type="submit" className="primary" disabled={busy || !username.trim() || !password}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        {demoUsers.length > 0 && (
          <div className="demo-users">
            <p className="hint">Demo accounts (password in the README):</p>
            {demoUsers.map((u) => (
              <button type="button" key={u} className={username === u ? "active" : ""} onClick={() => setUsername(u)}>
                <b>{u}</b> <span>{ROLE_HINTS[u] ?? ""}</span>
              </button>
            ))}
          </div>
        )}
      </form>
    </div>
  );
}
