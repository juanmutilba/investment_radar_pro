import type { CryptoStrategyMode, CryptoTestnetAutoStartBody } from "@/services/api";
import { loadCryptoMacroRegimeFilterPref } from "@/components/crypto/cryptoMacroRegimeFilterPref";

/** Debe coincidir con TESTNET_EXIT_RULE_VERSION del backend. */
export const CRYPTO_TESTNET_AUTO_PARAMS_VERSION = "testnet_tp1_sl08_trail05_activation1";
export const CRYPTO_TESTNET_AUTO_PARAMS_VERSION_KEY = "crypto_testnet_auto_params_version";
export const CRYPTO_TESTNET_AUTO_PARAMS_STORAGE_KEY = "crypto_testnet_auto_params_v1";

export type CryptoTestnetAutoFormFields = {
  strategyMode: CryptoStrategyMode;
  cycleMinutes: string;
  quote: string;
  maxOpen: string;
  cooldown: string;
  btcTrend: boolean;
  minScore: string;
  sl: string;
  tp: string;
  trail: string;
  trailActivation: string;
  beTrig: string;
  bePlus: string;
  exitMin: string;
  maxTrades: string;
  maxLoss: string;
  maxExposure: string;
  tf: string;
  maxQuote: string;
  limit: string;
};

/** Defaults oficiales Auto Testnet (backtest BTC / salidas testnet). */
export function getCryptoTestnetAutoDefaultParams(): CryptoTestnetAutoStartBody {
  return {
    strategy_mode: "daily_intraday",
    timeframe: "30m",
    limit: 200,
    min_entry_score: 70,
    require_btc_trend_up: false,
    cooldown_minutes: 60,
    max_open_positions: 3,
    quote_amount_usdt: 15,
    cycle_interval_minutes: 5,
    stop_loss_pct: 0.8,
    take_profit_pct: 1.0,
    trailing_stop_pct: 0.5,
    trailing_activation_pct: 1.0,
    break_even_trigger_pct: 0,
    break_even_plus_pct: 0,
    min_exit_value_usdt: 5,
    max_trades_per_day: 10,
    max_daily_loss_usdt: 10,
    max_total_exposure_usdt: 100,
    max_quote_per_order_usdt: 100,
    macro_regime_filter: false,
  };
}

