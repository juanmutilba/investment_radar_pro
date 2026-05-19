import type { CryptoStrategyMode } from "@/services/api";

export const CRYPTO_TESTNET_WHITELIST_SYMBOLS = [
  "BTC/USDT",
  "ETH/USDT",
  "SOL/USDT",
  "BNB/USDT",
  "XRP/USDT",
  "DOGE/USDT",
  "ADA/USDT",
  "LINK/USDT",
  "AVAX/USDT",
  "LTC/USDT",
  "ARB/USDT",
  "OP/USDT",
  "SUI/USDT",
  "NEAR/USDT",
  "PEPE/USDT",
  "WIF/USDT",
] as const;

function normalizeMode(mode: string | null | undefined): CryptoStrategyMode {
  const m = (mode || "trend_swing").trim().toLowerCase().replace(/-/g, "_");
  if (m === "daily_intraday" || m === "daily" || m === "intraday") {
    return "daily_intraday";
  }
  return "trend_swing";
}

export function isDailyIntradayMode(mode: string | null | undefined): boolean {
  return normalizeMode(mode) === "daily_intraday";
}

export function messageNoCandidates(mode: string | null | undefined): string {
  return isDailyIntradayMode(mode)
    ? "No hay setups intradía elegibles en la watchlist."
    : "No hay candidatos con señal compra_potencial en la watchlist.";
}

export function messageNoCandidatesCycle(mode: string | null | undefined): string {
  return isDailyIntradayMode(mode)
    ? "No se detectaron setups intradía válidos en este ciclo."
    : "No hay candidatos con señal compra_potencial en la watchlist.";
}

export function primaryReasonLabel(
  code: string | null | undefined,
  strategyMode?: string | null,
): string {
  if (!code) return "—";
  const mode = strategyMode ?? undefined;
  const labels: Record<string, string> = {
    no_opportunity: isDailyIntradayMode(mode)
      ? "Sin setups intradía elegibles"
      : "Sin oportunidades (compra_potencial)",
    watchlist_empty: "Watchlist vacía",
    scanner_empty: "Scanner sin filas",
    scanner_error: "Error de scanner",
    score_below_min: "Score por debajo del mínimo",
    already_open: "Posición ya abierta en el símbolo",
    cooldown_symbol: "Cooldown activo para el símbolo",
    btc_trend_filter: "BTC sin tendencia alcista",
    opened: "Se abrió posición",
    max_one_per_run: "Máximo 1 entrada por ejecución",
    max_open_positions: "Máximo de activos abiertos (cupo testnet)",
    no_entry: "Sin entrada tras evaluar candidatos",
    candidates_present: isDailyIntradayMode(mode)
      ? "Hay candidatos intradía"
      : "Hay candidatos con señal",
    not_whitelisted_testnet: "Fuera de whitelist Testnet",
  };
  return labels[code] ?? code;
}

export function assistedPrimaryReasonLabel(
  code: string | null | undefined,
  strategyMode?: string | null,
): string {
  if (!code) return "Sin propuesta en esta búsqueda.";
  const mode = strategyMode ?? undefined;
  const labels: Record<string, string> = {
    no_opportunity: messageNoCandidates(mode),
    testnet_balances_unavailable:
      "No se pudieron leer balances testnet: revisá credenciales, BINANCE_TESTNET_ENABLED y pulsá Refrescar datos.",
    max_open_positions:
      "Hay candidatos, pero no entra uno nuevo: ya alcanzaste el máximo de activos distintos con posición Testnet registrada por la app (no es monto total en USDT).",
    no_entry: "Ningún candidato pasó todos los filtros de entrada.",
    score_below_min: "Hay candidatos, pero el score quedó por debajo del mínimo configurado.",
    btc_trend_filter: "Hay candidatos, pero el filtro de tendencia BTC los descartó.",
    cooldown_symbol:
      "Hay candidatos en cooldown según el historial local de órdenes testnet guardado por esta app.",
    already_hold_base_testnet:
      "Ya hay una posición Testnet registrada por la app en este activo. El monitor no propone otra entrada en el mismo par hasta cerrarla (evita duplicar compras).",
    not_whitelisted_testnet:
      "El candidato no está en la whitelist Testnet de esta app (pares USDT habilitados).",
  };
  return labels[code] ?? `Motivo: ${code}`;
}

export function scanNoOpportunityHint(strategyMode?: string | null): string {
  return isDailyIntradayMode(strategyMode)
    ? "El escaneo corrió; no se detectaron setups intradía válidos en este ciclo."
    : "El escaneo corrió; no hubo señales compra_potencial en la watchlist.";
}

export function scanDiagnosisNoOpportunityHint(strategyMode?: string | null): string {
  return isDailyIntradayMode(strategyMode)
    ? "El scanner corrió, pero ningún activo tuvo un setup intradía elegible en este timeframe."
    : "El scanner corrió, pero ningún activo tuvo señal compra_potencial en este timeframe.";
}
