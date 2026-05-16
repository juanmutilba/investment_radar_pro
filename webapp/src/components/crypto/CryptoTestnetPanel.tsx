import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { CycleDiagnosticsPanel } from "@/components/crypto/CycleDiagnosticsPanel";
import { CryptoTimeframeField } from "@/components/crypto/CryptoTimeframeField";
import { normalizeTimeframeString } from "@/components/crypto/cryptoTimeframe";
import {
  getCryptoTestnetBalances,
  getCryptoTestnetMonitorCycles,
  getCryptoTestnetMonitorStatus,
  getCryptoTestnetOpenOrders,
  getCryptoTestnetOrders,
  getCryptoTestnetPositions,
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
  type CryptoTestnetBalancesPayload,
  type CryptoTestnetEvaluatedRow,
  type CryptoTestnetExitProposal,
  type CryptoTestnetMarketOrderRow,
  type CryptoTestnetMonitorCycleRow,
  type CryptoTestnetMonitorStatusPayload,
  type CryptoTestnetOpenOrdersPayload,
  type CryptoTestnetPositionsPayload,
  type CryptoTestnetProposeEntryPayload,
  type CryptoTestnetProposeExitsPayload,
  type CryptoTestnetStoredOrder,
  type CryptoTestnetStatusPayload,
  type CryptoTestnetStrategyProposal,
} from "@/services/api";

const HIGHLIGHT_ASSETS = ["BTC", "ETH", "SOL", "BNB", "USDT"] as const;
const ASSET_SORT_TIER: Record<string, number> = { BTC: 0, ETH: 1, SOL: 2, BNB: 3, USDT: 4 };
const PAIR_FOR_BASE: Record<string, string> = {
  BTC: "BTC/USDT",
  ETH: "ETH/USDT",
  SOL: "SOL/USDT",
  BNB: "BNB/USDT",
};
const TESTNET_WHITELIST_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"] as const;
const MAX_TESTNET_ORDER_USDT = 25;
const MIN_TESTNET_ORDER_USDT = 0.01;
const SMALL_USDT_WARN = 5;
const PROPOSAL_PREFILL_MESSAGE =
  "Propuesta cargada en el formulario. Revisá y confirmá manualmente.";

const TESTNET_PANEL_SECTIONS = [
  { id: "crypto-testnet-section-status", label: "Estado" },
  { id: "crypto-testnet-section-operate", label: "Operar" },
  { id: "crypto-testnet-section-proposals", label: "Propuestas" },
  { id: "crypto-testnet-section-monitor", label: "Monitor" },
  { id: "crypto-testnet-section-orders", label: "Órdenes" },
] as const;

type TestnetPanelGroupKey = "status" | "operate" | "proposals" | "monitor" | "orders";

type TestnetCollapsedGroups = Record<TestnetPanelGroupKey, boolean>;

function defaultTestnetCollapsedGroups(monitorRunning: boolean): TestnetCollapsedGroups {
  return {
    status: false,
    operate: false,
    proposals: false,
    monitor: !monitorRunning,
    orders: false,
  };
}

