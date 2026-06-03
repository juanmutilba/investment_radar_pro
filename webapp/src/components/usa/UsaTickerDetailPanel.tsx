import type { CSSProperties, ReactNode } from "react";

import type { ColumnDef } from "@/components/radar/radarTableModel";
import { cellForColumn, getRaw, parseNumberLoose, type CellFormatOptions } from "@/components/radar/radarTableCore";
import { renderCellInner, type RenderCellKeys } from "@/components/radar/radarTableCells";
import type { RadarRow } from "@/services/api";

import { UsaTickerEventsPanel } from "@/components/usa/UsaTickerEventsPanel";

function colKeys(columns: ColumnDef[], id: string): string[] {
  const c = columns.find((x) => x.id === id);
  return c?.keys ?? [];
}

function fmtStr(v: unknown): string {
  if (v === undefined || v === null) return "—";
  const s = String(v).trim();
  return s || "—";
}

const ALERT_EXTRA_KEYS = [
  "PrioridadRadar",
  "prioridad_radar",
  "prioridad",
  "TipoAlerta",
  "tipo_alerta",
  "UltimaAlerta",
  "ultima_alerta",
  "Alerta",
  "alerta",
] as const;

export function UsaTickerDetailPanel({
  ticker,
  row,
  columns,
  cellOpts,
  renderKeys,
  onClose,
}: {
  ticker: string;
  row: RadarRow | null;
  columns: ColumnDef[];
  cellOpts: CellFormatOptions;
  renderKeys: RenderCellKeys;
  onClose: () => void;
}) {
  const tickerKeys = colKeys(columns, "ticker");
  const empresaKeys = colKeys(columns, "empresa");
  const sectorKeys = colKeys(columns, "sector");
  const universoRaw =
    row != null ? getRaw(row, ["Universo", "universo", "TipoUniverso", "tipoUniverso"]) : undefined;

  const signalKeys = colKeys(columns, "signal");

  const columnById = Object.fromEntries(columns.map((c) => [c.id, c])) as Record<string, ColumnDef>;

  const renderCol = (id: string): ReactNode => {
    const c = columnById[id];
    if (!c || !row) return "—";
    const { text, missing } = cellForColumn(c, row, cellOpts);
    return renderCellInner(c, row, text, missing, renderKeys);
  };

  const alertExtras: { label: string; value: string }[] = [];
  if (row) {
    for (const k of ALERT_EXTRA_KEYS) {
      if (k in row && row[k] !== undefined && row[k] !== null && String(row[k]).trim() !== "") {
        alertExtras.push({ label: k, value: String(row[k]).trim() });
      }
    }
  }

  const setupVal = row ? getRaw(row, ["Setup", "setup"]) : undefined;
  const capVal = row ? getRaw(row, ["CapitalSugerido_%", "capital_sugerido", "CapitalSugerido"]) : undefined;
  const upsideVal = row ? getRaw(row, ["Upside_%", "upside", "Upside"]) : undefined;

  const cardStyle: CSSProperties = {
    border: "1px solid var(--border)",
    borderRadius: "var(--radius)",
    padding: "0.75rem 0.85rem",
    background: "var(--bg-panel, rgba(15, 23, 42, 0.18))",
    minWidth: 0,
  };

  const dtStyle: CSSProperties = { fontSize: "0.72rem", color: "var(--text-muted)" };
  const ddStyle: CSSProperties = { fontSize: "0.84rem", margin: "0.15rem 0 0.45rem", fontWeight: 500 };

  if (!row) {
    return (
      <div className="usa-ticker-detail-panel" style={{ margin: "1rem 0 0" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem" }}>
          <h2 className="dashboard-section-title" style={{ margin: 0, fontSize: "1rem" }}>
            Detalle · {ticker}
          </h2>
          <button type="button" className="radar-refresh-btn" onClick={onClose}>
            Cerrar
          </button>
        </div>
        <p className="msg-muted" style={{ marginTop: "0.65rem" }}>
          No hay fila para este ticker en el export actual (puede estar filtrado fuera del universo cargado).
        </p>
        <UsaTickerEventsPanel ticker={ticker} variant="embedded" />
      </div>
    );
  }

  return (
    <div className="usa-ticker-detail-panel" style={{ margin: "1rem 0 0" }}>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "0.5rem",
          marginBottom: "0.65rem",
        }}
      >
        <h2 className="dashboard-section-title" style={{ margin: 0, fontSize: "1.05rem" }}>
          Detalle · {fmtStr(getRaw(row, tickerKeys))}
        </h2>
        <button type="button" className="radar-refresh-btn" onClick={onClose}>
          Cerrar detalle
        </button>
      </div>
      <p className="msg-muted" style={{ margin: "0 0 0.75rem", fontSize: "0.78rem", lineHeight: 1.4 }}>
        Vista ficha desde el último radar exportado. La tabla de arriba sigue como screener.
      </p>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 260px), 1fr))",
          gap: "0.65rem",
        }}
      >
        <article style={cardStyle}>
          <h3 style={{ margin: "0 0 0.5rem", fontSize: "0.82rem", fontWeight: 600 }}>Resumen</h3>
          <dl style={{ margin: 0 }}>
            <dt style={dtStyle}>Empresa</dt>
            <dd style={ddStyle}>{fmtStr(getRaw(row, empresaKeys))}</dd>
            <dt style={dtStyle}>Sector</dt>
            <dd style={ddStyle}>{fmtStr(getRaw(row, sectorKeys))}</dd>
            <dt style={dtStyle}>Universo</dt>
            <dd style={ddStyle}>{fmtStr(universoRaw)}</dd>
            <dt style={dtStyle}>Precio</dt>
            <dd style={ddStyle}>{renderCol("precio")}</dd>
            <dt style={dtStyle}>CEDEAR</dt>
            <dd style={ddStyle}>{renderCol("cedear")}</dd>
          </dl>
        </article>

        <article style={cardStyle}>
          <h3 style={{ margin: "0 0 0.5rem", fontSize: "0.82rem", fontWeight: 600 }}>Scores</h3>
          <dl style={{ margin: 0 }}>
            <dt style={dtStyle}>TechScore</dt>
            <dd style={ddStyle}>{renderCol("tech")}</dd>
            <dt style={dtStyle}>FundScore</dt>
            <dd style={ddStyle}>{renderCol("fund")}</dd>
            <dt style={dtStyle}>RiskScore</dt>
            <dd style={ddStyle}>{renderCol("risk")}</dd>
            <dt style={dtStyle}>TotalScore</dt>
            <dd style={ddStyle}>{renderCol("total")}</dd>
          </dl>
        </article>

        <article style={cardStyle}>
          <h3 style={{ margin: "0 0 0.5rem", fontSize: "0.82rem", fontWeight: 600 }}>Señal técnica</h3>
          <dl style={{ margin: 0 }}>
            <dt style={dtStyle}>Tendencia</dt>
            <dd style={ddStyle}>{renderCol("trend")}</dd>
            <dt style={dtStyle}>RSI</dt>
            <dd style={ddStyle}>{renderCol("rsi")}</dd>
            <dt style={dtStyle}>MACD alcista</dt>
            <dd style={ddStyle}>{renderCol("macd")}</dd>
          </dl>
        </article>

        <article style={{ ...cardStyle, gridColumn: "1 / -1" }}>
          <h3 style={{ margin: "0 0 0.35rem", fontSize: "0.82rem", fontWeight: 600 }}>Eventos relevantes</h3>
          <UsaTickerEventsPanel ticker={ticker} variant="embedded" />
        </article>

        <article style={{ ...cardStyle, gridColumn: "1 / -1" }}>
          <h3 style={{ margin: "0 0 0.5rem", fontSize: "0.82rem", fontWeight: 600 }}>Alertas y estado (export)</h3>
          <p className="msg-muted" style={{ margin: "0 0 0.5rem", fontSize: "0.72rem" }}>
            Datos del radar exportado (SignalState, etc.). El módulo <strong>Alertas</strong> usa otra corrida y puede
            diferir.
          </p>
          <dl style={{ margin: 0 }}>
            <dt style={dtStyle}>Estado radar</dt>
            <dd style={ddStyle}>{fmtStr(getRaw(row, signalKeys))}</dd>
            <dt style={dtStyle}>Setup</dt>
            <dd style={ddStyle}>{fmtStr(setupVal)}</dd>
            <dt style={dtStyle}>Convicción</dt>
            <dd style={ddStyle}>{renderCol("conv")}</dd>
            <dt style={dtStyle}>Capital sugerido %</dt>
            <dd style={ddStyle}>{fmtStr(capVal)}</dd>
            <dt style={dtStyle}>Upside %</dt>
            <dd style={ddStyle}>
              {upsideVal !== undefined && upsideVal !== null && String(upsideVal).trim() !== ""
                ? String(parseNumberLoose(upsideVal) ?? String(upsideVal).trim())
                : "—"}
            </dd>
          </dl>
          {alertExtras.length > 0 ? (
            <ul className="msg-muted" style={{ margin: "0.5rem 0 0", paddingLeft: "1.1rem", fontSize: "0.78rem" }}>
              {alertExtras.map((x) => (
                <li key={x.label}>
                  <strong>{x.label}:</strong> {x.value}
                </li>
              ))}
            </ul>
          ) : (
            <p className="msg-muted" style={{ margin: "0.5rem 0 0", fontSize: "0.76rem" }}>
              Sin columnas extra de alertas en esta fila del export.
            </p>
          )}
        </article>
      </div>
    </div>
  );
}
