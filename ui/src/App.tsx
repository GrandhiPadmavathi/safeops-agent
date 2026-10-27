import { useCallback, useEffect, useState } from "react";
import { api, AuthExpired } from "./api";
import ApprovalsView from "./ApprovalsView";
import { Bars, Donut, Stat } from "./charts";
import Login from "./Login";
import RecordsView from "./RecordsView";
import type {
  AgentEvent, AgentResponse, Approval, AuditEntry, DomainInfo, Message, PendingApproval, Row, Session,
} from "./types";

type View = "chat" | "approvals" | "records";

function short(value: unknown): string {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return text.length > 220 ? `${text.slice(0, 220)}…` : text;
}

function EventLine({ event }: { event: AgentEvent }) {
  if (event.type === "tool_call") {
    return (
      <div className={`event ${event.risky ? "risky" : ""}`}>
        <span className="chip">{event.risky ? "risky call" : "lookup"}</span>
        <b>{event.tool}</b> {short(event.arguments)}
      </div>
    );
  }
  if (event.type === "tool_result") {
    const kind = event.rejected ? "rejected" : event.blocked ? "blocked" : "";
    const label = event.rejected ? "rejected" : event.blocked ? "blocked by policy" : "result";
    return (
      <div className={`event ${kind}`}>
        <span className="chip">{label}</span>
        <b>{event.tool}</b> {short(event.result)}
      </div>
    );
  }
  return null;
}

const ChatIcon = () => (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" />
  </svg>
);
const ApprovalsIcon = () => (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6l8-3z" />
    <path d="M8.5 12l2.5 2.5 4.5-5" />
  </svg>
);
const RecordsIcon = () => (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
  </svg>
);

function Insights({ log, audit, domain }: { log: Message[]; audit: AuditEntry[]; domain: string }) {
  const events = log.flatMap((m) => (m.kind === "event" ? [m.event] : []));
  const calls = events.filter((e): e is Extract<AgentEvent, { type: "tool_call" }> => e.type === "tool_call");
  const mine = audit.filter((a) => a.domain === domain);
  const approved = mine.filter((a) => a.event === "approval_decision" && a.decision === "approved").length;
  const rejected = mine.filter((a) => a.event === "approval_decision" && a.decision === "rejected").length;
  const blocked = mine.filter((a) => a.event === "action_blocked").length;
  const executed = mine.filter((a) => a.event === "action_executed").length;

  const usage = new Map<string, { n: number; risky: boolean }>();
  calls.forEach((c) => usage.set(c.tool, { n: (usage.get(c.tool)?.n ?? 0) + 1, risky: c.risky }));

  return (
    <aside className="insights">
      <h3>Session insights</h3>
      <div className="stats two">
        <Stat label="Tool calls (this chat)" value={calls.length} />
        <Stat label="Risky calls" value={calls.filter((c) => c.risky).length} tone="warn" />
        <Stat label="Actions executed" value={executed} tone="good" />
        <Stat label="Blocked by policy" value={blocked} tone="info" hint="Rejected by the dry-run check before a reviewer was asked" />
      </div>
      <div className="card">
        <Donut
          title="Safety decisions"
          size={120}
          data={[
            { label: "Approved", value: approved, color: "#1f9d55" },
            { label: "Rejected", value: rejected, color: "#d64545" },
            { label: "Policy block", value: blocked, color: "#7b4fd6" },
          ]}
        />
      </div>
      <div className="card">
        {usage.size ? (
          <Bars
            title="Tools used in this chat"
            data={[...usage.entries()].map(([tool, u]) => ({
              label: tool,
              value: u.n,
              color: u.risky ? "#e8a317" : "#3d6bf2",
            }))}
          />
        ) : (
          <>
            <h4>Tools used in this chat</h4>
            <p className="hint">Ask something to see which tools the agent picks.</p>
          </>
        )}
      </div>
    </aside>
  );
}

