export type Slice = { label: string; value: number; color: string };

export const STATUS_COLORS: Record<string, string> = {
  PLACED: "#3d6bf2",
  SHIPPED: "#e8a317",
  DELIVERED: "#1f9d55",
  CANCELLED: "#9aa4b8",
  ACTIVE: "#1f9d55",
  FROZEN: "#7b4fd6",
  BLOCKED: "#d64545",
  POSTED: "#3d6bf2",
  REVERSED: "#e8a317",
};

export const inr = (n: number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(n);

export function countBy<T>(rows: T[], key: (r: T) => string): Slice[] {
  const counts = new Map<string, number>();
  rows.forEach((r) => counts.set(key(r), (counts.get(key(r)) ?? 0) + 1));
  return [...counts.entries()].map(([label, value]) => ({
    label,
    value,
    color: STATUS_COLORS[label] ?? "#5a6680",
  }));
}

export function Donut({ data, size = 140, title, center }: {
  data: Slice[]; size?: number; title?: string; center?: string;
}) {
  const total = data.reduce((s, d) => s + d.value, 0);
  const r = size / 2 - 12;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <div className="donut">
      {title && <h4>{title}</h4>}
      <div className="donut-body">
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={title}>
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#edf0f5" strokeWidth={18} />
          {total > 0 &&
            data.map((d) => {
              const len = (d.value / total) * c;
              const el = (
                <circle
                  key={d.label}
                  cx={size / 2}
                  cy={size / 2}
                  r={r}
                  fill="none"
                  stroke={d.color}
                  strokeWidth={18}
                  strokeDasharray={`${len} ${c - len}`}
                  strokeDashoffset={-offset}
                  transform={`rotate(-90 ${size / 2} ${size / 2})`}
                >
                  <title>{`${d.label}: ${d.value}`}</title>
                </circle>
              );
              offset += len;
              return el;
            })}
          <text x="50%" y="48%" textAnchor="middle" className="donut-total">{center ?? total}</text>
          <text x="50%" y="62%" textAnchor="middle" className="donut-caption">total</text>
        </svg>
        <ul className="legend">
          {data.map((d) => (
            <li key={d.label}>
              <span className="swatch" style={{ background: d.color }} />
              {d.label} <b>{d.value}</b>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export type Bar = { label: string; value: number; color: string; part?: number; partColor?: string; note?: string };

export function Bars({ data, title, format = String, limit, limitLabel }: {
  data: Bar[]; title?: string; format?: (n: number) => string; limit?: number; limitLabel?: string;
}) {
  const max = Math.max(1, limit ?? 0, ...data.map((d) => d.value));
  return (
    <div className="bars">
      {title && <h4>{title}</h4>}
      <div className="bars-body">
        {data.map((d, i) => (
          <div className="bar-row" key={`${d.label}-${i}`} title={d.note}>
            <span className="bar-label">{d.label}</span>
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${(d.value / max) * 100}%`, background: d.color }}>
                {d.part ? (
                  <div
                    className="bar-part"
                    style={{ width: `${(d.part / d.value) * 100}%`, background: d.partColor ?? "#d64545" }}
                  />
                ) : null}
              </div>
              {limit !== undefined && (
                <div className="bar-limit" style={{ left: `${(limit / max) * 100}%` }} />
              )}
            </div>
            <span className="bar-value">{format(d.value)}</span>
          </div>
        ))}
        {limit !== undefined && (
          <p className="bar-limit-note">
            <span className="limit-swatch" /> {limitLabel ?? "limit"}: {format(limit)}
          </p>
        )}
      </div>
    </div>
  );
}

export function Stat({ label, value, tone = "default", hint }: {
  label: string; value: string | number; tone?: "default" | "good" | "warn" | "bad" | "info"; hint?: string;
}) {
  return (
    <div className={`stat ${tone}`} title={hint}>
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}
