import { useState } from "react";
import type { DomainInfo, PendingApproval } from "./types";

function age(ts: string | null): string {
  if (!ts) return "";
  const seconds = Math.max(0, Math.round((Date.now() - new Date(ts).getTime()) / 1000));
  return seconds < 60 ? `${seconds}s ago` : `${Math.round(seconds / 60)} min ago`;
}

export default function ApprovalsView({ items, domains, busy, onDecide }: {
  items: PendingApproval[];
  domains: DomainInfo[];
  busy: boolean;
  onDecide: (item: PendingApproval, approved: boolean, note: string) => void;
}) {
  const [notes, setNotes] = useState<Record<string, string>>({});
  const title = (name: string) => domains.find((d) => d.name === name)?.title ?? name;

  return (
    <section className="approvals-view">
      <h2>Approval queue</h2>
      <p className="hint">
        Risky actions requested by operators wait here. You can't decide on your own requests (separation of duties),
        and every decision is written to the audit log under your name.
      </p>
      {items.length === 0 && <div className="card hint">Nothing is waiting for approval.</div>}
      {items.map((item) => (
        <div key={item.thread_id} className="approval queue-item">
          <div className="queue-meta">
            <span className="chip">{title(item.domain)}</span>
            <span>requested by <b>{item.requested_by ?? "unknown"}</b> {age(item.requested_at)}</span>
          </div>
          <strong>{item.tool_name}</strong>
          <p>{item.summary}</p>
          <pre>{JSON.stringify(item.arguments, null, 2)}</pre>
          {item.can_decide ? (
            <>
              <input
                placeholder="Reviewer note (optional)"
                value={notes[item.thread_id] ?? ""}
                onChange={(e) => setNotes((n) => ({ ...n, [item.thread_id]: e.target.value }))}
              />
              <div className="actions">
                <button className="approve" disabled={busy}
                        onClick={() => onDecide(item, true, notes[item.thread_id] ?? "")}>Approve</button>
                <button className="reject" disabled={busy}
                        onClick={() => onDecide(item, false, notes[item.thread_id] ?? "")}>Reject</button>
              </div>
            </>
          ) : (
            <p className="hint">You requested this action, so another reviewer has to decide.</p>
          )}
        </div>
      ))}
    </section>
  );
}
