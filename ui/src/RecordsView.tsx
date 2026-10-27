import { useEffect, useRef, useState } from "react";
import { Bars, countBy, Donut, inr, Stat, STATUS_COLORS } from "./charts";
import type { AuditEntry, Row } from "./types";

type Records = Record<string, Row[]>;
const num = (v: unknown) => Number(v ?? 0);
const REFUND_LIMIT = 10_000;
const REVERSAL_LIMIT = 5_000;

function byCustomer(orders: Row[]): Map<string, number> {
  const totals = new Map<string, number>();
  orders.forEach((o) => totals.set(String(o.customer), (totals.get(String(o.customer)) ?? 0) + num(o.total)));
  return totals;
}

function EcommerceCharts({ records }: { records: Records }) {
  const orders = records.orders ?? [];
  const refunds = records.refunds ?? [];
  const revenue = orders.reduce((s, o) => s + num(o.total), 0);
  const refunded = orders.reduce((s, o) => s + num(o.refunded), 0);
  return (
    <>
      <div className="stats">
        <Stat label="Orders" value={orders.length} />
        <Stat label="Order value" value={inr(revenue)} tone="info" />
        <Stat label="Refunded" value={inr(refunded)} tone="warn" />
        <Stat label="Refund rate" value={`${revenue ? ((refunded / revenue) * 100).toFixed(1) : 0}%`}
              tone={refunded / Math.max(revenue, 1) > 0.1 ? "bad" : "good"} />
      </div>
      <div className="chart-grid">
        <div className="card"><Donut title="Orders by status" data={countBy(orders, (o) => String(o.status))} /></div>
        <div className="card">
          <Bars
            title="Order value by customer"
            format={inr}
            data={[...byCustomer(orders).entries()].map(([customer, total]) => ({
              label: customer,
              value: total,
              color: "#3d6bf2",
            }))}
          />
        </div>
        <div className="card">
          {refunds.length ? (
            <Bars
              title="Refunds issued"
              format={inr}
              data={refunds.map((r) => ({
                label: `${r.order} · ${r.reason}`,
                value: num(r.amount),
                color: "#d64545",
                note: String(r.reason),
              }))}
            />
          ) : (
            <><h4>Refunds issued</h4><p className="hint">No refunds yet.</p></>
          )}
        </div>
        <div className="card wide">
          <Bars
            title="Order value and refunded share"
            format={inr}
            limit={REFUND_LIMIT}
            limitLabel="Agent refund limit"
            data={orders.map((o) => ({
              label: String(o.order),
              value: num(o.total),
              part: num(o.refunded),
              color: STATUS_COLORS[String(o.status)] ?? "#5a6680",
              partColor: "#d64545",
              note: `${o.status} · refunded ${inr(num(o.refunded))}`,
            }))}
          />
          <p className="chart-note"><span className="swatch" style={{ background: "#d64545" }} /> refunded part of the order</p>
        </div>
      </div>
    </>
  );
}

function BankingCharts({ records }: { records: Records }) {
  const accounts = records.accounts ?? [];
  const cards = records.cards ?? [];
  const txns = records.transactions ?? [];
  const balance = accounts.reduce((s, a) => s + num(a.balance), 0);
  return (
    <>
      <div className="stats">
        <Stat label="Total balance" value={inr(balance)} tone="info" />
        <Stat label="Frozen accounts" value={accounts.filter((a) => a.status === "FROZEN").length} tone="warn" />
        <Stat label="Blocked cards" value={cards.filter((c) => c.status === "BLOCKED").length} tone="bad" />
        <Stat label="Reversed txns" value={txns.filter((t) => t.status === "REVERSED").length} tone="good" />
      </div>
      <div className="chart-grid">
        <div className="card">
          <Bars
            title="Balance by account"
            format={inr}
            data={accounts.map((a) => ({
              label: String(a.account),
              value: num(a.balance),
              color: STATUS_COLORS[String(a.status)] ?? "#5a6680",
              note: `${a.customer} · ${a.status}`,
            }))}
          />
        </div>
        <div className="card"><Donut title="Cards by status" data={countBy(cards, (c) => String(c.status))} /></div>
        <div className="card"><Donut title="Transactions by status" data={countBy(txns, (t) => String(t.status))} /></div>
        <div className="card wide">
          <Bars
            title="Transactions vs reversal limit"
            format={inr}
            limit={REVERSAL_LIMIT}
            limitLabel="Agent reversal limit"
            data={txns.map((t) => ({
              label: `${t.txn} ${t.merchant}`,
              value: num(t.amount),
              color: STATUS_COLORS[String(t.status)] ?? "#5a6680",
              note: `${t.account} · ${t.status}`,
            }))}
          />
        </div>
      </div>
    </>
  );
}

function rowKey(r: Row): string {
  return String(Object.values(r)[0]);
}

function Table({ name, rows, changed }: { name: string; rows: Row[]; changed: Set<string> }) {
  if (!rows.length) return null;
  const cols = Object.keys(rows[0]);
  return (
    <div className="card table">
      <h4>{name}</h4>
      <table>
        <thead>
          <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={changed.has(`${name}:${rowKey(r)}`) ? "changed" : ""}>
              {cols.map((c) => (
                <td key={c}>
                  {c === "status" ? (
                    <span className="pill" style={{ background: STATUS_COLORS[String(r[c])] ?? "#5a6680" }}>
                      {String(r[c])}
                    </span>
                  ) : typeof r[c] === "number" && ["total", "refunded", "amount", "balance"].includes(c) ? (
                    inr(Number(r[c]))
                  ) : (
                    String(r[c] ?? "")
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function RecordsView({ domain, title, records, audit, onReset, busy }: {
  domain: string; title: string; records: Records; audit: AuditEntry[]; onReset?: () => void; busy: boolean;
}) {
  const previous = useRef<{ domain: string; rows: Map<string, string> } | null>(null);
  const [changed, setChanged] = useState<Set<string>>(new Set());

  useEffect(() => {
    const rows = new Map<string, string>();
    Object.entries(records).forEach(([name, list]) =>
      list.forEach((r) => rows.set(`${name}:${rowKey(r)}`, JSON.stringify(r))),
    );
    const prev = previous.current;
    if (prev && prev.domain === domain) {
      const diff = new Set([...rows].filter(([k, v]) => prev.rows.get(k) !== v).map(([k]) => k));
      if (diff.size) setChanged(diff);
    } else {
      setChanged(new Set());
    }
    previous.current = { domain, rows };
  }, [records, domain]);

  const domainAudit = audit.filter((a) => a.domain === domain);

  return (
    <section className="records-view">
      <div className="view-head">
        <div>
          <h2>Live records</h2>
          <p className="hint">{title}. Rows the agent just changed are highlighted.</p>
        </div>
        {onReset && <button className="ghost" onClick={onReset} disabled={busy}>Reset demo data</button>}
      </div>

      {domain === "banking" ? <BankingCharts records={records} /> : <EcommerceCharts records={records} />}

      <div className="tables">
        {Object.entries(records).map(([name, rows]) => (
          <Table key={name} name={name} rows={rows} changed={changed} />
        ))}
      </div>

      <div className="card">
        <h4>Audit log</h4>
        {domainAudit.length === 0 && <p className="hint">No actions yet in this domain.</p>}
        <ul className="audit">
          {domainAudit.slice(0, 20).map((a, i) => (
            <li key={i} className={a.event}>
              <span>{a.ts.slice(11, 19)}</span> <b>{a.event.replace("_", " ")}</b> {a.tool}
              {a.decision ? ` · ${a.decision}` : ""}
              {a.summary ? <em> — {a.summary}</em> : null}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
