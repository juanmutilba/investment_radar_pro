import type { CryptoTestnetBalancesPayload } from "@/services/api";
import type { CryptoTestnetExitEvaluatedRow, CryptoTestnetExitProposal } from "@/services/api";

function fmtNum(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString("es-AR", { maximumFractionDigits: 4 });
}

const numFmt2 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 });

function lookupFreeBalance(balances: CryptoTestnetBalancesPayload | null, asset: string): number | null {
  if (!balances?.ok) return null;
  const row = balances.balances.find((r) => r.asset.toUpperCase() === asset.toUpperCase());
  if (row) return row.free;
  return 0;
}

export const NEAR_EXIT_THRESHOLD_PCT = 1.5;

export type PositionExitBadge = "profit" | "near_sl" | "near_tp" | "trailing";

export function positionExitBadges(
  evalRow: CryptoTestnetExitEvaluatedRow | undefined,
): PositionExitBadge[] {
  if (!evalRow) return [];
  const badges: PositionExitBadge[] = [];
  const pnl = evalRow.current_pnl_pct ?? evalRow.pnl_pct ?? evalRow.unrealized_pnl_pct;
  if (pnl != null && Number.isFinite(pnl) && pnl > 0) badges.push("profit");
  const distSl = evalRow.distance_to_stop_loss_pct;
  if (distSl != null && distSl >= 0 && distSl <= NEAR_EXIT_THRESHOLD_PCT) badges.push("near_sl");
  const distTp = evalRow.distance_to_take_profit_pct;
  if (distTp != null && distTp >= 0 && distTp <= NEAR_EXIT_THRESHOLD_PCT) badges.push("near_tp");
  const trailingLive =
    evalRow.trailing_activated === true ||
    (evalRow.trailing_activated == null &&
      evalRow.trailing_stop_price != null &&
      evalRow.trailing_stop_price > 0);
  if (
    trailingLive &&
    (evalRow.position_status === "holding" || evalRow.reason === "holding")
  ) {
    badges.push("trailing");
  }
  return badges;
}

const POSITION_EXIT_BADGE_LABELS: Record<PositionExitBadge, string> = {
  profit: "En ganancia",
  near_sl: "Cerca de SL",
  near_tp: "Cerca de TP",
  trailing: "Trailing activo",
};

export function positionExitBadgeLabel(badge: PositionExitBadge): string {
  return POSITION_EXIT_BADGE_LABELS[badge];
}

export function exitProposalReasonLabel(reason: string | null | undefined): string {
  if (!reason) return "—";
  const labels: Record<string, string> = {
    stop_loss: "Stop loss",
    take_profit: "Take profit",
    trailing_stop: "Trailing stop",
    break_even_protection: "Protección break-even",
    holding: "Mantener posición",
    no_free_base: "Sin saldo libre para vender.",
    no_price: "Precio USDT no disponible.",
    below_min_value: "Valor por debajo del mínimo USDT.",
    no_symbol: "Par no disponible.",
    no_app_position: "Sin posición app.",
    missing_avg_entry: "Sin entrada promedio en historial local.",
    no_sellable_amount: "Cantidad vendible nula.",
    missing_local_entry:
      "Sin base de compras local clara en el historial de la app.",
    inside_sl_tp_band: "Dentro de SL/TP; sin salida sugerida.",
  };
  return labels[reason] ?? reason;
}

type Props = {
  evaluated: CryptoTestnetExitEvaluatedRow[];
  connected: boolean;
  balances: CryptoTestnetBalancesPayload | null;
  onConfirmSell: (prop: CryptoTestnetExitProposal) => void;
  sellBusyAsset: string | null;
  isExitExecuted: (symbol: string, asset: string) => boolean;
  orderBusy?: boolean;
  compact?: boolean;
};

