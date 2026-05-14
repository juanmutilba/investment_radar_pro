import { useCallback, useEffect, useState } from "react";
import type { CSSProperties } from "react";
import {
  getCryptoAnalysis,
  getCryptoOhlcv,
  getCryptoStatus,
  getCryptoTicker,
  type CryptoAnalysisPayload,
  type CryptoAnalysisSignalKind,
  type CryptoOhlcvCandle,
  type CryptoOhlcvResponse,
  type CryptoStatusPayload,
  type CryptoTicker,
} from "@/services/api";

const SYM_BTC = "BTC/USDT";
const SYM_ETH = "ETH/USDT";
const ANALYSIS_TF = "1h";
const ANALYSIS_LIMIT = 200;

const dtFmt = new Intl.DateTimeFormat("es-AR", {
  dateStyle: "short",
  timeStyle: "short",
});

const numFmt2 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const numFmt0 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 });

function fmtPrice(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return numFmt2.format(v);
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const s = `${v >= 0 ? "+" : ""}${numFmt2.format(v)}%`;
  return s;
}

function fmtVol(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return numFmt0.format(v);
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

function pctStyle(pct: number | null): CSSProperties {
  if (pct === null || !Number.isFinite(pct)) return { color: "var(--text-muted)" };
  if (pct > 0) return { color: "rgba(21, 128, 61, 0.96)", fontWeight: 700 };
  if (pct < 0) return { color: "rgba(185, 28, 28, 0.96)", fontWeight: 700 };
  return { color: "var(--text-muted)" };
}

function fmtMacd(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toFixed(6);
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

function CryptoAnalysisCard({ title, payload }: { title: string; payload: CryptoAnalysisPayload | null }) {
  if (!payload) {
    return (
      <div className="card">
        <h3 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
          {title}
        </h3>
        <p className="msg-muted" style={{ margin: 0 }}>
          Sin datos de análisis.
        </p>
      </div>
    );
  }
  const a = payload.analysis;
  return (
    <div className="card">
      <h3 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
        {title}
      </h3>
      <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.65rem", fontSize: "0.82rem" }}>
        {payload.symbol} · {payload.timeframe} · {payload.limit} velas
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.45rem", alignItems: "center", marginBottom: "0.75rem" }}>
        <span className={signalBadgeClass(a.signal)} title="Señal heurística (sin órdenes)">
          {signalLabelEs(a.signal)}
        </span>
        <span className="radar-badge radar-badge--conv-media">Score {a.score}</span>
        <span className="radar-badge radar-badge--conv-media">Tendencia: {a.trend}</span>
        <span className="radar-badge radar-badge--conv-media">Momentum: {a.momentum}</span>
        <span className="radar-badge radar-badge--conv-media">Riesgo: {a.risk}</span>
      </div>
      <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
        <div className="stat__label">Precio (último cierre)</div>
        <div className="stat__value">{fmtPrice(a.price)}</div>
      </div>
      <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
        <div className="stat__label">RSI 14</div>
        <div className="stat__value">{Number.isFinite(a.rsi_14) ? a.rsi_14.toFixed(2) : "—"}</div>
      </div>
      <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
        <div className="stat__label">SMA 20</div>
        <div className="stat__value">{fmtPrice(a.sma_20)}</div>
      </div>
      <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
        <div className="stat__label">SMA 50</div>
        <div className="stat__value">{fmtPrice(a.sma_50)}</div>
      </div>
      <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
        <div className="stat__label">EMA 20</div>
        <div className="stat__value">{fmtPrice(a.ema_20)}</div>
      </div>
      <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
        <div className="stat__label">MACD hist</div>
        <div className="stat__value">{fmtMacd(a.macd_hist)}</div>
      </div>
      <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
        <div className="stat__label">MACD / señal</div>
        <div className="stat__value">
          {fmtMacd(a.macd)} / {fmtMacd(a.macd_signal)}
        </div>
      </div>
    </div>
  );
}

export function CryptoPage() {
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [fatalError, setFatalError] = useState<string | null>(null);
  const [status, setStatus] = useState<CryptoStatusPayload | null>(null);
  const [btc, setBtc] = useState<CryptoTicker | null>(null);
  const [eth, setEth] = useState<CryptoTicker | null>(null);
  const [ohlcv, setOhlcv] = useState<CryptoOhlcvResponse | null>(null);
  const [analysisBtc, setAnalysisBtc] = useState<CryptoAnalysisPayload | null>(null);
  const [analysisEth, setAnalysisEth] = useState<CryptoAnalysisPayload | null>(null);
  const [tickerError, setTickerError] = useState<string | null>(null);

  const load = useCallback(async (isRefresh: boolean) => {
    if (isRefresh) setRefreshing(true);
    else {
      setLoading(true);
      setFatalError(null);
    }
    setTickerError(null);
    try {
      const results = await Promise.allSettled([
        getCryptoStatus(),
        getCryptoTicker(SYM_BTC),
        getCryptoTicker(SYM_ETH),
        getCryptoOhlcv("BTC/USDT", "1h", 100),
        getCryptoAnalysis(SYM_BTC, ANALYSIS_TF, ANALYSIS_LIMIT),
        getCryptoAnalysis(SYM_ETH, ANALYSIS_TF, ANALYSIS_LIMIT),
      ]);

      const st = results[0];
      if (st.status === "rejected") {
        const msg = st.reason instanceof Error ? st.reason.message : "Error en /crypto/status";
        if (!isRefresh) {
          setFatalError(msg);
          setStatus(null);
          setBtc(null);
          setEth(null);
          setOhlcv(null);
          setAnalysisBtc(null);
          setAnalysisEth(null);
        } else {
          setTickerError(msg);
        }
        return;
      }
      setStatus(st.value);
      setFatalError(null);

      const parts: string[] = [];

      const rBtc = results[1];
      if (rBtc.status === "fulfilled") setBtc(rBtc.value);
      else {
        setBtc(null);
        parts.push(`BTC: ${rBtc.reason instanceof Error ? rBtc.reason.message : "error"}`);
      }
      const rEth = results[2];
      if (rEth.status === "fulfilled") setEth(rEth.value);
      else {
        setEth(null);
        parts.push(`ETH: ${rEth.reason instanceof Error ? rEth.reason.message : "error"}`);
      }
      const rOh = results[3];
      if (rOh.status === "fulfilled") setOhlcv(rOh.value);
      else {
        setOhlcv(null);
        parts.push(`OHLCV: ${rOh.reason instanceof Error ? rOh.reason.message : "error"}`);
      }
      const rAb = results[4];
      if (rAb.status === "fulfilled") setAnalysisBtc(rAb.value);
      else {
        setAnalysisBtc(null);
        parts.push(`Análisis BTC: ${rAb.reason instanceof Error ? rAb.reason.message : "error"}`);
      }
      const rAe = results[5];
      if (rAe.status === "fulfilled") setAnalysisEth(rAe.value);
      else {
        setAnalysisEth(null);
        parts.push(`Análisis ETH: ${rAe.reason instanceof Error ? rAe.reason.message : "error"}`);
      }
      setTickerError(parts.length > 0 ? parts.join(" · ") : null);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Error al cargar datos cripto";
      if (isRefresh) {
        setTickerError(msg);
      } else {
        setFatalError(msg);
        setStatus(null);
        setBtc(null);
        setEth(null);
        setOhlcv(null);
        setAnalysisBtc(null);
        setAnalysisEth(null);
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load(false);
  }, [load]);

  const statusHeadline = fatalError !== null ? "Error" : status !== null ? "Conectado" : "—";

  return (
    <>
      <h1 className="page-title">Cripto</h1>
      <p className="page-desc" style={{ maxWidth: "48rem" }}>
        Vista de solo lectura vía Binance (ccxt): estado de credenciales, precios de referencia BTC/ETH, señales
        técnicas heurísticas y velas recientes. Sin trading ni órdenes.
      </p>

      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap", marginBottom: "1rem" }}>
        <button type="button" className="radar-refresh-btn" onClick={() => void load(true)} disabled={loading || refreshing}>
          {refreshing ? "Actualizando…" : "Actualizar"}
        </button>
        {tickerError ? (
          <span className="msg-error" style={{ fontSize: "0.875rem" }}>
            {tickerError}
          </span>
        ) : null}
      </div>

      {loading && <p className="msg-muted">Cargando…</p>}
      {fatalError && !loading && <p className="msg-error">{fatalError}</p>}

      {!loading && fatalError === null && status && (
        <div className="card" style={{ marginBottom: "1rem" }}>
          <h2 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.65rem" }}>
            Estado Binance
          </h2>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center", marginBottom: "0.75rem" }}>
            <span
              className={`radar-badge ${statusHeadline === "Error" ? "radar-badge--conv-baja" : "radar-badge--conv-alta"}`}
              title="Respuesta del backend /crypto/status"
            >
              {statusHeadline}
            </span>
            <span className="radar-badge radar-badge--conv-media" title="CRYPTO_TRADING_ENABLED en .env">
              Trading UI: {status.trading_enabled ? "habilitado" : "deshabilitado"}
            </span>
            <span className="radar-badge radar-badge--conv-media" title="BINANCE_TESTNET en .env">
              Testnet: {status.testnet ? "sí" : "no"}
            </span>
            <span
              className={`radar-badge ${status.can_read_balance ? "radar-badge--conv-alta" : "radar-badge--conv-baja"}`}
              title="Lectura de balance (credenciales)"
            >
              Balance: {status.can_read_balance ? "OK" : "no OK"}
            </span>
          </div>
          <p className="msg-muted" style={{ margin: 0, fontSize: "0.9rem" }}>
            {status.message}
          </p>
        </div>
      )}

      {!loading && fatalError === null && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
            gap: "1rem",
            marginBottom: "1rem",
          }}
        >
          <div className="card">
            <h3 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
              {SYM_BTC}
            </h3>
            <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
              <div className="stat__label">Último</div>
              <div className="stat__value">{fmtPrice(btc ? readTickerLast(btc) : null)}</div>
            </div>
            <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
              <div className="stat__label">Variación (24h ref.)</div>
              <div className="stat__value" style={pctStyle(btc ? readTickerPct(btc) : null)}>
                {fmtPct(btc ? readTickerPct(btc) : null)}
              </div>
            </div>
            <div className="stat dashboard-stat">
              <div className="stat__label">Volumen (base)</div>
              <div className="stat__value">{fmtVol(btc ? readTickerVol(btc) : null)}</div>
            </div>
          </div>
          <div className="card">
            <h3 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
              {SYM_ETH}
            </h3>
            <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
              <div className="stat__label">Último</div>
              <div className="stat__value">{fmtPrice(eth ? readTickerLast(eth) : null)}</div>
            </div>
            <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
              <div className="stat__label">Variación (24h ref.)</div>
              <div className="stat__value" style={pctStyle(eth ? readTickerPct(eth) : null)}>
                {fmtPct(eth ? readTickerPct(eth) : null)}
              </div>
            </div>
            <div className="stat dashboard-stat">
              <div className="stat__label">Volumen (base)</div>
              <div className="stat__value">{fmtVol(eth ? readTickerVol(eth) : null)}</div>
            </div>
          </div>
        </div>
      )}

      {!loading && fatalError === null && (
        <div style={{ marginBottom: "1rem" }}>
          <h2 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.65rem" }}>
            Señales técnicas
          </h2>
          <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.75rem", maxWidth: "48rem", fontSize: "0.9rem" }}>
            Indicadores calculados en backend (SMA, EMA, RSI, MACD) sobre OHLCV; clasificación orientativa, no
            recomendación de inversión.
          </p>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
              gap: "1rem",
            }}
          >
            <CryptoAnalysisCard title="BTC/USDT" payload={analysisBtc} />
            <CryptoAnalysisCard title="ETH/USDT" payload={analysisEth} />
          </div>
        </div>
      )}

      {!loading && fatalError === null && ohlcv && ohlcv.candles.length > 0 && (
        <div className="card">
          <h2 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.65rem" }}>
            Velas {ohlcv.symbol} · {ohlcv.timeframe} · últimas {ohlcv.candles.length}
          </h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th style={{ textAlign: "right" }}>Open</th>
                  <th style={{ textAlign: "right" }}>High</th>
                  <th style={{ textAlign: "right" }}>Low</th>
                  <th style={{ textAlign: "right" }}>Close</th>
                  <th style={{ textAlign: "right" }}>Volume</th>
                </tr>
              </thead>
              <tbody>
                {ohlcv.candles.map((row: CryptoOhlcvCandle, i: number) => {
                  const [ts, open, high, low, close, vol] = row;
                  const d = new Date(ts);
                  return (
                    <tr key={`${ts}-${i}`}>
                      <td className="table-cell--nowrap">{Number.isFinite(d.getTime()) ? dtFmt.format(d) : "—"}</td>
                      <td style={{ textAlign: "right" }}>{fmtPrice(open)}</td>
                      <td style={{ textAlign: "right" }}>{fmtPrice(high)}</td>
                      <td style={{ textAlign: "right" }}>{fmtPrice(low)}</td>
                      <td style={{ textAlign: "right" }}>{fmtPrice(close)}</td>
                      <td style={{ textAlign: "right" }}>{fmtVol(vol)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!loading && fatalError === null && ohlcv && ohlcv.candles.length === 0 && (
        <p className="msg-muted">No hay velas en la respuesta de /crypto/ohlcv.</p>
      )}
    </>
  );
}