function Workspace({ session, onSignOut }: { session: Session; onSignOut: (reason?: string) => void }) {
  const { user, token } = session;
  const can = (permission: string) => user.permissions.includes(permission);
  const [view, setView] = useState<View>(can("chat") ? "chat" : "approvals");
  const [domains, setDomains] = useState<DomainInfo[]>([]);
  const [domain, setDomain] = useState("ecommerce");
  const [model, setModel] = useState("");
  const [threads, setThreads] = useState<Record<string, string | undefined>>({});
  const [messages, setMessages] = useState<Record<string, Message[]>>({});
  const [pending, setPending] = useState<Record<string, Approval | null>>({});
  const [records, setRecords] = useState<Record<string, Row[]>>({});
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [queue, setQueue] = useState<PendingApproval[]>([]);
  const [notice, setNotice] = useState("");
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const info = domains.find((d) => d.name === domain);
  const log = messages[domain] ?? [];
  const approval = pending[domain] ?? null;
  const myWaiting = Object.values(pending).filter(Boolean).length;
  const canApprove = can("approve");

  const call = useCallback(<T,>(path: string, body?: unknown) => api<T>(path, { token, body }), [token]);
  const fail = useCallback((e: unknown) => {
    if (e instanceof AuthExpired) onSignOut("Your session expired. Please sign in again.");
    else setError(e instanceof Error ? e.message : String(e));
  }, [onSignOut]);

  const refresh = useCallback(async () => {
    const [recs, aud, items] = await Promise.all([
      call<Record<string, Row[]>>(`/domains/${domain}/records`),
      call<AuditEntry[]>("/audit?limit=300"),
      canApprove ? call<PendingApproval[]>("/approvals") : Promise.resolve([]),
    ]);
    setRecords(recs);
    setAudit(aud.reverse());
    setQueue(items);
  }, [call, domain, canApprove]);

  useEffect(() => {
    api<DomainInfo[]>("/domains").then(setDomains).catch(fail);
    api<{ model: string }>("/health").then((h) => setModel(h.model)).catch(() => setModel("offline"));
  }, [fail]);

  useEffect(() => {
    refresh().catch(fail);
  }, [refresh, fail]);

  const apply = useCallback((res: AgentResponse) => {
    const dom = res.domain;
    setThreads((t) => ({ ...t, [dom]: res.thread_id }));
    setPending((p) => ({ ...p, [dom]: res.approval }));
    const added: Message[] = [];
    if (res.decision) {
      const d = res.decision;
      const verb = d.decision === "approved" ? "✔ Approved" : "✖ Rejected";
      added.push({ kind: "event", event: { type: "tool_result", tool: `${verb} by ${d.reviewer}`,
                                            result: d.note || d.summary, rejected: d.decision === "rejected" } });
    }
    res.events
      .filter((e) => e.type !== "approval_required")
      .forEach((event) => added.push({ kind: "event", event }));
    if (res.reply) added.push({ kind: "agent", text: res.reply });
    setMessages((m) => ({ ...m, [dom]: [...(m[dom] ?? []), ...added] }));
  }, []);

  useEffect(() => {
    const waitingThreads = Object.entries(pending)
      .filter(([, a]) => a)
      .map(([dom]) => threads[dom])
      .filter((t): t is string => !!t);
    if (!waitingThreads.length && !canApprove) return;
    const timer = setInterval(async () => {
      try {
        for (const threadId of waitingThreads) {
          const res = await call<AgentResponse>(`/threads/${threadId}`);
          if (res.status !== "awaiting_approval") apply(res);
        }
        await refresh();
      } catch (e) {
        fail(e);
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [pending, threads, canApprove, call, apply, refresh, fail]);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
      await refresh();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const send = (text: string) => {
    if (!text.trim() || busy || approval) return;
    setInput("");
    setMessages((m) => ({ ...m, [domain]: [...(m[domain] ?? []), { kind: "user", text }] }));
    run(async () => apply(await call<AgentResponse>("/chat", { domain, message: text, thread_id: threads[domain] })));
  };

  const decide = (item: PendingApproval, approved: boolean, note: string) =>
    run(async () => {
      const res = await call<AgentResponse>("/approve", { thread_id: item.thread_id, approved, note });
      setNotice(`${approved ? "Approved" : "Rejected"}: ${item.summary}${res.reply ? `. Agent: ${res.reply}` : ""}`);
    });

  const newChat = () => {
    setThreads((t) => ({ ...t, [domain]: undefined }));
    setMessages((m) => ({ ...m, [domain]: [] }));
    setPending((p) => ({ ...p, [domain]: null }));
  };

  const resetData = () =>
    run(async () => {
      await call("/reset", {});
      newChat();
    });

  const badge = canApprove ? queue.filter((q) => q.can_decide).length : myWaiting;

  return (
    <div className="app">
      <header>
        <h1>SafeOps Agent</h1>
        <nav>
          {domains.map((d) => (
            <button key={d.name} className={d.name === domain ? "active" : ""} onClick={() => setDomain(d.name)}>
              {d.title}
            </button>
          ))}
        </nav>
        <span className={`model ${model === "offline" ? "offline" : ""}`}>{model}</span>
        <span className="who" title={user.permissions.join(", ")}>
          {user.username} <i>{user.roles.join(", ")}</i>
        </span>
        <button className="signout" onClick={() => onSignOut()}>Sign out</button>
      </header>

      <div className="shell">
        <nav className="rail" aria-label="Views">
          {can("chat") && (
            <button className={view === "chat" ? "active" : ""} onClick={() => setView("chat")} title="Agent chat">
              <ChatIcon />
              <span>Agent chat</span>
              {!canApprove && badge > 0 && view !== "chat" && <i className="badge">{badge}</i>}
            </button>
          )}
          {canApprove && (
            <button className={view === "approvals" ? "active" : ""} onClick={() => setView("approvals")}
                    title="Approval queue">
              <ApprovalsIcon />
              <span>Approvals</span>
              {badge > 0 && <i className="badge">{badge}</i>}
            </button>
          )}
          <button className={view === "records" ? "active" : ""} onClick={() => setView("records")} title="Live records">
            <RecordsIcon />
            <span>Live records</span>
          </button>
        </nav>

        {view === "chat" && (
          <main className="chat-layout">
            <section className="chat">
              <p className="hint">
                {info?.description} Risky tools:{" "}
                {info?.tools.filter((t) => t.risky).map((t) => <code key={t.name}>{t.name}</code>)}
              </p>
              <div className="log">
                {log.length === 0 && (
                  <div className="samples">
                    <p className="hint">Try one of these:</p>
                    {info?.sample_prompts.map((p) => (
                      <button key={p} onClick={() => send(p)} disabled={busy}>{p}</button>
                    ))}
                  </div>
                )}
                {log.map((m, i) =>
                  m.kind === "event" ? (
                    <EventLine key={i} event={m.event} />
                  ) : (
                    <div key={i} className={`bubble ${m.kind}`}>{m.text}</div>
                  ),
                )}
                {busy && <div className="bubble agent thinking">thinking…</div>}
              </div>

              {approval && (
                <div className="approval">
                  <strong>Waiting for a reviewer</strong>
                  <p>{approval.summary}</p>
                  <pre>{JSON.stringify(approval.arguments, null, 2)}</pre>
                  <p className="hint">
                    Sent to the approval queue. Someone with the reviewer role, other than you, has to approve it
                    before anything changes. This page updates when they decide.
                  </p>
                </div>
              )}

              {error && <div className="error">{error}</div>}

              <form onSubmit={(e) => { e.preventDefault(); send(input); }}>
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={approval ? "Waiting for a reviewer's decision" : "Ask the agent…"}
                  disabled={busy || !!approval}
                />
                <button type="submit" disabled={busy || !!approval || !input.trim()}>Send</button>
                <button type="button" className="ghost" onClick={newChat} disabled={busy}>New chat</button>
              </form>
            </section>
            <Insights log={log} audit={audit} domain={domain} />
          </main>
        )}

        {view === "approvals" && (
          <main className="records-layout">
            {error && <div className="error">{error}</div>}
            {notice && <div className="notice">{notice}</div>}
            <ApprovalsView items={queue} domains={domains} busy={busy} onDecide={decide} />
          </main>
        )}

        {view === "records" && (
          <main className="records-layout">
            {error && <div className="error">{error}</div>}
            <RecordsView
              domain={domain}
              title={info?.title ?? domain}
              records={records}
              audit={audit}
              onReset={can("admin:reset") ? resetData : undefined}
              busy={busy}
            />
          </main>
        )}
      </div>
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [reason, setReason] = useState("");
  const signOut = useCallback((why?: string) => {
    setSession(null);
    setReason(why ?? "");
  }, []);

  if (!session) {
    return (
      <>
        {reason && <div className="notice floating">{reason}</div>}
        <Login onSignedIn={(s) => { setReason(""); setSession(s); }} />
      </>
    );
  }
  return <Workspace key={session.user.username} session={session} onSignOut={signOut} />;
}
