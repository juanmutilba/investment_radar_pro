import type { CSSProperties } from "react";
import type {
  CryptoAnalysisPayload,
  CryptoAnalysisSignalKind,
  CryptoScanRow,
  CryptoTicker,
} from "@/services/api";

/** Par CCXT en Binance; la UI muestra la etiqueta «ARS/USDT». */
export const SYM_ARS_BINANCE = "USDT/ARS";

export const DEFAULT_FAVORITE_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"];

const numFmt2 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const numFmt0 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 });

export function normalizeFavoriteSymbolInput(raw: string): string | null {
  const t = raw.trim().toUpperCase();
  if (!t) return null;
  if (t.includes("/")) return t;
  if (t.endsWith("USDT") && t.length > 4) {
    return `${t.slice(0, -4)}/USDT`;
  }
  return null;
}

function fmtPrice(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return numFmt2.format(v);
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${numFmt2.format(v)}%`;
}

function fmtVol(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return numFmt0.format(v);
}

function pctStyle(v: number | null | undefined): CSSProperties {
  if (v === null || v === undefined || !Number.isFinite(v)) return { color: "var(--text-muted)" };
  if (v > 0) return { color: "rgba(21, 128, 61, 0.96)", fontWeight: 600 };
  if (v < 0) return { color: "rgba(185, 28, 28, 0.96)", fontWeight: 600 };
  return { color: "var(--text-muted)" };
}

function readTickerLast(t: CryptoTicker): number | null {
  const x = t.last;
  return typeof x === "number" && Number.isFinite(x) ? x : null;
}

function readTickerPct(t: CryptoTicker): number | null {
  const x = t.percentage;
  return typeof x === "number" && Number.isFinite(x) ? x : null;
}

function readTickerVol(t: CryptoTicker): number | null {
  const x = t.baseVolume;
  return typeof x === "number" && Number.isFinite(x) ? x : null;
}

function signalBadgeClass(s: CryptoAnalysisSignalKind): string {
  if (s === "compra_potencial") return "radar-badge radar-badge--conv-alta";
  if (s === "cuidado") return "radar-badge radar-badge--conv-baja";
  return "radar-badge radar-badge--conv-media";
}

function signalLabelEs(s: CryptoAnalysisSignalKind): string {
  if (s === "compra_potencial") return "Compra potencial";
  if (s === "cuidado") return "Cuidado";
  return "Neutral";
}

export type PrincipalFavoriteQuote = {
  symbol: string;
  ticker: CryptoTicker | null;
  analysis: CryptoAnalysisPayload | null;
  scanRow: CryptoScanRow | null;
  primary: boolean;
};

export function CryptoPrincipalTickerCard({
  title,
  ticker,
  featured = false,
  footnote,
  lastLabel = "Último",
  showVolume = true,
}: {
  title: string;
  ticker: CryptoTicker | null;
  featured?: boolean;
  footnote?: string;
  lastLabel?: string;
  showVolume?: boolean;
}) {
  const last = ticker ? readTickerLast(ticker) : null;
  const sinDato = !ticker || last === null;

  return (
    <div className={`card${featured ? " crypto-principal-card--featured" : ""}`}>
      <h3 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
        {title}
      </h3>
      {footnote ? (
        <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.5rem", fontSize: "0.78rem" }}>
          {footnote}
        </p>
      ) : null}
      <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
        <div className="stat__label">{lastLabel}</div>
        <div className="stat__value">{sinDato ? "Sin dato" : fmtPrice(last)}</div>
      </div>
      <div className="stat dashboard-stat" style={{ marginBottom: showVolume ? "0.35rem" : 0 }}>
        <div className="stat__label">Variación (24h ref.)</div>
        <div className="stat__value" style={pctStyle(ticker ? readTickerPct(ticker) : null)}>
          {ticker ? fmtPct(readTickerPct(ticker)) : "—"}
        </div>
      </div>
      {showVolume ? (
        <div className="stat dashboard-stat">
          <div className="stat__label">Volumen (base)</div>
          <div className="stat__value">{ticker ? fmtVol(readTickerVol(ticker)) : "—"}</div>
        </div>
      ) : null}
    </div>
  );
}

export function CryptoFavoritesSection({
  quotes,
  watchlistSymbols,
  addDraft,
  addError,
  onAddDraftChange,
  onAdd,
  onRemove,
}: {
  quotes: PrincipalFavoriteQuote[];
  watchlistSymbols: string[];
  addDraft: string;
  addError: string | null;
  onAddDraftChange: (v: string) => void;
  onAdd: () => void;
  onRemove: (symbol: string) => void;
}) {
  const listId = "crypto-favorites-watchlist-options";

  return (
    <div className="card" style={{ marginBottom: "1rem" }}>
      <h2 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
        Favoritos
      </h2>
      <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.75rem", fontSize: "0.9rem" }}>
        Lista editable; se guarda en este navegador. BTC y ETH también aparecen arriba como mercados principales.
      </p>
      <div className="radar-toolbar" style={{ marginBottom: "0.75rem" }}>
        <label className="radar-toolbar__field" style={{ minWidth: "12rem", flex: "1 1 200px" }}>
          <span className="radar-toolbar__label">Símbolo</span>
          <input
            className="radar-toolbar__input"
            list={watchlistSymbols.length > 0 ? listId : undefined}
            value={addDraft}
            onChange={(ev) => onAddDraftChange(ev.target.value)}
            placeholder="BTC/USDT o BTCUSDT"
            onKeyDown={(ev) => {
              if (ev.key === "Enter") {
                ev.preventDefault();
                onAdd();
              }
            }}
          />
          {watchlistSymbols.length > 0 ? (
            <datalist id={listId}>
              {watchlistSymbols.map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>
          ) : null}
        </label>
        <button type="button" className="radar-refresh-btn" onClick={onAdd}>
          Agregar
        </button>
      </div>
      {addError ? (
        <p className="msg-error" style={{ fontSize: "0.875rem", marginTop: 0, marginBottom: "0.65rem" }}>
          {addError}
        </p>
      ) : null}
      <div className="table-wrap">
        <table className="crypto-favorites-table">
          <thead>
            <tr>
              <th>Símbolo</th>
              <th style={{ textAlign: "right" }}>Precio</th>
              <th style={{ textAlign: "right" }}>Variación</th>
              <th>Señal</th>
              <th>Tendencia</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {quotes.length === 0 ? (
              <tr>
                <td colSpan={6} className="msg-muted">
                  Sin favoritos. Agregá al menos un símbolo.
                </td>
              </tr>
            ) : (
              quotes.map((q) => {
                const last = q.ticker ? readTickerLast(q.ticker) : null;
                const pct = q.ticker ? readTickerPct(q.ticker) : null;
                const signal = q.analysis?.analysis.signal ?? q.scanRow?.signal ?? null;
                const trend = q.analysis?.analysis.trend ?? q.scanRow?.trend ?? null;
                return (
                  <tr
                    key={q.symbol}
                    className={q.primary ? "crypto-favorite-row--primary" : undefined}
                    title={q.primary ? "También en mercados principales" : undefined}
                  >
                    <td>
                      <strong>{q.symbol}</strong>
                    </td>
                    <td style={{ textAlign: "right" }}>{last !== null ? fmtPrice(last) : "—"}</td>
                    <td style={{ textAlign: "right" }}>
                      <span style={pctStyle(pct)}>{pct !== null ? fmtPct(pct) : "—"}</span>
                    </td>
                    <td>
                      {signal ? (
                        <span className={signalBadgeClass(signal)}>{signalLabelEs(signal)}</span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>{trend ?? "—"}</td>
                    <td style={{ textAlign: "right" }}>
                      <button
                        type="button"
                        className="radar-refresh-btn"
                        style={{ fontSize: "0.78rem", padding: "0.25rem 0.5rem" }}
                        onClick={() => onRemove(q.symbol)}
                      >
                        Quitar
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