export function TestnetExitEvaluationsTable({
  evaluated,
  connected,
  balances,
  onConfirmSell,
  sellBusyAsset,
  isExitExecuted,
  orderBusy = false,
  compact = false,
}: Props) {
  if (evaluated.length === 0) {
    return (
      <p className="msg-muted" style={{ margin: "0.75rem 0 0", fontSize: "0.88rem" }}>
        Sin posiciones abiertas registradas por la app para evaluar salidas.
      </p>
    );
  }

  return (
    <div className="table-wrap crypto-testnet-block-start" style={{ marginTop: compact ? 0 : "0.85rem" }}>
      <table className="crypto-testnet-table">
        <thead>
          <tr>
            <th>Par</th>
            <th className="crypto-testnet-num">Entrada</th>
            <th className="crypto-testnet-num">Actual</th>
            <th className="crypto-testnet-num">PnL %</th>
            <th className="crypto-testnet-num">SL</th>
            <th className="crypto-testnet-num">TP</th>
            <th className="crypto-testnet-num">Trail.</th>
            <th>Estado</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {evaluated.map((row, idx) => {
            const asset = (row.asset ?? "").toUpperCase();
            const sym = row.symbol ?? "—";
            const proposed = row.status === "proposed" && row.proposal;
            const pnl = row.current_pnl_pct ?? row.pnl_pct ?? row.unrealized_pnl_pct;
            const distSl = row.distance_to_stop_loss_pct;
            const distTp = row.distance_to_take_profit_pct;
            const freeOk = (lookupFreeBalance(balances, asset) ?? 0) > 1e-10;
            return (
              <tr key={`${sym}-${idx}`}>
                <td>{sym}</td>
                <td className="crypto-testnet-num">{fmtNum(row.avg_entry_price ?? row.avg_entry_usdt)}</td>
                <td className="crypto-testnet-num">{fmtNum(row.current_price ?? row.current_price_usdt)}</td>
                <td className="crypto-testnet-num">
                  {pnl != null && Number.isFinite(pnl) ? `${pnl >= 0 ? "+" : ""}${numFmt2.format(pnl)}%` : "—"}
                </td>
                <td className="crypto-testnet-num" title={distSl != null ? `Distancia SL: ${numFmt2.format(distSl)}%` : undefined}>
                  {fmtNum(row.stop_loss_price)}
                </td>
                <td className="crypto-testnet-num" title={distTp != null ? `Distancia TP: ${numFmt2.format(distTp)}%` : undefined}>
                  {fmtNum(row.take_profit_price)}
                </td>
                <td className="crypto-testnet-num">{fmtNum(row.trailing_stop_price)}</td>
                <td style={{ fontSize: "0.82rem", maxWidth: "12rem" }}>
                  {proposed ? (
                    <span className="crypto-side-badge crypto-side-badge--sell">
                      {exitProposalReasonLabel(row.exit_reason ?? row.reason)}
                    </span>
                  ) : (
                    <span className="msg-muted">
                      {exitProposalReasonLabel(row.position_status ?? row.reason)}
                      {row.message ? (
                        <span style={{ display: "block", marginTop: "0.2rem", fontSize: "0.78rem" }}>
                          {row.message}
                        </span>
                      ) : distSl != null || distTp != null ? (
                        <span style={{ display: "block", marginTop: "0.2rem", fontSize: "0.78rem" }}>
                          {distSl != null ? `Δ SL ${numFmt2.format(distSl)}%` : ""}
                          {distSl != null && distTp != null ? " · " : ""}
                          {distTp != null ? `Δ TP ${numFmt2.format(distTp)}%` : ""}
                        </span>
                      ) : null}
                    </span>
                  )}
                </td>
                <td>
                  {proposed && row.proposal ? (
                    isExitExecuted(row.proposal.symbol, row.proposal.asset) ? (
                      <span className="crypto-side-badge" role="status">
                        Ejecutada
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="radar-refresh-btn crypto-testnet-btn-compact"
                        onClick={() => onConfirmSell(row.proposal!)}
                        disabled={!connected || !freeOk || sellBusyAsset !== null || orderBusy}
                        title={!freeOk ? "Sin saldo libre testnet para vender" : undefined}
                      >
                        {sellBusyAsset === row.proposal.asset ? "Enviando…" : "Confirmar SELL Testnet"}
                      </button>
                    )
                  ) : (
                    <span className="msg-muted" style={{ fontSize: "0.8rem" }}>
                      Mantener
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
