import { Fragment, useCallback, useState } from "react";
import type { CryptoTestnetAppOpenPosition, CryptoTestnetAppPositionsPayload } from "@/services/api";

function fmtNum(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString("es-AR", { maximumFractionDigits: 4 });
}

const numFmt4 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 4 });

function baseAssetFromPair(pair: string): string {
  const [b] = pair.trim().split("/");
  return b ? b.toUpperCase() : "";
}

function sellableBaseAmount(
  position: CryptoTestnetAppOpenPosition,
  freeBase: number | null | undefined,
): number {
  let amt = position.amount_base;
  if (freeBase != null && Number.isFinite(freeBase) && freeBase >= 0) {
    amt = Math.min(amt, freeBase);
  }
  return amt > 1e-12 ? amt : 0;
}

type Props = {
  payload: CryptoTestnetAppPositionsPayload | null;
  error: string | null;
  loading: boolean;
  tab: "open" | "closed";
  onTabChange: (tab: "open" | "closed") => void;
  onRefresh: () => void;
  connected: boolean;
  lookupFreeBase: (asset: string) => number | null;
  onSell: (opts: { symbol: string; asset: string; amountBase: number }) => Promise<{ ok: boolean; error?: string }>;
  sellBusySymbol: string | null;
  feedbackMessage: string | null;
  feedbackError: string | null;
};

