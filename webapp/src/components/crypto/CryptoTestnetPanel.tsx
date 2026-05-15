import { useCallback, useEffect, useState } from "react";
import {
  getCryptoTestnetBalances,
  getCryptoTestnetStatus,
  getCryptoTestnetTicker,
  type CryptoTestnetBalancesPayload,
  type CryptoTestnetStatusPayload,
  type CryptoTestnetTickerPayload,
} from "@/services/api";

const HIGHLIGHT_ASSETS = ["USDT", "BTC", "ETH", "BNB"] as const;
const DEMO_SYMBOL = "BTC/USDT";

const numFmt2 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 8, minimumFractionDigits: 2 });

function fmtNum(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return numFmt2.format(v);
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${numFmt2.format(v)}%`;
}

function CryptoRefreshBadge({ active, label = "Actualizando…" }: { active: boolean; label?: string }) {
  if (!active) return null;
  return (
    <span className="radar-badge radar-badge--conv-media crypto-refresh-badge" role="status" aria-live="polite">
      <span className="crypto-inline-spinner" aria-hidden />
      {label}
    </span>
  );
}

export function CryptoTestnetPanel() {
  const [status, setStatus] = useState<CryptoTestnetStatusPayload | null>(null);
  const [balances, setBalances] = useState<CryptoTestnetBalancesPayload | null>(null);
  const [ticker, setTicker] = useState<CryptoTestnetTickerPayload | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [balancesLoading, setBalancesLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = useCallback(async (soft = false) => {
    if (!soft) setStatusLoading(true);
    try {
      const s = await getCryptoTestnetStatus();
      setStatus(s);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error al leer estado testnet");
    } finally {
      if (!soft) setStatusLoading(false);
    }
  }, []);

  const loadBalances = useCallback(async () => {
    setBalancesLoading(true);
    try {
      const [b, t] = await Promise.all([
        getCryptoTestnetBalances(),
        getCryptoTestnetTicker(DEMO_SYMBOL).catch(() => null),
      ]);
      setBalances(b);
      if (t) setTicker(t);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error al leer balances testnet");
    } finally {
      setBalancesLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadStatus(false);
  }, [loadStatus]);

  const connected =
    Boolean(status?.configured && status?.enabled && status?.can_read_balance);
  const showEnvHelp = status && !status.configured;

  return (
    <>
      <div
        className="crypto-testnet-banner"
        role="note"
        style={{
          marginBottom: "1rem",
          padding: "0.75rem 1rem",
          borderRadius: "var(--radius, 8px)",
          border: "1px solid rgba(194, 65, 12, 0.45)",
          background: "rgba(194, 65, 12, 0.08)",
          fontSize: "0.9rem",
        }}
      >
        <strong>Modo Testnet:</strong> dinero ficticio. No opera dinero real.
      </div>

      <div className="card" style={{ marginBottom: "1rem" }}>
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: "0.75rem",
            marginBottom: "0.75rem",
          }}
        >
          <h2 className="dashboard-section-title" style={{ margin: 0, flex: "1 1 auto" }}>
            Testnet Binance
          </h2>
          <button type="button" className="radar-refresh-btn" onClick={() => void loadStatus(false)} disabled={statusLoading}>
            {statusLoading ? "Refrescando…" : "Refrescar estado"}
          </button>
          <button
            type="button"
            className="radar-refresh-btn"
            onClick={() => void loadBalances()}
            disabled={balancesLoading || !status?.enabled || !status?.configured}
          >
            {balancesLoading ? "Cargando…" : "Refrescar balances"}
          </button>
          <CryptoRefreshBadge active={statusLoading} label="Actualizando estado…" />
          <CryptoRefreshBadge active={balancesLoading} label="Actualizando balances…" />
        </div>

        {error ? <p className="msg-error" style={{ marginBottom: "0.75rem" }}>{error}</p> : null}

        {showEnvHelp ? (
          <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.75rem", fontSize: "0.9rem" }}>
            Faltan <code>BINANCE_TESTNET_API_KEY</code> / <code>BINANCE_TESTNET_API_SECRET</code> en{" "}
            <code>.env</code>. Opcional: <code>BINANCE_TESTNET_ENABLED=true</code> para activar lectura.
          </p>
        ) : null}

        {statusLoading && !status ? <p className="msg-muted">Cargando estado testnet…</p> : null}

        {status ? (
          <>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginBottom: "0.85rem" }}>
              <span
                className={`radar-badge ${connected ? "radar-badge--conv-alta" : "radar-badge--conv-baja"}`}
                title="Conexión testnet"
              >
                {connected ? "Conectado" : "Sin conexión"}
              </span>
              <span className={`radar-badge ${status.configured ? "radar-badge--conv-alta" : "radar-badge--conv-baja"}`}>
                Configurado: {status.configured ? "sí" : "no"}
              </span>
              <span className={`radar-badge ${status.enabled ? "radar-badge--conv-alta" : "radar-badge--conv-media"}`}>
                Habilitado: {status.enabled ? "sí" : "no"}
              </span>
              <span className="radar-badge radar-badge--conv-media">Red: testnet</span>
            </div>
            <p className="msg-muted" style={{ margin: 0, fontSize: "0.9rem" }}>
              {status.message}
            </p>
          </>
        ) : null}
      </div>

      {balances ? (
        <div className="card" style={{ marginBottom: "1rem" }}>
          <h3 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.65rem" }}>
            Balances principales
          </h3>
          {!balances.ok ? (
            <p className="msg-error" style={{ fontSize: "0.875rem" }}>
              {balances.error ?? "No se pudieron leer balances"}
            </p>
          ) : (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
                gap: "0.65rem",
                marginBottom: "1rem",
              }}
            >
              {HIGHLIGHT_ASSETS.map((asset) => (
                <div key={asset} className="stat dashboard-stat" style={{ margin: 0 }}>
                  <div className="stat__label">{asset}</div>
                  <div className="stat__value">{fmtNum(balances.highlights?.[asset] ?? 0)}</div>
                </div>
              ))}
            </div>
          )}
          {balances.balances.length > 0 ? (
            <details className="crypto-history-details">
              <summary className="msg-muted" style={{ cursor: "pointer", marginBottom: "0.5rem" }}>
                Todos los activos con saldo ({balances.balances.length})
              </summary>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Activo</th>
                      <th style={{ textAlign: "right" }}>Libre</th>
                      <th style={{ textAlign: "right" }}>En uso</th>
                      <th style={{ textAlign: "right" }}>Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {balances.balances.map((row) => (
                      <tr key={row.asset}>
                        <td>{row.asset}</td>
                        <td style={{ textAlign: "right" }}>{fmtNum(row.free)}</td>
                        <td style={{ textAlign: "right" }}>{fmtNum(row.used)}</td>
                        <td style={{ textAlign: "right" }}>{fmtNum(row.total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          ) : balances.ok ? (
            <p className="msg-muted" style={{ margin: 0 }}>Sin saldos en la cuenta testnet.</p>
          ) : null}
        </div>
      ) : null}

      {ticker ? (
        <div className="card" style={{ marginBottom: "1rem" }}>
          <h3 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
            Ticker {DEMO_SYMBOL} (testnet)
          </h3>
          <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
            <div className="stat__label">Último</div>
            <div className="stat__value">{fmtNum(ticker.last)}</div>
          </div>
          <div className="stat dashboard-stat">
            <div className="stat__label">Variación (24h ref.)</div>
            <div className="stat__value">{fmtPct(ticker.percentage)}</div>
          </div>
        </div>
      ) : null}
    </>
  );
}
