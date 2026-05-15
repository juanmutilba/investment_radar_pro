import { useMemo, useState } from "react";
import type { CSSProperties } from "react";
import type { CryptoPaperEquityCurve, CryptoPaperEquityCurvePoint } from "@/services/api";

export const PAPER_SIM_INITIAL_CAPITAL_USDT = 10_000;

const curveDateFmt = new Intl.DateTimeFormat("es-AR", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

const numFmt0 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 });
const numFmt2 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2, minimumFractionDigits: 2 });

type SimEquityChartPoint = CryptoPaperEquityCurvePoint & {
  balance_usdt: number;
  isStart?: boolean;
};

function fmtUsdt(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `${numFmt2.format(v)} USDT`;
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${numFmt2.format(v)}%`;
}

function pnlStyle(v: number | null | undefined): CSSProperties {
  if (v === null || v === undefined || !Number.isFinite(v)) return {};
  if (v > 0) return { color: "var(--positive, #15803d)" };
  if (v < 0) return { color: "var(--negative, #b91c1c)" };
  return {};
}

function buildSimEquityChartSeries(curve: CryptoPaperEquityCurve | null): SimEquityChartPoint[] {
  if (!curve?.points.length) return [];
  const start: SimEquityChartPoint = {
    closed_at: null,
    symbol: "",
    pnl_usdt: 0,
    equity_usdt: 0,
    balance_usdt: PAPER_SIM_INITIAL_CAPITAL_USDT,
    drawdown_usdt: 0,
    drawdown_pct: null,
    isStart: true,
  };
  const closed = curve.points.map((p) => ({
    ...p,
    balance_usdt: PAPER_SIM_INITIAL_CAPITAL_USDT + p.equity_usdt,
    isStart: false as const,
  }));
  return [start, ...closed];
}

function fmtCurveAxisDate(iso: string | null): string {
  if (!iso) return "Inicio";
  const d = new Date(iso);
  return Number.isFinite(d.getTime()) ? curveDateFmt.format(d) : iso;
}

function PaperSimEquityCurveSvg({
  series,
  hoverIdx,
  onHover,
}: {
  series: SimEquityChartPoint[];
  hoverIdx: number | null;
  onHover: (idx: number | null) => void;
}) {
  const w = 720;
  const h = 260;
  const padL = 62;
  const padR = 18;
  const padT = 22;
  const padB = 52;
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;
  const balances = series.map((p) => p.balance_usdt);
  let minY = Math.min(...balances);
  let maxY = Math.max(...balances);
  if (minY === maxY) {
    minY -= 50;
    maxY += 50;
  }
  const spanY = maxY - minY || 1;
  const padY = Math.max(spanY * 0.08, 25);
  minY -= padY;
  maxY += padY;
  const n = series.length;
  const xOf = (i: number) => padL + (n <= 1 ? 0 : (i / (n - 1)) * innerW);
  const yOf = (v: number) => padT + innerH - ((v - minY) / (maxY - minY)) * innerH;
  const pts = series.map((p, i) => ({ x: xOf(i), y: yOf(p.balance_usdt), p, i }));
  const poly = pts.map((t) => `${t.x.toFixed(1)},${t.y.toFixed(1)}`).join(" ");
  const yTicks = [minY, (minY + maxY) / 2, maxY];
  const xTickIdx =
    n <= 1 ? [0] : n === 2 ? [0, n - 1] : [0, Math.floor((n - 1) / 2), n - 1];
  const hover = hoverIdx !== null ? pts[hoverIdx] : null;

  return (
    <div className="crypto-paper-equity-chart-wrap">
      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="crypto-paper-equity-chart"
        width="100%"
        height={h}
        role="img"
        aria-label="Curva de capital simulada"
        onMouseLeave={() => onHover(null)}
      >
        <text x={padL} y={16} fontSize="11" className="crypto-paper-equity-chart__title">
          Balance USDT
        </text>
        {yTicks.map((yv, i) => (
          <text
            key={`yl-${i}`}
            x={padL - 6}
            y={yOf(yv) + 3}
            fontSize="9"
            textAnchor="end"
            className="crypto-paper-equity-chart__tick"
          >
            {numFmt0.format(yv)}
          </text>
        ))}
        {xTickIdx.map((xi) => (
          <text
            key={`xl-${xi}`}
            x={xOf(xi)}
            y={h - 12}
            fontSize="9"
            textAnchor="middle"
            className="crypto-paper-equity-chart__tick"
          >
            {fmtCurveAxisDate(series[xi]?.closed_at ?? null)}
          </text>
        ))}
        <line
          x1={padL}
          y1={padT + innerH}
          x2={padL + innerW}
          y2={padT + innerH}
          className="crypto-paper-equity-chart__axis"
        />
        <line x1={padL} y1={padT} x2={padL} y2={padT + innerH} className="crypto-paper-equity-chart__axis" />
        <polyline
          fill="none"
          className="crypto-paper-equity-chart__line"
          strokeLinejoin="round"
          points={poly}
        />
        {hover ? (
          <line
            x1={hover.x}
            y1={padT}
            x2={hover.x}
            y2={padT + innerH}
            className="crypto-paper-equity-chart__cursor"
          />
        ) : null}
        {pts.map((t) => (
          <circle
            key={`pt-${t.i}-${t.p.closed_at ?? "start"}`}
            cx={t.x}
            cy={t.y}
            r={hoverIdx === t.i ? 7 : 5}
            className={`crypto-paper-equity-chart__dot${hoverIdx === t.i ? " crypto-paper-equity-chart__dot--active" : ""}`}
            onMouseEnter={() => onHover(t.i)}
          />
        ))}
        <rect
          x={padL}
          y={padT}
          width={innerW}
          height={innerH}
          fill="transparent"
          onMouseMove={(e) => {
            const rect = (e.currentTarget as SVGRectElement).getBoundingClientRect();
            const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
            const idx = Math.round(ratio * (n - 1));
            onHover(idx);
          }}
        />
      </svg>
      {hover ? (
        <div className="crypto-paper-equity-chart__tooltip" role="status">
          <div>
            <strong>{hover.p.isStart ? "Inicio" : fmtCurveAxisDate(hover.p.closed_at)}</strong>
          </div>
          {!hover.p.isStart ? (
            <>
              <div>Símbolo: {hover.p.symbol || "—"}</div>
              <div>
                PnL trade:{" "}
                <span style={pnlStyle(hover.p.pnl_usdt)}>{fmtUsdt(hover.p.pnl_usdt)}</span>
              </div>
            </>
          ) : null}
          <div>Balance: {fmtUsdt(hover.p.balance_usdt)}</div>
          <div>
            Drawdown: {fmtUsdt(hover.p.drawdown_usdt)}
            {hover.p.drawdown_pct !== null ? ` (${fmtPct(hover.p.drawdown_pct)})` : ""}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function PaperSimEquityCurvePanel({ paperEquityCurve }: { paperEquityCurve: CryptoPaperEquityCurve | null }) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const series = useMemo(() => buildSimEquityChartSeries(paperEquityCurve), [paperEquityCurve]);
  const hasCurve = series.length > 1;
  const summary = paperEquityCurve?.summary;
  const closedPnl = summary?.last_equity_usdt ?? 0;
  const currentBalance = PAPER_SIM_INITIAL_CAPITAL_USDT + closedPnl;
  const maxDd = summary?.max_drawdown_usdt ?? 0;
  const maxDdPct = summary?.max_drawdown_pct;

  return (
    <div className="card" style={{ marginBottom: "1rem" }}>
      <h2 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.65rem" }}>
        Curva de capital simulada
      </h2>
      <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.75rem", fontSize: "0.9rem" }}>
        Evolución del balance simulado (capital inicial {fmtUsdt(PAPER_SIM_INITIAL_CAPITAL_USDT)}) solo con trades
        cerrados.
      </p>
      {!hasCurve ? (
        <p className="msg-muted" style={{ margin: 0, fontSize: "0.875rem" }}>
          Sin curva todavía.
        </p>
      ) : (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
              gap: "0.65rem",
              marginBottom: "0.85rem",
            }}
          >
            <div className="stat dashboard-stat" style={{ margin: 0 }}>
              <div className="stat__label">Capital inicial</div>
              <div className="stat__value">{fmtUsdt(PAPER_SIM_INITIAL_CAPITAL_USDT)}</div>
            </div>
            <div className="stat dashboard-stat" style={{ margin: 0 }}>
              <div className="stat__label">Capital actual simulado</div>
              <div className="stat__value" style={pnlStyle(closedPnl)}>
                {fmtUsdt(currentBalance)}
              </div>
            </div>
            <div className="stat dashboard-stat" style={{ margin: 0 }}>
              <div className="stat__label">PnL cerrado</div>
              <div className="stat__value" style={pnlStyle(closedPnl)}>
                {fmtUsdt(closedPnl)}
              </div>
            </div>
            <div className="stat dashboard-stat" style={{ margin: 0 }}>
              <div className="stat__label">Max drawdown</div>
              <div className="stat__value" style={pnlStyle(maxDd)}>
                {fmtUsdt(maxDd)}
                {maxDdPct !== null && maxDdPct !== undefined ? (
                  <span className="msg-muted" style={{ fontSize: "0.78rem", marginLeft: "0.35rem" }}>
                    ({fmtPct(maxDdPct)})
                  </span>
                ) : null}
              </div>
            </div>
          </div>
          <PaperSimEquityCurveSvg series={series} hoverIdx={hoverIdx} onHover={setHoverIdx} />
        </>
      )}
    </div>
  );
}