function numField(v: unknown, fallback: number): number {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function boolField(v: unknown, fallback: boolean): boolean {
  return typeof v === "boolean" ? v : fallback;
}

function strField(v: unknown, fallback: string): string {
  return typeof v === "string" && v.trim() ? v.trim() : fallback;
}

/** Normaliza snapshot backend / localStorage hacia el body del API. */
export function normalizeCryptoTestnetAutoParams(raw: Record<string, unknown>): CryptoTestnetAutoStartBody {
  const d = getCryptoTestnetAutoDefaultParams();
  const maxTrades =
    raw.max_trades_per_day ?? raw.max_entries_per_day ?? d.max_trades_per_day;
  const exposure =
    raw.max_total_exposure_usdt ?? raw.max_exposure_usdt ?? raw.max_exposure_usd ?? d.max_total_exposure_usdt;
  const maxQuote =
    raw.max_quote_per_order_usdt ??
    raw.order_cap_usdt ??
    raw.max_order_usdt ??
    d.max_quote_per_order_usdt;
  const bePlus =
    raw.break_even_plus_pct ?? raw.break_even_stop_pct ?? raw.break_even_offset_pct ?? d.break_even_plus_pct;

  const modeRaw = strField(raw.strategy_mode, d.strategy_mode ?? "daily_intraday");
  const strategy_mode: CryptoStrategyMode =
    modeRaw === "daily_intraday" ? "daily_intraday" : "trend_swing";

  return {
    strategy_mode,
    timeframe: strField(raw.timeframe, d.timeframe ?? "30m"),
    limit: Math.round(numField(raw.limit, d.limit ?? 200)),
    min_entry_score: numField(raw.min_entry_score, d.min_entry_score ?? 70),
    require_btc_trend_up: boolField(raw.require_btc_trend_up, d.require_btc_trend_up ?? false),
    cooldown_minutes: Math.round(numField(raw.cooldown_minutes, d.cooldown_minutes ?? 60)),
    max_open_positions: Math.round(numField(raw.max_open_positions, d.max_open_positions ?? 3)),
    quote_amount_usdt: numField(raw.quote_amount_usdt, d.quote_amount_usdt ?? 15),
    cycle_interval_minutes: numField(raw.cycle_interval_minutes, d.cycle_interval_minutes ?? 5),
    stop_loss_pct: numField(raw.stop_loss_pct, d.stop_loss_pct ?? 0.8),
    take_profit_pct: numField(raw.take_profit_pct, d.take_profit_pct ?? 1.0),
    trailing_stop_pct: numField(raw.trailing_stop_pct, d.trailing_stop_pct ?? 0.5),
    trailing_activation_pct: numField(raw.trailing_activation_pct, d.trailing_activation_pct ?? 1.0),
    break_even_trigger_pct: numField(raw.break_even_trigger_pct, d.break_even_trigger_pct ?? 0),
    break_even_plus_pct: numField(bePlus, d.break_even_plus_pct ?? 0),
    min_exit_value_usdt: numField(raw.min_exit_value_usdt, d.min_exit_value_usdt ?? 5),
    max_trades_per_day: Math.round(numField(maxTrades, d.max_trades_per_day ?? 10)),
    max_daily_loss_usdt: numField(raw.max_daily_loss_usdt, d.max_daily_loss_usdt ?? 10),
    max_total_exposure_usdt: numField(exposure, d.max_total_exposure_usdt ?? 100),
    max_quote_per_order_usdt: numField(maxQuote, d.max_quote_per_order_usdt ?? 100),
    macro_regime_filter: loadCryptoMacroRegimeFilterPref(),
  };
}

export function cryptoTestnetAutoFormFieldsFromParams(
  p: CryptoTestnetAutoStartBody,
): CryptoTestnetAutoFormFields {
  return {
    strategyMode: p.strategy_mode === "daily_intraday" ? "daily_intraday" : "trend_swing",
    cycleMinutes: String(p.cycle_interval_minutes ?? 5),
    quote: String(p.quote_amount_usdt ?? 15),
    maxOpen: String(p.max_open_positions ?? 3),
    cooldown: String(p.cooldown_minutes ?? 60),
    btcTrend: Boolean(p.require_btc_trend_up),
    minScore: String(p.min_entry_score ?? 70),
    sl: String(p.stop_loss_pct ?? 0.8),
    tp: String(p.take_profit_pct ?? 1.0),
    trail: String(p.trailing_stop_pct ?? 0.5),
    trailActivation: String(p.trailing_activation_pct ?? 1.0),
    beTrig: String(p.break_even_trigger_pct ?? 0),
    bePlus: String(p.break_even_plus_pct ?? 0),
    exitMin: String(p.min_exit_value_usdt ?? 5),
    maxTrades: String(p.max_trades_per_day ?? 10),
    maxLoss: String(p.max_daily_loss_usdt ?? 10),
    maxExposure: String(p.max_total_exposure_usdt ?? 100),
    tf: p.timeframe ?? "30m",
    maxQuote: String(p.max_quote_per_order_usdt ?? 100),
    limit: String(p.limit ?? 200),
  };
}

export function createInitialCryptoTestnetAutoFormFields(): CryptoTestnetAutoFormFields {
  return cryptoTestnetAutoFormFieldsFromParams(resolveCryptoTestnetAutoParams());
}

export function persistCryptoTestnetAutoParams(params: CryptoTestnetAutoStartBody): void {
  if (typeof localStorage === "undefined") return;
  try {
    const normalized = normalizeCryptoTestnetAutoParams(params as Record<string, unknown>);
    localStorage.setItem(CRYPTO_TESTNET_AUTO_PARAMS_VERSION_KEY, CRYPTO_TESTNET_AUTO_PARAMS_VERSION);
    localStorage.setItem(CRYPTO_TESTNET_AUTO_PARAMS_STORAGE_KEY, JSON.stringify(normalized));
  } catch {
    /* localStorage opcional */
  }
}

export function resetCryptoTestnetAutoParamsStorage(): CryptoTestnetAutoStartBody {
  const defaults = getCryptoTestnetAutoDefaultParams();
  persistCryptoTestnetAutoParams(defaults);
  return defaults;
}

export function resolveCryptoTestnetAutoParams(): CryptoTestnetAutoStartBody {
  if (typeof localStorage === "undefined") {
    return getCryptoTestnetAutoDefaultParams();
  }
  try {
    const version = localStorage.getItem(CRYPTO_TESTNET_AUTO_PARAMS_VERSION_KEY);
    if (version !== CRYPTO_TESTNET_AUTO_PARAMS_VERSION) {
      return resetCryptoTestnetAutoParamsStorage();
    }
    const raw = localStorage.getItem(CRYPTO_TESTNET_AUTO_PARAMS_STORAGE_KEY);
    if (!raw) {
      return resetCryptoTestnetAutoParamsStorage();
    }
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (!parsed || typeof parsed !== "object") {
      return resetCryptoTestnetAutoParamsStorage();
    }
    const merged = normalizeCryptoTestnetAutoParams(parsed);
    persistCryptoTestnetAutoParams(merged);
    return merged;
  } catch {
    return resetCryptoTestnetAutoParamsStorage();
  }
}

/** Fallback numérico al construir payload o chips (evita 1.2 / 2.2 / 65 dispersos). */
export function cryptoTestnetAutoNumericFallback<K extends keyof CryptoTestnetAutoStartBody>(
  key: K,
): CryptoTestnetAutoStartBody[K] {
  return getCryptoTestnetAutoDefaultParams()[key];
}
