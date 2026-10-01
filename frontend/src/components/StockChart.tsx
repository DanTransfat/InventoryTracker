import type { HistoryPoint } from "../lib/api";
import { formatDateTime } from "../lib/format";

/** Step chart of stock over time, derived entirely from the ledger's balance_after values. */
export function StockChart({ points, threshold }: { points: HistoryPoint[]; threshold: number }) {
  if (points.length < 2) {
    return <p className="muted small">The chart appears once the item has at least two stock movements.</p>;
  }
  const W = 640, H = 180, PAD_L = 40, PAD_R = 12, PAD_T = 12, PAD_B = 24;
  // Movements are spaced evenly (one step per ledger row) rather than by clock time, so a
  // burst of activity in one afternoon stays readable next to a quiet month.
  const times = points.map((_, i) => i);
  const t0 = 0;
  const t1 = Math.max(points.length - 1, 1);
  const maxY = Math.max(threshold, ...points.map((p) => p.stock), 1) * 1.1;
  const x = (t: number) => PAD_L + ((t - t0) / (t1 - t0)) * (W - PAD_L - PAD_R);
  const y = (v: number) => PAD_T + (1 - v / maxY) * (H - PAD_T - PAD_B);

  let d = `M ${x(times[0])} ${y(points[0].stock)}`;
  for (let i = 1; i < points.length; i++) {
    d += ` H ${x(times[i])} V ${y(points[i].stock)}`;
  }
  const ticks = [0, Math.round(maxY / 2), Math.round(maxY / 1.1)];

  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Stock level over time, ${points.length} movements`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD_L} x2={W - PAD_R} y1={y(t)} y2={y(t)} className="chart-grid" />
            <text x={PAD_L - 6} y={y(t) + 4} className="chart-label" textAnchor="end">{t}</text>
          </g>
        ))}
        {threshold > 0 && (
          <g>
            <line x1={PAD_L} x2={W - PAD_R} y1={y(threshold)} y2={y(threshold)} className="chart-threshold" />
            <text x={W - PAD_R} y={y(threshold) - 4} className="chart-label chart-threshold-label" textAnchor="end">
              threshold {threshold}
            </text>
          </g>
        )}
        <path d={d} className="chart-line" />
        {points.map((p, i) => (
          <circle key={i} cx={x(times[i])} cy={y(p.stock)} r={2.5} className="chart-dot">
            <title>{`${formatDateTime(p.at)}: ${p.change > 0 ? "+" : ""}${p.change} (${p.type}) → ${p.stock}`}</title>
          </circle>
        ))}
        <text x={PAD_L} y={H - 6} className="chart-label">{formatDateTime(points[0].at)}</text>
        <text x={W - PAD_R} y={H - 6} className="chart-label" textAnchor="end">{formatDateTime(points[points.length - 1].at)}</text>
      </svg>
    </figure>
  );
}