export function TestnetAppPositionsCard({
  payload,
  error,
  loading,
  tab,
  onTabChange,
  onRefresh,
  connected,
  lookupFreeBase,
  onSell,
  sellBusySymbol,
  feedbackMessage,
  feedbackError,
}: Props) {
  const [partialSymbol, setPartialSymbol] = useState<string | null>(null);

  const runSell = useCallback(
    async (position: CryptoTestnetAppOpenPosition, amountBase: number, label: string) => {
      const asset = baseAssetFromPair(position.symbol);
      const ok = window.confirm(
        `¿Confirmar venta MARKET testnet (${label})?\n\n` +
          `Par: ${position.symbol}\n` +
          `Cantidad: ${numFmt4.format(amountBase)} ${asset}\n\n` +
          `Solo Binance Spot Testnet. Requiere confirmación manual.`,
      );
      if (!ok) return;
      await onSell({ symbol: position.symbol, asset, amountBase });
      setPartialSymbol(null);
    },
    [onSell],
  );

  const handleSellTotal = useCallback(
    (position: CryptoTestnetAppOpenPosition) => {
      const asset = baseAssetFromPair(position.symbol);
      const free = lookupFreeBase(asset);
      const amt = sellableBaseAmount(position, free);
      if (amt <= 1e-12) {
        window.alert(`Sin cantidad vendible para ${asset} (posición app o saldo libre testnet).`);
        return;
      }
      void runSell(position, amt, "total");
    },
    [lookupFreeBase, runSell],
  );

  const handleSellPartialPct = useCallback(
    (position: CryptoTestnetAppOpenPosition, pct: number) => {
      const asset = baseAssetFromPair(position.symbol);
      const free = lookupFreeBase(asset);
      const maxAmt = sellableBaseAmount(position, free);
      if (maxAmt <= 1e-12) {
        window.alert(`Sin cantidad vendible para ${asset}.`);
        return;
      }
      const amt = (maxAmt * pct) / 100;
      if (amt <= 1e-12) {
        window.alert("La cantidad calculada es demasiado pequeña para vender.");
        return;
      }
      void runSell(position, amt, `${pct}%`);
    },
    [lookupFreeBase, runSell],
  );

  return (
    <section
      id="crypto-testnet-app-positions"
      className="card crypto-testnet-section crypto-testnet-app-positions-card"
    >
      <div className="crypto-testnet-section-head">
        <div>
          <h3 className="dashboard-section-title crypto-testnet-section-title" style={{ margin: 0 }}>
            Posiciones Testnet
          </h3>
          <p className="msg-muted" style={{ margin: "0.35rem 0 0", fontSize: "0.82rem" }}>
            Rentabilidad desde órdenes registradas por esta app (<code>crypto_testnet_orders.json</code>). No usa
            saldos regalados del sandbox de Binance.
          </p>
        </div>
        <div className="crypto-testnet-toolbar">
          <button type="button" className="radar-refresh-btn" onClick={onRefresh} disabled={loading}>
            {loading ? "Refrescando…" : "Refrescar posiciones"}
          </button>
        </div>
      </div>
      {feedbackError ? (
        <p className="msg-error crypto-testnet-block-start" role="alert">
          {feedbackError}
        </p>
      ) : null}
      {feedbackMessage ? (
        <p
          className="crypto-testnet-note crypto-testnet-note--blue crypto-testnet-block-start"
          role="status"
          style={{ marginBottom: 0 }}
        >
          {feedbackMessage}
        </p>
      ) : null}
      {error ? <p className="msg-error crypto-testnet-block-start">{error}</p> : null}
      {payload?.ok ? (
        <>
          <div className="crypto-testnet-mini-grid crypto-testnet-mini-grid--dense crypto-testnet-block-start">
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">PnL realizado</span>
              <span className="crypto-testnet-kpi-value">{fmtNum(payload.realized_pnl_usdt)} USDT</span>
            </div>
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">PnL no realizado</span>
              <span className="crypto-testnet-kpi-value">
                {payload.unrealized_pnl_usdt != null ? `${fmtNum(payload.unrealized_pnl_usdt)} USDT` : "—"}
              </span>
            </div>
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">Abiertas</span>
              <span className="crypto-testnet-kpi-value">{payload.open_positions.length}</span>
            </div>
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">Cerradas</span>
              <span className="crypto-testnet-kpi-value">{payload.closed_positions.length}</span>
            </div>
          </div>
          <div className="crypto-testnet-toolbar crypto-testnet-block-start" style={{ gap: "0.35rem" }}>
            <button
              type="button"
              className={`radar-refresh-btn${tab === "open" ? " radar-refresh-btn--active" : ""}`}
              onClick={() => onTabChange("open")}
            >
              Abiertas ({payload.open_positions.length})
            </button>
            <button
              type="button"
              className={`radar-refresh-btn${tab === "closed" ? " radar-refresh-btn--active" : ""}`}
              onClick={() => onTabChange("closed")}
            >
              Cerradas ({payload.closed_positions.length})
            </button>
          </div>
          {tab === "open" ? (
            payload.open_positions.length === 0 ? (
              <p className="msg-muted crypto-testnet-block-start" style={{ fontSize: "0.85rem" }}>
                Sin posiciones abiertas registradas por la app.
              </p>
            ) : (
              <div className="table-wrap crypto-testnet-block-start">
                <table className="crypto-testnet-table">
                  <thead>
                    <tr>
                      <th>Par</th>
                      <th className="crypto-testnet-num">Cantidad</th>
                      <th className="crypto-testnet-num">Entrada prom.</th>
                      <th className="crypto-testnet-num">Precio actual</th>
                      <th className="crypto-testnet-num">Valor USDT</th>
                      <th className="crypto-testnet-num">PnL USDT</th>
                      <th className="crypto-testnet-num">PnL %</th>
                      <th>Abierta</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {payload.open_positions.map((p) => {
                      const asset = baseAssetFromPair(p.symbol);
                      const free = lookupFreeBase(asset);
                      const maxSell = sellableBaseAmount(p, free);
                      const busy = sellBusySymbol === p.symbol;
                      const partialOpen = partialSymbol === p.symbol;
                      const sellDisabled = !connected || busy || maxSell <= 1e-12;
                      return (
                        <Fragment key={p.symbol}>
                          <tr>
                            <td>{p.symbol}</td>
                            <td className="crypto-testnet-num">{numFmt4.format(p.amount_base)}</td>
                            <td className="crypto-testnet-num">{fmtNum(p.avg_entry_price)}</td>
                            <td className="crypto-testnet-num">{fmtNum(p.current_price ?? null)}</td>
                            <td className="crypto-testnet-num">{fmtNum(p.market_value_usdt ?? null)}</td>
                            <td className="crypto-testnet-num">{fmtNum(p.unrealized_pnl_usdt ?? null)}</td>
                            <td className="crypto-testnet-num">
                              {p.unrealized_pnl_pct != null && Number.isFinite(p.unrealized_pnl_pct)
                                ? `${p.unrealized_pnl_pct >= 0 ? "+" : ""}${p.unrealized_pnl_pct.toFixed(2)}%`
                                : "—"}
                            </td>
                            <td style={{ fontSize: "0.8rem", whiteSpace: "nowrap" }}>
                              {p.opened_at ? new Date(p.opened_at).toLocaleString("es-AR") : "—"}
                            </td>
                            <td>
                              <div
                                style={{
                                  display: "flex",
                                  flexDirection: "column",
                                  gap: "0.3rem",
                                  alignItems: "flex-start",
                                }}
                              >
                                <button
                                  type="button"
                                  className="radar-refresh-btn crypto-testnet-btn-compact"
                                  disabled={sellDisabled}
                                  title={maxSell <= 1e-12 ? "Sin saldo vendible" : undefined}
                                  onClick={() => handleSellTotal(p)}
                                >
                                  {busy ? "Enviando…" : "Vender total"}
                                </button>
                                <button
                                  type="button"
                                  className="radar-refresh-btn crypto-testnet-btn-compact"
                                  disabled={sellDisabled}
                                  onClick={() =>
                                    setPartialSymbol((prev) => (prev === p.symbol ? null : p.symbol))
                                  }
                                >
                                  {partialOpen ? "Ocultar parcial" : "Vender parcial"}
                                </button>
                              </div>
                            </td>
                          </tr>
                          {partialOpen ? (
                            <tr>
                              <td colSpan={9} style={{ paddingTop: 0, paddingBottom: "0.65rem" }}>
                                <div
                                  className="crypto-testnet-toolbar"
                                  style={{ flexWrap: "wrap", gap: "0.35rem", marginTop: "0.25rem" }}
                                >
                                  <span className="msg-muted" style={{ fontSize: "0.8rem", width: "100%" }}>
                                    Vendible ≈ {numFmt4.format(maxSell)} {asset}
                                    {free != null ? ` · libre testnet: ${numFmt4.format(free)}` : ""}
                                  </span>
                                  {[25, 50, 100].map((pct) => (
                                    <button
                                      key={pct}
                                      type="button"
                                      className="radar-refresh-btn crypto-testnet-btn-compact"
                                      disabled={sellDisabled}
                                      onClick={() => handleSellPartialPct(p, pct)}
                                    >
                                      {pct}%
                                    </button>
                                  ))}
                                </div>
                              </td>
                            </tr>
                          ) : null}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )
          ) : payload.closed_positions.length === 0 ? (
            <p className="msg-muted crypto-testnet-block-start" style={{ fontSize: "0.85rem" }}>
              Sin posiciones cerradas en el historial local.
            </p>
          ) : (
            <div className="table-wrap crypto-testnet-block-start">
              <table className="crypto-testnet-table">
                <thead>
                  <tr>
                    <th>Par</th>
                    <th className="crypto-testnet-num">Cantidad</th>
                    <th className="crypto-testnet-num">Entrada</th>
                    <th className="crypto-testnet-num">Salida</th>
                    <th className="crypto-testnet-num">PnL USDT</th>
                    <th className="crypto-testnet-num">PnL %</th>
                    <th>Cerrada</th>
                  </tr>
                </thead>
                <tbody>
                  {payload.closed_positions.map((p, idx) => (
                    <tr key={`${p.symbol}-${p.closed_at ?? idx}`}>
                      <td>{p.symbol}</td>
                      <td className="crypto-testnet-num">{numFmt4.format(p.amount_base)}</td>
                      <td className="crypto-testnet-num">{fmtNum(p.entry_price)}</td>
                      <td className="crypto-testnet-num">{fmtNum(p.exit_price)}</td>
                      <td className="crypto-testnet-num">{fmtNum(p.pnl_usdt)}</td>
                      <td className="crypto-testnet-num">
                        {p.pnl_pct != null && Number.isFinite(p.pnl_pct)
                          ? `${p.pnl_pct >= 0 ? "+" : ""}${p.pnl_pct.toFixed(2)}%`
                          : "—"}
                      </td>
                      <td style={{ fontSize: "0.8rem", whiteSpace: "nowrap" }}>
                        {p.closed_at ? new Date(p.closed_at).toLocaleString("es-AR") : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}
