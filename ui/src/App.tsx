import { useCallback, useEffect, useState } from "react";

type Tool = { name: string; risky: boolean; description: string };
type DomainInfo = { name: string; title: string; description: string; sample_prompts: string[]; tools: Tool[] };
type Approval = { tool_name: string; arguments: Record<string, unknown>; summary: string };
type AgentEvent =
  | { type: "tool_call"; tool: string; arguments: Record<string, unknown>; risky: boolean }
  | { type: "tool_result"; tool: string; result: unknown; rejected: boolean; blocked?: boolean }
  | ({ type: "approval_required" } & Approval);
type AgentResponse = {
  thread_id: string;
  status: "awaiting_approval" | "completed";
  events: AgentEvent[];
  reply: string;
  approval: Approval | null;
};
type Row = Record<string, string | number | null>;
type AuditEntry = { ts: string; event: string; domain?: string; tool?: string; decision?: string; summary?: string };
type Message =
  | { kind: "user"; text: string }
  | { kind: "agent"; text: string }
  | { kind: "event"; event: AgentEvent };

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
        → {event.tool}({short(event.arguments)})
      </div>
    );
  }
  if (event.type === "tool_result") {
    return (
      <div className={`event ${event.rejected ? "rejected" : event.blocked ? "blocked" : ""}`}>
        {event.blocked ? "⛔" : "←"} {event.tool}: {short(event.result)}
      </div>
    );
  }
  return <div className="event risky">⏸ paused for approval: {event.tool_name}</div>;
}

function Table({ name, rows }: { name: string; rows: Row[] }) {
  if (!rows.length) return null;
  const cols = Object.keys(rows[0]);
  return (
    <div className="table">
      <h4>{name}</h4>
      <table>
        <thead>
          <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>{cols.map((c) => <td key={c}>{String(r[c] ?? "")}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function App() {
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

  const refresh = useCallback(async () => {
    const [recs, aud] = await Promise.all([
      api<Record<string, Row[]>>(`/domains/${domain}/records`),
      api<AuditEntry[]>("/audit?limit=12"),
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
    await api("/reset", {});
    newChat();
    await refresh();
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
        <span className="model">{model}</span>
      </header>

      <main>
        <section className="chat">
          <p className="hint">
            {info?.description} Risky tools:{" "}
            {info?.tools.filter((t) => t.risky).map((t) => <code key={t.name}>{t.name}</code>)}
          </p>
          <div className="log">
            {log.length === 0 && (
              <div className="samples">
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

        <aside>
          <div className="panel-head">
            <h3>Live records</h3>
            <button className="ghost" onClick={resetData} disabled={busy}>Reset demo data</button>
          </div>
          {Object.entries(records).map(([name, rows]) => <Table key={name} name={name} rows={rows} />)}
          <h3>Audit log</h3>
          <ul className="audit">
            {audit.map((a, i) => (
              <li key={i} className={a.event}>
                <span>{a.ts.slice(11, 19)}</span> <b>{a.event}</b> {a.domain} {a.tool}
                {a.decision ? ` · ${a.decision}` : ""}
              </li>
            ))}
          </ul>
        </aside>
      </main>
    </div>
  );
}
