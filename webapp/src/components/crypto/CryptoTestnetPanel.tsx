import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";
import { CycleDiagnosticsPanel } from "@/components/crypto/CycleDiagnosticsPanel";
import {
  CryptoCandidateOpportunityPanel,
  mergeCandidateOpportunitiesWithEvaluated,
} from "@/components/crypto/CryptoCandidateOpportunityPanel";
import {
  assistedPrimaryReasonLabel,
  CRYPTO_TESTNET_WHITELIST_SYMBOLS,
} from "@/components/crypto/cryptoStrategyMessages";
import { CryptoTimeframeField } from "@/components/crypto/CryptoTimeframeField";
import { TestnetAppPositionsCard } from "@/components/crypto/TestnetAppPositionsCard";
import {
  TestnetExitEvaluationsTable,
  exitProposalReasonLabel,
} from "@/components/crypto/TestnetExitEvaluationsTable";
import { normalizeTimeframeString } from "@/components/crypto/cryptoTimeframe";
import {
  getCryptoTestnetAppPositions,
  getCryptoTestnetBalances,
  getCryptoTestnetMonitorCycles,
  getCryptoTestnetMonitorStatus,
  getCryptoTestnetOpenOrders,
  getCryptoTestnetOrders,
  getCryptoTestnetStatus,
  getCryptoTestnetTicker,
  postCryptoTestnetCancelOrder,
  postCryptoTestnetLimitOrder,
  postCryptoTestnetMarketOrder,
  postCryptoTestnetSyncHistory,
  postCryptoTestnetMonitorStart,
  postCryptoTestnetMonitorStop,
  postCryptoTestnetProposeEntry,
  postCryptoTestnetProposeExits,
  type CryptoTestnetAppPositionsPayload,
  type CryptoTestnetBalancesPayload,
  type CryptoTestnetEvaluatedRow,
  type CryptoTestnetExitEvaluatedRow,
  type CryptoTestnetExitProposal,
  type CryptoTestnetMarketOrderRow,
  type CryptoTestnetMonitorCycleRow,
  type CryptoTestnetMonitorParamsSnapshot,
  type CryptoTestnetMonitorStatusPayload,
  type CryptoTestnetOpenOrdersPayload,
  type CryptoPositionLimitsSnapshot,
  type CryptoTestnetProposeEntryPayload,
  type CryptoTestnetProposeExitsPayload,
  type CryptoTestnetStoredOrder,
  type CryptoTestnetStatusPayload,
  type CryptoTestnetTickerPayload,
  type CryptoStrategyMode,
} from "@/services/api";

const HIGHLIGHT_ASSETS = ["BTC", "ETH", "SOL", "BNB", "USDT"] as const;
const ASSET_SORT_TIER: Record<string, number> = { BTC: 0, ETH: 1, SOL: 2, BNB: 3, USDT: 4 };
const PAIR_FOR_BASE: Record<string, string> = {
  BTC: "BTC/USDT",
  ETH: "ETH/USDT",
  SOL: "SOL/USDT",
  BNB: "BNB/USDT",
};
const TESTNET_WHITELIST_SYMBOLS = CRYPTO_TESTNET_WHITELIST_SYMBOLS;
const TESTNET_MAX_ORDER_NOTIONAL_USDT = 100;
const MIN_TESTNET_ORDER_USDT = 0.01;
const TESTNET_MAX_ORDER_NOTIONAL_ERROR = `El importe debe ser menor o igual a ${TESTNET_MAX_ORDER_NOTIONAL_USDT} USDT`;
const SMALL_USDT_WARN = 5;
const TESTNET_PRICE_DRIFT_WARN_PCT = 0.5;
const MAX_OPEN_ASSETS_TOOLTIP =
  "Cuenta cuántos activos distintos tienen posición Testnet registrada por la app. No es monto total invertido.";
const MAX_USDT_EXPOSURE_FUTURE_NOTE =
  "Para limitar dinero total invertido usaremos exposición máxima USDT en un próximo paso.";
const TESTNET_ORDER_SUCCESS_MESSAGE = "Orden ejecutada. Revisá Posición Testnet.";
const TESTNET_BUY_SUCCESS_MESSAGE = TESTNET_ORDER_SUCCESS_MESSAGE;
const TESTNET_SELL_SUCCESS_MESSAGE = TESTNET_ORDER_SUCCESS_MESSAGE;
const TESTNET_MANUAL_AUTO_DISABLED_NOTE =
  "La ejecución automática queda deshabilitada en Testnet por seguridad.";
const MONITOR_CYCLES_COMPACT_DEFAULT = 5;
const MONITOR_CYCLES_EXPAND_MAX = 20;
const EXECUTED_PROPOSALS_STORAGE_KEY = "crypto_testnet_executed_proposals_v1";
const EXIT_PROPOSAL_PREFILL_MESSAGE =
  "Propuesta de salida cargada en el formulario. Revisá y confirmá manualmente.";

const EXIT_SEARCH_HELP_TEXT =
  "Evalúa salidas sobre posiciones Testnet registradas por la app (FIFO local). SL/TP por precio vs entrada; trailing y break-even opcional. La venta usa cantidad de posición app limitada por saldo libre testnet.";

const EXIT_SEARCH_BTN_TITLE =
  "Revisa la cartera activa Testnet y propone SELL por stop loss, take profit o trailing. No vende automáticamente.";

const MONITOR_EXITS_HELP_TEXT =
  "El monitor evalúa salidas sobre posiciones abiertas registradas por la app (mismos criterios SL/TP/trailing). Muestra diagnóstico aunque no haya venta sugerida; solo propone, no vende.";

const MONITOR_SAFE_MODE_NOTICE =
  "Modo seguro: SL, TP y trailing solo generan propuestas. No venden automáticamente.";

const MONITOR_MANUAL_EXIT_NOTICE =
  "Las salidas por SL/TP/trailing requieren confirmación manual. El monitor no ejecuta órdenes.";

const MONITOR_SL_TOOLTIP = "Propone salida si la pérdida llega a este porcentaje.";
const MONITOR_TP_TOOLTIP = "Propone salida si la ganancia llega a este porcentaje.";
const MONITOR_TRAIL_TOOLTIP =
  "Sigue el máximo alcanzado y propone salida si cae este porcentaje desde el máximo.";

const PORTFOLIO_ASSETS_DISCLAIMER =
  "Estos saldos son ficticios del entorno Binance Spot Testnet/Sandbox.";

const PORTFOLIO_NO_AUTO_EXPAND_NOTE =
  "No se abre automáticamente después de operar; usá Posiciones Testnet para ver PnL.";

const STRATEGY_COOLDOWN_FIELD_HINT =
  "Tiempo mínimo antes de volver a proponer una entrada en el mismo activo.";

const DEFAULT_MIN_SCORE = "65";
const MIN_SCORE_FIELD_HINT =
  "Filtro mínimo de calidad de señal. Combina tendencia, momentum, RSI/MACD, volumen y contexto BTC. A mayor score, menos propuestas pero más selectivas.";

const TESTNET_STRATEGY_TREND_HINT =
  "Más conservadora, sigue tendencia y filtra más.";
const TESTNET_STRATEGY_DAILY_HINT =
  "Más dinámica, permite pullbacks/rebotes controlados para trades cortos.";

type TestnetStrategyPreset = {
  tf: string;
  minScore: string;
  cooldown: string;
  btcTrend: boolean;
  sl: string;
  tp: string;
  trail: string;
};

function testnetStrategyPreset(mode: CryptoStrategyMode): TestnetStrategyPreset {
  if (mode === "daily_intraday") {
    return {
      tf: "30m",
      minScore: "58",
      cooldown: "45",
      btcTrend: false,
      sl: "1.2",
      tp: "2.2",
      trail: "1",
    };
  }
  return {
    tf: "1h",
    minScore: "70",
    cooldown: "120",
    btcTrend: true,
    sl: "2",
    tp: "4",
    trail: "1.5",
  };
}

function testnetStrategyModeLabel(mode: string | null | undefined): string {
  if (mode === "daily_intraday") return "Daily / Intradía";
  if (mode === "trend_swing") return "Trend / Swing";
  return mode?.trim() ? mode : "—";
}

function resolveTestnetStrategyMode(
  ...sources: Array<string | null | undefined>
): string | null {
  for (const s of sources) {
    if (s === "daily_intraday" || s === "trend_swing") return s;
  }
  return null;
}

type TestnetModule = "status" | "operate" | "position" | "proposals" | "monitor" | "orders";

const TESTNET_MODULE_TABS: { id: TestnetModule; label: string }[] = [
  { id: "status", label: "Estado" },
  { id: "operate", label: "Operar" },
  { id: "position", label: "Posición" },
  { id: "proposals", label: "Propuestas" },
  { id: "monitor", label: "Monitor" },
  { id: "orders", label: "Órdenes" },
];

function TestnetModuleHeader({ title, lead }: { title: string; lead: string }) {
  return (
    <header className="crypto-testnet-module-header">
      <h2 className="crypto-testnet-module-title">{title}</h2>
      <p className="crypto-testnet-module-lead msg-muted">{lead}</p>
    </header>
  );
}

