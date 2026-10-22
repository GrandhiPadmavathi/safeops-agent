import { useCallback, useEffect, useState } from "react";
import { Bars, Donut, Stat } from "./charts";
import RecordsView from "./RecordsView";
import type { AgentEvent, AgentResponse, Approval, AuditEntry, DomainInfo, Message, Row } from "./types";

type View = "chat" | "records";

async function api<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    if (res.ok) throw new Error(`Unexpected response from ${path}`);
  }
  if (!res.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    throw new Error(`${res.status} ${typeof detail === "string" ? detail : res.statusText}`);
  }
  return data as T;
}

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

export default function App() {
  const [view, setView] = useState<View>("chat");
  const [domains, setDomains] = useState<DomainInfo[]>([]);
  const [domain, setDomain] = useState("ecommerce");
  const [model, setModel] = useState("");
  const [threads, setThreads] = useState<Record<string, string | undefined>>({});
  const [messages, setMessages] = useState<Record<string, Message[]>>({});
  const [pending, setPending] = useState<Record<string, Approval | null>>({});
  const [records, setRecords] = useState<Record<string, Row[]>>({});
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [input, setInput] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const info = domains.find((d) => d.name === domain);
  const log = messages[domain] ?? [];
  const approval = pending[domain] ?? null;
  const waiting = Object.values(pending).filter(Boolean).length;

  const refresh = useCallback(async () => {
    const [recs, aud] = await Promise.all([
      api<Record<string, Row[]>>(`/domains/${domain}/records`),
      api<AuditEntry[]>("/audit?limit=300"),
    ]);
    setRecords(recs);
    setAudit(aud.reverse());
  }, [domain]);

  useEffect(() => {
    api<DomainInfo[]>("/domains").then(setDomains).catch((e) => setError(String(e)));
    api<{ model: string }>("/health").then((h) => setModel(h.model)).catch(() => setModel("offline"));
  }, []);

  useEffect(() => {
    refresh().catch((e) => setError(String(e)));
  }, [refresh]);

  const apply = (res: AgentResponse) => {
    setThreads((t) => ({ ...t, [domain]: res.thread_id }));
    setPending((p) => ({ ...p, [domain]: res.approval }));
    const added: Message[] = res.events
      .filter((e) => e.type !== "approval_required")
      .map((event) => ({ kind: "event", event }));
    if (res.reply) added.push({ kind: "agent", text: res.reply });
    setMessages((m) => ({ ...m, [domain]: [...(m[domain] ?? []), ...added] }));
  };

  const run = async (fn: () => Promise<AgentResponse>) => {
    setBusy(true);
    setError("");
    try {
      apply(await fn());
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const send = (text: string) => {
    if (!text.trim() || busy || approval) return;
    setInput("");
    setMessages((m) => ({ ...m, [domain]: [...(m[domain] ?? []), { kind: "user", text }] }));
    run(() => api<AgentResponse>("/chat", { domain, message: text, thread_id: threads[domain] }));
  };

  const decide = (approved: boolean) => {
    const threadId = threads[domain];
    if (!threadId) return;
    const text = `${approved ? "✔ Approved" : "✖ Rejected"}: ${approval?.summary}${note ? ` — ${note}` : ""}`;
    setMessages((m) => ({ ...m, [domain]: [...(m[domain] ?? []), { kind: "user", text }] }));
    setNote("");
    run(() => api<AgentResponse>("/approve", { thread_id: threadId, approved, reviewer: "ui-reviewer", note }));
  };

  const newChat = () => {
    setThreads((t) => ({ ...t, [domain]: undefined }));
    setMessages((m) => ({ ...m, [domain]: [] }));
    setPending((p) => ({ ...p, [domain]: null }));
  };

  const resetData = async () => {
    setBusy(true);
    try {
      await api("/reset", {});
      newChat();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

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
      </header>

      <div className="shell">
        <nav className="rail" aria-label="Views">
          <button className={view === "chat" ? "active" : ""} onClick={() => setView("chat")} title="Agent chat">
            <ChatIcon />
            <span>Agent chat</span>
            {waiting > 0 && view !== "chat" && <i className="badge">{waiting}</i>}
          </button>
          <button className={view === "records" ? "active" : ""} onClick={() => setView("records")} title="Live records">
            <RecordsIcon />
            <span>Live records</span>
          </button>
        </nav>

        {view === "chat" ? (
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
                  <strong>Approval needed</strong>
                  <p>{approval.summary}</p>
                  <pre>{JSON.stringify(approval.arguments, null, 2)}</pre>
                  <input placeholder="Reviewer note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
                  <div className="actions">
                    <button className="approve" onClick={() => decide(true)} disabled={busy}>Approve</button>
                    <button className="reject" onClick={() => decide(false)} disabled={busy}>Reject</button>
                  </div>
                </div>
              )}

              {error && <div className="error">{error}</div>}

              <form onSubmit={(e) => { e.preventDefault(); send(input); }}>
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={approval ? "Decide on the pending action first" : "Ask the agent…"}
                  disabled={busy || !!approval}
                />
                <button type="submit" disabled={busy || !!approval || !input.trim()}>Send</button>
                <button type="button" className="ghost" onClick={newChat} disabled={busy}>New chat</button>
              </form>
            </section>
            <Insights log={log} audit={audit} domain={domain} />
          </main>
        ) : (
          <main className="records-layout">
            {error && <div className="error">{error}</div>}
            <RecordsView
              domain={domain}
              title={info?.title ?? domain}
              records={records}
              audit={audit}
              onReset={resetData}
              busy={busy}
            />
          </main>
        )}
      </div>
    </div>
  );
}