function TestnetPanelGroup({
  sectionId,
  orderClassName,
  title,
  lead,
  collapsed,
  onToggle,
  groupKey,
  children,
}: {
  sectionId: string;
  orderClassName: string;
  title: string;
  lead: string;
  collapsed: boolean;
  onToggle: (key: TestnetPanelGroupKey) => void;
  groupKey: TestnetPanelGroupKey;
  children: ReactNode;
}) {
  return (
    <div
      id={sectionId}
      className={`crypto-testnet-group ${orderClassName}${collapsed ? " crypto-testnet-group--collapsed" : ""}`}
    >
      <header className="crypto-testnet-group-header crypto-testnet-group-header--collapsible">
        <div className="crypto-testnet-group-header-text">
          <h2 className="crypto-testnet-group-title">{title}</h2>
          <p className="crypto-testnet-group-lead msg-muted">{lead}</p>
        </div>
        <button
          type="button"
          className="crypto-testnet-group-toggle radar-refresh-btn"
          onClick={() => onToggle(groupKey)}
          aria-expanded={!collapsed}
          aria-controls={`${sectionId}-body`}
        >
          {collapsed ? "Mostrar" : "Ocultar"}
        </button>
      </header>
      {!collapsed ? (
        <div id={`${sectionId}-body`} className="crypto-testnet-group-body">
          {children}
        </div>
      ) : null}
    </div>
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
      value: `${MAX_TESTNET_ORDER_USDT} USDT`,
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
  if (lower.includes("notional") || lower.includes("-1013")) {
    return "La orden es demasiado chica para Binance.";
  }
  if (s.length > 320) return `${s.slice(0, 320)}…`;
  return s;
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

function assistedPrimaryReasonLabel(code: string | null | undefined): string {
  if (!code) return "Sin propuesta en esta búsqueda.";
  const labels: Record<string, string> = {
    no_opportunity: "No hay candidatos con señal compra_potencial en la watchlist.",
    testnet_balances_unavailable:
      "No se pudieron leer balances testnet: revisá credenciales, BINANCE_TESTNET_ENABLED y pulsá Refrescar datos.",
    max_open_positions:
      "Hay candidatos, pero no entra uno nuevo: ya alcanzaste el máximo de posiciones testnet permitido (activos con saldo).",
    no_entry: "Ningún candidato pasó todos los filtros de entrada.",
    score_below_min: "Hay candidatos, pero el score quedó por debajo del mínimo configurado.",
    btc_trend_filter: "Hay candidatos, pero el filtro de tendencia BTC los descartó.",
    cooldown_symbol:
      "Hay candidatos en cooldown según el historial local de órdenes testnet guardado por esta app.",
    already_hold_base_testnet: "Ya tenés saldo libre del activo en testnet (no se propone duplicar).",
    not_whitelisted_testnet: "El candidato no está en la whitelist testnet de esta app.",
  };
  return labels[code] ?? `Motivo: ${code}`;
}

function monitorCycleReasonLabel(row: CryptoTestnetMonitorCycleRow): string {
  if (row.entry_proposal_generated && row.entry_proposal?.symbol) {
    return `Entrada: ${row.entry_proposal.symbol}`;
  }
  if (row.entry_proposal_generated) {
    return "Entrada propuesta";
  }
  const entryR = row.no_entry_reason;
  if (entryR) return assistedPrimaryReasonLabel(entryR);
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

function exitProposalReasonLabel(reason: string | null | undefined): string {
  if (!reason) return "—";
  const labels: Record<string, string> = {
    stop_loss: "Stop loss",
    take_profit: "Take profit",
    trailing_stop: "Trailing stop",
    missing_local_entry:
      "Sin base de compras local clara: operaste fuera de esta app, faltan datos de costo en el historial o el saldo no coincide con BUY/SELL guardados.",
    no_free_base: "Sin saldo libre para vender.",
    no_price: "Precio USDT no disponible.",
    below_min_value: "Valor posición por debajo del mínimo USDT configurado.",
    inside_sl_tp_band: "Dentro de SL/TP y por encima del trailing; no se propone venta.",
    no_symbol: "Par no disponible.",
  };
  return labels[reason] ?? reason;
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
  approxUsdt: number | null;
  pair: string | null;
  highlight: boolean;
};

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
  const manualOrderSectionRef = useRef<HTMLElement | null>(null);
  const [lastOrder, setLastOrder] = useState<CryptoTestnetMarketOrderRow | null>(null);
  const [recentOrders, setRecentOrders] = useState<CryptoTestnetStoredOrder[]>([]);
  const [ordersTotal, setOrdersTotal] = useState(0);
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [ordersError, setOrdersError] = useState<string | null>(null);
  const [syncHistoryBusy, setSyncHistoryBusy] = useState(false);
  const [syncHistoryMessage, setSyncHistoryMessage] = useState<string | null>(null);
  const [syncHistoryError, setSyncHistoryError] = useState<string | null>(null);
  const [positionsPayload, setPositionsPayload] = useState<CryptoTestnetPositionsPayload | null>(null);
  const [positionsError, setPositionsError] = useState<string | null>(null);
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
  const [assistTf, setAssistTf] = useState("1h");
  const [assistQuote, setAssistQuote] = useState("10");
  const [assistMaxOpen, setAssistMaxOpen] = useState("3");
  const [assistCooldown, setAssistCooldown] = useState("0");
  const [assistBtcTrend, setAssistBtcTrend] = useState(false);
  const [assistMinScore, setAssistMinScore] = useState("0");
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
  const [collapsedGroups, setCollapsedGroups] = useState<TestnetCollapsedGroups>(() =>
    defaultTestnetCollapsedGroups(false),
  );
  const monitorCollapseInitRef = useRef(false);
  const [monitorIntervalMin, setMonitorIntervalMin] = useState("5");
  const [monTf, setMonTf] = useState("1h");
  const [monQuote, setMonQuote] = useState("10");
  const [monMaxOpen, setMonMaxOpen] = useState("3");
  const [monCooldown, setMonCooldown] = useState("0");
  const [monBtcTrend, setMonBtcTrend] = useState(false);
  const [monMinScore, setMonMinScore] = useState("0");
  const [monSl, setMonSl] = useState("2");
  const [monTp, setMonTp] = useState("4");
  const [monTrail, setMonTrail] = useState("");
  const [monBeTrig, setMonBeTrig] = useState("0");
  const [monBePlus, setMonBePlus] = useState("0");
  const [monExitMin, setMonExitMin] = useState("5");

  const monInputsLocked = Boolean(monitorStatus?.enabled);

  const prefillQuickSell = useCallback((pair: string | null | undefined) => {
    const p = (pair ?? "").trim();
    if (!p) return;
    setManualSymbol(p);
    setManualSide("sell");
    setSellMode("quote");
    setOrderFormError(null);
  }, []);

  const scrollToManualOrderForm = useCallback(() => {
    const el = manualOrderSectionRef.current ?? document.getElementById("crypto-testnet-manual-order");
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  const scrollToTestnetSection = useCallback((sectionId: string) => {
    document.getElementById(sectionId)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  const applyEntryProposalToManualForm = useCallback(
    (proposal: CryptoTestnetStrategyProposal) => {
      const sym = proposal.symbol?.trim();
      if (!sym) return;
      setManualSymbol(sym);
      setManualSide("buy");
      setManualOrderType("market");
      const q = proposal.quote_amount_usdt;
      if (typeof q === "number" && Number.isFinite(q) && q > 0) {
        setManualQuoteUsdt(String(q));
      }
      setOrderFormError(null);
      setProposalPrefillMessage(PROPOSAL_PREFILL_MESSAGE);
      window.requestAnimationFrame(() => scrollToManualOrderForm());
    },
    [scrollToManualOrderForm],
  );

  const applyExitProposalToManualForm = useCallback(
    (prop: CryptoTestnetExitProposal) => {
      const sym = prop.symbol?.trim();
      if (!sym) return;
      setManualSymbol(sym);
      setManualSide("sell");
      setManualOrderType("market");
      const base = prop.amount_base;
      if (typeof base === "number" && Number.isFinite(base) && base > 0) {
        setSellMode("advanced");
        const qty = formatBaseQtyForInput(base);
        if (qty) setManualAmountBase(qty);
      } else {
        const sq = prop.sell_quote_amount_usdt;
        if (typeof sq === "number" && Number.isFinite(sq) && sq > 0) {
          setSellMode("quote");
          setManualSellQuoteUsdt(String(sq));
        }
      }
      setOrderFormError(null);
      setProposalPrefillMessage(PROPOSAL_PREFILL_MESSAGE);
      window.requestAnimationFrame(() => scrollToManualOrderForm());
    },
    [scrollToManualOrderForm],
  );

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
      const [rb, rp, ro] = await Promise.allSettled([
        getCryptoTestnetBalances(),
        getCryptoTestnetPositions(),
        getCryptoTestnetOpenOrders(),
      ]);
      if (rb.status !== "fulfilled") throw rb.reason;
      const b = rb.value;
      setBalances(b);
      if (rp.status === "fulfilled") {
        setPositionsPayload(rp.value);
        setPositionsError(null);
      } else {
        setPositionsPayload(null);
        setPositionsError(rp.reason instanceof Error ? rp.reason.message : "Error al leer posiciones testnet");
      }
      if (ro.status === "fulfilled") {
        setOpenOrdersPayload(ro.value);
        setOpenOrdersError(null);
      } else {
        setOpenOrdersPayload(null);
        setOpenOrdersError(
          ro.reason instanceof Error ? ro.reason.message : "Error al leer órdenes abiertas testnet",
        );
      }
      const entries = await Promise.all(
        [...TESTNET_WHITELIST_SYMBOLS].map(async (sym) => {
          try {
            const t = await getCryptoTestnetTicker(sym);
            const last = t.last;
            const px = typeof last === "number" && Number.isFinite(last) && last > 0 ? last : null;
            return [sym, px] as const;
          } catch {
            return [sym, null] as const;
          }
        }),
      );
      const map: Record<string, number | null> = {};
      for (const [sym, px] of entries) map[sym] = px;
      setPriceByPair(map);
      setBalancesUpdatedAt(new Date().toISOString());
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error al leer balances testnet");
      setPositionsPayload(null);
      setPositionsError(null);
      setOpenOrdersPayload(null);
      setOpenOrdersError(null);
    } finally {
      setBalancesLoading(false);
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

  const loadMonitorStatus = useCallback(async () => {
    setMonitorStatusLoading(true);
    try {
      const m = await getCryptoTestnetMonitorStatus();
      setMonitorStatus(m);
      setMonitorBannerError(null);
    } catch (e: unknown) {
      setMonitorBannerError(e instanceof Error ? e.message : "Error al leer monitor testnet");
    } finally {
      setMonitorStatusLoading(false);
    }
  }, []);

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

  useEffect(() => {
    if (connected) void loadOrders();
  }, [connected, loadOrders]);

  useEffect(() => {
    if (connected) void loadBalances();
  }, [connected, loadBalances]);

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
        rows.push({ asset, free: row.free, approxUsdt: row.free, pair: null, highlight: true });
        continue;
      }
      const pair = PAIR_FOR_BASE[asset] ?? null;
      const px = pair ? priceByPair[pair] ?? null : null;
      const approx = px !== null ? row.free * px : null;
      if (approx !== null) totalApprox += approx;
      rows.push({ asset, free: row.free, approxUsdt: approx, pair, highlight });
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
      if (!connected || !manualSymbol.trim()) return;
      const symTrim = manualSymbol.trim();

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
        if (notional > MAX_TESTNET_ORDER_USDT + 1e-9) {
          setOrderFormError(`El notional (cantidad × precio) no puede superar ${MAX_TESTNET_ORDER_USDT} USDT.`);
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
          await Promise.all([loadBalances(), loadOrders(), loadOpenOrders()]);
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
          setOrderFormError(`Ingresá un monto USDT válido (mín. ${MIN_TESTNET_ORDER_USDT}).`);
          return;
        }
        if (q > MAX_TESTNET_ORDER_USDT + 1e-9) {
          setOrderFormError(`El monto no puede superar ${MAX_TESTNET_ORDER_USDT} USDT.`);
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
        if (sq > MAX_TESTNET_ORDER_USDT + 1e-9) {
          setOrderFormError(`El monto no puede superar ${MAX_TESTNET_ORDER_USDT} USDT.`);
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
        const res =
          manualSide === "buy"
            ? await postCryptoTestnetMarketOrder({
                symbol: symTrim,
                side: "buy",
                quote_amount_usdt: Number.parseFloat(manualQuoteUsdt.replace(",", ".")),
              })
            : sellMode === "quote"
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
        setOrderSuccessMessage("Orden MARKET enviada/ejecutada en Binance Spot Testnet.");
        await Promise.all([loadBalances(), loadOrders(), loadOpenOrders()]);
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
      pairPrice,
      sellMode,
      loadBalances,
      loadOpenOrders,
      loadOrders,
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
      const payload = await postCryptoTestnetProposeEntry({
        timeframe: normalizeTimeframeString(assistTf),
        limit: 200,
        quote_amount_usdt: Number.isFinite(q) && q > 0 ? Math.min(q, MAX_TESTNET_ORDER_USDT) : 10,
        max_open_positions: Number.isFinite(mo) && mo >= 1 ? mo : 3,
        cooldown_minutes: Number.isFinite(cd) && cd >= 0 ? cd : 0,
        require_btc_trend_up: assistBtcTrend,
        min_entry_score: Number.isFinite(ms) && ms >= 0 ? ms : 0,
      });
      setAssistedPayload(payload);
    } catch (e: unknown) {
      setAssistedError(e instanceof Error ? e.message : "Error al buscar propuesta");
      setAssistedPayload(null);
    } finally {
      setAssistedLoading(false);
    }
  }, [assistTf, assistQuote, assistMaxOpen, assistCooldown, assistBtcTrend, assistMinScore]);

  const handleAssistedConfirmBuy = useCallback(async () => {
    const p = assistedPayload?.proposal;
    if (!p || !connected) return;
    setAssistedConfirmBusy(true);
    setOrderFormError(null);
    try {
      const res = await postCryptoTestnetMarketOrder({
        symbol: p.symbol.trim(),
        side: "buy",
        quote_amount_usdt: p.quote_amount_usdt,
      });
      if (res.order) setLastOrder(res.order);
      setManualSymbol(p.symbol.trim());
      setManualSide("buy");
      await Promise.all([loadBalances(), loadOrders()]);
      setAssistedPayload(null);
      setError(null);
    } catch (e: unknown) {
      setOrderFormError(humanizeTestnetOrderError(e instanceof Error ? e.message : "Error al enviar orden testnet"));
    } finally {
      setAssistedConfirmBusy(false);
    }
  }, [assistedPayload, connected, loadBalances, loadOrders]);

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
      if (!connected) return;
      setExitConfirmAsset(prop.asset);
      setOrderFormError(null);
      try {
        await postCryptoTestnetMarketOrder({
          symbol: prop.symbol.trim(),
          side: "sell",
          amount_base: prop.amount_base,
        });
        setManualSymbol(prop.symbol.trim());
        setManualSide("sell");
        await Promise.all([loadBalances(), loadOrders()]);
        setError(null);
        setExitConfirmAsset(null);
        await handleExitAssistSearch();
      } catch (e: unknown) {
        setOrderFormError(humanizeTestnetOrderError(e instanceof Error ? e.message : "Error al enviar venta testnet"));
        setExitConfirmAsset(null);
      }
    },
    [connected, loadBalances, loadOrders, handleExitAssistSearch],
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
        quote_amount_usdt: Number.isFinite(q) && q > 0 ? Math.min(q, MAX_TESTNET_ORDER_USDT) : 10,
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
    if (!p || !connected) return;
    setMonitorConfirmBuyBusy(true);
    setOrderFormError(null);
    try {
      const res = await postCryptoTestnetMarketOrder({
        symbol: p.symbol.trim(),
        side: "buy",
        quote_amount_usdt: p.quote_amount_usdt,
      });
      if (res.order) setLastOrder(res.order);
      setManualSymbol(p.symbol.trim());
      setManualSide("buy");
      await Promise.all([loadBalances(), loadOrders(), loadMonitorStatus()]);
      setError(null);
    } catch (e: unknown) {
      setOrderFormError(humanizeTestnetOrderError(e instanceof Error ? e.message : "Error al enviar orden testnet"));
    } finally {
      setMonitorConfirmBuyBusy(false);
    }
  }, [monitorStatus?.last_entry_proposal, connected, loadBalances, loadOrders, loadMonitorStatus]);

  const handleMonitorConfirmSell = useCallback(
    async (prop: CryptoTestnetExitProposal) => {
      if (!connected) return;
      setMonitorSellBusyAsset(prop.asset);
      setOrderFormError(null);
      try {
        await postCryptoTestnetMarketOrder({
          symbol: prop.symbol.trim(),
          side: "sell",
          amount_base: prop.amount_base,
        });
        setManualSymbol(prop.symbol.trim());
        setManualSide("sell");
        await Promise.all([loadBalances(), loadOrders(), loadMonitorStatus()]);
        setError(null);
      } catch (e: unknown) {
        setOrderFormError(humanizeTestnetOrderError(e instanceof Error ? e.message : "Error al enviar venta testnet"));
      } finally {
        setMonitorSellBusyAsset(null);
      }
    },
    [connected, loadBalances, loadOrders, loadMonitorStatus],
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
  }, [loadBalances, loadOrders, connected]);

  const toggleTestnetGroup = useCallback((key: TestnetPanelGroupKey) => {
    setCollapsedGroups((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  useEffect(() => {
    if (monitorCollapseInitRef.current || monitorStatus == null) return;
    monitorCollapseInitRef.current = true;
    setCollapsedGroups((prev) => ({
      ...prev,
      monitor: !monitorStatus.running,
    }));
  }, [monitorStatus]);

  return (
    <div className="crypto-testnet-dashboard">
      <div className="crypto-testnet-page-banner" role="note">
        <strong>Spot Testnet Binance:</strong> saldo ficticio en la red oficial de pruebas; las órdenes son reales sólo
        contra ese sandbox (no contra tu cuenta spot real). Distinto del tab <strong>Bot (Simulador)</strong>, que es
        paper interno de la app.
      </div>

      <nav className="crypto-testnet-panel-nav" aria-label="Navegación del panel testnet">
        {TESTNET_PANEL_SECTIONS.map((item) => (
          <button
            key={item.id}
            type="button"
            className="crypto-testnet-panel-nav-link"
            onClick={() => scrollToTestnetSection(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <TestnetPanelGroup
        groupKey="status"
        sectionId="crypto-testnet-section-status"
        orderClassName="crypto-testnet-group--status"
        title="Estado y seguridad"
        lead="Conexión testnet, checklist de seguridad y resumen de cartera."
        collapsed={collapsedGroups.status}
        onToggle={toggleTestnetGroup}
      >
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

      <section className="card crypto-testnet-section crypto-testnet-security-card crypto-testnet-section--nested">
        <div className="crypto-testnet-section-head">
          <h3 className="dashboard-section-title crypto-testnet-section-title" style={{ margin: 0 }}>
            Seguridad Testnet
          </h3>
          <span
            className={`crypto-side-badge ${testnetSecurityAllOk ? "crypto-side-badge--buy" : ""}`}
            style={testnetSecurityAllOk ? undefined : { borderColor: "rgba(217, 119, 6, 0.55)", color: "#d97706" }}
          >
            {testnetSecurityAllOk ? "Checks OK" : "Revisar"}
          </span>
        </div>
        <p className="msg-muted" style={{ margin: "0.4rem 0 0", fontSize: "0.78rem" }}>
          Garantías de diseño de este módulo. El entorno en vivo se confirma con el estado de conexión arriba.
        </p>
        <ul className="crypto-testnet-security-list" aria-label="Checklist de seguridad testnet">
          {testnetSecurityChecks.map((row) => (
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
      </section>

      {/* 2 — Cartera Testnet */}
      {balances ? (
        <section className="card crypto-testnet-section">
          <h3 className="dashboard-section-title crypto-testnet-section-title">Cartera Testnet</h3>
          <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.65rem", fontSize: "0.85rem" }}>
            Resumen orientativo (balances + últimos precios testnet para armar órdenes). El detalle en vivo está en{" "}
            <strong>Posiciones reales</strong>.
          </p>
          {!balances.ok ? (
            <p className="msg-error" style={{ fontSize: "0.875rem" }}>
              {balances.error ?? "No se pudieron leer balances"}
            </p>
          ) : portfolio ? (
            <div className="crypto-testnet-mini-grid">
              <div className="crypto-testnet-kpi crypto-testnet-kpi--accent">
                <span className="crypto-testnet-kpi-label">Total aproximado USDT</span>
                <span className="crypto-testnet-kpi-value">{fmtNum(portfolio.totalApprox)} USDT</span>
              </div>
              <div className="crypto-testnet-kpi">
                <span className="crypto-testnet-kpi-label">USDT libre</span>
                <span className="crypto-testnet-kpi-value">{fmtNum(portfolio.usdtFree)}</span>
              </div>
              <div className="crypto-testnet-kpi">
                <span className="crypto-testnet-kpi-label">Activos con saldo</span>
                <span className="crypto-testnet-kpi-value">{portfolio.assetWithBalanceCount}</span>
              </div>
              <div className="crypto-testnet-kpi">
                <span className="crypto-testnet-kpi-label">Última actualización</span>
                <span className="crypto-testnet-kpi-value" style={{ fontSize: "0.85rem", fontWeight: 500 }}>
                  {balancesUpdatedAt ? fmtIsoLocalShort(balancesUpdatedAt) : "—"}
                </span>
              </div>
            </div>
          ) : null}
        </section>
      ) : null}
      </TestnetPanelGroup>

      <TestnetPanelGroup
        groupKey="proposals"
        sectionId="crypto-testnet-section-proposals"
        orderClassName="crypto-testnet-group--proposals"
        title="Propuestas asistidas"
        lead="Búsqueda manual de entradas y salidas; confirmá o cargá el formulario con «Usar propuesta»."
        collapsed={collapsedGroups.proposals}
        onToggle={toggleTestnetGroup}
      >
      {/* Propuesta asistida Testnet (estrategia propone; orden sólo si confirmás) */}
      <section className="card crypto-testnet-section">
        <h3 className="dashboard-section-title crypto-testnet-section-title">Propuesta asistida Testnet</h3>
        <div className="crypto-testnet-note crypto-testnet-note--blue crypto-testnet-block-start">
          La estrategia <strong>solo propone</strong>. La orden testnet se envía únicamente si pulsás{" "}
          <strong>Enviar BUY Testnet</strong>. No hay ejecución automática desde esta búsqueda.
        </div>
        <p className="msg-muted" style={{ marginTop: "0.65rem", marginBottom: "0.65rem", fontSize: "0.85rem" }}>
          Usa el mismo scanner y filtros que el bot paper para elegir el mejor candidato, pero sin abrir posición paper ni
          enviar órdenes hasta que confirmes. Monto máximo por orden testnet: {MAX_TESTNET_ORDER_USDT} USDT (whitelist y
          límites del backend siguen aplicando).
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
              max={MAX_TESTNET_ORDER_USDT}
              step="0.01"
              value={assistQuote}
              onChange={(ev) => setAssistQuote(ev.target.value)}
              disabled={assistedLoading}
            />
          </label>
          <label className="crypto-testnet-field">
            <span className="msg-muted">Máx. posiciones abiertas</span>
            <input
              type="number"
              className="radar-input"
              min={1}
              max={20}
              step={1}
              value={assistMaxOpen}
              onChange={(ev) => setAssistMaxOpen(ev.target.value)}
              disabled={assistedLoading}
            />
          </label>
          <label className="crypto-testnet-field">
            <span className="msg-muted">Cooldown (min)</span>
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
            <span className="msg-muted">Score mínimo</span>
            <input
              type="number"
              className="radar-input"
              min={0}
              max={100}
              step="0.5"
              value={assistMinScore}
              onChange={(ev) => setAssistMinScore(ev.target.value)}
              disabled={assistedLoading}
            />
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
                </div>
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
                  <button
                    type="button"
                    className="radar-refresh-btn"
                    onClick={() => applyEntryProposalToManualForm(assistedPayload.proposal!)}
                    disabled={orderBusy}
                  >
                    Usar propuesta
                  </button>
                  <button
                    type="button"
                    className="radar-refresh-btn"
                    onClick={() => void handleAssistedConfirmBuy()}
                    disabled={!connected || assistedConfirmBusy || orderBusy}
                  >
                    {assistedConfirmBusy ? "Enviando…" : "Enviar BUY Testnet"}
                  </button>
                </div>
                {!connected ? (
                  <p className="msg-muted" style={{ marginTop: "0.5rem", fontSize: "0.82rem" }}>
                    Conectá testnet (estado arriba) para poder confirmar la compra.
                  </p>
                ) : null}
              </>
            ) : (
              <p className="msg-muted" style={{ margin: "0.5rem 0 0", fontSize: "0.88rem" }}>
                {assistedPrimaryReasonLabel(assistedPayload.primary_reason)}
              </p>
            )}
            {Array.isArray(assistedPayload.evaluated) && assistedPayload.evaluated.length > 0 ? (
              <details style={{ marginTop: "0.75rem", fontSize: "0.82rem" }}>
                <summary className="msg-muted" style={{ cursor: "pointer" }}>
                  Evaluados ({assistedPayload.evaluated.length})
                </summary>
                <ul className="msg-muted" style={{ margin: "0.5rem 0 0", paddingLeft: "1.1rem", maxHeight: "180px", overflow: "auto" }}>
                  {assistedPayload.evaluated.map((row: CryptoTestnetEvaluatedRow, idx: number) => (
                    <li key={`${row.symbol ?? "sym"}-${idx}`}>
                      {row.symbol ?? "—"} · {row.status} — {row.reason}
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
          <strong>Confirmar SELL Testnet</strong> en una fila. No hay liquidación automática.
        </div>
        <p className="msg-muted" style={{ marginTop: "0.65rem", marginBottom: "0.65rem", fontSize: "0.85rem" }}>
          El precio de entrada y el PnL % son <strong>aproximados</strong>: se reconstruyen sólo con el historial local{" "}
          <code style={{ fontSize: "0.8rem" }}>crypto_testnet_orders.json</code> (órdenes que esta app registró). Si compraste
          fuera de la app o falta datos de coste en una compra, verás{" "}
          <span className="msg-muted">missing_local_entry</span> en el detalle evaluado.
        </p>
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
            (configurable en la búsqueda). SL y TP siguen usando el historial local de compras.
          </p>
        ) : null}
        {exitAssistPayload?.ok && exitAssistPayload.proposals.length > 0 ? (
          <div className="crypto-testnet-block-start table-wrap" style={{ marginTop: "0.85rem" }}>
            <table className="crypto-testnet-table">
              <thead>
                <tr>
                  <th>Activo</th>
                  <th>Motivo</th>
                  <th className="crypto-testnet-num">Precio</th>
                  <th className="crypto-testnet-num">Máximo</th>
                  <th className="crypto-testnet-num">Trailing %</th>
                  <th className="crypto-testnet-num">Precio trail.</th>
                  <th className="crypto-testnet-num">PnL %</th>
                  <th className="crypto-testnet-num">Valor USDT</th>
                  <th className="crypto-testnet-num">Entrada ~</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {exitAssistPayload.proposals.map((row) => (
                  <tr key={row.asset}>
                    <td>{row.asset}</td>
                    <td>{exitProposalReasonLabel(row.exit_reason ?? row.reason)}</td>
                    <td className="crypto-testnet-num">
                      {fmtNum(row.current_price ?? row.current_price_usdt)}
                    </td>
                    <td className="crypto-testnet-num">{fmtNum(row.highest_price)}</td>
                    <td className="crypto-testnet-num">{fmtNum(row.trailing_stop_pct)}</td>
                    <td className="crypto-testnet-num">{fmtNum(row.trailing_stop_price)}</td>
                    <td className="crypto-testnet-num">
                      {row.pnl_pct != null && Number.isFinite(row.pnl_pct) ? numFmt4.format(row.pnl_pct) : "—"}
                    </td>
                    <td className="crypto-testnet-num">{fmtNum(row.value_usdt)}</td>
                    <td className="crypto-testnet-num">{fmtNum(row.avg_entry_usdt)}</td>
                    <td>
                      <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem", alignItems: "flex-start" }}>
                        <button
                          type="button"
                          className="radar-refresh-btn crypto-testnet-btn-compact"
                          onClick={() => applyExitProposalToManualForm(row)}
                          disabled={orderBusy}
                        >
                          Usar propuesta
                        </button>
                        <button
                          type="button"
                          className="radar-refresh-btn crypto-testnet-btn-compact"
                          onClick={() => void handleExitAssistConfirmSell(row)}
                          disabled={!connected || exitConfirmAsset !== null || orderBusy}
                        >
                          {exitConfirmAsset === row.asset ? "Enviando…" : "Confirmar SELL Testnet"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : exitAssistPayload?.ok && exitAssistPayload.proposals.length === 0 ? (
          <p className="msg-muted crypto-testnet-block-start" style={{ marginTop: "0.75rem", fontSize: "0.88rem" }}>
            No hay salidas propuestas con los umbrales actuales (o ninguna posición supera el valor mínimo). Revisá el detalle
            evaluado si esperabas una venta por SL/TP o trailing.
          </p>
        ) : null}
        {exitAssistPayload?.ok &&
        exitAssistPayload.evaluated.some((r) => r.reason === "missing_local_entry") ? (
          <p className="msg-muted crypto-testnet-block-start" style={{ marginTop: "0.65rem", fontSize: "0.82rem" }}>
            <strong>Aviso:</strong> en al menos un activo no pudimos cuadrar la entrada con el historial local de esta app.
            Operá manualmente o mantené las compras/registros sólo desde acá si querés salidas asistidas.
          </p>
        ) : null}
        {exitAssistPayload?.ok && exitAssistPayload.evaluated.length > 0 ? (
          <details style={{ marginTop: "0.85rem", fontSize: "0.82rem" }}>
            <summary className="msg-muted" style={{ cursor: "pointer" }}>
              Evaluados ({exitAssistPayload.evaluated.length})
            </summary>
            <ul className="msg-muted" style={{ margin: "0.5rem 0 0", paddingLeft: "1.1rem", maxHeight: "200px", overflow: "auto" }}>
              {exitAssistPayload.evaluated.map((ev, idx) => (
                <li key={`${ev.asset ?? "a"}-${ev.symbol ?? "s"}-${idx}`}>
                  {ev.asset ?? "—"} ({ev.symbol ?? "—"}) · {ev.status ?? "—"} — {exitProposalReasonLabel(ev.reason)}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </section>
      </TestnetPanelGroup>

      <TestnetPanelGroup
        groupKey="monitor"
        sectionId="crypto-testnet-section-monitor"
        orderClassName="crypto-testnet-group--monitor"
        title="Monitor asistido"
        lead="Ciclos periódicos de propuestas; historial en JSONL; sin órdenes automáticas."
        collapsed={collapsedGroups.monitor}
        onToggle={toggleTestnetGroup}
      >
      {/* Monitor asistido Testnet */}
      <section className="card crypto-testnet-section">
        <h3 className="dashboard-section-title crypto-testnet-section-title">Monitor asistido Testnet</h3>
        <div className="crypto-testnet-note crypto-testnet-note--blue crypto-testnet-block-start">
          El monitor <strong>solo busca</strong> entradas y salidas cada cierto intervalo.{" "}
          <strong>No envía órdenes sin confirmación:</strong> las órdenes siguen siendo sólo por los botones de confirmación o el formulario manual.
        </div>
        <div className="crypto-testnet-mini-grid crypto-testnet-mini-grid--dense crypto-testnet-block-start">
          <div className="crypto-testnet-kpi crypto-testnet-kpi--accent">
            <span className="crypto-testnet-kpi-label">Estado</span>
            <span className="crypto-testnet-kpi-value">{monitorPhaseLabel}</span>
          </div>
          <div className="crypto-testnet-kpi">
            <span className="crypto-testnet-kpi-label">Intervalo</span>
            <span className="crypto-testnet-kpi-value">
              {monitorStatus?.interval_seconds != null
                ? `${Math.round(monitorStatus.interval_seconds / 60)} min`
                : "—"}
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
        </div>
        <div
          className="crypto-testnet-mini-grid crypto-testnet-mini-grid--dense"
          style={{ marginTop: "0.65rem" }}
        >
          <div className="crypto-testnet-kpi">
            <span className="crypto-testnet-kpi-label">Watchlist (Testnet scan)</span>
            <span className="crypto-testnet-kpi-value">{monitorStatus?.last_watchlist_count ?? "—"}</span>
          </div>
          <div className="crypto-testnet-kpi">
            <span className="crypto-testnet-kpi-label">Símbolos escaneados</span>
            <span className="crypto-testnet-kpi-value">{monitorStatus?.last_scan_count ?? "—"}</span>
          </div>
          <div className="crypto-testnet-kpi">
            <span className="crypto-testnet-kpi-label">Candidatos señal</span>
            <span className="crypto-testnet-kpi-value">{monitorStatus?.last_candidates_count ?? "—"}</span>
          </div>
          <div className="crypto-testnet-kpi">
            <span className="crypto-testnet-kpi-label">Propuesta entrada</span>
            <span className="crypto-testnet-kpi-value">
              {monitorStatus?.last_run_at == null
                ? "—"
                : monitorStatus?.last_entry_proposal_generated
                  ? "Sí"
                  : "No"}
            </span>
          </div>
          <div className="crypto-testnet-kpi">
            <span className="crypto-testnet-kpi-label">Propuestas salida</span>
            <span className="crypto-testnet-kpi-value">
              {monitorStatus?.last_run_at == null ? "—" : monitorStatus?.last_exit_proposals_count ?? 0}
            </span>
          </div>
          <div className="crypto-testnet-kpi">
            <span className="crypto-testnet-kpi-label">Sin propuesta entrada</span>
            <span
              className="crypto-testnet-kpi-value"
              style={{ fontSize: "0.78rem", fontWeight: 500 }}
              title={monitorStatus?.last_no_entry_reason ?? undefined}
            >
              {monitorStatus?.last_run_at == null
                ? "—"
                : monitorStatus?.last_entry_proposal_generated
                  ? "—"
                  : assistedPrimaryReasonLabel(monitorStatus?.last_no_entry_reason)}
            </span>
          </div>
        </div>
        {monitorStatus?.last_error ? (
          <p className="msg-error crypto-testnet-block-start" style={{ fontSize: "0.875rem", marginTop: "0.65rem" }}>
            Último error monitor: {monitorStatus.last_error}
          </p>
        ) : null}
        {monitorBannerError ? (
          <p className="msg-error crypto-testnet-block-start" style={{ fontSize: "0.875rem", marginTop: "0.5rem" }}>
            {monitorBannerError}
          </p>
        ) : null}

        <CycleDiagnosticsPanel
          startedAt={monitorStatus?.last_cycle_started_at}
          finishedAt={monitorStatus?.last_cycle_finished_at}
          durationMs={monitorStatus?.last_cycle_duration_ms}
          primaryReason={monitorStatus?.last_primary_reason ?? monitorStatus?.last_entry_primary_reason}
          summary={monitorStatus?.last_cycle_summary}
          lastScanDebug={monitorStatus?.last_scan_debug}
          bestRejected={monitorStatus?.best_rejected_candidate}
          entryCandidate={monitorStatus?.last_entry_candidate}
          primaryReasonLabel={assistedPrimaryReasonLabel}
          emptyHint="Sin datos de ciclo todavía. Iniciá el monitor Testnet y esperá la primera revisión (solo propuestas; sin órdenes automáticas)."
        />

        <div className="crypto-testnet-toolbar crypto-testnet-block-start" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
          <button
            type="button"
            className="radar-refresh-btn"
            onClick={() => void handleMonitorStart()}
            disabled={
              monitorActionBusy ||
              monInputsLocked ||
              statusLoading ||
              !status?.configured ||
              !status?.enabled
            }
          >
            {monitorActionBusy ? "Iniciando…" : "Iniciar monitor"}
          </button>
          <button
            type="button"
            className="radar-refresh-btn"
            onClick={() => void handleMonitorStop()}
            disabled={monitorActionBusy || !monitorStatus?.enabled}
          >
            Detener monitor
          </button>
          <button type="button" className="radar-refresh-btn" onClick={() => void loadMonitorStatus()} disabled={monitorStatusLoading}>
            {monitorStatusLoading ? "Estado…" : "Refrescar estado"}
          </button>
          <CryptoRefreshBadge active={monitorStatusLoading && Boolean(monitorStatus?.enabled)} label="Monitor…" />
        </div>

        <p className="msg-muted" style={{ marginTop: "0.75rem", marginBottom: "0.65rem", fontSize: "0.82rem" }}>
          Con el monitor <strong>activo</strong>, los parámetros de esta card quedan bloqueados hasta que lo detengas (las órdenes manuales de abajo siguen disponibles).
        </p>

        <div className="crypto-testnet-mini-grid crypto-testnet-mini-grid--dense" style={{ marginBottom: "0.75rem" }}>
          <label className="crypto-testnet-field">
            <span className="msg-muted">Intervalo (min)</span>
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
          <CryptoTimeframeField
            className="crypto-testnet-field"
            label="Timeframe entrada"
            value={monTf}
            onChange={setMonTf}
            disabled={monInputsLocked || monitorActionBusy}
            id="crypto-testnet-monitor-timeframe"
          />
          <label className="crypto-testnet-field">
            <span className="msg-muted">USDT entrada</span>
            <input
              type="number"
              className="radar-input"
              min={MIN_TESTNET_ORDER_USDT}
              max={MAX_TESTNET_ORDER_USDT}
              step="0.01"
              value={monQuote}
              onChange={(ev) => setMonQuote(ev.target.value)}
              disabled={monInputsLocked || monitorActionBusy}
            />
          </label>
          <label className="crypto-testnet-field">
            <span className="msg-muted">Máx. posiciones</span>
            <input
              type="number"
              className="radar-input"
              min={1}
              max={50}
              step={1}
              value={monMaxOpen}
              onChange={(ev) => setMonMaxOpen(ev.target.value)}
              disabled={monInputsLocked || monitorActionBusy}
            />
          </label>
          <label className="crypto-testnet-field">
            <span className="msg-muted">Cooldown (min)</span>
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
          <label className="crypto-testnet-field">
            <span className="msg-muted">Score mínimo</span>
            <input
              type="number"
              className="radar-input"
              min={0}
              max={100}
              step="0.5"
              value={monMinScore}
              onChange={(ev) => setMonMinScore(ev.target.value)}
              disabled={monInputsLocked || monitorActionBusy}
            />
          </label>
          <label className="crypto-testnet-field">
            <span className="msg-muted">SL % / TP %</span>
            <div style={{ display: "flex", gap: "0.35rem", alignItems: "center" }}>
              <input
                type="number"
                className="radar-input"
                min={0}
                step="0.1"
                value={monSl}
                onChange={(ev) => setMonSl(ev.target.value)}
                disabled={monInputsLocked || monitorActionBusy}
                style={{ flex: 1 }}
              />
              <input
                type="number"
                className="radar-input"
                min={0}
                step="0.1"
                value={monTp}
                onChange={(ev) => setMonTp(ev.target.value)}
                disabled={monInputsLocked || monitorActionBusy}
                style={{ flex: 1 }}
              />
            </div>
          </label>
          <label className="crypto-testnet-field">
            <span className="msg-muted">Trailing % (opc.)</span>
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
          <label className="crypto-testnet-field">
            <span className="msg-muted">Break-even trig / +%</span>
            <div style={{ display: "flex", gap: "0.35rem", alignItems: "center" }}>
              <input
                type="number"
                className="radar-input"
                min={0}
                step="0.1"
                value={monBeTrig}
                onChange={(ev) => setMonBeTrig(ev.target.value)}
                disabled={monInputsLocked || monitorActionBusy}
                style={{ flex: 1 }}
              />
              <input
                type="number"
                className="radar-input"
                min={0}
                step="0.1"
                value={monBePlus}
                onChange={(ev) => setMonBePlus(ev.target.value)}
                disabled={monInputsLocked || monitorActionBusy}
                style={{ flex: 1 }}
              />
            </div>
          </label>
          <label className="crypto-testnet-field">
            <span className="msg-muted">Mín. valor salida USDT</span>
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
          <label className="crypto-testnet-radio" style={{ alignSelf: "end", marginTop: "0.35rem" }}>
            <input
              type="checkbox"
              checked={monBtcTrend}
              onChange={(ev) => setMonBtcTrend(ev.target.checked)}
              disabled={monInputsLocked || monitorActionBusy}
            />
            Exigir BTC alcista (entrada)
          </label>
        </div>

        <div className="crypto-testnet-block-start">
          <h4 className="msg-muted" style={{ margin: "0 0 0.35rem", fontSize: "0.88rem", fontWeight: 600 }}>
            Entrada propuesta (último ciclo)
          </h4>
          {monitorStatus?.last_entry_proposal ? (
            <>
              <div className="crypto-testnet-mini-grid crypto-testnet-mini-grid--dense">
                <div className="crypto-testnet-kpi crypto-testnet-kpi--accent">
                  <span className="crypto-testnet-kpi-label">Par</span>
                  <span className="crypto-testnet-kpi-value">{monitorStatus.last_entry_proposal.symbol}</span>
                </div>
                <div className="crypto-testnet-kpi">
                  <span className="crypto-testnet-kpi-label">USDT</span>
                  <span className="crypto-testnet-kpi-value">{fmtNum(monitorStatus.last_entry_proposal.quote_amount_usdt)}</span>
                </div>
                <div className="crypto-testnet-kpi">
                  <span className="crypto-testnet-kpi-label">Score</span>
                  <span className="crypto-testnet-kpi-value">{monitorStatus.last_entry_proposal.score ?? "—"}</span>
                </div>
              </div>
              <p className="msg-muted" style={{ margin: "0.45rem 0 0", fontSize: "0.82rem" }}>
                Señal: {monitorStatus.last_entry_proposal.signal || "—"}
              </p>
              <div className="crypto-testnet-toolbar" style={{ marginTop: "0.65rem", flexWrap: "wrap", gap: "0.5rem" }}>
                <button
                  type="button"
                  className="radar-refresh-btn"
                  onClick={() => applyEntryProposalToManualForm(monitorStatus.last_entry_proposal!)}
                  disabled={orderBusy}
                >
                  Usar propuesta
                </button>
                <button
                  type="button"
                  className="radar-refresh-btn"
                  onClick={() => void handleMonitorConfirmBuy()}
                  disabled={!connected || monitorConfirmBuyBusy || orderBusy || exitConfirmAsset !== null || monitorSellBusyAsset !== null}
                >
                  {monitorConfirmBuyBusy ? "Enviando…" : "Confirmar BUY Testnet"}
                </button>
              </div>
              {!connected ? (
                <p className="msg-muted" style={{ marginTop: "0.35rem", fontSize: "0.8rem" }}>
                  Conectá testnet para confirmar la compra sugerida por el monitor.
                </p>
              ) : null}
            </>
          ) : (
            <p className="msg-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
              {monitorStatus?.enabled
                ? assistedPrimaryReasonLabel(monitorStatus.last_entry_primary_reason)
                : "Iniciá el monitor para revisar propuestas de entrada automáticamente."}
            </p>
          )}
        </div>

        <div className="crypto-testnet-block-start" style={{ marginTop: "1rem" }}>
          <h4 className="msg-muted" style={{ margin: "0 0 0.35rem", fontSize: "0.88rem", fontWeight: 600 }}>
            Salidas propuestas (último ciclo)
          </h4>
          {monitorStatus?.last_exit_proposals && monitorStatus.last_exit_proposals.length > 0 ? (
            <div className="table-wrap">
              <table className="crypto-testnet-table">
                <thead>
                  <tr>
                    <th>Activo</th>
                    <th>Motivo</th>
                    <th className="crypto-testnet-num">Precio</th>
                    <th className="crypto-testnet-num">Máximo</th>
                    <th className="crypto-testnet-num">Trailing %</th>
                    <th className="crypto-testnet-num">Precio trail.</th>
                    <th className="crypto-testnet-num">PnL %</th>
                    <th className="crypto-testnet-num">Valor USDT</th>
                    <th className="crypto-testnet-num">Entrada ~</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {monitorStatus.last_exit_proposals.map((row) => (
                    <tr key={row.asset}>
                      <td>{row.asset}</td>
                      <td>{exitProposalReasonLabel(row.exit_reason ?? row.reason)}</td>
                      <td className="crypto-testnet-num">
                        {fmtNum(row.current_price ?? row.current_price_usdt)}
                      </td>
                      <td className="crypto-testnet-num">{fmtNum(row.highest_price)}</td>
                      <td className="crypto-testnet-num">{fmtNum(row.trailing_stop_pct)}</td>
                      <td className="crypto-testnet-num">{fmtNum(row.trailing_stop_price)}</td>
                      <td className="crypto-testnet-num">
                        {row.pnl_pct != null && Number.isFinite(row.pnl_pct) ? numFmt4.format(row.pnl_pct) : "—"}
                      </td>
                      <td className="crypto-testnet-num">{fmtNum(row.value_usdt)}</td>
                      <td className="crypto-testnet-num">{fmtNum(row.avg_entry_usdt)}</td>
                      <td>
                        <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem", alignItems: "flex-start" }}>
                          <button
                            type="button"
                            className="radar-refresh-btn crypto-testnet-btn-compact"
                            onClick={() => applyExitProposalToManualForm(row)}
                            disabled={orderBusy}
                          >
                            Usar propuesta
                          </button>
                          <button
                            type="button"
                            className="radar-refresh-btn crypto-testnet-btn-compact"
                            onClick={() => void handleMonitorConfirmSell(row)}
                            disabled={
                              !connected ||
                              monitorSellBusyAsset !== null ||
                              exitConfirmAsset !== null ||
                              orderBusy ||
                              monitorConfirmBuyBusy
                            }
                          >
                            {monitorSellBusyAsset === row.asset ? "Enviando…" : "Confirmar SELL Testnet"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="msg-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
              {monitorStatus?.enabled
                ? "Sin ventas sugeridas por SL/TP en el último ciclo."
                : "Sin datos hasta iniciar el monitor."}
            </p>
          )}
        </div>

        <div className="crypto-testnet-block-start" style={{ marginTop: "1.1rem" }}>
          <div className="crypto-testnet-section-head">
            <div>
              <h4 className="msg-muted" style={{ margin: 0, fontSize: "0.88rem", fontWeight: 600 }}>
                Historial de ciclos monitor
              </h4>
              <p className="msg-muted" style={{ margin: "0.3rem 0 0", fontSize: "0.78rem" }}>
                Auditoría local ({monitorCyclesTotal} en archivo). No incluye órdenes ejecutadas.
              </p>
            </div>
            <div className="crypto-testnet-toolbar">
              <button
                type="button"
                className="radar-refresh-btn"
                style={{ fontSize: "0.82rem" }}
                onClick={() => void loadMonitorCycles(20)}
                disabled={monitorCyclesLoading}
              >
                {monitorCyclesLoading ? "Refrescando…" : "Refrescar"}
              </button>
              <CryptoRefreshBadge active={monitorCyclesLoading} />
            </div>
          </div>
          {monitorCyclesError ? (
            <p className="msg-error" style={{ margin: "0.5rem 0 0", fontSize: "0.82rem" }}>
              {monitorCyclesError}
            </p>
          ) : null}
          {monitorCycles.length > 0 ? (
            <div className="table-wrap" style={{ marginTop: "0.55rem" }}>
              <table className="crypto-testnet-table" style={{ fontSize: "0.8rem" }}>
                <thead>
                  <tr>
                    <th>Fecha/hora</th>
                    <th className="crypto-testnet-num">Escaneados</th>
                    <th className="crypto-testnet-num">Candidatos</th>
                    <th>Entrada</th>
                    <th className="crypto-testnet-num">Salidas</th>
                    <th>Razón</th>
                  </tr>
                </thead>
                <tbody>
                  {monitorCycles.map((row, idx) => (
                    <tr key={`${row.timestamp ?? "t"}-${idx}`}>
                      <td style={{ whiteSpace: "nowrap" }}>
                        {fmtIsoLocalShort(row.timestamp ?? row.cycle_finished_at ?? "")}
                      </td>
                      <td className="crypto-testnet-num">{row.scan_count ?? "—"}</td>
                      <td className="crypto-testnet-num">{row.candidates_count ?? "—"}</td>
                      <td>{row.entry_proposal_generated ? "Sí" : "No"}</td>
                      <td className="crypto-testnet-num">{row.exit_proposals_count ?? 0}</td>
                      <td
                        style={{ maxWidth: "14rem", overflow: "hidden", textOverflow: "ellipsis" }}
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
        </div>
      </section>
      </TestnetPanelGroup>

      <TestnetPanelGroup
        groupKey="operate"
        sectionId="crypto-testnet-section-operate"
        orderClassName="crypto-testnet-group--operate"
        title="Operación manual"
        lead="MARKET/LIMIT, usar propuesta y confirmación explícita antes de enviar."
        collapsed={collapsedGroups.operate}
        onToggle={toggleTestnetGroup}
      >
      {!connected ? (
        <p className="msg-muted crypto-testnet-note crypto-testnet-note--neutral" style={{ margin: 0 }}>
          Conectá testnet en <strong>Estado</strong> para habilitar el formulario manual y las posiciones en vivo.
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
              Límite por orden: hasta {MAX_TESTNET_ORDER_USDT} USDT · pares en whitelist · mercado spot testnet.
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
                    max={MAX_TESTNET_ORDER_USDT}
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
                        max={MAX_TESTNET_ORDER_USDT}
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

      {/* 4 — Posiciones reales */}
      {balances ? (
        <section className="card crypto-testnet-section crypto-testnet-real-positions">
          <h3 className="dashboard-section-title crypto-testnet-section-title">Posiciones reales</h3>
          <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.65rem", fontSize: "0.85rem" }}>
            Saldo spot en Binance Spot Testnet (no paper interno). Podés usar <strong>Vender</strong> para cargar el
            formulario de arriba.
          </p>
          {positionsError ? <p className="msg-error crypto-testnet-block-start">{positionsError}</p> : null}
          {!positionsPayload && balances.ok && !positionsError ? (
            <p className="msg-muted" style={{ margin: "0.5rem 0 0", fontSize: "0.88rem" }}>
              Refrescá datos para sincronizar posiciones desde testnet.
            </p>
          ) : null}
          {positionsPayload?.ok ? (
            <>
              <div className="crypto-testnet-mini-grid" style={{ marginBottom: "0.85rem" }}>
                <div className="crypto-testnet-kpi">
                  <span className="crypto-testnet-kpi-label">USDT (efectivo)</span>
                  <span className="crypto-testnet-kpi-value">{fmtNum(positionsPayload.cash_usdt)}</span>
                </div>
                <div className="crypto-testnet-kpi crypto-testnet-kpi--accent">
                  <span className="crypto-testnet-kpi-label">Valor total aprox.</span>
                  <span className="crypto-testnet-kpi-value">{fmtNum(positionsPayload.total_value_usdt)} USDT</span>
                </div>
                <div className="crypto-testnet-kpi">
                  <span className="crypto-testnet-kpi-label">Sincronizado</span>
                  <span className="crypto-testnet-kpi-value" style={{ fontSize: "0.85rem", fontWeight: 500 }}>
                    {fmtIsoLocalShort(positionsPayload.updated_at)}
                  </span>
                </div>
              </div>
              {positionsPayload.positions.length === 0 ? (
                <p className="msg-muted" style={{ margin: 0 }}>
                  Sin posiciones crypto (sólo efectivo USDT o cuenta vacía).
                </p>
              ) : (
                <div className="table-wrap">
                  <table className="crypto-testnet-table">
                    <thead>
                      <tr>
                        <th>Activo</th>
                        <th className="crypto-testnet-num">Libre</th>
                        <th className="crypto-testnet-num">En orden</th>
                        <th className="crypto-testnet-num">Total</th>
                        <th className="crypto-testnet-num">Precio USDT</th>
                        <th className="crypto-testnet-num">Valor USDT</th>
                        <th>Acción</th>
                      </tr>
                    </thead>
                    <tbody>
                      {positionsPayload.positions.map((r) => {
                        const canSell = Boolean(r.symbol);
                        return (
                          <tr key={r.asset} className={PAIR_FOR_BASE[r.asset] ? "crypto-testnet-row--hl" : undefined}>
                            <td className={PAIR_FOR_BASE[r.asset] ? "crypto-testnet-asset-hl" : undefined}>{r.asset}</td>
                            <td className="crypto-testnet-num">{numFmt4.format(r.free)}</td>
                            <td className="crypto-testnet-num">{numFmt4.format(r.used)}</td>
                            <td className="crypto-testnet-num">{numFmt4.format(r.total)}</td>
                            <td className="crypto-testnet-num">{fmtNum(r.last_price_usdt)}</td>
                            <td className="crypto-testnet-num">{r.value_usdt !== null ? fmtNum(r.value_usdt) : "—"}</td>
                            <td>
                              {canSell ? (
                                <button
                                  type="button"
                                  className="radar-refresh-btn crypto-testnet-btn-compact"
                                  onClick={() => prefillQuickSell(r.symbol)}
                                  disabled={orderBusy}
                                >
                                  Vender
                                </button>
                              ) : (
                                <span className="msg-muted" style={{ fontSize: "0.8rem" }}>
                                  —
                                </span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          ) : positionsPayload && !positionsPayload.ok ? (
            <p className="msg-error" style={{ margin: "0.5rem 0 0", fontSize: "0.875rem" }}>
              {positionsPayload.error ?? "No se pudieron leer posiciones testnet"}
            </p>
          ) : null}
        </section>
      ) : null}
      </TestnetPanelGroup>

      <TestnetPanelGroup
        groupKey="orders"
        sectionId="crypto-testnet-section-orders"
        orderClassName="crypto-testnet-group--orders"
        title="Órdenes e historial"
        lead="Órdenes abiertas en testnet, cancelación, sync LIMIT e historial local de la app."
        collapsed={collapsedGroups.orders}
        onToggle={toggleTestnetGroup}
      >
      {/* 5 — Órdenes abiertas */}
      {balances ? (
        <section className="card crypto-testnet-section">
          <div className="crypto-testnet-section-head">
            <div>
              <h3 className="dashboard-section-title crypto-testnet-section-title" style={{ margin: 0 }}>
                Órdenes abiertas
              </h3>
              <p className="msg-muted" style={{ margin: "0.35rem 0 0", fontSize: "0.82rem" }}>
                Lectura directa desde Binance Spot Testnet (cuando existan límites aparecerán acá). No es historial local ni paper.
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
      </TestnetPanelGroup>
    </div>
  );
}
