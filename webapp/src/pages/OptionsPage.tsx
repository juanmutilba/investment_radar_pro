import { useEffect, useMemo, useRef, useState } from "react";

import {
  fetchLatestRadarArgentina,
  fetchOptionsChain,
  type OptionContractRow,
  type OptionsChainResponse,
  type RadarRow,
} from "@/services/api";
import { formatTrend, getRaw } from "@/components/radar/radarTableCore";

type OptionUnderlying = { value: string; label: string; radarTicker: string; ravaUnderlying: string };

/** Subyacentes ByMA para GET /options/chain; `ravaUnderlying` es el ticker interno de Rava en ESTRATEGIAS. */
const CHAIN_UNDERLYINGS: readonly OptionUnderlying[] = [
  { value: "GGAL", label: "GGAL", radarTicker: "GGAL", ravaUnderlying: "GFG" },
  { value: "YPFD", label: "YPFD", radarTicker: "YPFD", ravaUnderlying: "YPF" },
  { value: "ALUA", label: "ALUA", radarTicker: "ALUA", ravaUnderlying: "ALU" },
] as const;

type FlatRow = {
  activo: string;
  tipo: "CALL" | "PUT";
  strike: number;
  expiryCode: string;
  raw: Record<string, unknown>;
};

type StrategyType = "Bull Call Spread" | "Bear Put Spread" | "Covered Call" | "Protective Put" | "Collar";
type LegAction = "BUY" | "SELL";
type ActiveTab = "panel" | "strategies";
type StrategiesFilter = "" | "Bull Call Spread" | "Covered Call";

type StrategyLeg = {
  action: LegAction;
  tipo: "CALL" | "PUT";
  symbol: string;
  expiry_date: string | null;
  strike: number | null;
  bid: number | null;
  ask: number | null;
  last: number | null;
  moneyness: string | null;
};

function fmtCell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number" && !Number.isFinite(v)) return "—";
  return String(v);
}