function TestnetSecurityCard({
  collapsed,
  onToggle,
  allOk,
  checks,
}: {
  collapsed: boolean;
  onToggle: () => void;
  allOk: boolean;
  checks: ReturnType<typeof buildTestnetSecurityChecks>;
}) {
  return (
    <section
      className={`card crypto-testnet-section crypto-testnet-security-card crypto-testnet-section--nested${
        collapsed ? " crypto-testnet-security-card--collapsed" : ""
      }`}
    >
      <header className="crypto-testnet-security-card-header crypto-testnet-group-header--collapsible">
        <div className="crypto-testnet-security-card-header-main">
          <h3 className="dashboard-section-title crypto-testnet-section-title" style={{ margin: 0 }}>
            Seguridad Testnet
          </h3>
          <span
            className={`crypto-side-badge ${allOk ? "crypto-side-badge--buy" : ""}`}
            style={allOk ? undefined : { borderColor: "rgba(217, 119, 6, 0.55)", color: "#d97706" }}
          >
            {allOk ? "Checks OK" : "Revisar"}
          </span>
        </div>
        <button
          type="button"
          className="crypto-testnet-group-toggle radar-refresh-btn"
          onClick={onToggle}
          aria-expanded={!collapsed}
          aria-controls="crypto-testnet-security-card-body"
        >
          {collapsed ? "Mostrar" : "Ocultar"}
        </button>
      </header>
      {!collapsed ? (
        <div id="crypto-testnet-security-card-body" className="crypto-testnet-security-card-body">
          <p className="msg-muted crypto-testnet-security-card-lead">
            Garantías de diseño de este módulo. El entorno en vivo se confirma con el estado de conexión arriba.
          </p>
          <ul className="crypto-testnet-security-list" aria-label="Checklist de seguridad testnet">
            {checks.map((row) => (
              <li
                key={row.id}
                className={`crypto-testnet-security-row ${row.ok ? "crypto-testnet-security-row--ok" : "crypto-testnet-security-row--warn"}`}
              >
                <span className="crypto-testnet-security-mark" aria-hidden>
                  {row.ok ? "✓" : "!"}
                </span>
                <span className="crypto-testnet-security-label">{row.label}</span>
                <span className="crypto-testnet-security-value">{row.value}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function CryptoTestnetMaxOpenAssetsLabel() {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
      Máx. activos abiertos
      <button
        type="button"
        className="crypto-testnet-field-hint-btn"
        title={MAX_OPEN_ASSETS_TOOLTIP}
        aria-label={MAX_OPEN_ASSETS_TOOLTIP}
      >
        ?
      </button>
    </span>
  );
}

function CryptoTestnetStrategyCooldownLabel() {
  return (
    <span className="crypto-testnet-field-label">
      <span className="msg-muted">Cooldown estrategia (min)</span>
      <button
        type="button"
        className="crypto-testnet-field-hint-btn"
        title={STRATEGY_COOLDOWN_FIELD_HINT}
        aria-label={STRATEGY_COOLDOWN_FIELD_HINT}
      >
        ?
      </button>
    </span>
  );
}

function CryptoTestnetMinScoreLabel() {
  return (
    <span className="crypto-testnet-field-label">
      <span className="msg-muted">Score mínimo</span>
      <button
        type="button"
        className="crypto-testnet-field-hint-btn"
        title={MIN_SCORE_FIELD_HINT}
        aria-label={MIN_SCORE_FIELD_HINT}
      >
        ?
      </button>
    </span>
  );
}

function TestnetPositionLimitsNote({ limits }: { limits?: CryptoPositionLimitsSnapshot | null }) {
  if (!limits) return null;
  const label = limits.position_source_label ?? "Posiciones Testnet registradas por la app";
  return (
    <p className="msg-muted" style={{ margin: "0.5rem 0 0", fontSize: "0.82rem" }}>
      <strong>Cupo usado por: {label}</strong>
      {" — "}
      {limits.open_positions_count}/{limits.max_open_positions} activos distintos
      {(limits.open_position_symbols?.length ?? 0) > 0
        ? ` (${limits.open_position_symbols.join(", ")})`
        : " (ninguna posición abierta registrada por la app)"}
      {(limits.rejected_by_max_open_positions_count ?? 0) > 0
        ? ` · rechazos por cupo: ${limits.rejected_by_max_open_positions_count}`
        : ""}
    </p>
  );
}

function CryptoTestnetStrategyModeField({
  value,
  onChange,
  disabled,
  id,
  fieldLabel = "Modo estrategia",
}: {
  value: CryptoStrategyMode;
  onChange: (ev: ChangeEvent<HTMLSelectElement>) => void;
  disabled?: boolean;
  id?: string;
  fieldLabel?: string;
}) {
  const hint = value === "daily_intraday" ? TESTNET_STRATEGY_DAILY_HINT : TESTNET_STRATEGY_TREND_HINT;
  return (
    <label className="crypto-testnet-field">
      <span className="crypto-testnet-field-label">
        <span className="msg-muted">{fieldLabel}</span>
        <button
          type="button"
          className="crypto-testnet-field-hint-btn"
          title={hint}
          aria-label={hint}
        >
          ?
        </button>
      </span>
      <select
        id={id}
        className="radar-input"
        value={value}
        onChange={onChange}
        disabled={disabled}
        aria-label="Modo estrategia Testnet"
      >
        <option value="trend_swing">Trend / Swing</option>
        <option value="daily_intraday">Daily / Intradía</option>
      </select>
    </label>
  );
}

function formatBaseQtyForInput(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "";
  const digits = value >= 1 ? 6 : 8;
  const s = value.toFixed(digits).replace(/\.?0+$/, "");
  return s || value.toString();
}

type TestnetSecurityCheckRow = {
  id: string;
  label: string;
  value: string;
  ok: boolean;
};

function testnetEnvironmentLabel(status: CryptoTestnetStatusPayload | null): string {
  if (!status) return "Spot Testnet (política de la app)";
  const urls = status.urls_api_safe;
  if (urls === "real") return "Revisar credenciales (.env)";
  if (urls === "sandbox" || status.sandbox_mode) return "Sandbox / Spot Testnet";
  if (urls === "testnet") return "Testnet";
  if (status.testnet) return "Testnet";
  if (urls === "unknown") return "Testnet (sin diagnóstico en vivo)";
  return "Spot Testnet";
}

function buildTestnetSecurityChecks(status: CryptoTestnetStatusPayload | null): TestnetSecurityCheckRow[] {
  const urls = status?.urls_api_safe;
  const realNotUsed = urls !== "real";
  const envOk = urls !== "real";

  return [
    {
      id: "no-real",
      label: "Binance real",
      value: realNotUsed ? "Deshabilitado / no usado" : "Posible cuenta real",
      ok: realNotUsed,
    },
    {
      id: "env",
      label: "Entorno",
      value: testnetEnvironmentLabel(status),
      ok: envOk,
    },
    {
      id: "no-auto-orders",
      label: "Órdenes automáticas",
      value: "Desactivadas",
      ok: true,
    },
    {
      id: "monitor-proposals",
      label: "Monitor",
      value: "Solo propuestas",
      ok: true,
    },
    {
      id: "manual-confirm",
      label: "Confirmación manual",
      value: "Requerida",
      ok: true,
    },
    {
      id: "order-cap",
      label: "Límite por orden",
      value: `${TESTNET_MAX_ORDER_NOTIONAL_USDT} USDT`,
      ok: true,
    },
    {
      id: "local-history",
      label: "Historial local",
      value: "data/crypto_testnet_orders.json",
      ok: true,
    },
  ];
}

const numFmt2 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 8, minimumFractionDigits: 2 });
const numFmt4 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 8, minimumFractionDigits: 0 });

function fmtNum(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return numFmt2.format(v);
}

function fmtIsoLocalShort(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("es-AR", { dateStyle: "short", timeStyle: "medium" });
}

function fmtExchangeMs(ts: number | null | undefined): string {
  if (ts === null || ts === undefined || !Number.isFinite(ts)) return "—";
  const ms = ts < 1e11 ? ts * 1000 : ts;
  const d = new Date(ms);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("es-AR", { dateStyle: "short", timeStyle: "medium" });
}

function baseAssetFromPair(pair: string): string {
  const [b] = pair.trim().split("/");
  return b ? b.toUpperCase() : "";
}

function lookupFreeBalance(
  bal: CryptoTestnetBalancesPayload | null | undefined,
  asset: string,
): number | null {
  if (!bal?.ok || !(asset ?? "").trim()) return null;
  const au = asset.trim().toUpperCase();
  const row = bal.balances.find((r) => r.asset.toUpperCase() === au);
  if (row) return row.free;
  return 0;
}

function humanizeTestnetOrderError(raw: string): string {
  const s = raw.replace(/^HTTP\s+\d+:\s*/i, "").trim();
  const lower = s.toLowerCase();
  if (
    lower.includes("falta monto") ||
    lower.includes("quote_amount_usdt debe ser") ||
    lower.includes("quote_amount_usdt es obligatorio")
  ) {
    return "Falta monto: indicá un importe USDT válido.";
  }
  if (lower.includes("símbolo no permitido") || lower.includes("whitelist") || lower.includes("no habilitado")) {
    return `Símbolo no habilitado: ${s}`;
  }
  if (
    lower.includes("testnet no configurado") ||
    lower.includes("binance_testnet_enabled=false") ||
    lower.includes("exchange testnet no disponible") ||
    lower.includes("no configurado (api key")
  ) {
    return "Testnet desconectado. Revisá el estado de conexión arriba.";
  }
  if (
    lower.includes("el importe debe ser menor o igual") ||
    lower.includes("monto máximo por orden") ||
    lower.includes("notional máximo") ||
    lower.includes("notional tras precisión supera")
  ) {
    return TESTNET_MAX_ORDER_NOTIONAL_ERROR;
  }
  if (lower.includes("notional") || lower.includes("-1013")) {
    return "La orden es demasiado chica para Binance.";
  }
  if (lower.startsWith("respuesta binance") || lower.includes("ccxt")) {
    return `Respuesta Binance/ccxt: ${s}`;
  }
  if (s.length > 320) return `${s.slice(0, 320)}…`;
  return s;
}

function normalizeTestnetPair(symbol: string): string {
  return symbol.trim().toUpperCase();
}

function appPositionsTabAfterSell(
  payload: CryptoTestnetAppPositionsPayload | null,
  symbol: string,
): "open" | "closed" {
  if (!payload?.ok) return "closed";
  const sym = normalizeTestnetPair(symbol);
  const stillOpen = payload.open_positions.some(
    (p) => normalizeTestnetPair(p.symbol) === sym && p.amount_base > 1e-10,
  );
  return stillOpen ? "open" : "closed";
}

function tickerLivePrice(t: CryptoTestnetTickerPayload | null | undefined): number | null {
  if (!t) return null;
  const px = t.price ?? t.last;
  return typeof px === "number" && Number.isFinite(px) && px > 0 ? px : null;
}

function priceDriftPct(signal: number, live: number): number | null {
  if (!Number.isFinite(signal) || signal <= 0 || !Number.isFinite(live) || live <= 0) return null;
  return ((live - signal) / signal) * 100;
}

function signalPriceForProposal(
  symbol: string,
  evaluated?: CryptoTestnetEvaluatedRow[] | null,
): number | null {
  const sym = normalizeTestnetPair(symbol);
  const row = evaluated?.find((r) => normalizeTestnetPair(r.symbol ?? "") === sym);
  const p = row?.price;
  return typeof p === "number" && Number.isFinite(p) && p > 0 ? p : null;
}

function proposalEntryKey(symbol: string): string {
  return `entry:${normalizeTestnetPair(symbol)}`;
}

function proposalExitKey(symbol: string, asset: string): string {
  return `exit:${normalizeTestnetPair(symbol)}:${asset.trim().toUpperCase()}`;
}

function loadExecutedProposalKeys(): Set<string> {
  try {
    const raw = sessionStorage.getItem(EXECUTED_PROPOSALS_STORAGE_KEY);
    if (!raw) return new Set();
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((x): x is string => typeof x === "string"));
  } catch {
    return new Set();
  }
}

function persistExecutedProposalKeys(keys: Set<string>): void {
  try {
    sessionStorage.setItem(EXECUTED_PROPOSALS_STORAGE_KEY, JSON.stringify([...keys]));
  } catch {
    /* sessionStorage opcional */
  }
}

function sideHistoryLabel(side: string | null | undefined): string {
  const s = (side ?? "").toLowerCase();
  if (s === "buy") return "COMPRA";
  if (s === "sell") return "VENTA";
  return "—";
}

function orderTypeLabel(row: { order_type?: string | null; type?: string | null; limit_price?: number | null }): string {
  const t = String(row.order_type ?? row.type ?? "").toUpperCase();
  if (t === "LIMIT" || t === "limit") return "LIMIT";
  if (t === "MARKET" || t === "market") return "MARKET";
  if (row.limit_price != null && Number.isFinite(Number(row.limit_price))) return "LIMIT";
  return "MARKET";
}

function monitorCycleStrategyLabel(row: CryptoTestnetMonitorCycleRow): string {
  const mode = resolveTestnetStrategyMode(
    row.strategy_mode,
    typeof row.scan_debug === "object" && row.scan_debug
      ? String((row.scan_debug as Record<string, unknown>).strategy_mode ?? "")
      : undefined,
  );
  return testnetStrategyModeLabel(mode);
}

function formatMonitorActiveParamsLine(p: CryptoTestnetMonitorParamsSnapshot | undefined): string {
  if (!p || Object.keys(p).length === 0) return "—";
  const parts: string[] = [];
  if (p.timeframe) parts.push(`TF ${p.timeframe}`);
  if (p.min_entry_score != null && Number.isFinite(p.min_entry_score)) {
    parts.push(`score ≥ ${p.min_entry_score}`);
  }
  if (p.cooldown_minutes != null) parts.push(`cooldown ${p.cooldown_minutes} min`);
  parts.push(p.require_btc_trend_up ? "BTC alcista" : "BTC libre");
  if (p.stop_loss_pct != null && p.take_profit_pct != null) {
    parts.push(`SL ${p.stop_loss_pct}% / TP ${p.take_profit_pct}%`);
  }
  if (p.trailing_stop_pct != null && Number.isFinite(p.trailing_stop_pct)) {
    parts.push(`trail ${p.trailing_stop_pct}%`);
  } else if (p.trailing_stop_pct === null) {
    parts.push("trail —");
  }
  if (p.max_open_positions != null) parts.push(`máx ${p.max_open_positions} activos`);
  if (p.quote_amount_usdt != null) parts.push(`${p.quote_amount_usdt} USDT/entrada`);
  return parts.length > 0 ? parts.join(" · ") : "—";
}

function monitorCycleReasonLabel(row: CryptoTestnetMonitorCycleRow): string {
  if (row.entry_proposal_generated && row.entry_proposal?.symbol) {
    return `Entrada: ${row.entry_proposal.symbol}`;
  }
  if (row.entry_proposal_generated) {
    return "Entrada propuesta";
  }
  const entryR = row.no_entry_reason;
  if (entryR) {
    return assistedPrimaryReasonLabel(
      entryR,
      resolveTestnetStrategyMode(row.strategy_mode),
    );
  }
  if ((row.exit_proposals_count ?? 0) > 0) {
    const first = row.exit_proposals?.[0];
    if (first?.exit_reason && first.asset) {
      return `Salida ${first.asset}: ${exitProposalReasonLabel(first.exit_reason)}`;
    }
    return "Salidas propuestas";
  }
  if (row.no_exit_reason) return row.no_exit_reason;
  return "—";
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

type PortfolioRow = {
  asset: string;
  free: number;
  total: number;
  approxUsdt: number | null;
  pair: string | null;
  highlight: boolean;
};

function isTestnetWhitelistPair(pair: string | null): boolean {
  return pair != null && (TESTNET_WHITELIST_SYMBOLS as readonly string[]).includes(pair);
}

export function CryptoTestnetPanel() {
  const [status, setStatus] = useState<CryptoTestnetStatusPayload | null>(null);
  const [balances, setBalances] = useState<CryptoTestnetBalancesPayload | null>(null);
  const [priceByPair, setPriceByPair] = useState<Record<string, number | null>>({});
  const [balancesUpdatedAt, setBalancesUpdatedAt] = useState<string | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [balancesLoading, setBalancesLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [manualSymbol, setManualSymbol] = useState<string>(TESTNET_WHITELIST_SYMBOLS[0]);
  const [manualSide, setManualSide] = useState<"buy" | "sell">("buy");
  const [sellMode, setSellMode] = useState<"quote" | "advanced">("quote");
  const [manualQuoteUsdt, setManualQuoteUsdt] = useState<string>("10");
  const [manualSellQuoteUsdt, setManualSellQuoteUsdt] = useState<string>("5");
  const [manualAmountBase, setManualAmountBase] = useState<string>("0.0001");
  const [manualOrderType, setManualOrderType] = useState<"market" | "limit">("market");
  const [manualLimitPrice, setManualLimitPrice] = useState<string>("");
  const [manualLimitQty, setManualLimitQty] = useState<string>("0.001");
  const [orderSuccessMessage, setOrderSuccessMessage] = useState<string | null>(null);
  const [orderBusy, setOrderBusy] = useState(false);
  const [orderFormError, setOrderFormError] = useState<string | null>(null);
  const [proposalPrefillMessage, setProposalPrefillMessage] = useState<string | null>(null);
  const [proposalOrderError, setProposalOrderError] = useState<string | null>(null);
  const [manualTickerAsOf, setManualTickerAsOf] = useState<string | null>(null);
  const [manualTickerRefreshing, setManualTickerRefreshing] = useState(false);
  const [priceDriftWarning, setPriceDriftWarning] = useState<string | null>(null);
  const manualOrderSectionRef = useRef<HTMLElement | null>(null);
  const [lastOrder, setLastOrder] = useState<CryptoTestnetMarketOrderRow | null>(null);
  const [recentOrders, setRecentOrders] = useState<CryptoTestnetStoredOrder[]>([]);
  const [ordersTotal, setOrdersTotal] = useState(0);
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [ordersError, setOrdersError] = useState<string | null>(null);
  const [syncHistoryBusy, setSyncHistoryBusy] = useState(false);
  const [syncHistoryMessage, setSyncHistoryMessage] = useState<string | null>(null);
  const [syncHistoryError, setSyncHistoryError] = useState<string | null>(null);
  const [appPositionsPayload, setAppPositionsPayload] = useState<CryptoTestnetAppPositionsPayload | null>(null);
  const [appPositionsError, setAppPositionsError] = useState<string | null>(null);
  const [appPositionsLoading, setAppPositionsLoading] = useState(false);
  const [appPositionsTab, setAppPositionsTab] = useState<"open" | "closed">("open");
  const [appPositionSellBusy, setAppPositionSellBusy] = useState<string | null>(null);
  const [appPositionFeedbackMessage, setAppPositionFeedbackMessage] = useState<string | null>(null);
  const [appPositionFeedbackError, setAppPositionFeedbackError] = useState<string | null>(null);
  const [executedProposalKeys, setExecutedProposalKeys] = useState<Set<string>>(() =>
    loadExecutedProposalKeys(),
  );
  const [openOrdersPayload, setOpenOrdersPayload] = useState<CryptoTestnetOpenOrdersPayload | null>(null);
  const [openOrdersError, setOpenOrdersError] = useState<string | null>(null);
  const [openOrdersLoading, setOpenOrdersLoading] = useState(false);
  const [cancelOpenOrderKey, setCancelOpenOrderKey] = useState<string | null>(null);
  const [cancelOpenOrderMessage, setCancelOpenOrderMessage] = useState<string | null>(null);
  const [cancelOpenOrderError, setCancelOpenOrderError] = useState<string | null>(null);
  const [assistedPayload, setAssistedPayload] = useState<CryptoTestnetProposeEntryPayload | null>(null);
  const [assistedLoading, setAssistedLoading] = useState(false);
  const [assistedError, setAssistedError] = useState<string | null>(null);
  const [assistedConfirmBusy, setAssistedConfirmBusy] = useState(false);
  const [testnetStrategyMode, setTestnetStrategyMode] = useState<CryptoStrategyMode>("trend_swing");
  const [assistTf, setAssistTf] = useState("1h");
  const [assistQuote, setAssistQuote] = useState("10");
  const [assistMaxOpen, setAssistMaxOpen] = useState("3");
  const [assistCooldown, setAssistCooldown] = useState("0");
  const [assistBtcTrend, setAssistBtcTrend] = useState(true);
  const [assistMinScore, setAssistMinScore] = useState("70");
  const [assistSl, setAssistSl] = useState("2");
  const [assistTp, setAssistTp] = useState("4");
  const [assistTrail, setAssistTrail] = useState("1.5");
  const [exitAssistPayload, setExitAssistPayload] = useState<CryptoTestnetProposeExitsPayload | null>(null);
  const [exitAssistLoading, setExitAssistLoading] = useState(false);
  const [exitAssistError, setExitAssistError] = useState<string | null>(null);
  const [exitSlPct, setExitSlPct] = useState("2");
  const [exitTpPct, setExitTpPct] = useState("4");
  const [exitMinValueUsdt, setExitMinValueUsdt] = useState("5");
  const [exitTrailingPct, setExitTrailingPct] = useState("");
  const [exitConfirmAsset, setExitConfirmAsset] = useState<string | null>(null);
  const [monitorStatus, setMonitorStatus] = useState<CryptoTestnetMonitorStatusPayload | null>(null);
  const [monitorStatusLoading, setMonitorStatusLoading] = useState(false);
  const [monitorBannerError, setMonitorBannerError] = useState<string | null>(null);
  const [monitorActionBusy, setMonitorActionBusy] = useState(false);
  const [monitorConfirmBuyBusy, setMonitorConfirmBuyBusy] = useState(false);
  const [monitorSellBusyAsset, setMonitorSellBusyAsset] = useState<string | null>(null);
  const [monitorCycles, setMonitorCycles] = useState<CryptoTestnetMonitorCycleRow[]>([]);
  const [monitorCyclesTotal, setMonitorCyclesTotal] = useState(0);
  const [monitorCyclesLoading, setMonitorCyclesLoading] = useState(false);
  const [monitorCyclesError, setMonitorCyclesError] = useState<string | null>(null);
  const [activeTestnetModule, setActiveTestnetModule] = useState<TestnetModule>("status");
  const [securityCardCollapsed, setSecurityCardCollapsed] = useState(true);
  const [portfolioAssetsExpanded, setPortfolioAssetsExpanded] = useState(false);
  const [monitorCyclesShowAll, setMonitorCyclesShowAll] = useState(false);
  const [monitorIntervalMin, setMonitorIntervalMin] = useState("5");
  const [monTf, setMonTf] = useState("1h");
  const [monQuote, setMonQuote] = useState("10");
  const [monMaxOpen, setMonMaxOpen] = useState("3");
  const [monCooldown, setMonCooldown] = useState("120");
  const [monBtcTrend, setMonBtcTrend] = useState(true);
  const [monMinScore, setMonMinScore] = useState("70");
  const [monSl, setMonSl] = useState("2");
  const [monTp, setMonTp] = useState("4");
  const [monTrail, setMonTrail] = useState("1.5");
  const [monBeTrig, setMonBeTrig] = useState("0");
  const [monBePlus, setMonBePlus] = useState("0");
  const [monExitMin, setMonExitMin] = useState("5");

  const monInputsLocked = Boolean(monitorStatus?.enabled);

  const applyTestnetStrategyPreset = useCallback((mode: CryptoStrategyMode) => {
    const p = testnetStrategyPreset(mode);
    setAssistTf(p.tf);
    setAssistMinScore(p.minScore);
    setAssistCooldown(p.cooldown);
    setAssistBtcTrend(p.btcTrend);
    setAssistSl(p.sl);
    setAssistTp(p.tp);
    setAssistTrail(p.trail);
    setMonTf(p.tf);
    setMonMinScore(p.minScore);
    setMonCooldown(p.cooldown);
    setMonBtcTrend(p.btcTrend);
    setMonSl(p.sl);
    setMonTp(p.tp);
    setMonTrail(p.trail);
  }, []);

  const handleTestnetStrategyModeChange = useCallback(
    (ev: ChangeEvent<HTMLSelectElement>) => {
      if (monInputsLocked) return;
      const mode: CryptoStrategyMode =
        ev.target.value === "daily_intraday" ? "daily_intraday" : "trend_swing";
      setTestnetStrategyMode(mode);
      applyTestnetStrategyPreset(mode);
    },
    [applyTestnetStrategyPreset, monInputsLocked],
  );

  const configuredTestnetStrategyLabel = useMemo(
    () => testnetStrategyModeLabel(testnetStrategyMode),
    [testnetStrategyMode],
  );

  const activeMonitorStrategyLabel = useMemo(() => {
    const mode = resolveTestnetStrategyMode(
      monitorStatus?.params?.strategy_mode,
      monitorStatus?.last_scan_debug?.strategy_mode,
    );
    return testnetStrategyModeLabel(mode);
  }, [monitorStatus?.last_scan_debug?.strategy_mode, monitorStatus?.params?.strategy_mode]);

  const monitorActiveParamsLine = useMemo(
    () =>
      monInputsLocked
        ? formatMonitorActiveParamsLine(monitorStatus?.params)
        : formatMonitorActiveParamsLine({
            timeframe: normalizeTimeframeString(monTf),
            min_entry_score: Number.parseFloat(monMinScore.replace(",", ".")),
            cooldown_minutes: Number.parseInt(monCooldown, 10),
            require_btc_trend_up: monBtcTrend,
            stop_loss_pct: Number.parseFloat(monSl.replace(",", ".")),
            take_profit_pct: Number.parseFloat(monTp.replace(",", ".")),
            trailing_stop_pct:
              monTrail.trim() === ""
                ? null
                : Number.parseFloat(monTrail.replace(",", ".")),
            max_open_positions: Number.parseInt(monMaxOpen, 10),
            quote_amount_usdt: Number.parseFloat(monQuote.replace(",", ".")),
            strategy_mode: testnetStrategyMode,
          }),
    [
      monInputsLocked,
      monitorStatus?.params,
      monTf,
      monMinScore,
      monCooldown,
      monBtcTrend,
      monSl,
      monTp,
      monTrail,
      monMaxOpen,
      monQuote,
      testnetStrategyMode,
    ],
  );

  const scrollToManualOrderForm = useCallback(() => {
    setActiveTestnetModule("operate");
    window.requestAnimationFrame(() => {
      const el = manualOrderSectionRef.current ?? document.getElementById("crypto-testnet-manual-order");
      el?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }, []);

  const openOperateWithSell = useCallback(
    (symbol: string, amountBase?: number) => {
      const sym = normalizeTestnetPair(symbol);
      if (!sym || !isTestnetWhitelistPair(sym)) return;
      setManualSymbol(sym);
      setManualSide("sell");
      setManualOrderType("market");
      setSellMode("advanced");
      setManualAmountBase(amountBase != null && amountBase > 0 ? formatBaseQtyForInput(amountBase) : "");
      setOrderFormError(null);
      setProposalPrefillMessage(`SELL precargado para ${sym}. Revisá cantidad y confirmá manualmente.`);
      scrollToManualOrderForm();
    },
    [scrollToManualOrderForm],
  );

  const prefillSellFromPortfolioAsset = useCallback(
    (row: PortfolioRow) => {
      const pair = row.pair;
      if (!pair || !isTestnetWhitelistPair(pair)) return;
      setManualSymbol(pair);
      setManualSide("sell");
      setManualOrderType("market");
      setSellMode("advanced");
      const qty = formatBaseQtyForInput(row.free);
      if (qty) setManualAmountBase(qty);
      setOrderFormError(null);
      setProposalPrefillMessage(EXIT_PROPOSAL_PREFILL_MESSAGE);
      window.requestAnimationFrame(() => scrollToManualOrderForm());
    },
    [scrollToManualOrderForm],
  );

  const switchTestnetModule = useCallback((mod: TestnetModule) => {
    setActiveTestnetModule(mod);
    window.requestAnimationFrame(() => {
      document.getElementById(`crypto-testnet-module-${mod}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }, []);

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

  const loadBalances = useCallback(async (opts?: { prefetchAllTickers?: boolean }) => {
    setBalancesLoading(true);
    const prefetchAll = opts?.prefetchAllTickers !== false;
    try {
      const [rb, ro] = await Promise.allSettled([
        getCryptoTestnetBalances(),
        getCryptoTestnetOpenOrders(),
      ]);
      if (rb.status !== "fulfilled") throw rb.reason;
      const b = rb.value;
      setBalances(b);
      if (ro.status === "fulfilled") {
        setOpenOrdersPayload(ro.value);
        setOpenOrdersError(null);
      } else {
        setOpenOrdersPayload(null);
        setOpenOrdersError(
          ro.reason instanceof Error ? ro.reason.message : "Error al leer órdenes abiertas testnet",
        );
      }
      if (prefetchAll) {
        const entries = await Promise.all(
          [...TESTNET_WHITELIST_SYMBOLS].map(async (sym) => {
            try {
              const t = await getCryptoTestnetTicker(sym);
              return [sym, tickerLivePrice(t)] as const;
            } catch {
              return [sym, null] as const;
            }
          }),
        );
        const map: Record<string, number | null> = {};
        for (const [sym, px] of entries) map[sym] = px;
        setPriceByPair(map);
      }
      setBalancesUpdatedAt(new Date().toISOString());
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error al leer balances testnet");
      setOpenOrdersPayload(null);
      setOpenOrdersError(null);
    } finally {
      setBalancesLoading(false);
    }
  }, []);

  const refreshSingleTicker = useCallback(async (symbol: string): Promise<number | null> => {
    const sym = symbol.trim();
    if (!sym) return null;
    try {
      const t = await getCryptoTestnetTicker(sym);
      const px = tickerLivePrice(t);
      setPriceByPair((prev) => ({ ...prev, [sym]: px }));
      setManualTickerAsOf(typeof t.as_of === "string" ? t.as_of : new Date().toISOString());
      return px;
    } catch {
      return null;
    }
  }, []);

  const loadOpenOrders = useCallback(async () => {
    setOpenOrdersLoading(true);
    try {
      const d = await getCryptoTestnetOpenOrders();
      setOpenOrdersPayload(d);
      setOpenOrdersError(null);
    } catch (e: unknown) {
      setOpenOrdersPayload(null);
      setOpenOrdersError(e instanceof Error ? e.message : "Error al leer órdenes abiertas testnet");
    } finally {
      setOpenOrdersLoading(false);
    }
  }, []);

  const handleCancelOpenOrder = useCallback(
    async (row: { symbol: string; order_id: string | number | null }) => {
      if (row.order_id == null) return;
      const sym = row.symbol.trim();
      const oidNum =
        typeof row.order_id === "number"
          ? row.order_id
          : Number.parseInt(String(row.order_id).trim(), 10);
      if (!sym || !Number.isFinite(oidNum) || oidNum <= 0) {
        setCancelOpenOrderError("order_id o símbolo inválido para cancelar");
        return;
      }
      const ok = window.confirm(
        `¿Cancelar la orden testnet #${oidNum} en ${sym}?\n\nSolo Binance Spot Testnet (sandbox). No se envía ninguna orden nueva.`,
      );
      if (!ok) return;

      const busyKey = `${sym}-${oidNum}`;
      setCancelOpenOrderKey(busyKey);
      setCancelOpenOrderError(null);
      setCancelOpenOrderMessage(null);
      try {
        const res = await postCryptoTestnetCancelOrder({ symbol: sym, order_id: oidNum });
        setCancelOpenOrderMessage(res.message ?? `Orden #${oidNum} cancelada en testnet.`);
        await Promise.all([loadOpenOrders(), loadBalances()]);
      } catch (e: unknown) {
        setCancelOpenOrderError(e instanceof Error ? e.message : "Error al cancelar orden testnet");
      } finally {
        setCancelOpenOrderKey(null);
      }
    },
    [loadBalances, loadOpenOrders],
  );

  const loadOrders = useCallback(async () => {
    setOrdersLoading(true);
    try {
      const { orders, total } = await getCryptoTestnetOrders(50);
      setRecentOrders(orders);
      setOrdersTotal(total);
      setOrdersError(null);
    } catch (e: unknown) {
      setOrdersError(e instanceof Error ? e.message : "Error al leer órdenes testnet locales");
    } finally {
      setOrdersLoading(false);
    }
  }, []);

  const loadAppPositions = useCallback(async (): Promise<CryptoTestnetAppPositionsPayload | null> => {
    setAppPositionsLoading(true);
    try {
      const p = await getCryptoTestnetAppPositions();
      setAppPositionsPayload(p);
      setAppPositionsError(null);
      return p;
    } catch (e: unknown) {
      setAppPositionsPayload(null);
      setAppPositionsError(e instanceof Error ? e.message : "Error al leer posiciones Testnet de la app");
      return null;
    } finally {
      setAppPositionsLoading(false);
    }
  }, []);

  const markProposalExecuted = useCallback((key: string) => {
    setExecutedProposalKeys((prev) => {
      const next = new Set(prev);
      next.add(key);
      persistExecutedProposalKeys(next);
      return next;
    });
  }, []);

  const refreshAfterTestnetOrder = useCallback(async (): Promise<CryptoTestnetAppPositionsPayload | null> => {
    const [, , , appPos] = await Promise.all([
      loadBalances({ prefetchAllTickers: false }),
      loadOrders(),
      loadOpenOrders(),
      loadAppPositions(),
    ]);
    return appPos;
  }, [loadBalances, loadOrders, loadOpenOrders, loadAppPositions]);

  const handleSyncOrderHistory = useCallback(async () => {
    setSyncHistoryBusy(true);
    setSyncHistoryError(null);
    setSyncHistoryMessage(null);
    try {
      const res = await postCryptoTestnetSyncHistory(50);
      if (!res.ok) {
        setSyncHistoryError(res.error ?? "No se pudo sincronizar el historial con testnet");
        if (Array.isArray(res.orders)) {
          setRecentOrders(res.orders);
          setOrdersTotal(res.total);
        }
        return;
      }
      setRecentOrders(res.orders);
      setOrdersTotal(res.total);
      setOrdersError(null);
      setSyncHistoryMessage(
        `Sincronizado: ${res.checked_count} revisadas, ${res.updated_count} actualizadas` +
          (res.errors_count > 0 ? `, ${res.errors_count} error(es)` : "") +
          ".",
      );
      await loadOpenOrders();
    } catch (e: unknown) {
      setSyncHistoryError(e instanceof Error ? e.message : "Error al sincronizar historial testnet");
    } finally {
      setSyncHistoryBusy(false);
    }
  }, [loadOpenOrders]);

  const applyMonitorParamsSnapshot = useCallback((p: CryptoTestnetMonitorParamsSnapshot) => {
    const mode = resolveTestnetStrategyMode(p.strategy_mode);
    if (mode === "daily_intraday" || mode === "trend_swing") {
      setTestnetStrategyMode(mode);
    }
    if (p.timeframe) setMonTf(normalizeTimeframeString(p.timeframe));
    if (p.quote_amount_usdt != null && Number.isFinite(p.quote_amount_usdt)) {
      setMonQuote(String(p.quote_amount_usdt));
    }
    if (p.max_open_positions != null) setMonMaxOpen(String(p.max_open_positions));
    if (p.cooldown_minutes != null) setMonCooldown(String(p.cooldown_minutes));
    if (typeof p.require_btc_trend_up === "boolean") setMonBtcTrend(p.require_btc_trend_up);
    if (p.min_entry_score != null && Number.isFinite(p.min_entry_score)) {
      setMonMinScore(String(p.min_entry_score));
    }
    if (p.stop_loss_pct != null && Number.isFinite(p.stop_loss_pct)) setMonSl(String(p.stop_loss_pct));
    if (p.take_profit_pct != null && Number.isFinite(p.take_profit_pct)) {
      setMonTp(String(p.take_profit_pct));
    }
    if (p.trailing_stop_pct == null) {
      setMonTrail("");
    } else if (Number.isFinite(p.trailing_stop_pct)) {
      setMonTrail(String(p.trailing_stop_pct));
    }
    if (p.break_even_trigger_pct != null && Number.isFinite(p.break_even_trigger_pct)) {
      setMonBeTrig(String(p.break_even_trigger_pct));
    }
    if (p.break_even_plus_pct != null && Number.isFinite(p.break_even_plus_pct)) {
      setMonBePlus(String(p.break_even_plus_pct));
    }
    if (p.min_exit_value_usdt != null && Number.isFinite(p.min_exit_value_usdt)) {
      setMonExitMin(String(p.min_exit_value_usdt));
    }
    if (p.interval_minutes != null && Number.isFinite(p.interval_minutes)) {
      setMonitorIntervalMin(String(p.interval_minutes));
    }
  }, []);

  const loadMonitorStatus = useCallback(async () => {
    setMonitorStatusLoading(true);
    try {
      const m = await getCryptoTestnetMonitorStatus();
      setMonitorStatus(m);
      if (m.enabled && m.params && Object.keys(m.params).length > 0) {
        applyMonitorParamsSnapshot(m.params);
      }
      setMonitorBannerError(null);
    } catch (e: unknown) {
      setMonitorBannerError(e instanceof Error ? e.message : "Error al leer monitor testnet");
    } finally {
      setMonitorStatusLoading(false);
    }
  }, [applyMonitorParamsSnapshot]);

  const loadMonitorCycles = useCallback(async (limit = 20) => {
    setMonitorCyclesLoading(true);
    try {
      const res = await getCryptoTestnetMonitorCycles(limit);
      if (!res.ok) {
        setMonitorCyclesError(res.error ?? "No se pudo leer historial de ciclos");
        setMonitorCycles([]);
        setMonitorCyclesTotal(0);
        return;
      }
      setMonitorCycles(res.cycles);
      setMonitorCyclesTotal(res.total);
      setMonitorCyclesError(null);
    } catch (e: unknown) {
      setMonitorCyclesError(e instanceof Error ? e.message : "Error al leer ciclos del monitor");
      setMonitorCycles([]);
      setMonitorCyclesTotal(0);
    } finally {
      setMonitorCyclesLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadStatus(false);
  }, [loadStatus]);

  useEffect(() => {
    void loadMonitorStatus();
    void loadMonitorCycles(20);
  }, [loadMonitorStatus, loadMonitorCycles]);

  useEffect(() => {
    if (!monitorStatus?.enabled) return undefined;
    const id = window.setInterval(() => {
      void loadMonitorStatus();
      void loadMonitorCycles(20);
    }, 12000);
    return () => window.clearInterval(id);
  }, [monitorStatus?.enabled, loadMonitorStatus, loadMonitorCycles]);

  const connected = Boolean(status?.configured && status?.enabled && status?.can_read_balance);
  const showEnvHelp = status && !status.configured;

  const appOpenSymbols = useMemo(() => {
    const s = new Set<string>();
    for (const p of appPositionsPayload?.open_positions ?? []) {
      if (p.symbol) s.add(normalizeTestnetPair(p.symbol));
    }
    return s;
  }, [appPositionsPayload?.open_positions]);

  const isEntryProposalExecuted = useCallback(
    (symbol: string) => {
      const sym = normalizeTestnetPair(symbol);
      return executedProposalKeys.has(proposalEntryKey(sym)) || appOpenSymbols.has(sym);
    },
    [executedProposalKeys, appOpenSymbols],
  );

  const isExitProposalExecuted = useCallback(
    (symbol: string, asset: string) => executedProposalKeys.has(proposalExitKey(symbol, asset)),
    [executedProposalKeys],
  );

  const goToPositionModule = useCallback((tab: "open" | "closed") => {
    setPortfolioAssetsExpanded(false);
    setActiveTestnetModule("position");
    setAppPositionsTab(tab);
    window.requestAnimationFrame(() => {
      document.getElementById("crypto-testnet-module-position")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }, []);

  const goToOrdersModule = useCallback(() => {
    setPortfolioAssetsExpanded(false);
    setActiveTestnetModule("orders");
    window.requestAnimationFrame(() => {
      document.getElementById("crypto-testnet-module-orders")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }, []);

  const executeTestnetMarketBuy = useCallback(
    async (opts: {
      symbol: string;
      quoteUsdt: number;
      signalPrice?: number | null;
    }): Promise<{ ok: true } | { ok: false; error: string }> => {
      if (!connected) {
        return { ok: false, error: "Testnet desconectado. Revisá el estado de conexión arriba." };
      }
      const sym = normalizeTestnetPair(opts.symbol);
      if (!sym || !isTestnetWhitelistPair(sym)) {
        return { ok: false, error: `Símbolo no habilitado en whitelist testnet: ${sym || "—"}` };
      }
      if (isEntryProposalExecuted(sym)) {
        return {
          ok: false,
          error: `Ya existe una posición Testnet registrada por la app para ${sym} o la entrada ya fue ejecutada.`,
        };
      }
      const q = opts.quoteUsdt;
      if (!Number.isFinite(q) || q < MIN_TESTNET_ORDER_USDT) {
        return {
          ok: false,
          error: `Falta monto: indicá al menos ${MIN_TESTNET_ORDER_USDT} USDT.`,
        };
      }
      if (q > TESTNET_MAX_ORDER_NOTIONAL_USDT + 1e-9) {
        return { ok: false, error: TESTNET_MAX_ORDER_NOTIONAL_ERROR };
      }

      setPriceDriftWarning(null);
      try {
        const t = await getCryptoTestnetTicker(sym);
        const livePx = tickerLivePrice(t);
        if (livePx !== null) {
          setPriceByPair((prev) => ({ ...prev, [sym]: livePx }));
          setManualTickerAsOf(typeof t.as_of === "string" ? t.as_of : new Date().toISOString());
        }
        const sig = opts.signalPrice;
        if (sig != null && livePx != null) {
          const drift = priceDriftPct(sig, livePx);
          if (drift !== null && Math.abs(drift) > TESTNET_PRICE_DRIFT_WARN_PCT) {
            setPriceDriftWarning(
              `El precio cambió ${drift >= 0 ? "+" : ""}${drift.toFixed(2)}% desde la señal. Revisá antes de confirmar.`,
            );
          }
        }
      } catch {
        /* continuar sin ticker en vivo */
      }

      try {
        const res = await postCryptoTestnetMarketOrder({
          symbol: sym,
          side: "buy",
          quote_amount_usdt: q,
        });
        if (res.order) setLastOrder(res.order);
        markProposalExecuted(proposalEntryKey(sym));
        setOrderSuccessMessage(TESTNET_BUY_SUCCESS_MESSAGE);
        setAppPositionFeedbackMessage(TESTNET_BUY_SUCCESS_MESSAGE);
        setAppPositionFeedbackError(null);
        setManualSymbol(sym);
        setManualSide("buy");
        await refreshAfterTestnetOrder();
        goToPositionModule("open");
        setError(null);
        return { ok: true };
      } catch (e: unknown) {
        return {
          ok: false,
          error: humanizeTestnetOrderError(e instanceof Error ? e.message : "Error al enviar orden testnet"),
        };
      }
    },
    [
      connected,
      isEntryProposalExecuted,
      markProposalExecuted,
      goToPositionModule,
      refreshAfterTestnetOrder,
    ],
  );

  const executeTestnetMarketSell = useCallback(
    async (opts: {
      symbol: string;
      asset: string;
      amountBase: number;
      fromProposal?: boolean;
    }): Promise<{ ok: true } | { ok: false; error: string }> => {
      if (!connected) {
        return { ok: false, error: "Testnet desconectado. Revisá el estado de conexión arriba." };
      }
      const sym = normalizeTestnetPair(opts.symbol);
      const asset = opts.asset.trim().toUpperCase();
      if (!sym || !isTestnetWhitelistPair(sym)) {
        return { ok: false, error: `Símbolo no habilitado en whitelist testnet: ${sym || "—"}` };
      }
      if (opts.fromProposal && isExitProposalExecuted(sym, asset)) {
        return { ok: false, error: "Esta propuesta de salida ya fue ejecutada en esta sesión." };
      }

      const freeBase = lookupFreeBalance(balances, asset);
      if (freeBase !== null && freeBase <= 1e-10) {
        return { ok: false, error: `Sin saldo libre de ${asset} para vender en testnet.` };
      }

      let amt = opts.amountBase;
      if (!Number.isFinite(amt) || amt <= 0) {
        return { ok: false, error: "Cantidad de venta inválida." };
      }
      if (freeBase !== null && amt > freeBase + 1e-12) {
        amt = freeBase;
      }
      const appOpen = appPositionsPayload?.open_positions?.find(
        (p) => normalizeTestnetPair(p.symbol) === sym,
      );
      if (appOpen && amt > appOpen.amount_base + 1e-12) {
        amt = appOpen.amount_base;
      }
      if (amt <= 1e-10) {
        return { ok: false, error: `No hay cantidad vendible para ${asset}.` };
      }

      try {
        const res = await postCryptoTestnetMarketOrder({
          symbol: sym,
          side: "sell",
          amount_base: amt,
        });
        if (res.order) setLastOrder(res.order);
        if (opts.fromProposal) markProposalExecuted(proposalExitKey(sym, asset));
        setOrderSuccessMessage(TESTNET_SELL_SUCCESS_MESSAGE);
        setAppPositionFeedbackMessage(TESTNET_SELL_SUCCESS_MESSAGE);
        setAppPositionFeedbackError(null);
        setManualSymbol(sym);
        setManualSide("sell");
        const appPos = await refreshAfterTestnetOrder();
        goToPositionModule(appPositionsTabAfterSell(appPos, sym));
        setError(null);
        return { ok: true };
      } catch (e: unknown) {
        return {
          ok: false,
          error: humanizeTestnetOrderError(e instanceof Error ? e.message : "Error al enviar venta testnet"),
        };
      }
    },
    [
      appPositionsPayload?.open_positions,
      balances,
      connected,
      isExitProposalExecuted,
      markProposalExecuted,
      goToPositionModule,
      goToOrdersModule,
      refreshAfterTestnetOrder,
    ],
  );

  const handleRefreshManualTicker = useCallback(async () => {
    setManualTickerRefreshing(true);
    setPriceDriftWarning(null);
    try {
      await refreshSingleTicker(manualSymbol);
    } finally {
      setManualTickerRefreshing(false);
    }
  }, [manualSymbol, refreshSingleTicker]);

  useEffect(() => {
    if (connected) void loadOrders();
  }, [connected, loadOrders]);

  useEffect(() => {
    if (connected) {
      void loadBalances();
      void loadAppPositions();
    }
  }, [connected, loadBalances, loadAppPositions]);

  const portfolio = useMemo((): {
    rows: PortfolioRow[];
    totalApprox: number;
    usdtFree: number;
    assetWithBalanceCount: number;
  } | null => {
    if (!balances?.ok) return null;
    const rows: PortfolioRow[] = [];
    let totalApprox = 0;
    const usdtBalanceRow = balances.balances.find((r) => r.asset.toUpperCase() === "USDT");
    const usdtFree = usdtBalanceRow?.free ?? 0;
    for (const row of balances.balances) {
      if (row.free <= 0) continue;
      const asset = row.asset.toUpperCase();
      const highlight = HIGHLIGHT_ASSETS.includes(asset as (typeof HIGHLIGHT_ASSETS)[number]);
      if (asset === "USDT") {
        totalApprox += row.free;
        rows.push({ asset, free: row.free, total: row.total, approxUsdt: row.free, pair: null, highlight: true });
        continue;
      }
      const pair = PAIR_FOR_BASE[asset] ?? null;
      const px = pair ? priceByPair[pair] ?? null : null;
      const approx = px !== null ? row.free * px : null;
      if (approx !== null) totalApprox += approx;
      rows.push({ asset, free: row.free, total: row.total, approxUsdt: approx, pair, highlight });
    }
    rows.sort((a, b) => {
      const ta = ASSET_SORT_TIER[a.asset] ?? 20;
      const tb = ASSET_SORT_TIER[b.asset] ?? 20;
      if (ta !== tb) return ta - tb;
      return a.asset.localeCompare(b.asset);
    });
    return { rows, totalApprox, usdtFree, assetWithBalanceCount: rows.length };
  }, [balances, priceByPair]);

  const baseAssetHint = baseAssetFromPair(manualSymbol);
  const pairPrice = priceByPair[manualSymbol] ?? null;
  const freeBaseForPair =
    balances?.ok && baseAssetHint ? lookupFreeBalance(balances, baseAssetHint) : null;
  const freeUsdt = balances?.ok ? lookupFreeBalance(balances, "USDT") : null;

  const baseAvailApproxUsdt =
    freeBaseForPair !== null && pairPrice !== null && pairPrice > 0 ? freeBaseForPair * pairPrice : null;

  const buyQuoteNum = Number.parseFloat(manualQuoteUsdt.replace(",", "."));
  const buyEstimateBase =
    manualSide === "buy" &&
    Number.isFinite(buyQuoteNum) &&
    buyQuoteNum > 0 &&
    pairPrice !== null &&
    pairPrice > 0
      ? buyQuoteNum / pairPrice
      : null;

  const sellQuoteNum = Number.parseFloat(manualSellQuoteUsdt.replace(",", "."));

  const limitNotionalEstimate = useMemo(() => {
    const q = Number.parseFloat(manualLimitQty.replace(",", "."));
    const p = Number.parseFloat(manualLimitPrice.replace(",", "."));
    if (!Number.isFinite(q) || !Number.isFinite(p) || q <= 0 || p <= 0) return null;
    return q * p;
  }, [manualLimitQty, manualLimitPrice]);

  const submitTestnetManualOrder = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      setOrderFormError(null);
      setOrderSuccessMessage(null);
      setLastOrder(null);
      setPriceDriftWarning(null);
      if (!connected) {
        setOrderFormError("Testnet desconectado. Revisá el estado de conexión arriba.");
        return;
      }
      if (!manualSymbol.trim()) return;
      const symTrim = normalizeTestnetPair(manualSymbol);
      if (!isTestnetWhitelistPair(symTrim)) {
        setOrderFormError(`Símbolo no habilitado en whitelist testnet: ${symTrim}`);
        return;
      }

      if (manualOrderType === "limit") {
        const qty = Number.parseFloat(manualLimitQty.replace(",", "."));
        const px = Number.parseFloat(manualLimitPrice.replace(",", "."));
        if (!Number.isFinite(qty) || qty <= 0) {
          setOrderFormError("Ingresá una cantidad positiva del activo base.");
          return;
        }
        if (!Number.isFinite(px) || px <= 0) {
          setOrderFormError("Ingresá un precio límite positivo en USDT.");
          return;
        }
        const notional = qty * px;
        if (notional > TESTNET_MAX_ORDER_NOTIONAL_USDT + 1e-9) {
          setOrderFormError(TESTNET_MAX_ORDER_NOTIONAL_ERROR);
          return;
        }
        if (manualSide === "buy") {
          if (freeUsdt !== null && freeUsdt + 1e-9 < notional) {
            setOrderFormError(`Supera tu USDT disponible (${fmtNum(freeUsdt)}).`);
            return;
          }
        } else {
          const fb = lookupFreeBalance(balances, baseAssetFromPair(symTrim));
          if (fb !== null && fb + 1e-12 < qty) {
            setOrderFormError(`Supera tu saldo de ${baseAssetFromPair(symTrim)} (${fmtNum(fb)}).`);
            return;
          }
        }
        setOrderBusy(true);
        try {
          const res = await postCryptoTestnetLimitOrder({
            symbol: symTrim,
            side: manualSide,
            quantity: qty,
            limit_price: px,
          });
          if (res.order) setLastOrder(res.order);
          setOrderSuccessMessage(
            "Orden LIMIT enviada a Binance Spot Testnet. Queda pendiente en el libro hasta que matchee el precio.",
          );
          await refreshAfterTestnetOrder();
          goToOrdersModule();
          setError(null);
        } catch (err: unknown) {
          const raw = err instanceof Error ? err.message : "Error al enviar orden limit testnet";
          setOrderFormError(humanizeTestnetOrderError(raw));
        } finally {
          setOrderBusy(false);
        }
        return;
      }

      if (manualSide === "buy") {
        const q = Number.parseFloat(manualQuoteUsdt.replace(",", "."));
        if (!Number.isFinite(q) || q < MIN_TESTNET_ORDER_USDT) {
          setOrderFormError(`Falta monto: indicá un monto USDT válido (mín. ${MIN_TESTNET_ORDER_USDT}).`);
          return;
        }
        if (q > TESTNET_MAX_ORDER_NOTIONAL_USDT + 1e-9) {
          setOrderFormError(TESTNET_MAX_ORDER_NOTIONAL_ERROR);
          return;
        }
        if (freeUsdt !== null && freeUsdt + 1e-9 < q) {
          setOrderFormError(`Supera tu USDT disponible (${fmtNum(freeUsdt)}).`);
          return;
        }
      } else if (sellMode === "quote") {
        const sq = Number.parseFloat(manualSellQuoteUsdt.replace(",", "."));
        if (!Number.isFinite(sq) || sq < MIN_TESTNET_ORDER_USDT) {
          setOrderFormError(`Indicá un monto en USDT (mín. ${MIN_TESTNET_ORDER_USDT}).`);
          return;
        }
        if (sq > TESTNET_MAX_ORDER_NOTIONAL_USDT + 1e-9) {
          setOrderFormError(TESTNET_MAX_ORDER_NOTIONAL_ERROR);
          return;
        }
        const fb = lookupFreeBalance(balances, baseAssetFromPair(symTrim));
        if (fb !== null && pairPrice !== null && pairPrice > 0) {
          const maxQuote = fb * pairPrice;
          if (sq > maxQuote + 1e-6) {
            setOrderFormError(`Supera lo que podés vender (~${fmtNum(maxQuote)} USDT con el precio actual).`);
            return;
          }
        }
      } else {
        const amt = Number.parseFloat(manualAmountBase.replace(",", "."));
        if (!Number.isFinite(amt) || amt <= 0) {
          setOrderFormError("Ingresá una cantidad positiva del activo.");
          return;
        }
        const fb = lookupFreeBalance(balances, baseAssetFromPair(symTrim));
        if (fb !== null && fb + 1e-12 < amt) {
          const b = baseAssetFromPair(symTrim);
          setOrderFormError(`Supera tu saldo disponible de ${b} (${fmtNum(fb)}).`);
          return;
        }
      }

      setOrderBusy(true);
      try {
        if (manualSide === "buy") {
          const qBuy = Number.parseFloat(manualQuoteUsdt.replace(",", "."));
          try {
            const t = await getCryptoTestnetTicker(symTrim);
            const livePx = tickerLivePrice(t);
            if (livePx !== null) {
              setPriceByPair((prev) => ({ ...prev, [symTrim]: livePx }));
              setManualTickerAsOf(typeof t.as_of === "string" ? t.as_of : new Date().toISOString());
            }
          } catch {
            /* ticker opcional antes de enviar */
          }
          const res = await postCryptoTestnetMarketOrder({
            symbol: symTrim,
            side: "buy",
            quote_amount_usdt: qBuy,
          });
        if (res.order) setLastOrder(res.order);
        markProposalExecuted(proposalEntryKey(symTrim));
        setOrderSuccessMessage(TESTNET_BUY_SUCCESS_MESSAGE);
        setAppPositionFeedbackMessage(TESTNET_BUY_SUCCESS_MESSAGE);
        setAppPositionFeedbackError(null);
          await refreshAfterTestnetOrder();
          goToPositionModule("open");
          setError(null);
          return;
        }

        const res =
          sellMode === "quote"
              ? await postCryptoTestnetMarketOrder({
                  symbol: symTrim,
                  side: "sell",
                  sell_quote_amount_usdt: Number.parseFloat(manualSellQuoteUsdt.replace(",", ".")),
                })
              : await postCryptoTestnetMarketOrder({
                  symbol: symTrim,
                  side: "sell",
                  amount_base: Number.parseFloat(manualAmountBase.replace(",", ".")),
                });
        if (res.order) setLastOrder(res.order);
        markProposalExecuted(proposalExitKey(symTrim, baseAssetFromPair(symTrim)));
        setOrderSuccessMessage(TESTNET_SELL_SUCCESS_MESSAGE);
        setAppPositionFeedbackMessage(TESTNET_SELL_SUCCESS_MESSAGE);
        setAppPositionFeedbackError(null);
        const appPos = await refreshAfterTestnetOrder();
        goToPositionModule(appPositionsTabAfterSell(appPos, symTrim));
        setError(null);
      } catch (err: unknown) {
        const raw = err instanceof Error ? err.message : "Error al enviar orden testnet";
        setOrderFormError(humanizeTestnetOrderError(raw));
      } finally {
        setOrderBusy(false);
      }
    },
    [
      balances,
      connected,
      freeUsdt,
      manualAmountBase,
      manualLimitPrice,
      manualLimitQty,
      manualOrderType,
      manualQuoteUsdt,
      manualSellQuoteUsdt,
      manualSide,
      manualSymbol,
      markProposalExecuted,
      goToPositionModule,
      goToOrdersModule,
      pairPrice,
      sellMode,
      refreshAfterTestnetOrder,
    ],
  );

  const buyWarnSmall =
    manualSide === "buy" &&
    Number.isFinite(buyQuoteNum) &&
    buyQuoteNum > 0 &&
    buyQuoteNum < SMALL_USDT_WARN;
  const sellWarnSmall =
    manualSide === "sell" &&
    sellMode === "quote" &&
    Number.isFinite(sellQuoteNum) &&
    sellQuoteNum > 0 &&
    sellQuoteNum < SMALL_USDT_WARN;

  const handleAssistedSearch = useCallback(async () => {
    setAssistedLoading(true);
    setAssistedError(null);
    setAssistedPayload(null);
    try {
      const q = Number.parseFloat(assistQuote.replace(",", "."));
      const mo = Number.parseInt(assistMaxOpen, 10);
      const cd = Number.parseInt(assistCooldown, 10);
      const ms = Number.parseFloat(assistMinScore.replace(",", "."));
      const sl = Number.parseFloat(assistSl.replace(",", "."));
      const tp = Number.parseFloat(assistTp.replace(",", "."));
      const tr = Number.parseFloat(assistTrail.replace(",", "."));
      const payload = await postCryptoTestnetProposeEntry({
        timeframe: normalizeTimeframeString(assistTf),
        limit: 200,
        quote_amount_usdt: Number.isFinite(q) && q > 0 ? Math.min(q, TESTNET_MAX_ORDER_NOTIONAL_USDT) : 10,
        max_open_positions: Number.isFinite(mo) && mo >= 1 ? mo : 3,
        cooldown_minutes: Number.isFinite(cd) && cd >= 0 ? cd : 0,
        require_btc_trend_up: assistBtcTrend,
        min_entry_score: Number.isFinite(ms) && ms >= 0 ? ms : 0,
        stop_loss_pct: Number.isFinite(sl) && sl >= 0 ? sl : 2,
        take_profit_pct: Number.isFinite(tp) && tp >= 0 ? tp : 4,
        trailing_stop_pct: Number.isFinite(tr) && tr >= 0 ? tr : 1.5,
        strategyMode: testnetStrategyMode,
      });
      setAssistedPayload(payload);
    } catch (e: unknown) {
      setAssistedError(e instanceof Error ? e.message : "Error al buscar propuesta");
      setAssistedPayload(null);
    } finally {
      setAssistedLoading(false);
    }
  }, [
    assistTf,
    assistQuote,
    assistMaxOpen,
    assistCooldown,
    assistBtcTrend,
    assistMinScore,
    assistSl,
    assistTp,
    assistTrail,
    testnetStrategyMode,
  ]);

  const handleAssistedConfirmBuy = useCallback(async () => {
    const p = assistedPayload?.proposal;
    if (!p || isEntryProposalExecuted(p.symbol)) return;
    setAssistedConfirmBusy(true);
    setOrderFormError(null);
    setProposalOrderError(null);
    const signalPx =
      signalPriceForProposal(p.symbol, assistedPayload?.evaluated);
    const result = await executeTestnetMarketBuy({
      symbol: p.symbol,
      quoteUsdt: p.quote_amount_usdt,
      signalPrice: signalPx,
    });
    if (result.ok) {
      setProposalOrderError(null);
    } else {
      setProposalOrderError(result.error);
      setOrderFormError(result.error);
    }
    setAssistedConfirmBusy(false);
  }, [assistedPayload, executeTestnetMarketBuy, isEntryProposalExecuted]);

  const handleExitAssistSearch = useCallback(async () => {
    setExitAssistLoading(true);
    setExitAssistError(null);
    setExitAssistPayload(null);
    try {
      const sl = Number.parseFloat(exitSlPct.replace(",", "."));
      const tp = Number.parseFloat(exitTpPct.replace(",", "."));
      const mv = Number.parseFloat(exitMinValueUsdt.replace(",", "."));
      const trRaw = exitTrailingPct.trim().replace(",", ".");
      const tr = trRaw === "" ? null : Number.parseFloat(trRaw);
      const payload = await postCryptoTestnetProposeExits({
        stop_loss_pct: Number.isFinite(sl) && sl >= 0 ? sl : 2,
        take_profit_pct: Number.isFinite(tp) && tp >= 0 ? tp : 4,
        min_value_usdt: Number.isFinite(mv) && mv >= 0 ? mv : 5,
        trailing_stop_pct:
          trRaw !== "" && tr !== null && Number.isFinite(tr) && tr >= 0 ? tr : null,
      });
      if (!payload.ok) {
        setExitAssistError(payload.error ?? "No se pudieron evaluar salidas testnet");
        setExitAssistPayload(null);
        return;
      }
      setExitAssistPayload(payload);
    } catch (e: unknown) {
      setExitAssistError(e instanceof Error ? e.message : "Error al buscar salidas");
      setExitAssistPayload(null);
    } finally {
      setExitAssistLoading(false);
    }
  }, [exitSlPct, exitTpPct, exitMinValueUsdt, exitTrailingPct]);

  const handleExitAssistConfirmSell = useCallback(
    async (prop: CryptoTestnetExitProposal) => {
      if (!connected || isExitProposalExecuted(prop.symbol, prop.asset)) return;
      setExitConfirmAsset(prop.asset);
      setOrderFormError(null);
      setProposalOrderError(null);
      const result = await executeTestnetMarketSell({
        symbol: prop.symbol,
        asset: prop.asset,
        amountBase: prop.amount_base,
        fromProposal: true,
      });
      if (!result.ok) {
        setProposalOrderError(result.error);
        setOrderFormError(result.error);
      } else {
        setProposalOrderError(null);
        await handleExitAssistSearch();
      }
      setExitConfirmAsset(null);
    },
    [connected, executeTestnetMarketSell, handleExitAssistSearch, isExitProposalExecuted],
  );

  const handleSellFromAppPosition = useCallback(
    async (opts: { symbol: string; asset: string; amountBase: number }) => {
      setAppPositionSellBusy(opts.symbol);
      setAppPositionFeedbackError(null);
      setAppPositionFeedbackMessage(null);
      const result = await executeTestnetMarketSell({
        symbol: opts.symbol,
        asset: opts.asset,
        amountBase: opts.amountBase,
        fromProposal: false,
      });
      if (result.ok) {
        setAppPositionFeedbackMessage(TESTNET_SELL_SUCCESS_MESSAGE);
        setOrderSuccessMessage(TESTNET_SELL_SUCCESS_MESSAGE);
      } else {
        setAppPositionFeedbackError(result.error);
        setOrderFormError(result.error);
      }
      setAppPositionSellBusy(null);
      return { ok: result.ok };
    },
    [executeTestnetMarketSell],
  );

  const lookupFreeBaseForAsset = useCallback(
    (asset: string) => lookupFreeBalance(balances, asset),
    [balances],
  );

  const handleMonitorStart = useCallback(async () => {
    setMonitorActionBusy(true);
    setMonitorBannerError(null);
    try {
      const interval = Number.parseFloat(monitorIntervalMin.replace(",", "."));
      const q = Number.parseFloat(monQuote.replace(",", "."));
      const mo = Number.parseInt(monMaxOpen, 10);
      const cd = Number.parseInt(monCooldown, 10);
      const ms = Number.parseFloat(monMinScore.replace(",", "."));
      const sl = Number.parseFloat(monSl.replace(",", "."));
      const tp = Number.parseFloat(monTp.replace(",", "."));
      const bet = Number.parseFloat(monBeTrig.replace(",", "."));
      const bep = Number.parseFloat(monBePlus.replace(",", "."));
      const xmv = Number.parseFloat(monExitMin.replace(",", "."));
      const trRaw = monTrail.trim().replace(",", ".");
      const tr = trRaw === "" ? null : Number.parseFloat(trRaw);

      const m = await postCryptoTestnetMonitorStart({
        interval_minutes: Number.isFinite(interval) && interval >= 1 ? interval : 5,
        quote_amount_usdt: Number.isFinite(q) && q > 0 ? Math.min(q, TESTNET_MAX_ORDER_NOTIONAL_USDT) : 10,
        timeframe: normalizeTimeframeString(monTf),
        limit: 200,
        max_open_positions: Number.isFinite(mo) && mo >= 1 ? mo : 3,
        cooldown_minutes: Number.isFinite(cd) && cd >= 0 ? cd : 0,
        require_btc_trend_up: monBtcTrend,
        min_entry_score: Number.isFinite(ms) && ms >= 0 ? ms : 0,
        stop_loss_pct: Number.isFinite(sl) && sl >= 0 ? sl : 2,
        take_profit_pct: Number.isFinite(tp) && tp >= 0 ? tp : 4,
        trailing_stop_pct:
          trRaw !== "" && tr !== null && Number.isFinite(tr) && tr >= 0 ? tr : null,
        break_even_trigger_pct: Number.isFinite(bet) && bet >= 0 ? bet : 0,
        break_even_plus_pct: Number.isFinite(bep) && bep >= 0 ? bep : 0,
        min_exit_value_usdt: Number.isFinite(xmv) && xmv >= 0 ? xmv : 5,
        strategy_mode: testnetStrategyMode,
      });
      setMonitorStatus(m);
      void loadMonitorCycles(20);
    } catch (e: unknown) {
      setMonitorBannerError(e instanceof Error ? e.message : "No se pudo iniciar el monitor");
    } finally {
      setMonitorActionBusy(false);
    }
  }, [
    monitorIntervalMin,
    monQuote,
    monMaxOpen,
    monCooldown,
    monTf,
    monBtcTrend,
    monMinScore,
    monSl,
    monTp,
    monTrail,
    monBeTrig,
    monBePlus,
    monExitMin,
    testnetStrategyMode,
    loadMonitorCycles,
  ]);

  const handleMonitorStop = useCallback(async () => {
    setMonitorActionBusy(true);
    setMonitorBannerError(null);
    try {
      const m = await postCryptoTestnetMonitorStop();
      setMonitorStatus(m);
      void loadMonitorCycles(20);
    } catch (e: unknown) {
      setMonitorBannerError(e instanceof Error ? e.message : "No se pudo detener el monitor");
    } finally {
      setMonitorActionBusy(false);
    }
  }, [loadMonitorCycles]);

  const handleMonitorConfirmBuy = useCallback(async () => {
    const p = monitorStatus?.last_entry_proposal;
    if (!p || isEntryProposalExecuted(p.symbol)) return;
    setMonitorConfirmBuyBusy(true);
    setOrderFormError(null);
    setProposalOrderError(null);
    const signalPx =
      signalPriceForProposal(p.symbol, monitorStatus?.last_evaluated_entries);
    const result = await executeTestnetMarketBuy({
      symbol: p.symbol,
      quoteUsdt: p.quote_amount_usdt,
      signalPrice: signalPx,
    });
    if (result.ok) {
      setProposalOrderError(null);
      void loadMonitorStatus();
    } else {
      setProposalOrderError(result.error);
      setOrderFormError(result.error);
    }
    setMonitorConfirmBuyBusy(false);
  }, [
    monitorStatus?.last_entry_proposal,
    monitorStatus?.last_evaluated_entries,
    executeTestnetMarketBuy,
    isEntryProposalExecuted,
    loadMonitorStatus,
  ]);

  const handleMonitorConfirmSell = useCallback(
    async (prop: CryptoTestnetExitProposal) => {
      if (!connected || isExitProposalExecuted(prop.symbol, prop.asset)) return;
      setMonitorSellBusyAsset(prop.asset);
      setOrderFormError(null);
      setProposalOrderError(null);
      const result = await executeTestnetMarketSell({
        symbol: prop.symbol,
        asset: prop.asset,
        amountBase: prop.amount_base,
        fromProposal: true,
      });
      if (!result.ok) {
        setProposalOrderError(result.error);
        setOrderFormError(result.error);
      } else {
        setProposalOrderError(null);
        void loadMonitorStatus();
      }
      setMonitorSellBusyAsset(null);
    },
    [connected, executeTestnetMarketSell, isExitProposalExecuted, loadMonitorStatus],
  );

  const monitorPhaseLabel = useMemo(() => {
    if (!monitorStatus?.enabled) return "Detenido";
    if (monitorStatus.running) return "Ejecutando revisión";
    return "Activo";
  }, [monitorStatus?.enabled, monitorStatus?.running]);

  const testnetSecurityChecks = useMemo(() => buildTestnetSecurityChecks(status), [status]);
  const testnetSecurityAllOk = useMemo(
    () => testnetSecurityChecks.every((row) => row.ok),
    [testnetSecurityChecks],
  );

  const refreshTestnetDatos = useCallback(() => {
    void loadBalances();
    if (connected) void loadOrders();
    void loadAppPositions();
  }, [connected, loadAppPositions, loadBalances, loadOrders]);

  const monitorCyclesVisible = useMemo(() => {
    const limit = monitorCyclesShowAll ? MONITOR_CYCLES_EXPAND_MAX : MONITOR_CYCLES_COMPACT_DEFAULT;
    return monitorCycles.slice(0, limit);
  }, [monitorCycles, monitorCyclesShowAll]);

  const exitEvalBySymbol = useMemo(() => {
    const map = new Map<string, CryptoTestnetExitEvaluatedRow>();
    const rows = exitAssistPayload?.evaluated ?? monitorStatus?.last_evaluated_exits ?? [];
    for (const row of rows) {
      const sym = row.symbol?.trim().toUpperCase();
      if (sym) map.set(sym, row);
    }
    return map;
  }, [exitAssistPayload?.evaluated, monitorStatus?.last_evaluated_exits]);

  return (
    <div className="crypto-testnet-dashboard">
      <div className="crypto-testnet-page-banner" role="note">
        <strong>Spot Testnet Binance:</strong> saldo ficticio en la red oficial de pruebas; las órdenes son reales sólo
        contra ese sandbox (no contra tu cuenta spot real). Distinto del tab <strong>Bot (Simulador)</strong>, que es
        paper interno de la app.
      </div>

      <nav className="crypto-testnet-tabs" role="tablist" aria-label="Módulos testnet">
        {TESTNET_MODULE_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTestnetModule === tab.id}
            className={`crypto-testnet-tab${activeTestnetModule === tab.id ? " crypto-testnet-tab--active" : ""}`}
            onClick={() => switchTestnetModule(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {activeTestnetModule === "status" ? (
      <div className="crypto-testnet-module" id="crypto-testnet-module-status" role="tabpanel">
        <TestnetModuleHeader
          title="Estado"
          lead="Conexión testnet, checklist de seguridad y cartera sandbox (saldos ficticios)."
        />
      {/* 1 — Estado Testnet */}
      <section className="card crypto-testnet-section">
        <div className="crypto-testnet-section-head">
          <h2 className="dashboard-section-title crypto-testnet-section-title">Estado Testnet</h2>
          <div className="crypto-testnet-toolbar">
            <button type="button" className="radar-refresh-btn" onClick={() => void loadStatus(false)} disabled={statusLoading}>
              {statusLoading ? "Refrescando…" : "Refrescar estado"}
            </button>
            <button
              type="button"
              className="radar-refresh-btn"
              onClick={() => void refreshTestnetDatos()}
              disabled={balancesLoading || !status?.enabled || !status?.configured}
            >
              {balancesLoading ? "Actualizando…" : "Refrescar datos"}
            </button>
            <CryptoRefreshBadge active={statusLoading} label="Estado…" />
            <CryptoRefreshBadge active={balancesLoading} label="Datos…" />
          </div>
        </div>

        {error ? <p className="msg-error crypto-testnet-block-start">{error}</p> : null}

        {showEnvHelp ? (
          <p className="msg-muted crypto-testnet-block-start" style={{ fontSize: "0.88rem" }}>
            Configurá credenciales de testnet en <code>.env</code> y activá{" "}
            <code>BINANCE_TESTNET_ENABLED=true</code>; reiniciá la API tras cambios.
          </p>
        ) : null}

        {statusLoading && !status ? <p className="msg-muted">Cargando estado…</p> : null}

        {status ? (
          <div className="crypto-testnet-mini-grid">
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">Conexión</span>
              <span className={`crypto-testnet-kpi-value ${connected ? "crypto-testnet-kpi-value--ok" : ""}`}>
                {connected ? "Lista" : "No disponible"}
              </span>
            </div>
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">Configurado</span>
              <span className="crypto-testnet-kpi-value">{status.configured ? "Sí" : "No"}</span>
            </div>
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">Habilitado</span>
              <span className="crypto-testnet-kpi-value">{status.enabled ? "Sí" : "No"}</span>
            </div>
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">Sandbox</span>
              <span className="crypto-testnet-kpi-value">{status.testnet ? "Sí" : "—"}</span>
            </div>
          </div>
        ) : null}
        {status ? (
          <p className="msg-muted" style={{ margin: "0.75rem 0 0", fontSize: "0.88rem" }}>
            {status.message}
          </p>
        ) : null}
      </section>

      <TestnetSecurityCard
        collapsed={securityCardCollapsed}
        onToggle={() => setSecurityCardCollapsed((prev) => !prev)}
        allOk={testnetSecurityAllOk}
        checks={testnetSecurityChecks}
      />

      {/* 2 — Cartera Testnet */}
      {balances ? (
        <section className="card crypto-testnet-section">
          <div className="crypto-testnet-section-head">
            <h3 className="dashboard-section-title crypto-testnet-section-title" style={{ margin: 0 }}>
              Cartera Testnet
            </h3>
            <span className="crypto-side-badge crypto-testnet-portfolio-badge">Ficticio / Sandbox</span>
          </div>
          <p className="crypto-testnet-portfolio-disclaimer">
            Saldos ficticios del sandbox. No representan dinero real ni tu cuenta real. {PORTFOLIO_NO_AUTO_EXPAND_NOTE}{" "}
            El cupo de entradas usa posiciones originadas por la app (
            <code style={{ fontSize: "0.8rem" }}>crypto_testnet_orders.json</code>).
          </p>
          <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.65rem", fontSize: "0.82rem" }}>
            Las salidas asistidas miran saldos reales del sandbox. El cupo de activos abiertos en propuestas/monitor cuenta
            cuántos símbolos distintos tienen posición registrada por la app (no monto USDT total).{" "}
            {MAX_USDT_EXPOSURE_FUTURE_NOTE}
          </p>
          <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.65rem", fontSize: "0.85rem" }}>
            Resumen orientativo (balances sandbox). Rentabilidad de operaciones en{" "}
            <strong>Posiciones Testnet (app)</strong>; saldos en vivo en <strong>Posiciones reales</strong>.
          </p>
          {!balances.ok ? (
            <p className="msg-error" style={{ fontSize: "0.875rem" }}>
              {balances.error ?? "No se pudieron leer balances"}
            </p>
          ) : portfolio ? (
            <>
            <div className="crypto-testnet-mini-grid">
              <div className="crypto-testnet-kpi crypto-testnet-kpi--accent">
                <span className="crypto-testnet-kpi-label">Total aproximado USDT</span>
                <span className="crypto-testnet-kpi-value">{fmtNum(portfolio.totalApprox)} USDT</span>
              </div>
              <div className="crypto-testnet-kpi">
                <span className="crypto-testnet-kpi-label">USDT libre</span>
                <span className="crypto-testnet-kpi-value">{fmtNum(portfolio.usdtFree)}</span>
              </div>
              <button
                type="button"
                className="crypto-testnet-kpi crypto-testnet-kpi--clickable"
                onClick={() => setPortfolioAssetsExpanded((prev) => !prev)}
                aria-expanded={portfolioAssetsExpanded}
                aria-controls="crypto-testnet-portfolio-assets-panel"
                title={portfolioAssetsExpanded ? "Ocultar activos con saldo" : "Ver activos con saldo"}
              >
                <span className="crypto-testnet-kpi-label">Activos con saldo</span>
                <span className="crypto-testnet-kpi-value">
                  {portfolio.assetWithBalanceCount}
                  <span className="crypto-testnet-kpi-chevron" aria-hidden>
                    {portfolioAssetsExpanded ? " ▾" : " ▸"}
                  </span>
                </span>
              </button>
              <div className="crypto-testnet-kpi">
                <span className="crypto-testnet-kpi-label">Última actualización</span>
                <span className="crypto-testnet-kpi-value" style={{ fontSize: "0.85rem", fontWeight: 500 }}>
                  {balancesUpdatedAt ? fmtIsoLocalShort(balancesUpdatedAt) : "—"}
                </span>
              </div>
            </div>
            {portfolioAssetsExpanded ? (
              <div id="crypto-testnet-portfolio-assets-panel" className="crypto-testnet-portfolio-assets">
                <p className="msg-muted crypto-testnet-portfolio-assets-lead">{PORTFOLIO_ASSETS_DISCLAIMER}</p>
                {portfolio.rows.length === 0 ? (
                  <p className="msg-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
                    Sin activos con saldo libre.
                  </p>
                ) : (
                  <div className="table-wrap">
                    <table className="crypto-testnet-table crypto-testnet-table--compact">
                      <thead>
                        <tr>
                          <th>Activo</th>
                          <th>Par</th>
                          <th className="crypto-testnet-num">Libre</th>
                          <th className="crypto-testnet-num">Total</th>
                          <th className="crypto-testnet-num">Valor est. USDT</th>
                          <th>Acción</th>
                        </tr>
                      </thead>
                      <tbody>
                        {portfolio.rows.map((row) => {
                          const canPrefillSell = row.asset !== "USDT" && isTestnetWhitelistPair(row.pair);
                          return (
                            <tr key={row.asset} className={row.highlight ? "crypto-testnet-row--hl" : undefined}>
                              <td className={row.highlight ? "crypto-testnet-asset-hl" : undefined}>{row.asset}</td>
                              <td>{row.pair ?? "—"}</td>
                              <td className="crypto-testnet-num">{numFmt4.format(row.free)}</td>
                              <td className="crypto-testnet-num">{numFmt4.format(row.total)}</td>
                              <td className="crypto-testnet-num">
                                {row.approxUsdt !== null ? fmtNum(row.approxUsdt) : "—"}
                              </td>
                              <td>
                                {row.asset === "USDT" ? (
                                  <span className="msg-muted" style={{ fontSize: "0.8rem" }}>
                                    —
                                  </span>
                                ) : canPrefillSell ? (
                                  <button
                                    type="button"
                                    className="radar-refresh-btn crypto-testnet-btn-compact"
                                    onClick={() => prefillSellFromPortfolioAsset(row)}
                                    disabled={orderBusy}
                                  >
                                    Usar para SELL
                                  </button>
                                ) : (
                                  <button
                                    type="button"
                                    className="radar-refresh-btn crypto-testnet-btn-compact"
                                    disabled
                                    title="Par no habilitado en whitelist testnet"
                                  >
                                    Usar para SELL
                                  </button>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ) : null}
            </>
          ) : null}
        </section>
      ) : null}
      </div>
      ) : null}

      {activeTestnetModule === "proposals" ? (
      <div className="crypto-testnet-module" id="crypto-testnet-module-proposals" role="tabpanel">
        <TestnetModuleHeader
          title="Propuestas"
          lead="Entradas y salidas asistidas; confirmación manual obligatoria (sin auto-trading)."
        />
      <p className="crypto-testnet-note crypto-testnet-note--blue" style={{ marginBottom: "0.75rem" }}>
        {TESTNET_MANUAL_AUTO_DISABLED_NOTE}
      </p>
      <div
        className="crypto-testnet-mini-grid crypto-testnet-mini-grid--dense"
        style={{ marginBottom: "0.75rem" }}
      >
        <CryptoTestnetStrategyModeField
          id="crypto-testnet-strategy-mode"
          value={testnetStrategyMode}
          onChange={handleTestnetStrategyModeChange}
          disabled={monInputsLocked || assistedLoading || monitorActionBusy}
        />
        <div className="crypto-testnet-kpi" style={{ alignSelf: "end" }}>
          <span className="crypto-testnet-kpi-label">
            {monInputsLocked ? "Monitor (activo)" : "Propuesta manual"}
          </span>
          <span className="crypto-testnet-kpi-value" style={{ fontSize: "0.82rem", fontWeight: 500 }}>
            {monInputsLocked ? activeMonitorStrategyLabel : configuredTestnetStrategyLabel}
          </span>
        </div>
      </div>
      {monInputsLocked ? (
        <p className="msg-muted" style={{ margin: "0 0 0.75rem", fontSize: "0.82rem" }}>
          Monitor activo: detenelo para cambiar el modo estrategia (los parámetros del ciclo siguen los del arranque).
        </p>
      ) : (
        <p className="msg-muted" style={{ margin: "0 0 0.75rem", fontSize: "0.82rem" }}>
          El mismo modo aplica a propuestas manuales y al monitor al iniciarlo.
        </p>
      )}
      {/* Propuesta asistida Testnet (estrategia propone; orden sólo si confirmás) */}
      <section className="card crypto-testnet-section">
        <h3 className="dashboard-section-title crypto-testnet-section-title">Propuesta asistida Testnet</h3>
        <div className="crypto-testnet-note crypto-testnet-note--blue crypto-testnet-block-start">
          La estrategia <strong>solo propone</strong>. La orden testnet se envía únicamente si pulsás{" "}
          <strong>Enviar BUY Testnet</strong>. No hay ejecución automática desde esta búsqueda.
        </div>
        <p className="msg-muted" style={{ marginTop: "0.65rem", marginBottom: "0.65rem", fontSize: "0.85rem" }}>
          Usa el mismo scanner y filtros que el bot paper para elegir el mejor candidato, pero sin abrir posición paper ni
          enviar órdenes hasta que confirmes. Monto máximo por orden testnet: {TESTNET_MAX_ORDER_NOTIONAL_USDT} USDT (whitelist y
          límites del backend siguen aplicando). Cupo y duplicados usan posiciones registradas por la app (
          <code style={{ fontSize: "0.8rem" }}>crypto_testnet_orders.json</code>), no saldos ficticios del sandbox.
        </p>
        <div className="crypto-testnet-mini-grid crypto-testnet-mini-grid--dense" style={{ marginBottom: "0.75rem" }}>
          <CryptoTimeframeField
            className="crypto-testnet-field"
            label="Timeframe"
            value={assistTf}
            onChange={setAssistTf}
            disabled={assistedLoading || statusLoading}
            id="crypto-testnet-assist-timeframe"
          />
          <label className="crypto-testnet-field">
            <span className="msg-muted">USDT por entrada</span>
            <input
              type="number"
              className="radar-input"
              min={MIN_TESTNET_ORDER_USDT}
              max={TESTNET_MAX_ORDER_NOTIONAL_USDT}
              step="0.01"
              value={assistQuote}
              onChange={(ev) => setAssistQuote(ev.target.value)}
              disabled={assistedLoading}
            />
          </label>
          <label className="crypto-testnet-field">
            <CryptoTestnetMaxOpenAssetsLabel />
            <input
              type="number"
              className="radar-input"
              min={1}
              max={20}
              step={1}
              value={assistMaxOpen}
              onChange={(ev) => setAssistMaxOpen(ev.target.value)}
              disabled={assistedLoading}
              title={MAX_OPEN_ASSETS_TOOLTIP}
            />
          </label>
          <p className="msg-muted" style={{ margin: 0, fontSize: "0.78rem", gridColumn: "1 / -1" }}>
            {MAX_USDT_EXPOSURE_FUTURE_NOTE}
          </p>
          <label className="crypto-testnet-field">
            <CryptoTestnetStrategyCooldownLabel />
            <input
              type="number"
              className="radar-input"
              min={0}
              max={10080}
              step={1}
              value={assistCooldown}
              onChange={(ev) => setAssistCooldown(ev.target.value)}
              disabled={assistedLoading}
            />
          </label>
          <label className="crypto-testnet-field">
            <CryptoTestnetMinScoreLabel />
            <input
              type="number"
              className="radar-input"
              min={0}
              max={100}
              step="0.5"
              placeholder={DEFAULT_MIN_SCORE}
              value={assistMinScore}
              onChange={(ev) => setAssistMinScore(ev.target.value)}
              disabled={assistedLoading}
            />
            <span className="crypto-testnet-field-suggestion">
              Sugerido: {testnetStrategyMode === "daily_intraday" ? "58" : "70"}
            </span>
          </label>
          <label className="crypto-testnet-radio" style={{ alignSelf: "end", marginTop: "0.35rem" }}>
            <input
              type="checkbox"
              checked={assistBtcTrend}
              onChange={(ev) => setAssistBtcTrend(ev.target.checked)}
              disabled={assistedLoading}
            />
            Exigir BTC alcista
          </label>
        </div>
        <div className="crypto-testnet-toolbar" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
          <button
            type="button"
            className="radar-refresh-btn"
            onClick={() => void handleAssistedSearch()}
            disabled={
              assistedLoading ||
              statusLoading ||
              !status?.configured ||
              !status?.enabled
            }
          >
            {assistedLoading ? "Buscando…" : "Buscar propuesta"}
          </button>
          <CryptoRefreshBadge active={assistedLoading} label="Scanner…" />
        </div>
        {!status?.configured || !status?.enabled ? (
          <p className="msg-muted crypto-testnet-block-start" style={{ fontSize: "0.82rem" }}>
            Habilitá testnet en <code>.env</code> y esperá estado &quot;Lista&quot; para buscar propuestas con balances en vivo.
          </p>
        ) : null}
        {assistedError ? (
          <p className="msg-error crypto-testnet-block-start" style={{ fontSize: "0.875rem" }}>
            {assistedError}
          </p>
        ) : null}
        {assistedPayload ? (
          <div className="crypto-testnet-block-start">
            {assistedPayload.proposal ? (
              <>
                <div className="crypto-testnet-mini-grid crypto-testnet-mini-grid--dense">
                  <div className="crypto-testnet-kpi crypto-testnet-kpi--accent">
                    <span className="crypto-testnet-kpi-label">Par propuesto</span>
                    <span className="crypto-testnet-kpi-value">{assistedPayload.proposal.symbol}</span>
                  </div>
                  <div className="crypto-testnet-kpi">
                    <span className="crypto-testnet-kpi-label">Monto USDT</span>
                    <span className="crypto-testnet-kpi-value">{fmtNum(assistedPayload.proposal.quote_amount_usdt)}</span>
                  </div>
                  <div className="crypto-testnet-kpi">
                    <span className="crypto-testnet-kpi-label">Score</span>
                    <span className="crypto-testnet-kpi-value">{assistedPayload.proposal.score}</span>
                  </div>
                  <div className="crypto-testnet-kpi">
                    <span className="crypto-testnet-kpi-label">TF</span>
                    <span className="crypto-testnet-kpi-value">{assistedPayload.proposal.timeframe}</span>
                  </div>
                  <div className="crypto-testnet-kpi">
                    <span className="crypto-testnet-kpi-label">Modo</span>
                    <span className="crypto-testnet-kpi-value" style={{ fontSize: "0.78rem", fontWeight: 500 }}>
                      {testnetStrategyModeLabel(
                        resolveTestnetStrategyMode(
                          assistedPayload.strategy_mode,
                          assistedPayload.scan_debug?.strategy_mode,
                          testnetStrategyMode,
                        ),
                      )}
                    </span>
                  </div>
                </div>
                <TestnetPositionLimitsNote limits={assistedPayload.position_limits} />
                <p className="msg-muted" style={{ margin: "0.65rem 0 0", fontSize: "0.85rem" }}>
                  <strong>Señal:</strong> {assistedPayload.proposal.signal || "—"}
                </p>
                <p className="msg-muted" style={{ margin: "0.35rem 0 0", fontSize: "0.85rem" }}>
                  <strong>Motivo:</strong> {assistedPayload.proposal.reason || "—"}
                </p>
                <p className="msg-muted" style={{ margin: "0.65rem 0 0", fontSize: "0.82rem" }}>
                  <strong>Riesgo sugerido</strong> (referencia; la orden mercado no coloca SL/TP automático):
                </p>
                <ul className="msg-muted" style={{ fontSize: "0.82rem", margin: "0.35rem 0 0", paddingLeft: "1.15rem" }}>
                  <li>Stop loss {assistedPayload.proposal.risk.stop_loss_pct}%</li>
                  <li>Take profit {assistedPayload.proposal.risk.take_profit_pct}%</li>
                  <li>Trailing {assistedPayload.proposal.risk.trailing_stop_pct}%</li>
                  <li>
                    Break-even trigger {assistedPayload.proposal.risk.break_even_trigger_pct}% · más{" "}
                    {assistedPayload.proposal.risk.break_even_plus_pct}%
                  </li>
                </ul>
                <div className="crypto-testnet-toolbar" style={{ marginTop: "0.85rem", flexWrap: "wrap", gap: "0.5rem" }}>
                  {isEntryProposalExecuted(assistedPayload.proposal!.symbol) ? (
                    <span className="crypto-side-badge crypto-side-badge--buy" role="status">
                      Ejecutada
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="radar-refresh-btn"
                      onClick={() => void handleAssistedConfirmBuy()}
                      disabled={!connected || assistedConfirmBusy || orderBusy}
                    >
                      {assistedConfirmBusy ? "Enviando…" : "Confirmar manualmente (BUY)"}
                    </button>
                  )}
                </div>
                {proposalOrderError ? (
                  <p className="crypto-testnet-warn" style={{ marginTop: "0.5rem", marginBottom: 0 }} role="alert">
                    {proposalOrderError}
                  </p>
                ) : null}
                {priceDriftWarning ? (
                  <p className="crypto-testnet-warn" style={{ marginTop: "0.35rem", marginBottom: 0 }} role="status">
                    {priceDriftWarning}
                  </p>
                ) : null}
                {!connected ? (
                  <p className="msg-muted" style={{ marginTop: "0.5rem", fontSize: "0.82rem" }}>
                    Conectá testnet (estado arriba) para poder confirmar la compra.
                  </p>
                ) : null}
              </>
            ) : (
              <>
                <p className="msg-muted" style={{ margin: "0.5rem 0 0", fontSize: "0.88rem" }}>
                  {assistedPrimaryReasonLabel(
                    assistedPayload.primary_reason,
                    assistedPayload.strategy_mode ?? assistedPayload.scan_debug?.strategy_mode ?? testnetStrategyMode,
                  )}
                </p>
                <p className="msg-muted" style={{ margin: "0.35rem 0 0", fontSize: "0.82rem" }}>
                  <strong>Modo:</strong>{" "}
                  {testnetStrategyModeLabel(
                    resolveTestnetStrategyMode(
                      assistedPayload.strategy_mode,
                      assistedPayload.scan_debug?.strategy_mode,
                      testnetStrategyMode,
                    ),
                  )}
                </p>
                <TestnetPositionLimitsNote limits={assistedPayload.position_limits} />
              </>
            )}
            <CryptoCandidateOpportunityPanel
              opportunities={mergeCandidateOpportunitiesWithEvaluated(
                assistedPayload.candidate_opportunities,
                undefined,
                assistedPayload.evaluated,
              )}
            />
            {Array.isArray(assistedPayload.evaluated) && assistedPayload.evaluated.length > 0 ? (
              <details style={{ marginTop: "0.75rem", fontSize: "0.82rem" }}>
                <summary className="msg-muted" style={{ cursor: "pointer" }}>
                  Evaluados ({assistedPayload.evaluated.length})
                </summary>
                <ul className="msg-muted" style={{ margin: "0.5rem 0 0", paddingLeft: "1.1rem", maxHeight: "180px", overflow: "auto" }}>
                  {assistedPayload.evaluated.map((row: CryptoTestnetEvaluatedRow, idx: number) => (
                    <li key={`${row.symbol ?? "sym"}-${idx}`}>
                      {row.symbol ?? "—"} · {row.status} —{" "}
                      {(row.rejection_reason || row.evaluation_outcome) &&
                      (row.reason === "not_whitelisted_testnet" ||
                        row.reason === "already_hold_base_testnet")
                        ? (row.rejection_reason ?? row.evaluation_outcome)
                        : row.evaluation_outcome ??
                          assistedPrimaryReasonLabel(
                            row.reason,
                            assistedPayload.strategy_mode ??
                              assistedPayload.scan_debug?.strategy_mode ??
                              testnetStrategyMode,
                          )}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </div>
        ) : null}
      </section>

      {/* Salidas asistidas Testnet */}
      <section className="card crypto-testnet-section">
        <h3 className="dashboard-section-title crypto-testnet-section-title">Salidas asistidas Testnet</h3>
        <div className="crypto-testnet-note crypto-testnet-note--blue crypto-testnet-block-start">
          La estrategia <strong>solo propone ventas</strong>. La orden testnet se envía únicamente si pulsás{" "}
          <strong>Confirmar manualmente (SELL)</strong> en cada fila. No hay liquidación automática.
        </div>
        <p className="msg-muted" style={{ marginTop: "0.65rem", marginBottom: "0.65rem", fontSize: "0.85rem" }}>
          Las salidas se calculan sobre <strong>posiciones abiertas registradas por la app</strong> (
          <code style={{ fontSize: "0.8rem" }}>crypto_testnet_orders.json</code>), con precio de entrada promedio, precio
          actual y PnL. La cantidad de venta es la de la posición app, limitada por tu saldo libre en testnet.
        </p>
        <p className="crypto-testnet-help-text">{EXIT_SEARCH_HELP_TEXT}</p>
        <div className="crypto-testnet-mini-grid crypto-testnet-mini-grid--dense" style={{ marginBottom: "0.75rem" }}>
          <label className="crypto-testnet-field">
            <span className="msg-muted">Stop loss %</span>
            <input
              type="number"
              className="radar-input"
              min={0}
              max={100}
              step="0.1"
              value={exitSlPct}
              onChange={(ev) => setExitSlPct(ev.target.value)}
              disabled={exitAssistLoading}
            />
          </label>
          <label className="crypto-testnet-field">
            <span className="msg-muted">Take profit %</span>
            <input
              type="number"
              className="radar-input"
              min={0}
              max={500}
              step="0.1"
              value={exitTpPct}
              onChange={(ev) => setExitTpPct(ev.target.value)}
              disabled={exitAssistLoading}
            />
          </label>
          <label className="crypto-testnet-field">
            <span className="msg-muted">Mín. valor USDT</span>
            <input
              type="number"
              className="radar-input"
              min={0}
              max={1000}
              step="0.5"
              value={exitMinValueUsdt}
              onChange={(ev) => setExitMinValueUsdt(ev.target.value)}
              disabled={exitAssistLoading}
            />
          </label>
          <label className="crypto-testnet-field">
            <span className="msg-muted">Trailing % (opcional)</span>
            <input
              type="number"
              className="radar-input"
              min={0}
              max={100}
              step="0.1"
              placeholder="—"
              value={exitTrailingPct}
              onChange={(ev) => setExitTrailingPct(ev.target.value)}
              disabled={exitAssistLoading}
            />
          </label>
        </div>
        <div className="crypto-testnet-toolbar" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
          <button
            type="button"
            className="radar-refresh-btn"
            onClick={() => void handleExitAssistSearch()}
            disabled={
              exitAssistLoading ||
              statusLoading ||
              !status?.configured ||
              !status?.enabled
            }
            title={EXIT_SEARCH_BTN_TITLE}
          >
            {exitAssistLoading ? "Buscando…" : "Buscar salidas"}
          </button>
          <CryptoRefreshBadge active={exitAssistLoading} label="Evaluando…" />
        </div>
        {!status?.configured || !status?.enabled ? (
          <p className="msg-muted crypto-testnet-block-start" style={{ fontSize: "0.82rem" }}>
            Habilitá testnet en <code>.env</code> para leer posiciones y precios antes de buscar salidas.
          </p>
        ) : null}
        {exitAssistError ? (
          <p className="msg-error crypto-testnet-block-start" style={{ fontSize: "0.875rem" }}>
            {exitAssistError}
          </p>
        ) : null}
        {exitAssistPayload?.ok && exitTrailingPct.trim() === "" ? (
          <p className="msg-muted crypto-testnet-block-start" style={{ fontSize: "0.82rem" }}>
            Trailing stop: con el campo vacío se usa{" "}
            <strong>
              {exitAssistPayload.trailing_stop_pct_effective ??
                exitAssistPayload.default_trailing_stop_pct ??
                1.5}
              %
            </strong>{" "}
            (configurable en la búsqueda). SL/TP comparan precio actual vs entrada promedio de la posición app.
          </p>
        ) : null}
        {exitAssistPayload?.ok ? (
          <TestnetExitEvaluationsTable
            evaluated={exitAssistPayload.evaluated}
            connected={connected}
            balances={balances}
            onConfirmSell={(prop) => void handleExitAssistConfirmSell(prop)}
            sellBusyAsset={exitConfirmAsset}
            isExitExecuted={isExitProposalExecuted}
            orderBusy={orderBusy}
          />
        ) : null}
        {exitAssistPayload?.ok &&
        exitAssistPayload.evaluated.some((r) => r.reason === "missing_local_entry") ? (
          <p className="msg-muted crypto-testnet-block-start" style={{ marginTop: "0.65rem", fontSize: "0.82rem" }}>
            <strong>Aviso:</strong> en al menos un activo no pudimos cuadrar la entrada con el historial local de esta app.
            Operá manualmente o mantené las compras/registros sólo desde acá si querés salidas asistidas.
          </p>
        ) : null}
      </section>
      </div>
      ) : null}

      {activeTestnetModule === "monitor" ? (
      <div className="crypto-testnet-module" id="crypto-testnet-module-monitor" role="tabpanel">
        <TestnetModuleHeader
          title="Monitor"
          lead="Ciclos periódicos de propuestas; historial compacto; sin órdenes automáticas."
        />
      {/* Monitor asistido Testnet */}
      <section className="card crypto-testnet-section">
        <h3 className="dashboard-section-title crypto-testnet-section-title">Monitor asistido Testnet</h3>

        <div className="crypto-monitor-config-layout">
          <h4 className="crypto-monitor-config-layout-title">Configuración monitor</h4>
          {monInputsLocked ? (
            <p className="msg-muted crypto-monitor-config-layout-lead">
              Detené el monitor para cambiar parámetros.
            </p>
          ) : (
            <p className="msg-muted crypto-monitor-config-layout-lead">
              Al iniciar usará <strong>{configuredTestnetStrategyLabel}</strong> y los valores de abajo.
            </p>
          )}

          <div className="crypto-monitor-config-row">
            <div className="crypto-monitor-config-card crypto-monitor-config-card--general">
              <h5 className="crypto-monitor-config-card-heading">General</h5>
              <CryptoTestnetStrategyModeField
                id="crypto-testnet-monitor-strategy-mode"
                fieldLabel="Estrategia"
                value={testnetStrategyMode}
                onChange={handleTestnetStrategyModeChange}
                disabled={monInputsLocked || monitorActionBusy}
              />
              <div className="crypto-monitor-timeframe-box">
                <CryptoTimeframeField
                  className="crypto-testnet-field crypto-testnet-field--timeframe"
                  label="Timeframe"
                  value={monTf}
                  onChange={setMonTf}
                  disabled={monInputsLocked || monitorActionBusy}
                  id="crypto-testnet-monitor-timeframe"
                />
              </div>
              <label className="crypto-testnet-field">
                <span className="crypto-testnet-field-label">USDT por entrada</span>
                <input
                  type="number"
                  className="radar-input"
                  min={MIN_TESTNET_ORDER_USDT}
                  max={TESTNET_MAX_ORDER_NOTIONAL_USDT}
                  step="0.01"
                  value={monQuote}
                  onChange={(ev) => setMonQuote(ev.target.value)}
                  disabled={monInputsLocked || monitorActionBusy}
                />
              </label>
            </div>

            <div className="crypto-monitor-config-card crypto-monitor-config-card--filters">
              <h5 className="crypto-monitor-config-card-heading">Filtros</h5>
              <label className="crypto-testnet-field">
                <CryptoTestnetMinScoreLabel />
                <input
                  type="number"
                  className="radar-input"
                  min={0}
                  max={100}
                  step="0.5"
                  placeholder={DEFAULT_MIN_SCORE}
                  value={monMinScore}
                  onChange={(ev) => setMonMinScore(ev.target.value)}
                  disabled={monInputsLocked || monitorActionBusy}
                />
              </label>
              <label className="crypto-testnet-field">
                <CryptoTestnetMaxOpenAssetsLabel />
                <input
                  type="number"
                  className="radar-input"
                  min={1}
                  max={50}
                  step={1}
                  value={monMaxOpen}
                  onChange={(ev) => setMonMaxOpen(ev.target.value)}
                  disabled={monInputsLocked || monitorActionBusy}
                  title={MAX_OPEN_ASSETS_TOOLTIP}
                />
              </label>
              <label className="crypto-testnet-field crypto-testnet-radio">
                <input
                  type="checkbox"
                  checked={monBtcTrend}
                  onChange={(ev) => setMonBtcTrend(ev.target.checked)}
                  disabled={monInputsLocked || monitorActionBusy}
                />
                <span className="crypto-testnet-field-label">BTC trend</span>
              </label>
            </div>

            <div className="crypto-monitor-config-card crypto-monitor-config-card--frequency">
              <h5 className="crypto-monitor-config-card-heading">Frecuencia</h5>
              <label className="crypto-testnet-field">
                <span className="crypto-testnet-field-label">Intervalo monitor (min)</span>
                <input
                  type="number"
                  className="radar-input"
                  min={1}
                  max={1440}
                  step={1}
                  value={monitorIntervalMin}
                  onChange={(ev) => setMonitorIntervalMin(ev.target.value)}
                  disabled={monInputsLocked || monitorActionBusy}
                />
              </label>
              <label className="crypto-testnet-field">
                <CryptoTestnetStrategyCooldownLabel />
                <input
                  type="number"
                  className="radar-input"
                  min={0}
                  max={10080}
                  step={1}
                  value={monCooldown}
                  onChange={(ev) => setMonCooldown(ev.target.value)}
                  disabled={monInputsLocked || monitorActionBusy}
                />
              </label>
            </div>
          </div>

          <div className="crypto-monitor-config-row crypto-monitor-config-row--risk">
            <div className="crypto-monitor-config-card crypto-monitor-config-card--risk">
              <h5 className="crypto-monitor-config-card-heading">Riesgo (solo propuestas)</h5>
              <div className="crypto-monitor-risk-grid">
                <label className="crypto-testnet-field" title={MONITOR_SL_TOOLTIP}>
                  <span className="crypto-testnet-field-label">Stop Loss %</span>
                  <input
                    type="number"
                    className="radar-input"
                    min={0}
                    step="0.1"
                    value={monSl}
                    onChange={(ev) => setMonSl(ev.target.value)}
                    disabled={monInputsLocked || monitorActionBusy}
                  />
                </label>
                <label className="crypto-testnet-field" title={MONITOR_TP_TOOLTIP}>
                  <span className="crypto-testnet-field-label">Take Profit %</span>
                  <input
                    type="number"
                    className="radar-input"
                    min={0}
                    step="0.1"
                    value={monTp}
                    onChange={(ev) => setMonTp(ev.target.value)}
                    disabled={monInputsLocked || monitorActionBusy}
                  />
                </label>
                <label className="crypto-testnet-field" title={MONITOR_TRAIL_TOOLTIP}>
                  <span className="crypto-testnet-field-label">Trailing Stop %</span>
                  <input
                    type="number"
                    className="radar-input"
                    min={0}
                    step="0.1"
                    placeholder="—"
                    value={monTrail}
                    onChange={(ev) => setMonTrail(ev.target.value)}
                    disabled={monInputsLocked || monitorActionBusy}
                  />
                </label>
              </div>
              <div className="crypto-monitor-risk-extra">
                <label className="crypto-testnet-field">
                  <span className="crypto-testnet-field-label">Mín. valor salida USDT</span>
                  <input
                    type="number"
                    className="radar-input"
                    min={0}
                    step="0.5"
                    value={monExitMin}
                    onChange={(ev) => setMonExitMin(ev.target.value)}
                    disabled={monInputsLocked || monitorActionBusy}
                  />
                </label>
                <label className="crypto-testnet-field">
                  <span className="crypto-testnet-field-label">Break-even trig / +%</span>
                  <div className="crypto-monitor-risk-be-row">
                    <input
                      type="number"
                      className="radar-input"
                      min={0}
                      step="0.1"
                      value={monBeTrig}
                      onChange={(ev) => setMonBeTrig(ev.target.value)}
                      disabled={monInputsLocked || monitorActionBusy}
                    />
                    <input
                      type="number"
                      className="radar-input"
                      min={0}
                      step="0.1"
                      value={monBePlus}
                      onChange={(ev) => setMonBePlus(ev.target.value)}
                      disabled={monInputsLocked || monitorActionBusy}
                    />
                  </div>
                </label>
              </div>
            </div>
          </div>

          <p className="msg-muted crypto-monitor-config-footnote">{MAX_USDT_EXPOSURE_FUTURE_NOTE}</p>
        </div>
        <div className="crypto-monitor-actions">
          <button
            type="button"
            className="radar-refresh-btn crypto-testnet-btn-monitor-start"
            onClick={() => void handleMonitorStart()}
            disabled={
              monitorActionBusy ||
              monInputsLocked ||
              statusLoading ||
              !status?.configured ||
              !status?.enabled
            }
            title={`Iniciar con ${configuredTestnetStrategyLabel}`}
          >
            {monitorActionBusy && !monitorStatus?.enabled
              ? "Iniciando…"
              : `Iniciar monitor (${configuredTestnetStrategyLabel})`}
          </button>
          <button
            type="button"
            className="radar-refresh-btn crypto-testnet-btn-monitor-stop"
            onClick={() => void handleMonitorStop()}
            disabled={monitorActionBusy || !monitorStatus?.enabled}
          >
            {monitorActionBusy && monitorStatus?.enabled ? "Deteniendo…" : "Detener monitor"}
          </button>
          <button
            type="button"
            className="radar-refresh-btn"
            onClick={() => void loadMonitorStatus()}
            disabled={monitorStatusLoading}
          >
            {monitorStatusLoading ? "Estado…" : "Refrescar estado"}
          </button>
          <CryptoRefreshBadge active={monitorStatusLoading && Boolean(monitorStatus?.enabled)} label="Monitor…" />
        </div>

        <div className="crypto-testnet-note crypto-testnet-note--neutral crypto-monitor-safe-notice" role="note">
          <strong>{MONITOR_SAFE_MODE_NOTICE}</strong>
        </div>
        <p className="msg-muted crypto-monitor-safe-hint">{MONITOR_MANUAL_EXIT_NOTICE}</p>
        <p className="msg-muted crypto-monitor-safe-hint" style={{ marginTop: "0.25rem" }}>
          {MONITOR_EXITS_HELP_TEXT}
        </p>

        {monitorBannerError ? (
          <p className="msg-error crypto-testnet-block-start" style={{ fontSize: "0.875rem", marginTop: "0.5rem" }}>
            {monitorBannerError}
          </p>
        ) : null}

        <h4 className="crypto-monitor-subsection-title crypto-testnet-block-start">Estado del monitor</h4>
        <div className="crypto-testnet-mini-grid crypto-testnet-mini-grid--dense crypto-monitor-kpi-grid">
          <div className="crypto-testnet-kpi crypto-testnet-kpi--accent">
            <span className="crypto-testnet-kpi-label">Estado</span>
            <span className="crypto-testnet-kpi-value">{monitorPhaseLabel}</span>
          </div>
          <div className="crypto-testnet-kpi">
            <span className="crypto-testnet-kpi-label">Modo</span>
            <span className="crypto-testnet-kpi-value" style={{ fontSize: "0.78rem", fontWeight: 500 }}>
              {monInputsLocked ? activeMonitorStrategyLabel : configuredTestnetStrategyLabel}
            </span>
          </div>
          <div className="crypto-testnet-kpi">
            <span className="crypto-testnet-kpi-label">Última revisión</span>
            <span className="crypto-testnet-kpi-value" style={{ fontSize: "0.82rem", fontWeight: 500 }}>
              {monitorStatus?.last_run_at ? fmtIsoLocalShort(monitorStatus.last_run_at) : "—"}
            </span>
          </div>
          <div className="crypto-testnet-kpi">
            <span className="crypto-testnet-kpi-label">Próxima revisión ~</span>
            <span className="crypto-testnet-kpi-value" style={{ fontSize: "0.82rem", fontWeight: 500 }}>
              {monitorStatus?.enabled && monitorStatus.next_run_at ? fmtIsoLocalShort(monitorStatus.next_run_at) : "—"}
            </span>
          </div>
          <div className="crypto-testnet-kpi">
            <span className="crypto-testnet-kpi-label">Escaneados</span>
            <span className="crypto-testnet-kpi-value">{monitorStatus?.last_scan_count ?? "—"}</span>
          </div>
          <div className="crypto-testnet-kpi">
            <span className="crypto-testnet-kpi-label">Candidatos</span>
            <span className="crypto-testnet-kpi-value">{monitorStatus?.last_candidates_count ?? "—"}</span>
          </div>
        </div>

        {monitorStatus?.last_error ? (
          <p className="msg-error" style={{ fontSize: "0.875rem", marginBottom: "0.5rem" }}>
            Último error monitor: {monitorStatus.last_error}
          </p>
        ) : null}

        {monInputsLocked && monitorActiveParamsLine ? (
          <p className="msg-muted" style={{ margin: "0 0 0.65rem", fontSize: "0.78rem", lineHeight: 1.45 }}>
            <strong>Parámetros activos:</strong> {monitorActiveParamsLine}
          </p>
        ) : null}

        <details style={{ marginBottom: "0.65rem", fontSize: "0.82rem" }}>
          <summary className="msg-muted" style={{ cursor: "pointer" }}>
            Diagnóstico del último ciclo
          </summary>
          <div style={{ marginTop: "0.5rem" }}>
            <CycleDiagnosticsPanel
              startedAt={monitorStatus?.last_cycle_started_at}
              finishedAt={monitorStatus?.last_cycle_finished_at}
              durationMs={monitorStatus?.last_cycle_duration_ms}
              primaryReason={monitorStatus?.last_primary_reason ?? monitorStatus?.last_entry_primary_reason}
              summary={monitorStatus?.last_cycle_summary}
              lastScanDebug={monitorStatus?.last_scan_debug}
              bestRejected={monitorStatus?.best_rejected_candidate}
              entryCandidate={monitorStatus?.last_entry_candidate}
              primaryReasonLabel={(code) =>
                assistedPrimaryReasonLabel(
                  code,
                  monitorStatus?.params?.strategy_mode ??
                    monitorStatus?.last_scan_debug?.strategy_mode ??
                    testnetStrategyMode,
                )
              }
              emptyHint="Sin datos de ciclo todavía. Iniciá el monitor y esperá la primera revisión."
            />
          </div>
        </details>

        <div className="crypto-monitor-proposals-block">
          <h4 className="crypto-monitor-subsection-title">Última propuesta de entrada</h4>
          {monitorStatus?.last_entry_proposal ? (
            <>
              <div className="crypto-testnet-mini-grid crypto-testnet-mini-grid--dense">
                <div className="crypto-testnet-kpi crypto-testnet-kpi--accent">
                  <span className="crypto-testnet-kpi-label">Par</span>
                  <span className="crypto-testnet-kpi-value">{monitorStatus.last_entry_proposal.symbol}</span>
                </div>
                <div className="crypto-testnet-kpi">
                  <span className="crypto-testnet-kpi-label">USDT</span>
                  <span className="crypto-testnet-kpi-value">
                    {fmtNum(monitorStatus.last_entry_proposal.quote_amount_usdt)}
                  </span>
                </div>
                <div className="crypto-testnet-kpi">
                  <span className="crypto-testnet-kpi-label">Score</span>
                  <span className="crypto-testnet-kpi-value">{monitorStatus.last_entry_proposal.score ?? "—"}</span>
                </div>
              </div>
              <p className="msg-muted" style={{ margin: "0.45rem 0 0", fontSize: "0.82rem" }}>
                Señal: {monitorStatus.last_entry_proposal.signal || "—"}
              </p>
              <div className="crypto-testnet-toolbar" style={{ marginTop: "0.55rem", flexWrap: "wrap", gap: "0.5rem" }}>
                {isEntryProposalExecuted(monitorStatus.last_entry_proposal.symbol) ? (
                  <span className="crypto-side-badge crypto-side-badge--buy" role="status">
                    Ejecutada
                  </span>
                ) : (
                  <button
                    type="button"
                    className="radar-refresh-btn"
                    onClick={() => void handleMonitorConfirmBuy()}
                    disabled={
                      !connected ||
                      monitorConfirmBuyBusy ||
                      orderBusy ||
                      exitConfirmAsset !== null ||
                      monitorSellBusyAsset !== null
                    }
                  >
                    {monitorConfirmBuyBusy ? "Enviando…" : "Confirmar manualmente (BUY)"}
                  </button>
                )}
              </div>
              {proposalOrderError ? (
                <p className="crypto-testnet-warn" style={{ marginTop: "0.35rem", marginBottom: 0 }} role="alert">
                  {proposalOrderError}
                </p>
              ) : null}
              {priceDriftWarning ? (
                <p className="crypto-testnet-warn" style={{ marginTop: "0.35rem", marginBottom: 0 }} role="status">
                  {priceDriftWarning}
                </p>
              ) : null}
            </>
          ) : (
            <p className="msg-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
              {monitorStatus?.enabled
                ? assistedPrimaryReasonLabel(
                    monitorStatus.last_entry_primary_reason,
                    monitorStatus?.params?.strategy_mode ??
                      monitorStatus?.last_scan_debug?.strategy_mode ??
                      testnetStrategyMode,
                  )
                : "Sin propuesta de entrada en el último ciclo (o monitor detenido)."}
            </p>
          )}

          <h4 className="crypto-monitor-subsection-title" style={{ marginTop: "1rem" }}>
            Evaluación de salidas (último ciclo)
          </h4>
          {monitorStatus?.last_run_at ? (
            <TestnetExitEvaluationsTable
              evaluated={monitorStatus.last_evaluated_exits ?? []}
              connected={connected}
              balances={balances}
              onConfirmSell={(prop) => void handleMonitorConfirmSell(prop)}
              sellBusyAsset={monitorSellBusyAsset}
              isExitExecuted={isExitProposalExecuted}
              orderBusy={orderBusy || monitorConfirmBuyBusy}
              compact
            />
          ) : (
            <p className="msg-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
              Sin datos hasta iniciar el monitor.
            </p>
          )}
        </div>

        <TestnetAppPositionsCard
          payload={appPositionsPayload}
          error={appPositionsError}
          loading={appPositionsLoading}
          tab="open"
          onTabChange={() => {}}
          onRefresh={() => void loadAppPositions()}
          connected={connected}
          lookupFreeBase={lookupFreeBaseForAsset}
          onSell={handleSellFromAppPosition}
          sellBusySymbol={appPositionSellBusy}
          feedbackMessage={appPositionFeedbackMessage}
          feedbackError={appPositionFeedbackError}
          onOpenManualSell={openOperateWithSell}
          exitEvalBySymbol={exitEvalBySymbol}
          openOnly
          sectionTitle="Posiciones Testnet abiertas"
        />

        <div className="crypto-monitor-cycles-block">
          <div className="crypto-testnet-section-head">
            <div>
              <h4 className="crypto-monitor-subsection-title" style={{ margin: 0 }}>
                Historial de ciclos
              </h4>
              <p className="msg-muted" style={{ margin: "0.3rem 0 0", fontSize: "0.78rem" }}>
                Últimos {monitorCyclesShowAll ? MONITOR_CYCLES_EXPAND_MAX : MONITOR_CYCLES_COMPACT_DEFAULT} de{" "}
                {monitorCyclesTotal} registrados.
              </p>
            </div>
            <div className="crypto-testnet-toolbar">
              <button
                type="button"
                className="radar-refresh-btn crypto-testnet-btn-compact"
                onClick={() => void loadMonitorCycles(MONITOR_CYCLES_EXPAND_MAX)}
                disabled={monitorCyclesLoading}
              >
                {monitorCyclesLoading ? "…" : "Refrescar"}
              </button>
            </div>
          </div>
          {monitorCyclesError ? (
            <p className="msg-error" style={{ margin: "0.5rem 0 0", fontSize: "0.82rem" }}>
              {monitorCyclesError}
            </p>
          ) : null}
          {monitorCycles.length > 0 ? (
            <div className="table-wrap crypto-testnet-cycle-list-compact" style={{ marginTop: "0.55rem" }}>
              <table className="crypto-testnet-table crypto-testnet-table--compact">
                <thead>
                  <tr>
                    <th>Fecha/hora</th>
                    <th>Estrategia</th>
                    <th className="crypto-testnet-num">Escaneados</th>
                    <th className="crypto-testnet-num">Candidatos</th>
                    <th>Entrada</th>
                    <th className="crypto-testnet-num">Salidas</th>
                    <th>Razón</th>
                  </tr>
                </thead>
                <tbody>
                  {monitorCyclesVisible.map((row, idx) => (
                    <tr key={`${row.timestamp ?? "t"}-${idx}`}>
                      <td style={{ whiteSpace: "nowrap" }}>
                        {fmtIsoLocalShort(row.timestamp ?? row.cycle_finished_at ?? "")}
                      </td>
                      <td style={{ fontSize: "0.76rem", whiteSpace: "nowrap" }}>
                        {monitorCycleStrategyLabel(row)}
                      </td>
                      <td className="crypto-testnet-num">{row.scan_count ?? "—"}</td>
                      <td className="crypto-testnet-num">{row.candidates_count ?? "—"}</td>
                      <td>{row.entry_proposal_generated ? "Sí" : "No"}</td>
                      <td className="crypto-testnet-num">{row.exit_proposals_count ?? 0}</td>
                      <td
                        style={{ maxWidth: "12rem", overflow: "hidden", textOverflow: "ellipsis" }}
                        title={monitorCycleReasonLabel(row)}
                      >
                        {monitorCycleReasonLabel(row)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : monitorCyclesLoading ? (
            <p className="msg-muted" style={{ margin: "0.5rem 0 0", fontSize: "0.82rem" }}>
              Cargando historial…
            </p>
          ) : (
            <p className="msg-muted" style={{ margin: "0.5rem 0 0", fontSize: "0.82rem" }}>
              Sin ciclos registrados. Iniciá el monitor y esperá al menos una revisión.
            </p>
          )}
          {monitorCycles.length > MONITOR_CYCLES_COMPACT_DEFAULT ? (
            <div className="crypto-testnet-toolbar" style={{ marginTop: "0.45rem", gap: "0.35rem" }}>
              <button
                type="button"
                className="radar-refresh-btn crypto-testnet-btn-compact"
                onClick={() => setMonitorCyclesShowAll((v) => !v)}
              >
                {monitorCyclesShowAll ? "Mostrar menos" : "Mostrar más"}
              </button>
            </div>
          ) : null}
        </div>
      </section>
      </div>
      ) : null}

      {activeTestnetModule === "operate" ? (
      <div className="crypto-testnet-module" id="crypto-testnet-module-operate" role="tabpanel">
        <TestnetModuleHeader
          title="Operar"
          lead="Órdenes MARKET/LIMIT manuales en Spot Testnet; confirmación explícita antes de enviar."
        />
      {!connected ? (
        <p className="msg-muted crypto-testnet-note crypto-testnet-note--neutral" style={{ margin: 0 }}>
          Conectá testnet en el módulo <strong>Estado</strong> para habilitar el formulario manual.
        </p>
      ) : null}

      {connected ? (
        <>
          {/* 3 — Abrir orden manual (Spot Testnet) */}
          <section
            ref={manualOrderSectionRef}
            id="crypto-testnet-manual-order"
            className="card crypto-testnet-section crypto-testnet-manual-card"
          >
            <h3 className="dashboard-section-title crypto-testnet-section-title">Abrir orden manual</h3>
            <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.65rem", fontSize: "0.875rem" }}>
              <strong>Dinero ficticio de Binance</strong>, ejecución real sólo contra <strong>Spot Testnet</strong> (no el
              simulador paper de esta app).
            </p>
            <div className="crypto-testnet-note crypto-testnet-note--blue">
              Límite por orden: hasta {TESTNET_MAX_ORDER_NOTIONAL_USDT} USDT · pares en whitelist · mercado spot testnet.
            </div>
            {proposalPrefillMessage ? (
              <p
                className="crypto-testnet-note crypto-testnet-note--blue"
                style={{ marginTop: "0.65rem", marginBottom: 0, fontSize: "0.875rem" }}
                role="status"
              >
                {proposalPrefillMessage}
              </p>
            ) : null}
            <form className="crypto-testnet-order-form" onSubmit={(ev) => void submitTestnetManualOrder(ev)}>
              <fieldset className="crypto-testnet-fieldset" style={{ marginBottom: "0.75rem" }}>
                <legend className="msg-muted crypto-testnet-legend">Tipo de orden</legend>
                <div className="crypto-testnet-radio-row">
                  <label className="crypto-testnet-radio">
                    <input
                      type="radio"
                      name="testnet-order-type"
                      checked={manualOrderType === "market"}
                      onChange={() => setManualOrderType("market")}
                      disabled={orderBusy}
                    />
                    MARKET
                  </label>
                  <label className="crypto-testnet-radio">
                    <input
                      type="radio"
                      name="testnet-order-type"
                      checked={manualOrderType === "limit"}
                      onChange={() => setManualOrderType("limit")}
                      disabled={orderBusy}
                    />
                    LIMIT
                  </label>
                </div>
              </fieldset>
              <div className="radar-toolbar" style={{ marginBottom: "0.85rem" }}>
                <label className="radar-toolbar__field">
                  <span className="radar-toolbar__label">Par</span>
                  <select
                    className="radar-toolbar__select"
                    value={manualSymbol}
                    onChange={(ev) => setManualSymbol(ev.target.value)}
                    disabled={orderBusy}
                  >
                    {TESTNET_WHITELIST_SYMBOLS.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <fieldset className="crypto-testnet-fieldset">
                <legend className="msg-muted crypto-testnet-legend">Lado</legend>
                <div className="crypto-testnet-radio-row">
                  <label className="crypto-testnet-radio">
                    <input
                      type="radio"
                      name="testnet-order-side"
                      checked={manualSide === "buy"}
                      onChange={() => setManualSide("buy")}
                      disabled={orderBusy}
                    />
                    BUY
                  </label>
                  <label className="crypto-testnet-radio">
                    <input
                      type="radio"
                      name="testnet-order-side"
                      checked={manualSide === "sell"}
                      onChange={() => setManualSide("sell")}
                      disabled={orderBusy}
                    />
                    SELL
                  </label>
                </div>
              </fieldset>

              <div className="crypto-testnet-mini-grid crypto-testnet-mini-grid--dense">
                <div className="crypto-testnet-kpi">
                  <span className="crypto-testnet-kpi-label">{manualSide === "buy" ? "USDT disponible" : `${baseAssetHint} disponible`}</span>
                  <span className="crypto-testnet-kpi-value">
                    {manualSide === "buy"
                      ? fmtNum(freeUsdt)
                      : `${fmtNum(freeBaseForPair)} ${baseAssetHint}`}
                  </span>
                </div>
                <div className="crypto-testnet-kpi">
                  <span className="crypto-testnet-kpi-label">Valor aprox. disponible</span>
                  <span className="crypto-testnet-kpi-value">
                    {manualSide === "buy" ? `${fmtNum(freeUsdt)} USDT` : `${fmtNum(baseAvailApproxUsdt)} USDT`}
                  </span>
                </div>
                <div className="crypto-testnet-kpi">
                  <span className="crypto-testnet-kpi-label">Precio actual testnet</span>
                  <span className="crypto-testnet-kpi-value">{fmtNum(pairPrice)} USDT</span>
                </div>
              </div>
              {manualSide === "buy" && manualOrderType === "market" ? (
                <div style={{ marginTop: "0.35rem" }}>
                  <button
                    type="button"
                    className="radar-refresh-btn"
                    style={{ fontSize: "0.78rem", padding: "0.2rem 0.55rem" }}
                    onClick={() => void handleRefreshManualTicker()}
                    disabled={orderBusy || manualTickerRefreshing}
                  >
                    {manualTickerRefreshing ? "Actualizando…" : "Actualizar precio"}
                  </button>
                </div>
              ) : null}
              {manualTickerAsOf ? (
                <p className="msg-muted" style={{ margin: "0.35rem 0 0", fontSize: "0.78rem" }}>
                  Ticker testnet: {manualTickerAsOf}
                </p>
              ) : null}
              {priceDriftWarning ? (
                <p className="crypto-testnet-warn" style={{ marginTop: "0.5rem", marginBottom: 0 }} role="status">
                  {priceDriftWarning}
                </p>
              ) : null}

              {manualOrderType === "limit" ? (
                <>
                  <label className="crypto-testnet-field">
                    <span className="msg-muted">Cantidad ({baseAssetHint})</span>
                    <input
                      type="number"
                      className="radar-input"
                      min={0}
                      step="any"
                      value={manualLimitQty}
                      onChange={(ev) => setManualLimitQty(ev.target.value)}
                      disabled={orderBusy}
                    />
                  </label>
                  <label className="crypto-testnet-field">
                    <span className="msg-muted">Precio límite (USDT)</span>
                    <input
                      type="number"
                      className="radar-input"
                      min={0}
                      step="any"
                      value={manualLimitPrice}
                      onChange={(ev) => setManualLimitPrice(ev.target.value)}
                      disabled={orderBusy}
                      placeholder={pairPrice != null ? String(pairPrice) : "ej. precio actual"}
                    />
                    {limitNotionalEstimate !== null ? (
                      <span className="msg-muted" style={{ fontSize: "0.82rem", marginTop: "0.35rem" }}>
                        Notional ≈ {fmtNum(limitNotionalEstimate)} USDT (cantidad × precio límite)
                      </span>
                    ) : null}
                  </label>
                  <p className="msg-muted" style={{ fontSize: "0.82rem", marginTop: 0 }}>
                    La orden LIMIT queda en <strong>órdenes abiertas</strong> hasta que el mercado llegue al precio.
                    Podés cancelarla desde la tabla de abajo.
                  </p>
                </>
              ) : manualSide === "buy" ? (
                <label className="crypto-testnet-field">
                  <span className="msg-muted">Monto en USDT (comprás contra {manualSymbol})</span>
                  <input
                    type="number"
                    className="radar-input"
                    min={MIN_TESTNET_ORDER_USDT}
                    max={TESTNET_MAX_ORDER_NOTIONAL_USDT}
                    step="0.01"
                    value={manualQuoteUsdt}
                    onChange={(ev) => setManualQuoteUsdt(ev.target.value)}
                    disabled={orderBusy}
                  />
                  {buyEstimateBase !== null ? (
                    <span className="msg-muted" style={{ fontSize: "0.82rem", marginTop: "0.35rem" }}>
                      ≈ {numFmt4.format(buyEstimateBase)} {baseAssetHint} (estimación al precio actual)
                    </span>
                  ) : null}
                  {buyWarnSmall ? (
                    <p className="crypto-testnet-warn">Montos menores a {SMALL_USDT_WARN} USDT suelen fallar por filtros de Binance.</p>
                  ) : null}
                </label>
              ) : (
                <>
                  <fieldset className="crypto-testnet-fieldset">
                    <legend className="msg-muted crypto-testnet-legend">Cómo vender</legend>
                    <div className="crypto-testnet-radio-row">
                      <label className="crypto-testnet-radio">
                        <input
                          type="radio"
                          name="testnet-sell-mode"
                          checked={sellMode === "quote"}
                          onChange={() => setSellMode("quote")}
                          disabled={orderBusy}
                        />
                        Vender por USDT aprox. (recomendado)
                      </label>
                      <label className="crypto-testnet-radio">
                        <input
                          type="radio"
                          name="testnet-sell-mode"
                          checked={sellMode === "advanced"}
                          onChange={() => setSellMode("advanced")}
                          disabled={orderBusy}
                        />
                        Vender cantidad exacta ({baseAssetHint})
                      </label>
                    </div>
                  </fieldset>

                  {sellMode === "quote" ? (
                    <label className="crypto-testnet-field">
                      <span className="msg-muted">Monto aproximado a vender en USDT</span>
                      <input
                        type="number"
                        className="radar-input"
                        min={MIN_TESTNET_ORDER_USDT}
                        max={TESTNET_MAX_ORDER_NOTIONAL_USDT}
                        step="0.01"
                        value={manualSellQuoteUsdt}
                        onChange={(ev) => setManualSellQuoteUsdt(ev.target.value)}
                        disabled={orderBusy}
                      />
                      {sellWarnSmall ? (
                        <p className="crypto-testnet-warn">Montos menores a {SMALL_USDT_WARN} USDT suelen fallar por filtros de Binance.</p>
                      ) : null}
                    </label>
                  ) : (
                    <label className="crypto-testnet-field">
                      <span className="msg-muted">Cantidad exacta en {baseAssetHint}</span>
                      <input
                        type="number"
                        className="radar-input"
                        min={0}
                        step="any"
                        value={manualAmountBase}
                        onChange={(ev) => setManualAmountBase(ev.target.value)}
                        disabled={orderBusy}
                      />
                    </label>
                  )}
                </>
              )}

              <div>
                <button type="submit" className="radar-refresh-btn" disabled={orderBusy}>
                  {orderBusy
                    ? "Enviando…"
                    : manualOrderType === "limit"
                      ? manualSide === "buy"
                        ? "Enviar LIMIT BUY"
                        : "Enviar LIMIT SELL"
                      : manualSide === "buy"
                        ? "Comprar"
                        : "Vender"}
                </button>
              </div>
            </form>
            {orderFormError ? <p className="msg-error crypto-testnet-block-start">{orderFormError}</p> : null}
            {orderSuccessMessage ? (
              <p
                className="msg-muted crypto-testnet-block-start"
                style={{ fontSize: "0.875rem", color: "var(--success, #16a34a)" }}
              >
                {orderSuccessMessage}
              </p>
            ) : null}

            <div className="crypto-testnet-manual-footer">
              <h4 className="crypto-testnet-subheading">Última orden enviada</h4>
              {lastOrder ? (
                <div className="crypto-testnet-last-order">
                  <span
                    className={`crypto-side-badge ${
                      String(lastOrder.side).toLowerCase() === "sell" ? "crypto-side-badge--sell" : "crypto-side-badge--buy"
                    }`}
                  >
                    {String(lastOrder.side).toUpperCase()}
                  </span>
                  <div className="crypto-testnet-last-grid">
                    <div>
                      <span className="crypto-testnet-lo-label">Tipo</span>
                      <span className="crypto-testnet-lo-value">{orderTypeLabel(lastOrder)}</span>
                    </div>
                    <div>
                      <span className="crypto-testnet-lo-label">Par</span>
                      <span className="crypto-testnet-lo-value">{lastOrder.symbol}</span>
                    </div>
                    {lastOrder.price != null ? (
                      <div>
                        <span className="crypto-testnet-lo-label">Precio límite</span>
                        <span className="crypto-testnet-lo-value">{fmtNum(lastOrder.price)} USDT</span>
                      </div>
                    ) : null}
                    <div>
                      <span className="crypto-testnet-lo-label">Cantidad</span>
                      <span className="crypto-testnet-lo-value">
                        {fmtNum(lastOrder.amount ?? lastOrder.filled)}
                      </span>
                    </div>
                    <div>
                      <span className="crypto-testnet-lo-label">Cost / notional</span>
                      <span className="crypto-testnet-lo-value">{fmtNum(lastOrder.cost)} USDT</span>
                    </div>
                    <div>
                      <span className="crypto-testnet-lo-label">Precio medio</span>
                      <span className="crypto-testnet-lo-value">{fmtNum(lastOrder.average)}</span>
                    </div>
                    <div>
                      <span className="crypto-testnet-lo-label">Estado</span>
                      <span className="crypto-testnet-lo-value">{lastOrder.status ?? "—"}</span>
                    </div>
                    <div>
                      <span className="crypto-testnet-lo-label">Hora</span>
                      <span className="crypto-testnet-lo-value">{fmtExchangeMs(lastOrder.timestamp)}</span>
                    </div>
                  </div>
                </div>
              ) : (
                <p className="msg-muted" style={{ margin: 0, fontSize: "0.875rem" }}>
                  Cuando envíes una orden aparece el resumen acá.
                </p>
              )}
            </div>
          </section>
        </>
      ) : null}

      </div>
      ) : null}

      {activeTestnetModule === "position" ? (
      <div className="crypto-testnet-module" id="crypto-testnet-module-position" role="tabpanel">
        <TestnetModuleHeader
          title="Posición Testnet"
          lead="PnL desde órdenes registradas por la app. Venta directa con confirmación o precarga en Operar."
        />
        <TestnetAppPositionsCard
          payload={appPositionsPayload}
          error={appPositionsError}
          loading={appPositionsLoading}
          tab={appPositionsTab}
          onTabChange={setAppPositionsTab}
          onRefresh={() => void loadAppPositions()}
          connected={connected}
          lookupFreeBase={lookupFreeBaseForAsset}
          onSell={handleSellFromAppPosition}
          sellBusySymbol={appPositionSellBusy}
          feedbackMessage={appPositionFeedbackMessage}
          feedbackError={appPositionFeedbackError}
          onOpenManualSell={openOperateWithSell}
          exitEvalBySymbol={exitEvalBySymbol}
        />
      </div>
      ) : null}

      {activeTestnetModule === "orders" ? (
      <div className="crypto-testnet-module" id="crypto-testnet-module-orders" role="tabpanel">
        <TestnetModuleHeader
          title="Órdenes / Historial"
          lead="Órdenes LIMIT pendientes en testnet e historial local de la app."
        />

      {balances ? (
        <section className="card crypto-testnet-section">
          <div className="crypto-testnet-section-head">
            <div>
              <h3 className="dashboard-section-title crypto-testnet-section-title" style={{ margin: 0 }}>
                Órdenes abiertas Testnet
              </h3>
              <p className="msg-muted" style={{ margin: "0.35rem 0 0", fontSize: "0.82rem" }}>
                Esta sección muestra órdenes <strong>LIMIT</strong> pendientes. Las órdenes{" "}
                <strong>MARKET</strong> ejecutadas aparecen en <strong>Historial</strong> y el módulo{" "}
                <strong>Posición</strong>.
              </p>
            </div>
            <div className="crypto-testnet-toolbar">
              <button type="button" className="radar-refresh-btn" onClick={() => void loadOpenOrders()} disabled={openOrdersLoading}>
                {openOrdersLoading ? "Refrescando…" : "Refrescar órdenes abiertas"}
              </button>
              <CryptoRefreshBadge active={openOrdersLoading} label="Órdenes abiertas…" />
            </div>
          </div>
          {openOrdersError ? <p className="msg-error">{openOrdersError}</p> : null}
          {cancelOpenOrderError ? (
            <p className="msg-error" style={{ fontSize: "0.875rem", marginTop: "0.5rem" }}>
              {cancelOpenOrderError}
            </p>
          ) : null}
          {cancelOpenOrderMessage ? (
            <p className="msg-muted" style={{ fontSize: "0.875rem", marginTop: "0.5rem", color: "var(--success, #16a34a)" }}>
              {cancelOpenOrderMessage}
            </p>
          ) : null}
          {openOrdersPayload?.ok ? (
            openOrdersPayload.orders.length === 0 ? (
              <div className="crypto-testnet-empty-panel" role="status">
                Sin órdenes abiertas en testnet.
              </div>
            ) : (
              <div className="table-wrap">
                <table className="crypto-testnet-table">
                  <thead>
                    <tr>
                      <th>Fecha</th>
                      <th>Símbolo</th>
                      <th>Lado</th>
                      <th>Tipo</th>
                      <th className="crypto-testnet-num">Precio</th>
                      <th className="crypto-testnet-num">Cantidad</th>
                      <th className="crypto-testnet-num">Ejecutado</th>
                      <th className="crypto-testnet-num">Pendiente</th>
                      <th>Estado</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {openOrdersPayload.orders.map((r, idx) => (
                      <tr key={`${String(r.order_id)}-${r.symbol}-${idx}`}>
                        <td style={{ whiteSpace: "nowrap", fontSize: "0.82rem" }}>{fmtExchangeMs(r.timestamp)}</td>
                        <td>{r.symbol}</td>
                        <td>{sideHistoryLabel(r.side)}</td>
                        <td>{r.type ?? "—"}</td>
                        <td className="crypto-testnet-num">{fmtNum(r.price)}</td>
                        <td className="crypto-testnet-num">{fmtNum(r.amount)}</td>
                        <td className="crypto-testnet-num">{fmtNum(r.filled)}</td>
                        <td className="crypto-testnet-num">{fmtNum(r.remaining)}</td>
                        <td>{r.status}</td>
                        <td>
                          {r.order_id != null ? (
                            <button
                              type="button"
                              className="radar-refresh-btn"
                              style={{ fontSize: "0.78rem", padding: "0.2rem 0.5rem" }}
                              disabled={
                                !connected ||
                                openOrdersLoading ||
                                cancelOpenOrderKey === `${r.symbol}-${String(r.order_id)}`
                              }
                              onClick={() => void handleCancelOpenOrder(r)}
                            >
                              {cancelOpenOrderKey === `${r.symbol}-${String(r.order_id)}`
                                ? "Cancelando…"
                                : "Cancelar"}
                            </button>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          ) : openOrdersPayload && !openOrdersPayload.ok ? (
            <p className="msg-error" style={{ margin: "0.5rem 0 0", fontSize: "0.875rem" }}>
              {openOrdersPayload.error ?? "No se pudieron leer órdenes abiertas"}
            </p>
          ) : balances.ok && !openOrdersError ? (
            <p className="msg-muted" style={{ margin: "0.5rem 0 0", fontSize: "0.88rem" }}>
              Refrescá datos o el botón para cargar órdenes abiertas desde testnet.
            </p>
          ) : null}
        </section>
      ) : null}

      {/* 6 — Historial local */}
      {connected ? (
        <section className="card crypto-testnet-section">
          <div className="crypto-testnet-section-head">
            <div>
              <h3 className="dashboard-section-title crypto-testnet-section-title" style={{ margin: 0 }}>
                Historial local
              </h3>
              <p className="msg-muted" style={{ margin: "0.35rem 0 0", fontSize: "0.82rem" }}>
                Órdenes que esta app registró en disco ({ordersTotal} en archivo). Mostrando las últimas {recentOrders.length}.
                No es el libro completo de Binance.
              </p>
            </div>
            <div className="crypto-testnet-toolbar">
              <button type="button" className="radar-refresh-btn" onClick={() => void loadOrders()} disabled={ordersLoading}>
                {ordersLoading ? "Refrescando…" : "Refrescar historial"}
              </button>
              <button
                type="button"
                className="radar-refresh-btn"
                onClick={() => void handleSyncOrderHistory()}
                disabled={ordersLoading || syncHistoryBusy || !connected}
                title="Consulta Binance Spot Testnet y actualiza órdenes LIMIT abiertas en el historial local (no envía ni cancela órdenes)."
              >
                {syncHistoryBusy ? "Sincronizando…" : "Sincronizar estado"}
              </button>
              <CryptoRefreshBadge active={ordersLoading || syncHistoryBusy} />
            </div>
          </div>
          {syncHistoryMessage ? (
            <p className="msg-muted crypto-testnet-block-start" style={{ fontSize: "0.875rem", margin: 0 }}>
              {syncHistoryMessage}
            </p>
          ) : null}
          {syncHistoryError ? (
            <p className="msg-error crypto-testnet-block-start" style={{ fontSize: "0.875rem", margin: 0 }}>
              {syncHistoryError}
            </p>
          ) : null}
          {ordersError ? <p className="msg-error">{ordersError}</p> : null}
          {recentOrders.length > 0 ? (
            <div className="table-wrap">
              <table className="crypto-testnet-table">
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>Tipo orden</th>
                    <th>Lado</th>
                    <th>Símbolo</th>
                    <th className="crypto-testnet-num">Cantidad</th>
                    <th className="crypto-testnet-num">Ejecutado</th>
                    <th className="crypto-testnet-num">Pendiente</th>
                    <th className="crypto-testnet-num">Cost</th>
                    <th className="crypto-testnet-num">Avg</th>
                    <th>Estado</th>
                  </tr>
                </thead>
                <tbody>
                  {recentOrders.map((row, idx) => (
                    <tr key={`${row.created_at}-${String(row.order_id)}-${idx}`}>
                      <td style={{ whiteSpace: "nowrap", fontSize: "0.82rem" }}>{fmtIsoLocalShort(row.created_at)}</td>
                      <td>{orderTypeLabel(row)}</td>
                      <td>{sideHistoryLabel(row.side)}</td>
                      <td>{row.symbol ?? "—"}</td>
                      <td className="crypto-testnet-num">{fmtNum(row.amount)}</td>
                      <td className="crypto-testnet-num">{fmtNum(row.filled)}</td>
                      <td className="crypto-testnet-num">{fmtNum(row.remaining)}</td>
                      <td className="crypto-testnet-num">{fmtNum(row.cost)}</td>
                      <td className="crypto-testnet-num">{fmtNum(row.average)}</td>
                      <td>{row.status ?? row.raw_status ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : ordersLoading ? (
            <p className="msg-muted" style={{ margin: 0 }}>
              Cargando…
            </p>
          ) : (
            <p className="msg-muted" style={{ margin: 0 }}>
              Sin órdenes registradas en local.
            </p>
          )}
        </section>
      ) : null}
      </div>
      ) : null}
    </div>
  );
}