function toNumberOrNull(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string") {
    const t = v.trim().replace(",", ".");
    if (!t) return null;
    const n = Number(t);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function formatNumber(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString("es-AR", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function formatInteger(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString("es-AR", { maximumFractionDigits: 0 });
}

function formatTrendLabel(value: unknown): string {
  // Reutiliza exactamente la misma lógica del radar (Acciones Argentina).
  const out = formatTrend(value);
  return out.missing ? "-" : out.text;
}

function getExpiryDateRaw(raw: Record<string, unknown>): string | null {
  const candidates = [raw.expiry_date, raw.vencimiento, raw.expiration_date, raw.expiration];
  for (const c of candidates) {
    if (typeof c === "string" && c.trim()) return c.trim();
  }
  return null;
}

function expiryKeyFromRaw(raw: Record<string, unknown>): string {
  const s = getExpiryDateRaw(raw);
  if (!s) return "";
  // Normalizar a YYYY-MM-DD (evita datetime con timezone)
  return String(s).slice(0, 10);
}

function formatExpiryMonthLabel(yyyyMmDd: string): string {
  // Evitar shift por timezone: tratar como medianoche local
  const d = new Date(`${yyyyMmDd}T00:00:00`);
  if (Number.isNaN(d.getTime())) return yyyyMmDd;
  const dtf = new Intl.DateTimeFormat("es-AR", { month: "long", year: "numeric" });
  // Capitalizar primera letra (Intl devuelve en minúsculas en es-AR)
  const s = dtf.format(d);
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : yyyyMmDd;
}

function moneyStatus(raw: Record<string, unknown>): string | null {
  const ms = raw.money_status;
  if (typeof ms === "string" && ms.trim()) return ms.trim();
  // fallback suave si el backend cambia el nombre
  const m = raw.moneyness_status;
  if (typeof m === "string" && m.trim()) return m.trim();
  return null;
}

function strategyHelpText(t: StrategyType): string {
  switch (t) {
    case "Bull Call Spread":
      return "Comprar call de strike menor y vender call de strike mayor.";
    case "Bear Put Spread":
      return "Comprar put de strike mayor y vender put de strike menor.";
    case "Covered Call":
      return "Tener el activo y vender call OTM.";
    case "Protective Put":
      return "Tener el activo y comprar put como cobertura.";
    case "Collar":
      return "Tener el activo, comprar put y vender call.";
  }
}

function legKey(leg: Pick<StrategyLeg, "symbol" | "action">): string {
  return `${leg.symbol}::${leg.action}`;
}

function buildLegFromRow(r: FlatRow): StrategyLeg {
  const o = r.raw;
  const symbol = typeof o.simbolo === "string" && o.simbolo.trim() ? o.simbolo.trim() : "";
  const expiry_date = getExpiryDateRaw(o);
  return {
    action: "BUY",
    tipo: r.tipo,
    symbol,
    expiry_date,
    strike: Number.isFinite(r.strike) ? r.strike : null,
    bid: toNumberOrNull(o.bid),
    ask: toNumberOrNull(o.ask),
    last: toNumberOrNull(o.ultimo),
    moneyness: moneyStatus(o),
  };
}

function legPriceUsed(leg: StrategyLeg): number | null {
  if (leg.action === "BUY") {
    return leg.ask ?? leg.last ?? null;
  }
  return leg.bid ?? leg.last ?? null;
}

function daysToExpiryRaw(raw: Record<string, unknown>): number | null {
  const d = toNumberOrNull(raw.days_to_expiry);
  if (d === null) return null;
  const di = Math.trunc(d);
  return Number.isFinite(di) ? di : null;
}

function expiryKeyFromMergedContract(c: OptionContractRow): string {
  if (c.expiry === null || c.expiry === undefined || c.expiry === "") return "";
  return String(c.expiry).slice(0, 10);
}

function mergedContractTypeUpper(c: OptionContractRow): string {
  return (c.option_type ?? "").toString().trim().toUpperCase();
}

function mergedContractVolume(c: OptionContractRow): number {
  const v = c.volume;
  if (typeof v === "number" && Number.isFinite(v)) return v;
  return 0;
}

function mergedContractLastSortKey(c: OptionContractRow): number {
  const v = c.last;
  if (typeof v === "number" && Number.isFinite(v)) return v;
  return -Infinity;
}

/** Orden por defecto del panel: vencimiento → tipo → strike → símbolo. */
function sortMergedDefault(a: OptionContractRow, b: OptionContractRow): number {
  const eA = expiryKeyFromMergedContract(a);
  const eB = expiryKeyFromMergedContract(b);
  const cmpE = eA.localeCompare(eB);
  if (cmpE !== 0) return cmpE;
  const tA = mergedContractTypeUpper(a);
  const tB = mergedContractTypeUpper(b);
  const cmpT = tA.localeCompare(tB);
  if (cmpT !== 0) return cmpT;
  const sA = a.strike ?? -Infinity;
  const sB = b.strike ?? -Infinity;
  if (sA !== sB) return sA - sB;
  return (a.symbol ?? "").localeCompare(b.symbol ?? "", "es");
}

function tieBreakExpiryTypeStrike(a: OptionContractRow, b: OptionContractRow): number {
  const eA = expiryKeyFromMergedContract(a);
  const eB = expiryKeyFromMergedContract(b);
  const cmpE = eA.localeCompare(eB);
  if (cmpE !== 0) return cmpE;
  const tA = mergedContractTypeUpper(a);
  const tB = mergedContractTypeUpper(b);
  const cmpT = tA.localeCompare(tB);
  if (cmpT !== 0) return cmpT;
  const sA = a.strike ?? -Infinity;
  const sB = b.strike ?? -Infinity;
  return sA - sB;
}

/** Moneyness: ATM si |strike-spot|/spot ≤ 3%; luego ITM/OTM según CALL/PUT (mismo criterio panel y estrategias). */
type MoneynessKind = "ITM" | "ATM" | "OTM" | "SIN_DATO";

function getMoneynessFromValues(
  strike: number | null | undefined,
  optionKind: string,
  spot: number | null,
): MoneynessKind {
  if (spot === null || !Number.isFinite(spot) || spot <= 0) return "SIN_DATO";
  if (strike === null || strike === undefined || !Number.isFinite(strike)) return "SIN_DATO";
  const rel = Math.abs(strike - spot) / spot;
  if (rel <= 0.03) return "ATM";
  const t = optionKind.toString().trim().toUpperCase();
  const isCall = t.includes("CALL") || t === "C";
  const isPut = t.includes("PUT") || t === "P" || t === "V";
  if (!isCall && !isPut) return "SIN_DATO";
  if (isCall) {
    if (strike < spot) return "ITM";
    return "OTM";
  }
  if (strike > spot) return "ITM";
  return "OTM";
}

function getMoneyness(row: OptionContractRow, spot: number | null): MoneynessKind {
  return getMoneynessFromValues(row.strike, mergedContractTypeUpper(row), spot);
}

function mergedMoneynessRowClass(m: MoneynessKind): string {
  switch (m) {
    case "ITM":
      return "option-row-itm";
    case "ATM":
      return "option-row-atm";
    case "OTM":
      return "option-row-otm";
    default:
      return "moneyness-row-none";
  }
}

function mergedMoneynessBadgeClass(m: MoneynessKind): string {
  switch (m) {
    case "ITM":
      return "moneyness-badge moneyness-itm";
    case "ATM":
      return "moneyness-badge moneyness-atm";
    case "OTM":
      return "moneyness-badge moneyness-otm";
    default:
      return "moneyness-badge moneyness-none";
  }
}

function mergedMoneynessBadgeText(m: MoneynessKind): string {
  switch (m) {
    case "ITM":
      return "ITM";
    case "ATM":
      return "ATM";
    case "OTM":
      return "OTM";
    default:
      return "Sin dato";
  }
}

type OptionTypeFilter = "all" | "CALL" | "PUT";
type PanelSortMode = "expiry_type_strike" | "symbol" | "volume_desc" | "last_desc";

export function OptionsPage() {
  const [selectedUnderlying, setSelectedUnderlying] = useState<string>("GGAL");
  const [selectedExpiry, setSelectedExpiry] = useState<string>("");
  const [optionTypeFilter, setOptionTypeFilter] = useState<OptionTypeFilter>("all");
  const [hideZeroVolume, setHideZeroVolume] = useState(false);
  const [panelSort, setPanelSort] = useState<PanelSortMode>("expiry_type_strike");
  /** Override opcional si el spot del API no alcanza o el usuario quiere otro valor. */
  const [manualSpotInput, setManualSpotInput] = useState("");
  const [onlyWithVolume, setOnlyWithVolume] = useState(false);
  const [onlyWithTrades, setOnlyWithTrades] = useState(false);
  const [onlyAtm, setOnlyAtm] = useState(false);
  const [activeTab, setActiveTab] = useState<ActiveTab>("panel");
  const [strategyType, setStrategyType] = useState<StrategyType>("Bull Call Spread");
  const [strategiesFilter, setStrategiesFilter] = useState<StrategiesFilter>("");
  const [showManualStrategy, setShowManualStrategy] = useState(false);
  const [showBullCallSpread, setShowBullCallSpread] = useState(false);
  const [showCoveredCall, setShowCoveredCall] = useState(false);
  const [selectedLegs, setSelectedLegs] = useState<StrategyLeg[]>([]);
  const [mergedChain, setMergedChain] = useState<OptionsChainResponse | null>(null);
  const [loadingChain, setLoadingChain] = useState(true);
  const [errorChain, setErrorChain] = useState<string | null>(null);
  /** Invalida respuestas viejas (cambio de activo, desmontaje, StrictMode). */
  const optionsChainReqRef = useRef(0);
  const [loadingUnderlyingContext, setLoadingUnderlyingContext] = useState(false);
  const [underlyingSignal, setUnderlyingSignal] = useState<string | null>(null);
  const [underlyingTrendRaw, setUnderlyingTrendRaw] = useState<unknown>(null);

  const selectedUnderlyingMeta = useMemo(() => {
    return CHAIN_UNDERLYINGS.find((u) => u.value === selectedUnderlying) ?? {
      value: selectedUnderlying,
      label: selectedUnderlying,
      radarTicker: selectedUnderlying,
      ravaUnderlying: selectedUnderlying,
    };
  }, [selectedUnderlying]);

  const chainIsIolPrimary = useMemo(() => {
    const rows = mergedChain?.contracts ?? [];
    if (rows.length === 0) return false;
    return rows.some((c) => c.iol_universe === true || (c.source ?? "").toLowerCase() === "iol_primary");
  }, [mergedChain]);

  const underlyingRadarSymbol = selectedUnderlyingMeta.radarTicker;

  useEffect(() => {
    const reqId = ++optionsChainReqRef.current;
    setLoadingChain(true);
    setErrorChain(null);
    console.log("[OPTIONS_FRONT] fetch chain", selectedUnderlying);
    fetchOptionsChain(selectedUnderlying, false)
      .then((res) => {
        if (reqId !== optionsChainReqRef.current) return;
        setMergedChain(res);
      })
      .catch((e: unknown) => {
        if (reqId !== optionsChainReqRef.current) return;
        setErrorChain(e instanceof Error ? e.message : String(e));
        setMergedChain(null);
      })
      .finally(() => {
        if (reqId !== optionsChainReqRef.current) return;
        setLoadingChain(false);
      });
    return () => {
      optionsChainReqRef.current += 1;
    };
  }, [selectedUnderlying]);

  useEffect(() => {
    setManualSpotInput("");
  }, [selectedUnderlying]);

  useEffect(() => {
    setSelectedExpiry("");
  }, [selectedUnderlying]);

  // Estrategias usan la misma cadena que el Panel: mergedChain (GET /options/chain).

  useEffect(() => {
    let cancelled = false;
    setLoadingUnderlyingContext(true);
    setUnderlyingSignal(null);
    setUnderlyingTrendRaw(null);
    fetchLatestRadarArgentina()
      .then((res) => {
        if (cancelled) return;
        const rows: RadarRow[] = res?.rows ?? [];
        const keysTicker = ["Ticker", "ticker", "Especie", "especie", "Simbolo", "simbolo", "Símbolo", "símbolo"];
        const keysSignal = ["SignalState", "signal_state", "signalState", "Signal", "signal"];
        // Reutilizar el MISMO campo que la tabla Acciones Argentina:
        // COLUMNS_ARGENTINA (id="trend") => keys ["Trend", "trend"] y formatTrend().
        const keysTrend = ["Trend", "trend"];

        const target = underlyingRadarSymbol.trim().toUpperCase();
        let found: RadarRow | null = null;
        for (const r of rows) {
          const t = getRaw(r, keysTicker);
          const s = (t ?? "").toString().trim().toUpperCase();
          if (s === target) {
            found = r;
            break;
          }
        }
        if (!found) return;
        const sig = getRaw(found, keysSignal);
        const tr = getRaw(found, keysTrend);
        setUnderlyingSignal(sig === undefined ? null : String(sig));
        setUnderlyingTrendRaw(tr === undefined ? null : tr);
      })
      .catch(() => {
        // silent: no bloquear /options si falla el radar
      })
      .finally(() => {
        if (!cancelled) setLoadingUnderlyingContext(false);
      });
    return () => {
      cancelled = true;
    };
  }, [underlyingRadarSymbol]);

  const underlyingTrendLabel = useMemo(() => formatTrendLabel(underlyingTrendRaw), [underlyingTrendRaw]);

  const signalBadgeClass = useMemo(() => {
    const s = (underlyingSignal ?? "").trim().toLowerCase();
    if (!s) return "options-underlying-badge options-underlying-badge-neutral";
    if (s.includes("compra") || s.includes("buy") || s.includes("mejora")) {
      return "options-underlying-badge options-underlying-badge-positive";
    }
    if (s.includes("venta") || s.includes("sell") || s.includes("deterioro")) {
      return "options-underlying-badge options-underlying-badge-negative";
    }
    if (s.includes("neutral") || s.includes("lateral") || s.includes("sin")) {
      return "options-underlying-badge options-underlying-badge-neutral";
    }
    return "options-underlying-badge options-underlying-badge-neutral";
  }, [underlyingSignal]);

  const trendBadgeClass = useMemo(() => {
    const s = (underlyingTrendLabel ?? "").trim().toLowerCase();
    if (!s) return "options-underlying-badge options-underlying-badge-neutral";
    if (s === "-") return "options-underlying-badge options-underlying-badge-neutral";
    if (s.includes("sub") || s.includes("alc")) return "options-underlying-badge options-underlying-badge-positive";
    if (s.includes("baj") || s.includes("bear")) return "options-underlying-badge options-underlying-badge-negative";
    if (s.includes("pla") || s.includes("lat")) return "options-underlying-badge options-underlying-badge-neutral";
    return "options-underlying-badge options-underlying-badge-neutral";
  }, [underlyingTrendLabel]);

  const emptyHintPanel = useMemo(() => {
    if (loadingChain || errorChain) return null;
    if ((mergedChain?.contracts.length ?? 0) === 0) return "Sin contratos para este subyacente.";
    return null;
  }, [loadingChain, errorChain, mergedChain]);

  const emptyHintStrategies = useMemo(() => {
    if (loadingChain || errorChain) return null;
    if ((mergedChain?.contracts.length ?? 0) === 0) return "Sin contratos para este subyacente.";
    return null;
  }, [loadingChain, errorChain, mergedChain]);

  const expiryOptions = useMemo(() => {
    const set = new Set<string>();
    for (const c of mergedChain?.contracts ?? []) {
      const k = expiryKeyFromMergedContract(c);
      if (k) set.add(k);
    }
    return Array.from(set).sort();
  }, [mergedChain]);

  const expirySummary = useMemo(() => {
    const counts = new Map<string, number>();
    for (const c of mergedChain?.contracts ?? []) {
      const k = expiryKeyFromMergedContract(c);
      if (!k) continue;
      counts.set(k, (counts.get(k) ?? 0) + 1);
    }
    const items = Array.from(counts.entries()).sort(([a], [b]) => a.localeCompare(b));
    return items.map(([k, count]) => ({ key: k, label: formatExpiryMonthLabel(k), count }));
  }, [mergedChain]);

  const parsedManualSpot = useMemo(() => {
    const t = manualSpotInput.trim().replace(",", ".");
    if (!t) return null;
    const n = Number(t);
    return Number.isFinite(n) && n > 0 ? n : null;
  }, [manualSpotInput]);

  /** Spot numérico del GET /options/chain (solo > 0 es usable; string ya normalizado en api.ts). */
  const apiChainSpot = useMemo((): number | null => {
    const s = mergedChain?.spot;
    if (typeof s === "number" && Number.isFinite(s) && s > 0) return s;
    return null;
  }, [mergedChain]);

  /**
   * Manual > 0 gana; si no, spot del API si > 0; si no, null (sin fallback inventado).
   */
  const effectivePanelSpot = useMemo((): number | null => {
    if (parsedManualSpot !== null && parsedManualSpot > 0) return parsedManualSpot;
    if (apiChainSpot !== null && apiChainSpot > 0) return apiChainSpot;
    return null;
  }, [parsedManualSpot, apiChainSpot]);

  useEffect(() => {
    console.log("[OPTIONS_FRONT_SPOT]", mergedChain?.spot, mergedChain?.spot_source);
  }, [mergedChain]);

  const filterCounts = useMemo(() => {
    let withVolume = 0;
    let withTrades = 0;
    let withAtm = 0;
    for (const c of mergedChain?.contracts ?? []) {
      const vol = typeof c.volume === "number" && Number.isFinite(c.volume) ? c.volume : 0;
      if (vol > 0) withVolume += 1;
      const last = typeof c.last === "number" && Number.isFinite(c.last) ? c.last : 0;
      if (last > 0) withTrades += 1;
      const m = getMoneynessFromValues(c.strike, mergedContractTypeUpper(c), effectivePanelSpot);
      if (m === "ATM") withAtm += 1;
    }
    return { withVolume, withTrades, withAtm };
  }, [mergedChain, effectivePanelSpot]);

  const mergedFilteredContracts = useMemo(() => {
    const list = mergedChain?.contracts ?? [];
    const filtered = list.filter((c) => {
      if (selectedExpiry) {
        const k = expiryKeyFromMergedContract(c);
        if (k !== selectedExpiry) return false;
      }
      if (optionTypeFilter === "CALL") {
        const t = mergedContractTypeUpper(c);
        if (!t.includes("CALL")) return false;
      }
      if (optionTypeFilter === "PUT") {
        const t = mergedContractTypeUpper(c);
        if (!t.includes("PUT")) return false;
      }
      if (hideZeroVolume && mergedContractVolume(c) <= 0) return false;
      return true;
    });
    return filtered.slice().sort((a, b) => {
      switch (panelSort) {
        case "symbol": {
          const cmp = (a.symbol ?? "").localeCompare(b.symbol ?? "", "es");
          if (cmp !== 0) return cmp;
          return sortMergedDefault(a, b);
        }
        case "volume_desc": {
          const va = mergedContractVolume(a);
          const vb = mergedContractVolume(b);
          if (vb !== va) return vb - va;
          return tieBreakExpiryTypeStrike(a, b);
        }
        case "last_desc": {
          const la = mergedContractLastSortKey(a);
          const lb = mergedContractLastSortKey(b);
          if (lb !== la) return lb - la;
          return tieBreakExpiryTypeStrike(a, b);
        }
        default:
          return sortMergedDefault(a, b);
      }
    });
  }, [mergedChain, selectedExpiry, optionTypeFilter, hideZeroVolume, panelSort]);

  const panelFilteredEmptyHint = useMemo(() => {
    if (loadingChain || errorChain) return null;
    const raw = mergedChain?.contracts ?? [];
    if (raw.length === 0) return null;
    if (mergedFilteredContracts.length > 0) return null;
    if (hideZeroVolume) {
      const allVolZero = raw.every((c) => mergedContractVolume(c) <= 0);
      if (allVolZero) {
        return "No hay contratos con volumen > 0 para estos filtros. Desactivá «Ocultar volumen 0» para ver la cadena.";
      }
    }
    return "Sin resultados con los filtros actuales.";
  }, [loadingChain, errorChain, mergedChain, mergedFilteredContracts.length, hideZeroVolume]);

  const volumeFilterHidesAllIolRows = useMemo(() => {
    if (!hideZeroVolume) return false;
    const raw = mergedChain?.contracts ?? [];
    if (raw.length === 0) return false;
    return raw.every((c) => mergedContractVolume(c) <= 0);
  }, [hideZeroVolume, mergedChain]);

  const strategyRows = useMemo((): FlatRow[] => {
    const rows: FlatRow[] = [];
    for (const c of mergedChain?.contracts ?? []) {
      const ot = mergedContractTypeUpper(c);
      const tipo: "CALL" | "PUT" | null = ot.includes("CALL") ? "CALL" : ot.includes("PUT") ? "PUT" : null;
      if (!tipo) continue;
      const strike = typeof c.strike === "number" && Number.isFinite(c.strike) ? c.strike : null;
      if (strike === null) continue;
      const expiryKey = expiryKeyFromMergedContract(c);
      rows.push({
        activo: selectedUnderlying,
        tipo,
        strike,
        expiryCode: expiryKey,
        raw: {
          simbolo: c.symbol,
          expiry_date: c.expiry,
          bid: c.bid,
          ask: c.ask,
          ultimo: c.last,
          volumen_float: c.volume,
          open_interest: c.open_interest,
          source: c.source,
          field_sources: c.field_sources,
        },
      });
    }
    rows.sort((a, b) => a.strike - b.strike);
    return rows;
  }, [mergedChain, selectedUnderlying]);

  const filteredRows = useMemo(() => {
    return strategyRows.filter((r) => {
      const o = r.raw;
      if (selectedExpiry) {
        const k = r.expiryCode;
        if (!k) return false;
        if (k !== selectedExpiry) return false;
      }
      if (onlyWithVolume) {
        const vf = toNumberOrNull(o.volumen_float);
        if (vf === null || vf <= 0) return false;
      }
      if (onlyWithTrades) {
        const last = toNumberOrNull(o.ultimo);
        if (last === null || last <= 0) return false;
      }
      if (onlyAtm) {
        const m = getMoneynessFromValues(r.strike, r.tipo, effectivePanelSpot);
        if (m !== "ATM") return false;
      }
      return true;
    });
  }, [strategyRows, selectedExpiry, onlyWithVolume, onlyWithTrades, onlyAtm, effectivePanelSpot]);

  const calls = useMemo(
    () => filteredRows.filter((r) => r.tipo === "CALL").slice().sort((a, b) => a.strike - b.strike),
    [filteredRows],
  );
  const puts = useMemo(
    () => filteredRows.filter((r) => r.tipo === "PUT").slice().sort((a, b) => a.strike - b.strike),
    [filteredRows],
  );

  const bullCallSpreads = useMemo(() => {
    // Combos: BUY call (ask) en strike menor, SELL call (bid) en strike mayor, mismo vencimiento.
    // Filtramos débito > 0 y ganancia máxima > 0.
    type CallRow = {
      expiryKey: string;
      strike: number;
      ask: number | null;
      bid: number | null;
    };
    const byExp = new Map<string, CallRow[]>();
    for (const r of calls) {
      const exp = expiryKeyFromRaw(r.raw);
      if (!exp) continue;
      const ask = toNumberOrNull(r.raw.ask);
      const bid = toNumberOrNull(r.raw.bid);
      const arr = byExp.get(exp) ?? [];
      arr.push({ expiryKey: exp, strike: r.strike, ask, bid });
      byExp.set(exp, arr);
    }
    const out: {
      expiryKey: string;
      buyStrike: number;
      sellStrike: number;
      buyAsk: number;
      sellBid: number;
      debit: number;
      maxGain: number;
      maxLoss: number;
      breakEven: number;
    }[] = [];
    const expiries = Array.from(byExp.keys()).sort();
    for (const exp of expiries) {
      const arr = (byExp.get(exp) ?? []).slice().sort((a, b) => a.strike - b.strike);
      for (let i = 0; i < arr.length; i++) {
        const buy = arr[i];
        if (buy.ask === null || buy.ask <= 0) continue;
        for (let j = i + 1; j < arr.length; j++) {
          const sell = arr[j];
          if (sell.bid === null || sell.bid <= 0) continue;
          const debit = buy.ask - sell.bid;
          if (!(debit > 0)) continue;
          const width = sell.strike - buy.strike;
          if (!(width > 0)) continue;
          const maxGain = width - debit;
          if (!(maxGain > 0)) continue;
          out.push({
            expiryKey: exp,
            buyStrike: buy.strike,
            sellStrike: sell.strike,
            buyAsk: buy.ask,
            sellBid: sell.bid,
            debit,
            maxGain,
            maxLoss: debit,
            breakEven: buy.strike + debit,
          });
        }
      }
    }
    out.sort((a, b) => a.expiryKey.localeCompare(b.expiryKey) || a.buyStrike - b.buyStrike || a.sellStrike - b.sellStrike);
    return out.slice(0, 30);
  }, [calls]);

  const coveredCalls = useMemo(() => {
    const out: {
      expiryKey: string;
      strike: number;
      bid: number;
      intrinsic: number | null;
      timeValue: number | null;
      days: number | null;
      tnaPct: number | null;
      breakEven: number | null;
      moneyness: string | null;
    }[] = [];
    for (const r of calls) {
      const exp = expiryKeyFromRaw(r.raw);
      if (!exp) continue;
      const bid = toNumberOrNull(r.raw.bid);
      if (bid === null || bid <= 0) continue;
      const days = daysToExpiryRaw(r.raw);
      const breakEven = effectivePanelSpot !== null ? effectivePanelSpot - bid : null;

      const intrinsic =
        effectivePanelSpot !== null && effectivePanelSpot > 0
          ? Math.max(0, effectivePanelSpot - r.strike)
          : null;
      const timeValue =
        intrinsic !== null
          ? bid - intrinsic
          : null;

      const tnaPct =
        effectivePanelSpot !== null &&
          effectivePanelSpot > 0 &&
          days !== null &&
          days > 0 &&
          timeValue !== null &&
          timeValue > 0
          ? (timeValue / effectivePanelSpot) * (365 / days) * 100
          : null;
      out.push({
        expiryKey: exp,
        strike: r.strike,
        bid,
        intrinsic,
        timeValue,
        days,
        tnaPct,
        breakEven,
        moneyness: moneyStatus(r.raw),
      });
    }
    out.sort((a, b) => a.expiryKey.localeCompare(b.expiryKey) || a.strike - b.strike);
    return out.slice(0, 30);
  }, [calls, effectivePanelSpot]);

  const netCost = useMemo(() => {
    let net = 0;
    let ok = false;
    for (const leg of selectedLegs) {
      const p = legPriceUsed(leg);
      if (p === null) continue;
      ok = true;
      net += leg.action === "BUY" ? -p : p;
    }
    return { ok, net };
  }, [selectedLegs]);

  return (
    <div className="page options-page">
      <header className="page__header">
        <h1>Opciones</h1>
        <p className="page__subtitle">
          Panel: cadena unificada. Estrategias: misma cadena del panel. Activo: <strong>{selectedUnderlying}</strong>
        </p>
        {chainIsIolPrimary && !loadingChain && !errorChain ? (
          <p className="page__subtitle" style={{ marginTop: "0.35rem", fontWeight: 600 }}>
            Universo operable: IOL
          </p>
        ) : null}
      </header>

      <div className="radar-toolbar options-toolbar" role="toolbar" aria-label="Opciones de cadena">
        <label className="radar-toolbar__field">
          <span className="radar-toolbar__label">Activo</span>
          <select
            className="radar-toolbar__select"
            value={selectedUnderlying}
            onChange={(ev) => setSelectedUnderlying(ev.target.value)}
            aria-label="Activo subyacente"
          >
            {CHAIN_UNDERLYINGS.map((u) => (
              <option key={u.value} value={u.value}>
                {u.label}
              </option>
            ))}
          </select>
        </label>
        <label className="radar-toolbar__field">
          <span className="radar-toolbar__label">Vencimiento</span>
          <select
            className="radar-toolbar__select"
            value={selectedExpiry}
            onChange={(ev) => setSelectedExpiry(ev.target.value)}
            disabled={expiryOptions.length === 0}
            aria-label="Vencimiento"
          >
            <option value="">Todos los vencimientos</option>
            {expiryOptions.map((k) => (
              <option key={k} value={k}>
                {formatExpiryMonthLabel(k)}
              </option>
            ))}
          </select>
        </label>
        {activeTab === "panel" ? (
          <>
            <label className="radar-toolbar__field">
              <span className="radar-toolbar__label">Tipo</span>
              <select
                className="radar-toolbar__select"
                value={optionTypeFilter}
                onChange={(ev) => setOptionTypeFilter(ev.target.value as OptionTypeFilter)}
                aria-label="Tipo de opción"
              >
                <option value="all">Todas</option>
                <option value="CALL">CALL</option>
                <option value="PUT">PUT</option>
              </select>
            </label>
            <label className="radar-toolbar__field" style={{ flexDirection: "row", alignItems: "center", gap: "0.45rem" }}>
              <input
                type="checkbox"
                checked={hideZeroVolume}
                onChange={(ev) => setHideZeroVolume(ev.target.checked)}
                aria-label="Ocultar contratos con volumen 0"
              />
              <span className="radar-toolbar__label" style={{ margin: 0 }}>
                Ocultar volumen 0
              </span>
            </label>
            <label className="radar-toolbar__field">
              <span className="radar-toolbar__label">Ordenar por</span>
              <select
                className="radar-toolbar__select"
                value={panelSort}
                onChange={(ev) => setPanelSort(ev.target.value as PanelSortMode)}
                aria-label="Ordenar tabla"
              >
                <option value="expiry_type_strike">Vencimiento / Tipo / Strike</option>
                <option value="symbol">Símbolo</option>
                <option value="volume_desc">Volumen mayor a menor</option>
                <option value="last_desc">Último mayor a menor</option>
              </select>
            </label>
            <label className="radar-toolbar__field">
              <span className="radar-toolbar__label">Spot manual</span>
              <input
                className="radar-toolbar__select"
                type="number"
                inputMode="decimal"
                step="any"
                min="0"
                placeholder={apiChainSpot !== null ? String(apiChainSpot) : "Ej. 8500"}
                value={manualSpotInput}
                onChange={(ev) => setManualSpotInput(ev.target.value)}
                aria-label="Spot manual (opcional; prioridad sobre el del servidor)"
                style={{ minWidth: "7rem" }}
              />
            </label>
          </>
        ) : null}
        {activeTab === "strategies" ? (
          <div className="radar-toolbar__field" style={{ gap: "0.45rem" }}>
            <span className="radar-toolbar__label">Filtros (Rava)</span>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
              <button
                type="button"
                className={`options-filter-toggle${onlyWithVolume ? " options-filter-toggle-active" : ""}`}
                aria-pressed={onlyWithVolume}
                onClick={() => setOnlyWithVolume((v) => !v)}
              >
                Con volumen{mergedChain?.contracts?.length ? ` (${formatInteger(filterCounts.withVolume)})` : ""}
              </button>
              <button
                type="button"
                className={`options-filter-toggle${onlyWithTrades ? " options-filter-toggle-active" : ""}`}
                aria-pressed={onlyWithTrades}
                onClick={() => setOnlyWithTrades((v) => !v)}
              >
                Con operaciones{mergedChain?.contracts?.length ? ` (${formatInteger(filterCounts.withTrades)})` : ""}
              </button>
              <button
                type="button"
                className={`options-filter-toggle${onlyAtm ? " options-filter-toggle-active" : ""}`}
                aria-pressed={onlyAtm}
                onClick={() => setOnlyAtm((v) => !v)}
              >
                Solo ATM{mergedChain?.contracts?.length ? ` (${formatInteger(filterCounts.withAtm)})` : ""}
              </button>
            </div>
          </div>
        ) : null}
      </div>

      <div className="options-tabs" role="tablist" aria-label="Secciones de opciones">
        <button
          type="button"
          className={`options-tab${activeTab === "panel" ? " options-tab-active" : ""}`}
          role="tab"
          aria-selected={activeTab === "panel"}
          onClick={() => {
            setActiveTab("panel");
            setSelectedExpiry("");
          }}
        >
          PANEL
        </button>
        <button
          type="button"
          className={`options-tab${activeTab === "strategies" ? " options-tab-active" : ""}`}
          role="tab"
          aria-selected={activeTab === "strategies"}
          onClick={() => {
            setActiveTab("strategies");
            setSelectedExpiry("");
          }}
        >
          ESTRATEGIAS
        </button>
      </div>

      <div className="options-underlying-card" aria-label="Subyacente">
        <div style={{ display: "flex", flexDirection: "column", gap: "0.15rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
            <div className="options-underlying-label" style={{ margin: 0 }}>
              Subyacente
            </div>
            <div className="options-underlying-symbol">
              <code>{mergedChain?.underlying ?? selectedUnderlying}</code>
            </div>
          </div>
          <div className="options-underlying-meta">
            <span className={signalBadgeClass} title="SignalState">
              {loadingUnderlyingContext ? "Signal: …" : `Signal: ${underlyingSignal?.trim() ? underlyingSignal : "-"}`}
            </span>
            <span className={trendBadgeClass} title="Tendencia">
              {loadingUnderlyingContext ? "Tendencia: …" : `Tendencia: ${underlyingTrendLabel}`}
            </span>
            <span className="options-underlying-badge options-underlying-badge-neutral" title="Ticker en Radar Argentina">
              Radar: {underlyingRadarSymbol}
            </span>
            {activeTab === "strategies" ? (
              <span className="options-underlying-badge options-underlying-badge-neutral" title="Ticker Rava (cadena)">
                Rava: {selectedUnderlyingMeta.ravaUnderlying}
              </span>
            ) : null}
            {selectedUnderlyingMeta.label !== selectedUnderlying ? (
              <span className="options-underlying-badge options-underlying-badge-neutral" title="Etiqueta visible">
                Label: {selectedUnderlyingMeta.label}
              </span>
            ) : null}
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "0.15rem" }}>
          <div className="options-underlying-label">Precio subyacente</div>
          <div className="options-underlying-price" style={{ textAlign: "right" }}>
            {effectivePanelSpot !== null && effectivePanelSpot > 0 ? (
              <>
                {(mergedChain?.spot_symbol ?? "").trim() || selectedUnderlying} ={" "}
                {formatNumber(effectivePanelSpot, 2)}
                {parsedManualSpot !== null ? (
                  <> (manual)</>
                ) : mergedChain?.spot_source ? (
                  <> ({mergedChain.spot_source})</>
                ) : null}
              </>
            ) : (
              <span className="msg-muted">Precio subyacente no disponible</span>
            )}
          </div>
        </div>
      </div>

      <div className="msg-muted" style={{ marginTop: "0.25rem" }}>
        <div>
          {chainIsIolPrimary
            ? mergedChain?.enrich_sources === true
              ? "Cadena operable desde IOL (Allaria/Rava enriquecen campos por contrato). "
              : "Cadena operable desde IOL (enriquecimiento Allaria/Rava desactivado). "
            : "Cadena desde el backend (Allaria + Rava). "}
          {mergedChain && !loadingChain && !errorChain ? (
            <span>
              <strong>Subyacente (normalizado):</strong> {mergedChain.underlying}
              {" — "}
              <strong>Spot subyacente:</strong>{" "}
              {effectivePanelSpot !== null && effectivePanelSpot > 0 ? (
                <>$ {formatNumber(effectivePanelSpot, 2)}</>
              ) : (
                <em>Precio subyacente no disponible</em>
              )}
              {" — "}
              <strong>Fuente:</strong>{" "}
              {parsedManualSpot !== null ? "manual" : (mergedChain.spot_source ?? "—")}
              {mergedChain.spot_symbol ? (
                <>
                  {" "}
                  (<code>{mergedChain.spot_symbol}</code>)
                </>
              ) : null}
              {" — "}
              <strong>Total contratos:</strong> {mergedChain.total}
              {activeTab === "panel" ? (
                <>
                  {" — "}
                  <strong>Filtrados:</strong> {mergedFilteredContracts.length}
                  {hideZeroVolume ? (
                    <>
                      {" — "}
                      <em>Ocultando volumen 0</em>
                    </>
                  ) : null}
                </>
              ) : null}
            </span>
          ) : null}
        </div>
        {activeTab === "strategies" ? (
          <div style={{ marginTop: "0.35rem" }}>
            Estrategias usan la misma cadena que el Panel (universo operable).{" "}
            {chainIsIolPrimary ? (
              <strong>Estrategias calculadas sobre universo IOL</strong>
            ) : (
              <strong>Estrategias calculadas sobre fallback Allaria/Rava</strong>
            )}
            {!loadingChain && !errorChain && (strategyRows.length > 0 || (mergedChain?.contracts.length ?? 0) > 0) ? (
              <div style={{ marginTop: "0.35rem" }}>
                <strong>Total contratos:</strong> {mergedChain?.total ?? strategyRows.length}
                {expirySummary.length > 0 ? (
                  <span>
                    {" "}
                    — <strong>Vencimientos:</strong>{" "}
                    {expirySummary.map((it, idx) => (
                      <span key={it.key}>
                        {idx ? " · " : ""}
                        {it.label}: {it.count}
                      </span>
                    ))}
                  </span>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      {loadingChain && <p>Cargando cadena…</p>}
      {errorChain && (
        <p role="alert">
          Error cadena: {errorChain}
        </p>
      )}
      {activeTab === "panel" && emptyHintPanel && <p>{emptyHintPanel}</p>}
      {activeTab === "panel" && panelFilteredEmptyHint ? (
        <div className="msg-muted" style={{ marginTop: "0.35rem" }}>
          <p style={{ marginBottom: "0.35rem" }}>{panelFilteredEmptyHint}</p>
          {volumeFilterHidesAllIolRows && mergedFilteredContracts.length === 0 ? (
            <button type="button" className="options-filter-toggle" onClick={() => setHideZeroVolume(false)}>
              Mostrar contratos sin volumen
            </button>
          ) : null}
        </div>
      ) : null}

      {activeTab === "panel" && !loadingChain && !errorChain && mergedFilteredContracts.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Símbolo</th>
                <th>Vencimiento</th>
                <th>Tipo</th>
                <th>Strike</th>
                <th>Moneyness</th>
                <th>Bid</th>
                <th>Ask</th>
                <th>Último</th>
                <th>Volumen</th>
                <th>OI</th>
                <th>Fuente</th>
              </tr>
            </thead>
            <tbody>
              {mergedFilteredContracts.map((c, i) => {
                const m = getMoneyness(c, effectivePanelSpot);
                return (
                  <tr key={`${c.symbol}-${i}`} className={mergedMoneynessRowClass(m)}>
                    <td>{fmtCell(c.symbol)}</td>
                    <td>{expiryKeyFromMergedContract(c) || "—"}</td>
                    <td>{fmtCell(c.option_type)}</td>
                    <td style={{ textAlign: "right" }}>{formatNumber(c.strike, 2)}</td>
                    <td>
                      <span className={mergedMoneynessBadgeClass(m)}>{mergedMoneynessBadgeText(m)}</span>
                    </td>
                    <td style={{ textAlign: "right" }}>{formatNumber(c.bid, 2)}</td>
                    <td style={{ textAlign: "right" }}>{formatNumber(c.ask, 2)}</td>
                    <td style={{ textAlign: "right" }}>{formatNumber(c.last, 2)}</td>
                    <td style={{ textAlign: "right" }}>{formatInteger(c.volume)}</td>
                    <td style={{ textAlign: "right" }}>{formatInteger(c.open_interest)}</td>
                    <td>{fmtCell(c.source)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      {activeTab === "strategies" ? (
        <div>
          {loadingChain && <p>Cargando cadena…</p>}
          {errorChain && (
            <p role="alert">
              Error: {errorChain}
            </p>
          )}
          {emptyHintStrategies && !loadingChain && !errorChain && <p>{emptyHintStrategies}</p>}
          <section className="options-strategy-panel" aria-label="Crear estrategia manual">
              <button
                type="button"
                className="strategy-collapsible-header"
                onClick={() => setShowManualStrategy((v) => !v)}
                aria-expanded={showManualStrategy}
              >
                <div className="strategy-collapsible-title">
                  <span style={{ width: "1.15rem", display: "inline-block" }}>
                    {showManualStrategy ? "−" : "+"}
                  </span>
                  Crear estrategia manual
                </div>
                <div className="strategy-collapsible-summary">
                  {selectedLegs.length} patas
                </div>
              </button>

              {showManualStrategy ? (
                <div className="strategy-collapsible-body">
                  <div
                    style={{
                      display: "flex",
                      alignItems: "baseline",
                      justifyContent: "space-between",
                      gap: "0.75rem",
                      flexWrap: "wrap",
                    }}
                  >
                    <div className="msg-muted" style={{ marginTop: 0 }}>
                      {strategyHelpText(strategyType)}
                    </div>
                    <button type="button" className="options-filter-toggle" onClick={() => setSelectedLegs([])}>
                      Limpiar estrategia
                    </button>
                  </div>

                  <div style={{ display: "flex", flexWrap: "wrap", gap: "0.85rem 1.25rem", marginTop: "0.75rem" }}>
                    <label className="radar-toolbar__field" style={{ margin: 0 }}>
                      <span className="radar-toolbar__label">Tipo de estrategia</span>
                      <select
                        className="radar-toolbar__select"
                        value={strategyType}
                        onChange={(ev) => setStrategyType(ev.target.value as StrategyType)}
                      >
                        <option value="Bull Call Spread">Bull Call Spread</option>
                        <option value="Bear Put Spread">Bear Put Spread</option>
                        <option value="Covered Call">Covered Call</option>
                        <option value="Protective Put">Protective Put</option>
                        <option value="Collar">Collar</option>
                      </select>
                    </label>
                    <div className="radar-toolbar__field" style={{ margin: 0 }}>
                      <span className="radar-toolbar__label">Modo</span>
                      <div style={{ padding: "0.45rem 0" }}>
                        <strong>Manual</strong>
                      </div>
                    </div>
                    <div className="radar-toolbar__field" style={{ margin: 0 }}>
                      <span className="radar-toolbar__label">Patas</span>
                      <div style={{ padding: "0.45rem 0" }}>
                        <strong>{selectedLegs.length}</strong>
                      </div>
                    </div>
                    <div className="radar-toolbar__field strategy-net-cost" style={{ margin: 0 }}>
                      <span className="radar-toolbar__label">Costo neto estimado</span>
                      <div style={{ padding: "0.45rem 0" }}>
                        {netCost.ok ? (
                          <strong>
                            {netCost.net < 0 ? "Débito" : netCost.net > 0 ? "Crédito" : "Neto"}{" "}
                            {netCost.net !== 0 ? `$ ${formatNumber(Math.abs(netCost.net), 2)}` : "$ 0,00"}
                          </strong>
                        ) : (
                          <span className="msg-muted">—</span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div style={{ marginTop: "0.75rem" }}>
                    <div className="options-section-title" style={{ marginBottom: "0.35rem" }}>
                      Patas seleccionadas
                    </div>
                    {selectedLegs.length === 0 ? (
                      <div className="msg-muted">Agregá patas desde las tablas CALLS/PUTS de esta pestaña (cadena Rava) con el botón “Agregar”.</div>
                    ) : (
                      <div className="table-wrap">
                        <table className="strategy-leg-table">
                          <thead>
                            <tr>
                              <th>Acción</th>
                              <th>Tipo</th>
                              <th>Ticker</th>
                              <th>Vencimiento</th>
                              <th>Strike</th>
                              <th>Precio usado</th>
                              <th></th>
                            </tr>
                          </thead>
                          <tbody>
                            {selectedLegs.map((leg) => {
                              const k = legKey(leg);
                              const p = legPriceUsed(leg);
                              return (
                                <tr key={k}>
                                  <td className="strategy-leg-action">
                                    <select
                                      className="radar-toolbar__select"
                                      value={leg.action}
                                      onChange={(ev) => {
                                        const nextAction = ev.target.value as LegAction;
                                        setSelectedLegs((prev) => {
                                          const next = prev.map((x) => (legKey(x) === k ? { ...x, action: nextAction } : x));
                                          const seen = new Set<string>();
                                          return next.filter((x) => {
                                            const kk = legKey(x);
                                            if (seen.has(kk)) return false;
                                            seen.add(kk);
                                            return true;
                                          });
                                        });
                                      }}
                                    >
                                      <option value="BUY">Comprar</option>
                                      <option value="SELL">Vender</option>
                                    </select>
                                  </td>
                                  <td>{leg.tipo}</td>
                                  <td>{leg.symbol ? leg.symbol : "—"}</td>
                                  <td>{leg.expiry_date ? leg.expiry_date.slice(0, 10) : "—"}</td>
                                  <td style={{ textAlign: "right" }}>{leg.strike !== null ? formatNumber(leg.strike, 2) : "-"}</td>
                                  <td style={{ textAlign: "right" }}>{p !== null ? `$ ${formatNumber(p, 2)}` : "-"}</td>
                                  <td style={{ textAlign: "right" }}>
                                    <button
                                      type="button"
                                      className="option-add-leg-button"
                                      onClick={() => setSelectedLegs((prev) => prev.filter((x) => legKey(x) !== k))}
                                    >
                                      Quitar
                                    </button>
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>

                  <div style={{ marginTop: "0.95rem" }}>
                    <div className="options-section-title" style={{ marginBottom: "0.35rem" }}>
                      Agregar patas (desde la cadena)
                    </div>
                    <div className="msg-muted" style={{ marginBottom: "0.5rem" }}>
                      Usá estos botones para sumar patas al constructor manual.
                    </div>
                    <div className="table-wrap">
                      <table className="strategy-leg-table">
                        <thead>
                          <tr>
                            <th></th>
                            <th>Tipo</th>
                            <th>Ticker</th>
                            <th>Vencimiento</th>
                            <th style={{ textAlign: "right" }}>Strike</th>
                            <th style={{ textAlign: "right" }}>Bid</th>
                            <th style={{ textAlign: "right" }}>Ask</th>
                            <th style={{ textAlign: "right" }}>Último</th>
                            <th>Moneyness</th>
                          </tr>
                        </thead>
                        <tbody>
                          {calls.slice(0, 40).map((r, i) => {
                            const o = r.raw;
                            const key = `add-calls-${r.expiryCode}-${r.strike}-${i}`;
                            const canAdd = typeof o.simbolo === "string" && o.simbolo.trim();
                            const m = getMoneynessFromValues(r.strike, r.tipo, effectivePanelSpot);
                            return (
                              <tr key={key} className={mergedMoneynessRowClass(m)}>
                                <td style={{ whiteSpace: "nowrap" }}>
                                  <button
                                    type="button"
                                    className="option-add-leg-button"
                                    disabled={!canAdd}
                                    onClick={() => {
                                      const leg = buildLegFromRow(r);
                                      if (!leg.symbol) return;
                                      setSelectedLegs((prev) => {
                                        const kk = legKey(leg);
                                        if (prev.some((x) => legKey(x) === kk)) return prev;
                                        return [...prev, leg];
                                      });
                                    }}
                                  >
                                    Agregar
                                  </button>
                                </td>
                                <td>{r.tipo}</td>
                                <td>{fmtCell(o.simbolo)}</td>
                                <td>{fmtCell(o.expiry_date)}</td>
                                <td style={{ textAlign: "right" }}>{formatNumber(r.strike, 2)}</td>
                                <td style={{ textAlign: "right" }}>{formatNumber(toNumberOrNull(o.bid), 2)}</td>
                                <td style={{ textAlign: "right" }}>{formatNumber(toNumberOrNull(o.ask), 2)}</td>
                                <td style={{ textAlign: "right" }}>{formatNumber(toNumberOrNull(o.ultimo), 2)}</td>
                                <td>
                                  <span className={mergedMoneynessBadgeClass(m)}>{mergedMoneynessBadgeText(m)}</span>
                                </td>
                              </tr>
                            );
                          })}
                          {puts.slice(0, 40).map((r, i) => {
                            const o = r.raw;
                            const key = `add-puts-${r.expiryCode}-${r.strike}-${i}`;
                            const canAdd = typeof o.simbolo === "string" && o.simbolo.trim();
                            const m = getMoneynessFromValues(r.strike, r.tipo, effectivePanelSpot);
                            return (
                              <tr key={key} className={mergedMoneynessRowClass(m)}>
                                <td style={{ whiteSpace: "nowrap" }}>
                                  <button
                                    type="button"
                                    className="option-add-leg-button"
                                    disabled={!canAdd}
                                    onClick={() => {
                                      const leg = buildLegFromRow(r);
                                      if (!leg.symbol) return;
                                      setSelectedLegs((prev) => {
                                        const kk = legKey(leg);
                                        if (prev.some((x) => legKey(x) === kk)) return prev;
                                        return [...prev, leg];
                                      });
                                    }}
                                  >
                                    Agregar
                                  </button>
                                </td>
                                <td>{r.tipo}</td>
                                <td>{fmtCell(o.simbolo)}</td>
                                <td>{fmtCell(o.expiry_date)}</td>
                                <td style={{ textAlign: "right" }}>{formatNumber(r.strike, 2)}</td>
                                <td style={{ textAlign: "right" }}>{formatNumber(toNumberOrNull(o.bid), 2)}</td>
                                <td style={{ textAlign: "right" }}>{formatNumber(toNumberOrNull(o.ask), 2)}</td>
                                <td style={{ textAlign: "right" }}>{formatNumber(toNumberOrNull(o.ultimo), 2)}</td>
                                <td>
                                  <span className={mergedMoneynessBadgeClass(m)}>{mergedMoneynessBadgeText(m)}</span>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  <div className="payoff-placeholder" style={{ marginTop: "0.85rem" }}>
                    <div className="options-section-title" style={{ marginBottom: "0.25rem" }}>
                      Gráfico de payoff
                    </div>
                    <div className="msg-muted">Próximamente: ganancia/pérdida y break even según patas seleccionadas.</div>
                  </div>
                </div>
              ) : null}
            </section>

            <section className="strategy-section" aria-label="Oportunidades prearmadas">
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-end",
                  justifyContent: "space-between",
                  gap: "0.75rem",
                  flexWrap: "wrap",
                }}
              >
                <h2 style={{ margin: 0 }}>Oportunidades</h2>
                <label className="radar-toolbar__field" style={{ margin: 0 }}>
                  <span className="radar-toolbar__label">Tipo de estrategia</span>
                  <select
                    className="radar-toolbar__select"
                    value={strategiesFilter}
                    onChange={(ev) => setStrategiesFilter(ev.target.value as StrategiesFilter)}
                  >
                    <option value="">Todas</option>
                    <option value="Bull Call Spread">Bull Call Spread</option>
                    <option value="Covered Call">Covered Call</option>
                  </select>
                </label>
              </div>

              {strategiesFilter === "" || strategiesFilter === "Bull Call Spread" ? (
                <div style={{ marginTop: "0.75rem" }}>
                  <button
                    type="button"
                    className="strategy-collapsible-header"
                    onClick={() => setShowBullCallSpread((v) => !v)}
                    aria-expanded={showBullCallSpread}
                  >
                    <div className="strategy-collapsible-title">
                      <span style={{ width: "1.15rem", display: "inline-block" }}>
                        {showBullCallSpread ? "−" : "+"}
                      </span>
                      Bull Call Spread
                    </div>
                    <div className="strategy-collapsible-summary">
                      {bullCallSpreads.length} oportunidades
                    </div>
                  </button>
                  {showBullCallSpread ? (
                    <div className="strategy-collapsible-body">
                      {bullCallSpreads.length === 0 ? (
                        <div className="msg-muted">Sin combinaciones válidas con el feed actual.</div>
                      ) : (
                        <div className="table-wrap">
                          <table className="strategy-opportunities-table">
                            <thead>
                              <tr>
                                <th>Vencimiento</th>
                                <th style={{ textAlign: "right" }}>Strike compra</th>
                                <th style={{ textAlign: "right" }}>Strike venta</th>
                                <th style={{ textAlign: "right" }}>Prima compra</th>
                                <th style={{ textAlign: "right" }}>Prima venta</th>
                                <th style={{ textAlign: "right" }}>Débito neto</th>
                                <th style={{ textAlign: "right" }}>Ganancia máx.</th>
                                <th style={{ textAlign: "right" }}>Pérdida máx.</th>
                                <th style={{ textAlign: "right" }}>Break even</th>
                                <th>Moneyness</th>
                              </tr>
                            </thead>
                            <tbody>
                              {bullCallSpreads.map((x, idx) => {
                                const mBuy = getMoneynessFromValues(x.buyStrike, "CALL", effectivePanelSpot);
                                const mSell = getMoneynessFromValues(x.sellStrike, "CALL", effectivePanelSpot);
                                return (
                                <tr key={`${x.expiryKey}-${x.buyStrike}-${x.sellStrike}-${idx}`} className={mergedMoneynessRowClass(mBuy)}>
                                  <td>{formatExpiryMonthLabel(x.expiryKey)}</td>
                                  <td style={{ textAlign: "right" }}>{formatNumber(x.buyStrike, 2)}</td>
                                  <td style={{ textAlign: "right" }}>{formatNumber(x.sellStrike, 2)}</td>
                                  <td style={{ textAlign: "right" }}>{formatNumber(x.buyAsk, 2)}</td>
                                  <td style={{ textAlign: "right" }}>{formatNumber(x.sellBid, 2)}</td>
                                  <td style={{ textAlign: "right" }}>{formatNumber(x.debit, 2)}</td>
                                  <td style={{ textAlign: "right" }}>{formatNumber(x.maxGain, 2)}</td>
                                  <td style={{ textAlign: "right" }}>{formatNumber(x.maxLoss, 2)}</td>
                                  <td style={{ textAlign: "right" }}>{formatNumber(x.breakEven, 2)}</td>
                                  <td>
                                    <span className={mergedMoneynessBadgeClass(mBuy)} title="Strike compra (call)">
                                      C {mergedMoneynessBadgeText(mBuy)}
                                    </span>
                                    <span className="msg-muted" style={{ margin: "0 0.2rem" }}>
                                      ·
                                    </span>
                                    <span className={mergedMoneynessBadgeClass(mSell)} title="Strike venta (call)">
                                      V {mergedMoneynessBadgeText(mSell)}
                                    </span>
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
                </div>
              ) : null}

              {strategiesFilter === "" || strategiesFilter === "Covered Call" ? (
                <div style={{ marginTop: "0.95rem" }}>
                  <button
                    type="button"
                    className="strategy-collapsible-header"
                    onClick={() => setShowCoveredCall((v) => !v)}
                    aria-expanded={showCoveredCall}
                  >
                    <div className="strategy-collapsible-title">
                      <span style={{ width: "1.15rem", display: "inline-block" }}>
                        {showCoveredCall ? "−" : "+"}
                      </span>
                      Covered Call
                    </div>
                    <div className="strategy-collapsible-summary">
                      {coveredCalls.length} oportunidades
                    </div>
                  </button>
                  {showCoveredCall ? (
                    <div className="strategy-collapsible-body">
                      {coveredCalls.length === 0 ? (
                        <div className="msg-muted">Sin calls con bid &gt; 0 en el feed actual.</div>
                      ) : (
                        <div className="table-wrap">
                          <table className="strategy-opportunities-table">
                            <thead>
                              <tr>
                                <th>Vencimiento</th>
                                <th style={{ textAlign: "right" }}>Subyacente</th>
                                <th style={{ textAlign: "right" }}>Strike</th>
                                <th style={{ textAlign: "right" }}>Prima</th>
                                <th style={{ textAlign: "right" }}>Intrínseco</th>
                                <th style={{ textAlign: "right" }}>Valor tiempo</th>
                                <th style={{ textAlign: "right" }}>Días</th>
                                <th style={{ textAlign: "right" }} title="TNA calculada solo sobre valor tiempo">
                                  TNA
                                </th>
                                <th style={{ textAlign: "right" }}>Break even</th>
                                <th>Moneyness</th>
                              </tr>
                            </thead>
                            <tbody>
                              {coveredCalls.map((x, idx) => {
                                const m = getMoneynessFromValues(x.strike, "CALL", effectivePanelSpot);
                                return (
                                <tr key={`${x.expiryKey}-${x.strike}-${idx}`} className={mergedMoneynessRowClass(m)}>
                                  <td>{formatExpiryMonthLabel(x.expiryKey)}</td>
                                  <td style={{ textAlign: "right" }}>
                                    {effectivePanelSpot !== null ? formatNumber(effectivePanelSpot, 2) : "-"}
                                  </td>
                                  <td style={{ textAlign: "right" }}>{formatNumber(x.strike, 2)}</td>
                                  <td style={{ textAlign: "right" }}>{formatNumber(x.bid, 2)}</td>
                                  <td style={{ textAlign: "right", color: "var(--text-muted)" }}>
                                    {x.intrinsic !== null && x.intrinsic > 0 ? formatNumber(x.intrinsic, 2) : "-"}
                                  </td>
                                  <td
                                    style={{
                                      textAlign: "right",
                                      color:
                                        x.timeValue !== null && x.timeValue > 0
                                          ? "rgba(22, 163, 74, 0.9)"
                                          : "var(--text-muted)",
                                    }}
                                  >
                                    {x.timeValue !== null && x.timeValue > 0 ? formatNumber(x.timeValue, 2) : "-"}
                                  </td>
                                  <td style={{ textAlign: "right" }}>
                                    {x.days !== null ? formatInteger(x.days) : "-"}
                                  </td>
                                  <td style={{ textAlign: "right" }}>
                                    {x.tnaPct !== null ? `${formatNumber(x.tnaPct, 2)}%` : "-"}
                                  </td>
                                  <td style={{ textAlign: "right" }}>
                                    {x.breakEven !== null ? formatNumber(x.breakEven, 2) : "-"}
                                  </td>
                                  <td>
                                    <span className={mergedMoneynessBadgeClass(m)}>{mergedMoneynessBadgeText(m)}</span>
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
                </div>
              ) : null}

              <div className="msg-muted" style={{ marginTop: "0.9rem" }}>
                Próximamente: Bear Put Spread, Protective Put, Collar.
              </div>
            </section>
        </div>
      ) : null}
    </div>
  );
}
