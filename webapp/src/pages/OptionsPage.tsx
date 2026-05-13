import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  fetchIolStatus,
  fetchIvSmile,
  fetchLatestRadarArgentina,
  fetchOptionsChain,
  fetchOptionsQuotes,
  postIolReconnect,
  type IolOptionQuotePayload,
  type IolStatusPayload,
  type IvSmileGroup,
  type IvSmilePoint,
  type OptionContractRow,
  type OptionsChainResponse,
  type RadarRow,
} from "@/services/api";
import { formatTrend, getRaw } from "@/components/radar/radarTableCore";
import {
  impliedVolatilityAnnualPercent,
  IV_RISK_FREE_RATE_ANNUAL,
  optionMarkPriceForIv,
} from "@/utils/impliedVolatility";

type OptionUnderlying = { value: string; label: string; radarTicker: string; ravaUnderlying: string };

/** Subyacentes ByMA para GET /options/chain; `ravaUnderlying` es el ticker interno de Rava en ESTRATEGIAS. */
/** Mapeo cadena/universo opciones → ticker accionario en UI (sin tocar backend). */
const CHAIN_UNDERLYING_TO_EQUITY_TICKER: Readonly<Record<string, string>> = {
  GFG: "GGAL",
};

const CHAIN_UNDERLYINGS: readonly OptionUnderlying[] = [
  { value: "GGAL", label: "GGAL", radarTicker: "GGAL", ravaUnderlying: "GFG" },
  { value: "YPFD", label: "YPFD", radarTicker: "YPFD", ravaUnderlying: "YPF" },
  { value: "ALUA", label: "ALUA", radarTicker: "ALUA", ravaUnderlying: "ALU" },
  { value: "PAMP", label: "PAMP", radarTicker: "PAMP", ravaUnderlying: "PAMP" },
  { value: "COME", label: "COME", radarTicker: "COME", ravaUnderlying: "COME" },
  { value: "BMA", label: "BMA", radarTicker: "BMA", ravaUnderlying: "BMA" },
  { value: "TXAR", label: "TXAR", radarTicker: "TXAR", ravaUnderlying: "TXAR" },
] as const;

/** Siempre enriquecer cadena (IOL + referencia Allaria/Rava); sin toggle en UI. */
const ENRICH_CHAIN_SOURCES = true;

/** Máximo de especies por request GET /options/quotes (prioridad operable). */
const IOL_QUOTES_VISIBLE_CAP = 12;

/** Nominal por contrato (BYMA acciones) para capital comprometido en tablas de estrategia. */
const OPTIONS_STRATEGY_LOT_SIZE = 100;

/** Umbrales alertas operativas (TNA anualizada mostrada en tablas). */
const OP_ALERT_TNA_WARN_PCT = 60;
const OP_ALERT_TNA_DANGER_PCT = 100;
/** Collar: |neto|/spot ≤ este % → “casi cero” en pesos relativos. */
const OP_ALERT_COLLAR_NET_ABS_PCT_SPOT = 0.5;
/** Collar: pérdida máx. aprox / spot ≤ este % → “baja” para subir severidad a warning. */
const OP_ALERT_COLLAR_LOW_LOSS_PCT_SPOT = 12;

/**
 * TODO(fase siguiente): alertas “Bull Call Spread barato” usando `bullCallSpreads` (débito vs anchura o vs spot)
 * cuando haya criterio estable. No mostrar filas hasta entonces.
 */

/** Edad máxima (ms) de última puntada IOL útil para mostrar OK vs OLD en columna Estado. */
const IOL_QUOTE_UI_FRESH_MS = 30_000;

type PanelQuoteStatusCode = "OK" | "BASE" | "PEND" | "OLD";

const PANEL_QUOTE_STATUS_TOOLTIP: Record<PanelQuoteStatusCode, string> = {
  OK: "Cotización actualizada desde IOL",
  BASE: "Usando datos base de la cadena",
  PEND: "Esperando actualización de puntas",
  OLD: "Cotización desactualizada",
};

/** Etiqueta corta en tablas (detalle en `title`). */
const PANEL_QUOTE_STATUS_SHORT: Record<PanelQuoteStatusCode, string> = {
  OK: "OK",
  BASE: "Base",
  PEND: "Pend.",
  OLD: "Ant.",
};

const OPTIONS_DESACOPLE_IV_COL_TOOLTIP =
  "Diferencia relativa contra la IV promedio del mismo vencimiento y tipo. Verde = prima cara relativa; rojo = prima barata relativa.";

type FlatRow = {
  activo: string;
  tipo: "CALL" | "PUT";
  strike: number;
  expiryCode: string;
  raw: Record<string, unknown>;
};

type StrategyType = "Bull Call Spread" | "Bear Put Spread" | "Covered Call" | "Protective Put" | "Collar";
type LegAction = "BUY" | "SELL";
type ActiveTab = "panel" | "strategies" | "ivSmile";
type StrategiesFilter =
  | ""
  | "Bull Call Spread"
  | "Covered Call"
  | "CALL Descubierta"
  | "Cash Secured Put"
  | "Collar";

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

/** OI en panel: no mostrar 0 como dato real (suele venir ausente como 0). */
function formatPanelOpenInterest(oi: number | null | undefined): string {
  if (oi === null || oi === undefined || !Number.isFinite(oi) || oi <= 0) return "—";
  return oi.toLocaleString("es-AR", { maximumFractionDigits: 0 });
}

function equityUnderlyingDisplayLabel(chainUnderlying: string | null | undefined, selectedUnderlying: string): string {
  const c = (chainUnderlying ?? "").trim();
  const s = selectedUnderlying.trim();
  const u = (c || s).toUpperCase();
  if (!u) return "—";
  return CHAIN_UNDERLYING_TO_EQUITY_TICKER[u] ?? u;
}

function callPutKindFromContractTypeUpper(ou: string): "CALL" | "PUT" | null {
  const t = ou.trim().toUpperCase();
  if (t.includes("PUT") && !t.includes("CALL")) return "PUT";
  if (t.includes("CALL")) return "CALL";
  return null;
}

function ivAvgBucketKey(expiryYyyyMmDd: string, kind: "CALL" | "PUT"): string {
  return `${expiryYyyyMmDd}_${kind}`;
}

export function formatIvVsVto(diff: number | null): string {
  if (diff === null || !Number.isFinite(diff)) return "—";
  const sign = diff > 0 ? "+" : "";
  return `${sign}${formatNumber(diff, 1)} pp`;
}

export function ivVsVtoDiffFromMap(
  avgMap: Map<string, number>,
  expiryYyyyMmDd: string,
  optionTypeUpper: string,
  ivPct: number | null,
): number | null {
  if (!expiryYyyyMmDd || ivPct === null || !Number.isFinite(ivPct)) return null;
  const kind = callPutKindFromContractTypeUpper(optionTypeUpper);
  if (!kind) return null;
  const avg = avgMap.get(ivAvgBucketKey(expiryYyyyMmDd, kind));
  if (avg === undefined || !Number.isFinite(avg)) return null;
  return ivPct - avg;
}

/** ((ivPct / avgIv) − 1) × 100; mismo mapa de promedios por vencimiento + CALL/PUT. */
function desacopleIvPctRelFromMap(
  avgMap: Map<string, number>,
  expiryYyyyMmDd: string,
  optionTypeUpper: string,
  ivPct: number | null,
): number | null {
  if (!expiryYyyyMmDd || ivPct === null || !Number.isFinite(ivPct) || ivPct <= 0) return null;
  const kind = callPutKindFromContractTypeUpper(optionTypeUpper);
  if (!kind) return null;
  const avg = avgMap.get(ivAvgBucketKey(expiryYyyyMmDd, kind));
  if (avg === undefined || !Number.isFinite(avg) || avg <= 0) return null;
  return (ivPct / avg - 1) * 100;
}

function formatDesacopleIvPct(pct: number | null): string {
  if (pct === null || !Number.isFinite(pct)) return "—";
  const sign = pct > 0 ? "+" : "";
  return `${sign}${formatNumber(pct, 1)}%`;
}

function desacopleIvPctCellClass(pct: number | null): string {
  if (pct === null || !Number.isFinite(pct)) return "";
  if (pct > 10) return "options-desacople-iv-pos";
  if (pct < -10) return "options-desacople-iv-neg";
  return "options-desacople-iv-neu";
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

/** Días calendario hasta vencimiento (medianoche local); null si fecha inválida o ya vencida. */
function daysBetweenTodayAndExpiry(yyyyMmDd: string): number | null {
  if (!yyyyMmDd || yyyyMmDd.length < 10) return null;
  const end = new Date(`${yyyyMmDd.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(end.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = Math.round((end.getTime() - today.getTime()) / 86400000);
  return diff >= 0 ? diff : null;
}

function expiryKeyFromMergedContract(c: OptionContractRow): string {
  if (c.expiry === null || c.expiry === undefined || c.expiry === "") return "";
  return String(c.expiry).slice(0, 10);
}

function mergedContractTypeUpper(c: OptionContractRow): string {
  return (c.option_type ?? "").toString().trim().toUpperCase();
}

function getLiveQuote(
  row: OptionContractRow,
  quotes: Record<string, IolOptionQuotePayload>,
): IolOptionQuotePayload | undefined {
  const s = (row.symbol ?? "").trim().toUpperCase();
  if (!s) return undefined;
  return quotes[s];
}

/** Puntas/volumen/opciones: overlay IOL por especie si valor > 0; si no, datos mergeados de la cadena. Sin NaN; null si no hay dato útil. */
function getEffectiveBid(row: OptionContractRow, quotes: Record<string, IolOptionQuotePayload>): number | null {
  const q = getLiveQuote(row, quotes);
  if (q && !q.error && typeof q.bid === "number" && Number.isFinite(q.bid) && q.bid > 0) return q.bid;
  const m = row.bid;
  if (typeof m === "number" && Number.isFinite(m)) return m;
  return null;
}

function getEffectiveAsk(row: OptionContractRow, quotes: Record<string, IolOptionQuotePayload>): number | null {
  const q = getLiveQuote(row, quotes);
  if (q && !q.error && typeof q.ask === "number" && Number.isFinite(q.ask) && q.ask > 0) return q.ask;
  const m = row.ask;
  if (typeof m === "number" && Number.isFinite(m)) return m;
  return null;
}

function getEffectiveVolume(row: OptionContractRow, quotes: Record<string, IolOptionQuotePayload>): number | null {
  const q = getLiveQuote(row, quotes);
  if (q && !q.error && q.volume !== undefined && q.volume !== null) {
    const v = typeof q.volume === "number" ? q.volume : Number(q.volume);
    if (Number.isFinite(v) && v > 0) return v;
  }
  const m = row.volume;
  if (typeof m === "number" && Number.isFinite(m)) return m;
  return null;
}

function getEffectiveOperations(row: OptionContractRow, quotes: Record<string, IolOptionQuotePayload>): number | null {
  const q = getLiveQuote(row, quotes);
  if (!q || q.error) return null;
  if (q.cantidad_operaciones !== undefined && q.cantidad_operaciones !== null) {
    const n =
      typeof q.cantidad_operaciones === "number" ? q.cantidad_operaciones : Number(q.cantidad_operaciones);
    if (Number.isFinite(n) && n > 0) return n;
  }
  return null;
}

function displayQuoteTime(row: OptionContractRow, quotes: Record<string, IolOptionQuotePayload>): string | null {
  const q = getLiveQuote(row, quotes);
  if (!q || q.error) return null;
  const fh = q.fecha_hora;
  if (typeof fh === "string" && fh.trim()) return fh.trim();
  return null;
}

function iolRealQuoteUsedForRow(row: OptionContractRow, quotes: Record<string, IolOptionQuotePayload>): boolean {
  const q = getLiveQuote(row, quotes);
  if (!q || q.error) return false;
  const qb = typeof q.bid === "number" && Number.isFinite(q.bid) && q.bid > 0;
  const qa = typeof q.ask === "number" && Number.isFinite(q.ask) && q.ask > 0;
  const qv = q.volume !== undefined && q.volume !== null && Number.isFinite(Number(q.volume)) && Number(q.volume) > 0;
  const qo =
    q.cantidad_operaciones !== undefined &&
    q.cantidad_operaciones !== null &&
    Number.isFinite(Number(q.cantidad_operaciones)) &&
    Number(q.cantidad_operaciones) > 0;
  return qb || qa || qv || qo;
}

/** IV % anual (misma lógica en panel y oportunidades): mark bid/ask/último + BS. */
function impliedVolAnnualPercentFromInputs(
  bid: number | null,
  ask: number | null,
  last: number | null,
  spot: number | null,
  strike: number | null,
  daysToExpiry: number | null,
  optionTypeLabel: string,
): number | null {
  const mark = optionMarkPriceForIv(bid, ask, last);
  const ou = optionTypeLabel.trim().toUpperCase();
  let call: boolean | null = null;
  if (ou.includes("PUT") && !ou.includes("CALL")) call = false;
  else if (ou.includes("CALL")) call = true;
  if (call === null) return null;
  if (spot === null || !Number.isFinite(spot) || spot <= 0) return null;
  if (strike === null || !Number.isFinite(strike) || strike <= 0) return null;
  if (daysToExpiry === null || daysToExpiry <= 0) return null;
  if (mark === null || mark <= 0) return null;
  return impliedVolatilityAnnualPercent({
    spot,
    strike,
    markPrice: mark,
    timeYears: daysToExpiry / 365,
    call,
  });
}

function impliedVolAnnualPercentForContract(
  row: OptionContractRow,
  quotes: Record<string, IolOptionQuotePayload>,
  spot: number | null,
  daysToExpiry: number | null,
): number | null {
  const bid = getEffectiveBid(row, quotes);
  const ask = getEffectiveAsk(row, quotes);
  const last = typeof row.last === "number" && Number.isFinite(row.last) && row.last > 0 ? row.last : null;
  const strike = typeof row.strike === "number" && Number.isFinite(row.strike) ? row.strike : null;
  return impliedVolAnnualPercentFromInputs(
    bid,
    ask,
    last,
    spot,
    strike,
    daysToExpiry,
    mergedContractTypeUpper(row),
  );
}

function panelRowQuoteStatus(
  row: OptionContractRow,
  opts: {
    chainIsIolPrimary: boolean;
    quoteFetchSymbolSet: Set<string>;
    iolQuotes: Record<string, IolOptionQuotePayload>;
    loadingIolQuotes: boolean;
    responseSeen: Record<string, boolean | undefined>;
    lastGoodAt: Record<string, number>;
    nowMs: number;
  },
): PanelQuoteStatusCode {
  const sym = (row.symbol ?? "").trim().toUpperCase();
  if (!sym) return "BASE";
  if (!opts.chainIsIolPrimary) return "BASE";
  if (!opts.quoteFetchSymbolSet.has(sym)) return "BASE";
  const hasReal = iolRealQuoteUsedForRow(row, opts.iolQuotes);
  if (hasReal) {
    const t = opts.lastGoodAt[sym];
    if (typeof t === "number" && Number.isFinite(t) && opts.nowMs - t <= IOL_QUOTE_UI_FRESH_MS) return "OK";
    return "OLD";
  }
  if (opts.loadingIolQuotes) return "PEND";
  if (!(sym in opts.responseSeen)) return "PEND";
  return "BASE";
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

function effVolForQuotes(c: OptionContractRow, quotes: Record<string, IolOptionQuotePayload>): number {
  return getEffectiveVolume(c, quotes) ?? 0;
}

function symUpperContract(c: OptionContractRow): string {
  return (c.symbol ?? "").trim().toUpperCase();
}

/**
 * Símbolos para GET /options/quotes: ATM/proximidad al spot, volumen efectivo > 0,
 * tapas CALL/PUT con volumen, relleno por orden visible; sin duplicados; máximo `cap`.
 */
function selectPrioritizedIolQuoteSymbols(
  rows: OptionContractRow[],
  spot: number | null,
  quotes: Record<string, IolOptionQuotePayload>,
  cap: number,
): { symbols: string[]; reasonSummary: string } {
  const seen = new Set<string>();
  const ordered: string[] = [];
  let nProx = 0;
  let nVol = 0;
  let nTapCall = 0;
  let nTapPut = 0;
  let nFill = 0;

  const pushRow = (c: OptionContractRow): boolean => {
    const s = symUpperContract(c);
    if (!s || seen.has(s)) return false;
    if (ordered.length >= cap) return false;
    seen.add(s);
    ordered.push(s);
    return true;
  };

  const typeU = (c: OptionContractRow) => mergedContractTypeUpper(c);
  const isCall = (c: OptionContractRow) => typeU(c).includes("CALL");
  const isPut = (c: OptionContractRow) => typeU(c).includes("PUT");
  const distToSpot = (c: OptionContractRow): number => {
    if (spot === null || !Number.isFinite(spot) || spot <= 0) return Number.POSITIVE_INFINITY;
    const k = c.strike;
    if (k === null || k === undefined || !Number.isFinite(k)) return Number.POSITIVE_INFINITY;
    return Math.abs(k - spot);
  };
  const isAtmRow = (c: OptionContractRow) => getMoneynessFromValues(c.strike, typeU(c), spot) === "ATM";

  // (a) ATM y cercanía al spot
  const byProximity = [...rows].sort((a, b) => {
    const aAtm = isAtmRow(a) ? 0 : 1;
    const bAtm = isAtmRow(b) ? 0 : 1;
    if (aAtm !== bAtm) return aAtm - bAtm;
    return distToSpot(a) - distToSpot(b);
  });
  for (const c of byProximity) {
    if (pushRow(c)) nProx += 1;
    if (ordered.length >= cap) break;
  }

  // (b) volumen efectivo > 0 (mayor volumen primero)
  const byVolume = [...rows]
    .filter((c) => effVolForQuotes(c, quotes) > 0)
    .sort((a, b) => effVolForQuotes(b, quotes) - effVolForQuotes(a, quotes));
  for (const c of byVolume) {
    if (pushRow(c)) nVol += 1;
    if (ordered.length >= cap) break;
  }

  // (c) tapas CALL / PUT con volumen (primeras y últimas del bloque por strike)
  const tapN = 4;
  const callsVol = [...rows]
    .filter(isCall)
    .sort((a, b) => (a.strike ?? 0) - (b.strike ?? 0))
    .filter((c) => effVolForQuotes(c, quotes) > 0);
  const putsVol = [...rows]
    .filter(isPut)
    .sort((a, b) => (a.strike ?? 0) - (b.strike ?? 0))
    .filter((c) => effVolForQuotes(c, quotes) > 0);
  const callHead = callsVol.slice(0, tapN);
  const callTail = callsVol.slice(-tapN);
  const putHead = putsVol.slice(0, tapN);
  const putTail = putsVol.slice(-tapN);
  for (const c of [...callHead, ...callTail, ...putHead, ...putTail]) {
    if (ordered.length >= cap) break;
    if (!pushRow(c)) continue;
    if (isCall(c)) nTapCall += 1;
    else if (isPut(c)) nTapPut += 1;
  }

  // Relleno: orden ya aplicado en `rows` (panel)
  for (const c of rows) {
    if (pushRow(c)) nFill += 1;
    if (ordered.length >= cap) break;
  }

  const reasonSummary = `proximity_atm=${nProx},vol_gt0=${nVol},tap_call_put=${nTapCall}+${nTapPut},fill=${nFill}`;
  return { symbols: ordered.slice(0, cap), reasonSummary };
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

/** Badge de origen de puntas en tabla (texto corto para la celda). */
function displayBaSourceBadge(c: OptionContractRow, quotes: Record<string, IolOptionQuotePayload>): { label: string; title: string } {
  if (iolRealQuoteUsedForRow(c, quotes)) {
    return { label: "Puntas IOL", title: "Cotización por especie (filas visibles)" };
  }
  const m = (c.bidask_source_mode ?? "").trim();
  switch (m) {
    case "iol_live":
      return { label: "IOL", title: "Puntas desde cadena/merge IOL" };
    case "allaria_fallback":
      return { label: "ALL", title: "Puntas desde Allaria" };
    case "rava_fallback":
      return { label: "RAV", title: "Puntas desde Rava" };
    default:
      return { label: "—", title: "Sin bid/ask útiles" };
  }
}

function iolAuthLikeMessage(m: string | null): boolean {
  const s = (m ?? "").trim().toLowerCase();
  if (!s) return false;
  return /\b(auth|token|sesion|sesión|login|401|403|unauthorized|forbidden|invalid_grant|invalid_client)\b/.test(s);
}

/** Banner reconexión: credenciales cargadas pero token inválido o error explícito de auth. */
function iolUiNeedsReconnect(st: IolStatusPayload | null): boolean {
  if (!st || !st.configured) return false;
  if (!st.auth_ok) return true;
  if (st.http_status === 401 || st.http_status === 403) return true;
  return iolAuthLikeMessage(st.message);
}

const OPTIONS_NAKED_CALL_RISK_TOOLTIP =
  "La pérdida potencial crece si el subyacente sube sin cobertura.";

function smileMoneynessKind(m: string): "ATM" | "ITM" | "OTM" | "OTHER" {
  const u = m.toUpperCase();
  if (u.includes("ATM")) return "ATM";
  if (u.includes("ITM")) return "ITM";
  if (u.includes("OTM")) return "OTM";
  return "OTHER";
}

function formatIvSmileDiffPct(pct: number | null | undefined): string {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return "—";
  const sign = pct > 0 ? "+" : "";
  return `${sign}${formatNumber(pct, 0)}%`;
}

function ivSmileDiffCellClass(pct: number | null | undefined): string {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return "";
  if (pct >= 10) return "options-iv-smile-diff-rich";
  if (pct <= -10) return "options-iv-smile-diff-cheap";
  return "options-iv-smile-diff-neu";
}

/** Δ IV temporal: expansión (tonos cálidos) vs contracción (azul). */
function ivSmileDeltaIvCellClass(pct: number | null | undefined): string {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return "";
  if (pct > 0) return "options-iv-smile-delta-expand";
  if (pct < 0) return "options-iv-smile-delta-contract";
  return "";
}

/** Motivos cortos para Top IV; solo entra lo que el punto ya expone (sin inventar). */
function collarNetCommentClass(comentario: string): string {
  if (comentario === "Crédito neto") return "options-badge-net options-badge-net--credit";
  if (comentario === "Débito neto") return "options-badge-net options-badge-net--debit";
  if (comentario === "Costo neutro") return "options-badge-net options-badge-net--neutral";
  return "options-badge-net";
}

function topIvSmileOpportunityReasons(p: IvSmilePoint, spot: number | null): string[] {
  const reasons: string[] = [];
  if (p.iv_expanding) reasons.push("IV en expansión");
  if (p.iv_crushing) reasons.push("IV en crush");
  if (p.rich_iv) reasons.push("IV alta vs promedio");
  else if (p.cheap_iv) reasons.push("IV baja vs promedio");
  if (spot !== null && spot > 0 && Number.isFinite(p.strike)) {
    const d = (Math.abs(p.strike - spot) / spot) * 100;
    if (Number.isFinite(d) && d <= 8) reasons.push("cerca del spot");
  }
  const vol = p.volume ?? 0;
  if (Number.isFinite(vol) && vol > 0) reasons.push("volumen en cadena");
  const bid = p.bid;
  if (bid !== undefined && bid !== null && Number.isFinite(bid) && bid > 0) reasons.push("bid en cadena");
  return reasons;
}

function IvSmileSvgChart({
  points,
  spot,
  avgIvPct,
}: {
  points: IvSmilePoint[];
  spot: number | null;
  avgIvPct: number | null;
}) {
  if (points.length === 0) return <p className="msg-muted">Sin puntos para graficar.</p>;
  const w = 720;
  const h = 248;
  const padL = 56;
  const padR = 18;
  const padT = 22;
  const padB = 48;
  const sk = points.map((p) => p.strike);
  const iv = points.map((p) => p.iv_pct);
  let minK = Math.min(...sk);
  let maxK = Math.max(...sk);
  let minV = Math.min(...iv);
  let maxV = Math.max(...iv);
  if (avgIvPct !== null && Number.isFinite(avgIvPct)) {
    minV = Math.min(minV, avgIvPct);
    maxV = Math.max(maxV, avgIvPct);
  }
  if (minK === maxK) {
    minK -= 1;
    maxK += 1;
  }
  const spanV = maxV - minV || 1;
  const padV = Math.max(spanV * 0.1, 0.8);
  minV -= padV;
  maxV += padV;
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;
  const xOf = (strike: number) => padL + ((strike - minK) / (maxK - minK)) * innerW;
  const yOf = (v: number) => padT + innerH - ((v - minV) / (maxV - minV)) * innerH;
  const pts = points.map((p) => ({ x: xOf(p.strike), y: yOf(p.iv_pct), p }));
  const poly = pts.map((t) => `${t.x.toFixed(1)},${t.y.toFixed(1)}`).join(" ");
  const spotInRange = spot !== null && Number.isFinite(spot) && spot > 0 && spot >= minK && spot <= maxK;
  const xSpot = spotInRange ? xOf(spot) : null;
  const yAvg =
    avgIvPct !== null && Number.isFinite(avgIvPct) && avgIvPct >= minV && avgIvPct <= maxV
      ? yOf(avgIvPct)
      : null;
  const yTicks = [minV, (minV + maxV) / 2, maxV];
  const xTicks = [minK, (minK + maxK) / 2, maxK];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="options-iv-smile-chart" width="100%" height={h} role="img" aria-label="IV por strike">
      <text x={padL} y={16} fontSize="11" className="options-iv-smile-chart__title">
        IV % vs strike
      </text>
      {yTicks.map((yv, i) => (
        <text
          key={`yl-${i}`}
          x={padL - 6}
          y={yOf(yv) + 3}
          fontSize="9"
          textAnchor="end"
          className="options-iv-smile-chart__tick"
        >
          {formatNumber(yv, 0)}%
        </text>
      ))}
      {xTicks.map((xv, i) => (
        <text
          key={`xl-${i}`}
          x={xOf(xv)}
          y={h - 10}
          fontSize="9"
          textAnchor="middle"
          className="options-iv-smile-chart__tick"
        >
          {formatNumber(xv, 0)}
        </text>
      ))}
      <line
        x1={padL}
        y1={padT + innerH}
        x2={padL + innerW}
        y2={padT + innerH}
        className="options-iv-smile-chart__axis"
      />
      <line x1={padL} y1={padT} x2={padL} y2={padT + innerH} className="options-iv-smile-chart__axis" />
      {yAvg !== null ? (
        <line
          x1={padL}
          y1={yAvg}
          x2={padL + innerW}
          y2={yAvg}
          className="options-iv-smile-chart__avg-line"
        />
      ) : null}
      {avgIvPct !== null && Number.isFinite(avgIvPct) ? (
        <text x={padL + innerW - 4} y={(yAvg ?? padT + innerH / 2) - 6} fontSize="9" textAnchor="end" className="options-iv-smile-chart__avg-label">
          Prom. IV {formatNumber(avgIvPct, 1)}%
        </text>
      ) : null}
      {xSpot !== null ? (
        <line x1={xSpot} y1={padT} x2={xSpot} y2={padT + innerH} className="options-iv-smile-chart__atm-line" />
      ) : null}
      {xSpot !== null ? (
        <text x={xSpot + 4} y={padT + 12} fontSize="9" className="options-iv-smile-chart__atm-label">
          ATM
        </text>
      ) : null}
      <polyline fill="none" className="options-iv-smile-chart__line" strokeLinejoin="round" points={poly} />
      {pts.map((t, idx) => {
        const k = smileMoneynessKind(t.p.moneyness);
        const dotClass =
          k === "ATM"
            ? "options-iv-smile-dot--atm"
            : k === "OTM"
              ? "options-iv-smile-dot--otm"
              : k === "ITM"
                ? "options-iv-smile-dot--itm"
                : "options-iv-smile-dot--neu";
        const tip = `Strike: ${formatNumber(t.p.strike, 2)}\nIV: ${formatNumber(t.p.iv_pct, 1)}%\nEspecie: ${t.p.symbol?.trim() || "—"}\nMoneyness: ${t.p.moneyness}`;
        return (
          <g key={`ivpt-${idx}-${t.p.symbol}-${t.p.strike}-${t.p.iv_pct}`}>
            <title>{tip}</title>
            <circle cx={t.x} cy={t.y} r={5} className={`options-iv-smile-dot ${dotClass}`} />
          </g>
        );
      })}
    </svg>
  );
}

type OptionTypeFilter = "all" | "CALL" | "PUT";
type PanelHeaderSort =
  | { kind: "default" }
  | { kind: "strike"; dir: "asc" | "desc" }
  | { kind: "expiry"; dir: "asc" | "desc" };

export function OptionsPage() {
  const [selectedUnderlying, setSelectedUnderlying] = useState<string>("");
  const [selectedExpiry, setSelectedExpiry] = useState<string>("");
  const [optionTypeFilter, setOptionTypeFilter] = useState<OptionTypeFilter>("all");
  const [hideZeroVolume, setHideZeroVolume] = useState(false);
  const [panelHeaderSort, setPanelHeaderSort] = useState<PanelHeaderSort>({ kind: "default" });
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
  const [showNakedShortCall, setShowNakedShortCall] = useState(false);
  const [showCashSecuredPut, setShowCashSecuredPut] = useState(false);
  const [showCollar, setShowCollar] = useState(false);
  const [selectedLegs, setSelectedLegs] = useState<StrategyLeg[]>([]);
  const [mergedChain, setMergedChain] = useState<OptionsChainResponse | null>(null);
  const [loadingChain, setLoadingChain] = useState(false);
  const [errorChain, setErrorChain] = useState<string | null>(null);
  const [hasRequestedChain, setHasRequestedChain] = useState(false);
  /** Invalida respuestas viejas (cambio de activo, desmontaje, StrictMode). */
  const optionsChainReqRef = useRef(0);
  const iolQuotesReqRef = useRef(0);
  const iolQuoteSymbolListRef = useRef<string[]>([]);
  const selectedUnderlyingRef = useRef("");
  const [iolQuotes, setIolQuotes] = useState<Record<string, IolOptionQuotePayload>>({});
  const [loadingIolQuotes, setLoadingIolQuotes] = useState(false);
  const [loadingUnderlyingContext, setLoadingUnderlyingContext] = useState(false);
  const [underlyingSignal, setUnderlyingSignal] = useState<string | null>(null);
  const [underlyingTrendRaw, setUnderlyingTrendRaw] = useState<unknown>(null);
  const [iolStatus, setIolStatus] = useState<IolStatusPayload | null>(null);
  const [iolReconnecting, setIolReconnecting] = useState(false);
  const [iolReconnectHint, setIolReconnectHint] = useState<string | null>(null);
  const [ivSmileItems, setIvSmileItems] = useState<IvSmileGroup[]>([]);
  const [ivSmileLoading, setIvSmileLoading] = useState(false);
  const [ivSmileErr, setIvSmileErr] = useState<string | null>(null);
  const [smileExpiry, setSmileExpiry] = useState("");
  const [smileSide, setSmileSide] = useState<"CALL" | "PUT">("CALL");

  selectedUnderlyingRef.current = selectedUnderlying;

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

  const chainIsIolPrimaryRef = useRef(chainIsIolPrimary);
  chainIsIolPrimaryRef.current = chainIsIolPrimary;

  const underlyingRadarSymbol = selectedUnderlyingMeta.radarTicker;

  const equityUnderlyingDisplayTicker = useMemo(
    () => equityUnderlyingDisplayLabel(mergedChain?.underlying, selectedUnderlying),
    [mergedChain?.underlying, selectedUnderlying],
  );

  const onPanelSortHeaderExpiryClick = useCallback(() => {
    setPanelHeaderSort((prev) => {
      if (prev.kind === "expiry") {
        if (prev.dir === "asc") return { kind: "expiry", dir: "desc" };
        return { kind: "default" };
      }
      return { kind: "expiry", dir: "asc" };
    });
  }, []);

  const onPanelSortHeaderStrikeClick = useCallback(() => {
    setPanelHeaderSort((prev) => {
      if (prev.kind === "strike") {
        if (prev.dir === "asc") return { kind: "strike", dir: "desc" };
        return { kind: "default" };
      }
      return { kind: "strike", dir: "asc" };
    });
  }, []);

  useEffect(() => {
    setManualSpotInput("");
  }, [selectedUnderlying]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const s = await fetchIolStatus();
        if (!cancelled) setIolStatus(s);
      } catch {
        if (!cancelled) setIolStatus(null);
      }
    };
    void load();
    const id = window.setInterval(() => void load(), 45_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (activeTab !== "ivSmile") return;
    const u = selectedUnderlying.trim();
    if (!u) {
      setIvSmileItems([]);
      setIvSmileErr(null);
      return;
    }
    let cancelled = false;
    setIvSmileLoading(true);
    setIvSmileErr(null);
    void fetchIvSmile(u)
      .then((data) => {
        if (cancelled) return;
        setIvSmileItems(data.items);
        setSmileExpiry((prev) => {
          const exps = [...new Set(data.items.map((it) => it.expiration))].filter(Boolean).sort();
          if (exps.length === 0) return "";
          if (prev && exps.includes(prev)) return prev;
          return exps[0] ?? "";
        });
      })
      .catch((e) => {
        if (!cancelled) setIvSmileErr(e instanceof Error ? e.message : "Error al cargar sonrisa IV");
      })
      .finally(() => {
        if (!cancelled) setIvSmileLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeTab, selectedUnderlying]);

  const onIolReconnect = useCallback(async () => {
    setIolReconnecting(true);
    setIolReconnectHint(null);
    try {
      await postIolReconnect();
      const s = await fetchIolStatus();
      setIolStatus(s);
    } catch (e) {
      setIolReconnectHint(e instanceof Error ? e.message : "No se pudo reconectar");
    } finally {
      setIolReconnecting(false);
    }
  }, []);

  const smileExpiryOptions = useMemo(
    () => [...new Set(ivSmileItems.map((i) => i.expiration))].filter(Boolean).sort(),
    [ivSmileItems],
  );

  const ivSmileActiveGroup = useMemo((): IvSmileGroup | null => {
    if (!smileExpiry || ivSmileItems.length === 0) return null;
    return ivSmileItems.find((it) => it.expiration === smileExpiry && it.option_type === smileSide) ?? null;
  }, [ivSmileItems, smileExpiry, smileSide]);

  const ivSmileActivePoints = useMemo(() => ivSmileActiveGroup?.points ?? [], [ivSmileActiveGroup]);

  const ivSmileActiveAvgIvPct = useMemo((): number | null => {
    const v = ivSmileActiveGroup?.avg_iv_pct;
    return typeof v === "number" && Number.isFinite(v) ? v : null;
  }, [ivSmileActiveGroup]);

  // Estrategias usan la misma cadena que el Panel: mergedChain (GET /options/chain).

  useEffect(() => {
    if (!underlyingRadarSymbol.trim()) {
      setLoadingUnderlyingContext(false);
      setUnderlyingSignal(null);
      setUnderlyingTrendRaw(null);
      return;
    }
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
    if (!hasRequestedChain) return null;
    if (loadingChain || errorChain) return null;
    if ((mergedChain?.contracts.length ?? 0) === 0) return "Sin contratos para este subyacente.";
    return null;
  }, [hasRequestedChain, loadingChain, errorChain, mergedChain]);

  const emptyHintStrategies = useMemo(() => {
    if (!hasRequestedChain) return null;
    if (loadingChain || errorChain) return null;
    if ((mergedChain?.contracts.length ?? 0) === 0) return "Sin contratos para este subyacente.";
    return null;
  }, [hasRequestedChain, loadingChain, errorChain, mergedChain]);

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

  const ivSmileRichOpportunities = useMemo(() => {
    type Row = {
      symbol: string;
      strike: number;
      iv_pct: number;
      iv_diff_vs_avg_pct: number;
      bid: number;
      distPct: number | null;
      expiration: string;
    };
    const spot = effectivePanelSpot;
    const rows: Row[] = [];
    for (const g of ivSmileItems) {
      for (const p of g.points) {
        if (!p.rich_iv) continue;
        const vol = p.volume ?? 0;
        if (vol <= 0) continue;
        const bid = p.bid;
        if (bid === null || bid === undefined || !(bid > 0)) continue;
        const dp = p.iv_diff_vs_avg_pct;
        if (dp === null || dp === undefined || !Number.isFinite(dp)) continue;
        let distPct: number | null = null;
        if (spot !== null && spot > 0) {
          distPct = (Math.abs(p.strike - spot) / spot) * 100;
        }
        rows.push({
          symbol: (p.symbol ?? "").trim() || "—",
          strike: p.strike,
          iv_pct: p.iv_pct,
          iv_diff_vs_avg_pct: dp,
          bid,
          distPct,
          expiration: g.expiration,
        });
      }
    }
    rows.sort((a, b) => b.iv_diff_vs_avg_pct - a.iv_diff_vs_avg_pct);
    return rows.slice(0, 50);
  }, [ivSmileItems, effectivePanelSpot]);

  const ivSmileTemporalMoves = useMemo(() => {
    type Row = {
      symbol: string;
      strike: number;
      iv_pct: number;
      iv_change_pct: number;
      iv_diff_vs_avg_pct: number | null;
      bid: number | null;
      expiration: string;
    };
    const rows: Row[] = [];
    for (const g of ivSmileItems) {
      for (const p of g.points) {
        if (!p.iv_expanding && !p.iv_crushing) continue;
        const ch = p.iv_change_pct;
        if (ch === null || ch === undefined || !Number.isFinite(ch)) continue;
        const dp = p.iv_diff_vs_avg_pct;
        rows.push({
          symbol: (p.symbol ?? "").trim() || "—",
          strike: p.strike,
          iv_pct: p.iv_pct,
          iv_change_pct: ch,
          iv_diff_vs_avg_pct: dp === null || dp === undefined || !Number.isFinite(dp) ? null : dp,
          bid:
            p.bid !== undefined && p.bid !== null && typeof p.bid === "number" && Number.isFinite(p.bid) && p.bid > 0
              ? p.bid
              : null,
          expiration: g.expiration,
        });
      }
    }
    rows.sort((a, b) => Math.abs(b.iv_change_pct) - Math.abs(a.iv_change_pct));
    return rows.slice(0, 80);
  }, [ivSmileItems]);

  /** Top 5 ranking compuesto (temporal > |Δ IV| > |vs prom| > cercanía spot > volumen > bid). */
  const ivSmileTopIvOpportunities = useMemo(() => {
    type TopRow = {
      key: string;
      symbol: string;
      option_type: string;
      strike: number;
      expiration: string;
      iv_pct: number;
      iv_change_pct: number | null;
      iv_expanding: boolean;
      iv_crushing: boolean;
      reasonLine: string;
      sortTemporal: number;
      sortAbsCh: number;
      sortAbsDp: number;
      sortSpot: number;
      sortVol: number;
      sortBid: number;
    };
    const spot = effectivePanelSpot;
    const pool: TopRow[] = [];
    for (const g of ivSmileItems) {
      const ot = (g.option_type ?? "").trim() || "—";
      for (const p of g.points) {
        if (!Number.isFinite(p.iv_pct)) continue;
        const sym = (p.symbol ?? "").trim();
        const ch = p.iv_change_pct;
        const absCh = ch !== null && ch !== undefined && Number.isFinite(ch) ? Math.abs(ch) : 0;
        const dp = p.iv_diff_vs_avg_pct;
        const absDp = dp !== null && dp !== undefined && Number.isFinite(dp) ? Math.abs(dp) : 0;
        let spotScore = 0;
        if (spot !== null && spot > 0 && Number.isFinite(p.strike)) {
          const dist = Math.abs(p.strike - spot) / spot;
          spotScore = Number.isFinite(dist) ? 1 / (1 + dist * 12) : 0;
        }
        const vol = p.volume !== undefined && Number.isFinite(p.volume) ? Math.max(0, p.volume) : 0;
        const bidOk =
          p.bid !== undefined && p.bid !== null && Number.isFinite(p.bid) && p.bid > 0 ? 1 : 0;
        const temporal = p.iv_expanding || p.iv_crushing ? 1 : 0;
        const reasons = topIvSmileOpportunityReasons(p, spot);
        pool.push({
          key: `${g.expiration}-${ot}-${sym || "x"}-${p.strike}`,
          symbol: sym || "—",
          option_type: ot,
          strike: p.strike,
          expiration: g.expiration,
          iv_pct: p.iv_pct,
          iv_change_pct: ch !== null && ch !== undefined && Number.isFinite(ch) ? ch : null,
          iv_expanding: Boolean(p.iv_expanding),
          iv_crushing: Boolean(p.iv_crushing),
          reasonLine: reasons.length ? reasons.join(" · ") : "—",
          sortTemporal: temporal,
          sortAbsCh: absCh,
          sortAbsDp: absDp,
          sortSpot: spotScore,
          sortVol: vol,
          sortBid: bidOk,
        });
      }
    }
    pool.sort((a, b) => {
      if (a.sortTemporal !== b.sortTemporal) return b.sortTemporal - a.sortTemporal;
      if (a.sortAbsCh !== b.sortAbsCh) return b.sortAbsCh - a.sortAbsCh;
      if (a.sortAbsDp !== b.sortAbsDp) return b.sortAbsDp - a.sortAbsDp;
      if (a.sortSpot !== b.sortSpot) return b.sortSpot - a.sortSpot;
      if (a.sortVol !== b.sortVol) return b.sortVol - a.sortVol;
      return b.sortBid - a.sortBid;
    });
    return pool.slice(0, 5);
  }, [ivSmileItems, effectivePanelSpot]);

  const ivAvgPctByExpiryType = useMemo(() => {
    const buckets = new Map<string, number[]>();
    for (const c of mergedChain?.contracts ?? []) {
      const ek = expiryKeyFromMergedContract(c);
      if (!ek) continue;
      const kind = callPutKindFromContractTypeUpper(mergedContractTypeUpper(c));
      if (!kind) continue;
      const dte = daysBetweenTodayAndExpiry(ek);
      const iv = impliedVolAnnualPercentForContract(c, iolQuotes, effectivePanelSpot, dte);
      if (iv === null || !Number.isFinite(iv)) continue;
      const k = ivAvgBucketKey(ek, kind);
      const arr = buckets.get(k) ?? [];
      arr.push(iv);
      buckets.set(k, arr);
    }
    const out = new Map<string, number>();
    for (const [k, arr] of buckets.entries()) {
      if (arr.length < 3) continue;
      out.set(k, arr.reduce((s, v) => s + v, 0) / arr.length);
    }
    return out;
  }, [mergedChain, effectivePanelSpot, iolQuotes]);

  const contractBySymbol = useMemo(() => {
    const m = new Map<string, OptionContractRow>();
    for (const c of mergedChain?.contracts ?? []) {
      const s = (c.symbol ?? "").trim().toUpperCase();
      if (s) m.set(s, c);
    }
    return m;
  }, [mergedChain]);

  const contractBySymbolRef = useRef(contractBySymbol);
  contractBySymbolRef.current = contractBySymbol;

  /** undefined = aún no hubo respuesta para el snapshot actual; false = vino respuesta sin esa especie; true = vino en payload. */
  const iolQuoteResponseSeenRef = useRef<Record<string, boolean | undefined>>({});
  const iolLastGoodQuoteAtRef = useRef<Record<string, number>>({});
  const [iolQuoteStatusTick, setIolQuoteStatusTick] = useState(0);

  const filterCounts = useMemo(() => {
    let withVolume = 0;
    let withTrades = 0;
    let withAtm = 0;
    for (const c of mergedChain?.contracts ?? []) {
      const vol = getEffectiveVolume(c, iolQuotes) ?? 0;
      if (vol > 0) withVolume += 1;
      const last = typeof c.last === "number" && Number.isFinite(c.last) ? c.last : 0;
      if (last > 0) withTrades += 1;
      const m = getMoneynessFromValues(c.strike, mergedContractTypeUpper(c), effectivePanelSpot);
      if (m === "ATM") withAtm += 1;
    }
    return { withVolume, withTrades, withAtm };
  }, [mergedChain, effectivePanelSpot, iolQuotes]);

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
      if (hideZeroVolume && (getEffectiveVolume(c, iolQuotes) ?? 0) <= 0) return false;
      return true;
    });
    return filtered.slice().sort((a, b) => {
      if (panelHeaderSort.kind === "strike") {
        const sA = a.strike ?? -Infinity;
        const sB = b.strike ?? -Infinity;
        if (sA !== sB) return panelHeaderSort.dir === "asc" ? sA - sB : sB - sA;
        return tieBreakExpiryTypeStrike(a, b);
      }
      if (panelHeaderSort.kind === "expiry") {
        const eA = expiryKeyFromMergedContract(a);
        const eB = expiryKeyFromMergedContract(b);
        const cmpE = eA.localeCompare(eB);
        if (cmpE !== 0) return panelHeaderSort.dir === "asc" ? cmpE : -cmpE;
        return tieBreakExpiryTypeStrike(a, b);
      }
      return sortMergedDefault(a, b);
    });
  }, [mergedChain, selectedExpiry, optionTypeFilter, hideZeroVolume, panelHeaderSort, iolQuotes]);

  const iolQuotePick = useMemo(() => {
    const totalVisible = mergedFilteredContracts.length;
    const { symbols, reasonSummary } = selectPrioritizedIolQuoteSymbols(
      mergedFilteredContracts,
      effectivePanelSpot,
      iolQuotes,
      IOL_QUOTES_VISIBLE_CAP,
    );
    return { symbols, reasonSummary, totalVisible };
  }, [mergedFilteredContracts, effectivePanelSpot, iolQuotes]);

  const iolQuoteSymbolList = iolQuotePick.symbols;
  const iolQuotePrioritySummary = iolQuotePick.reasonSummary;
  const iolQuoteTotalVisible = iolQuotePick.totalVisible;

  const iolQuoteKey = iolQuoteSymbolList.join("|");

  iolQuoteSymbolListRef.current = iolQuoteSymbolList;

  const iolQuoteFetchSymbolSet = useMemo(
    () => new Set(iolQuoteSymbolList.map((s) => s.trim().toUpperCase()).filter(Boolean)),
    [iolQuoteSymbolList],
  );

  useEffect(() => {
    iolQuoteResponseSeenRef.current = {};
  }, [iolQuoteKey]);

  useEffect(() => {
    const id = window.setInterval(() => {
      setIolQuoteStatusTick((x) => x + 1);
    }, 8000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!hasRequestedChain || !mergedChain) return;
    console.log("[OPTIONS_ENRICH_PRIORITY]", {
      totalVisible: iolQuoteTotalVisible,
      selected: iolQuoteSymbolList.length,
      cap: IOL_QUOTES_VISIBLE_CAP,
      selectedSymbols: iolQuoteSymbolList.slice(),
      reasonSummary: iolQuotePrioritySummary,
    });
  }, [
    hasRequestedChain,
    mergedChain,
    iolQuoteKey,
    iolQuoteSymbolList,
    iolQuotePrioritySummary,
    iolQuoteTotalVisible,
  ]);

  const loadChain = useCallback((underlying: string) => {
    const u = underlying.trim();
    if (!u) return;
    const reqId = ++optionsChainReqRef.current;
    iolQuotesReqRef.current += 1;
    iolQuoteResponseSeenRef.current = {};
    iolLastGoodQuoteAtRef.current = {};
    setLoadingIolQuotes(false);
    setLoadingChain(true);
    setErrorChain(null);
    setIolQuotes({});
    setHasRequestedChain(true);
    setMergedChain(null);
    fetchOptionsChain(u, ENRICH_CHAIN_SOURCES)
      .then((res) => {
        if (reqId !== optionsChainReqRef.current) return;
        console.info("[OPTIONS_CHAIN]", {
          underlying: u,
          contracts: res.total,
          spot: res.spot ?? null,
          spot_source: res.spot_source ?? null,
          spot_source_detail: res.spot_source_detail ?? null,
          spot_cache_hit: res.spot_cache_hit ?? null,
          spot_fetch_ms: res.spot_fetch_ms ?? null,
          spot_symbol_used: res.spot_symbol_used ?? null,
          spot_updated_at: res.spot_updated_at ?? res.spot_as_of ?? null,
        });
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
  }, []);

  const pickUnderlying = useCallback(
    (value: string) => {
      const v = value.trim();
      if (!v) return;
      setSelectedUnderlying(v);
      setSelectedExpiry("");
      setOptionTypeFilter("all");
      setMergedChain(null);
      setErrorChain(null);
      setIolQuotes({});
      setLoadingIolQuotes(false);
      setPanelHeaderSort({ kind: "default" });
      void loadChain(v);
    },
    [loadChain],
  );

  const fetchOptionsQuotesLogged = useCallback(async (syms: string[], source: "debounce" | "manual") => {
    const und = selectedUnderlyingRef.current.trim() || "—";
    const n = syms.length;
    const t0 = performance.now();
    try {
      const data = await fetchOptionsQuotes(syms);
      const ms = Math.round(performance.now() - t0);
      console.info("[OPTIONS_QUOTES]", { underlying: und, symbols: n, ms, source, ok: true });
      return data;
    } catch {
      const ms = Math.round(performance.now() - t0);
      console.info("[OPTIONS_QUOTES]", { underlying: und, symbols: n, ms, source, ok: false });
      return {};
    }
  }, []);

  const applyIolQuotesFetchResult = useCallback((symsSnapshot: string[], data: Record<string, IolOptionQuotePayload>, req: number) => {
    if (req !== iolQuotesReqRef.current) return;
    const upperKeys = new Set(
      Object.keys(data)
        .map((k) => k.trim().toUpperCase())
        .filter((k) => k.length > 0),
    );
    const seen = { ...iolQuoteResponseSeenRef.current };
    for (const s of symsSnapshot) {
      const u = s.trim().toUpperCase();
      if (!u) continue;
      seen[u] = upperKeys.has(u);
    }
    iolQuoteResponseSeenRef.current = seen;
    const now = Date.now();
    const cmap = contractBySymbolRef.current;
    for (const k of Object.keys(data)) {
      const u = k.trim().toUpperCase();
      if (!u) continue;
      const row = cmap.get(u);
      if (row && iolRealQuoteUsedForRow(row, data)) {
        iolLastGoodQuoteAtRef.current[u] = now;
      }
    }
    const fetchSet = new Set(symsSnapshot.map((s) => s.trim().toUpperCase()).filter(Boolean));
    const lastGoodSnapshot = { ...iolLastGoodQuoteAtRef.current };
    const nowMs = Date.now();
    for (const rawS of symsSnapshot) {
      const u = rawS.trim().toUpperCase();
      if (!u) continue;
      const row = cmap.get(u);
      let q: IolOptionQuotePayload | undefined;
      for (const [dk, dv] of Object.entries(data)) {
        if (dk.trim().toUpperCase() === u) {
          q = dv;
          break;
        }
      }
      const hasPayload = upperKeys.has(u);
      const statusCalculated: PanelQuoteStatusCode = row
        ? panelRowQuoteStatus(row, {
            chainIsIolPrimary: chainIsIolPrimaryRef.current,
            quoteFetchSymbolSet: fetchSet,
            iolQuotes: data,
            loadingIolQuotes: false,
            responseSeen: seen,
            lastGoodAt: lastGoodSnapshot,
            nowMs,
          })
        : "BASE";
      console.log("[OPTIONS_QUOTE_APPLY]", {
        symbol: u,
        hasPayload,
        bid: q?.bid ?? null,
        ask: q?.ask ?? null,
        volume: q?.volume ?? null,
        operations: q?.cantidad_operaciones ?? null,
        iolRealQuoteUsedForRow: row ? iolRealQuoteUsedForRow(row, data) : false,
        statusCalculated,
      });
    }
    setIolQuotes(data);
  }, []);

  const refreshVisibleQuotes = useCallback(() => {
    const syms = iolQuoteSymbolListRef.current;
    if (!mergedChain || syms.length === 0 || !chainIsIolPrimary) return;
    const req = ++iolQuotesReqRef.current;
    setLoadingIolQuotes(true);
    const symsSnapshot = syms.slice();
    void fetchOptionsQuotesLogged(symsSnapshot, "manual")
      .then((data) => {
        applyIolQuotesFetchResult(symsSnapshot, data, req);
      })
      .finally(() => {
        if (req !== iolQuotesReqRef.current) return;
        setLoadingIolQuotes(false);
      });
  }, [mergedChain, chainIsIolPrimary, fetchOptionsQuotesLogged, applyIolQuotesFetchResult]);

  useEffect(() => {
    if (!hasRequestedChain || !mergedChain || loadingChain) return;
    if (!chainIsIolPrimary) return;
    if (iolQuoteSymbolList.length === 0) return;
    let alive = true;
    const symsSnapshot = iolQuoteSymbolList.slice();
    const tmo = window.setTimeout(() => {
      if (!alive) return;
      const req = ++iolQuotesReqRef.current;
      setLoadingIolQuotes(true);
      void fetchOptionsQuotesLogged(symsSnapshot, "debounce")
        .then((data) => {
          applyIolQuotesFetchResult(symsSnapshot, data, req);
        })
        .finally(() => {
          if (req !== iolQuotesReqRef.current) return;
          setLoadingIolQuotes(false);
        });
    }, 280);
    return () => {
      alive = false;
      window.clearTimeout(tmo);
    };
  }, [hasRequestedChain, mergedChain, loadingChain, chainIsIolPrimary, iolQuoteKey, activeTab, fetchOptionsQuotesLogged, applyIolQuotesFetchResult]);

  const panelFilteredEmptyHint = useMemo(() => {
    if (loadingChain || errorChain) return null;
    const raw = mergedChain?.contracts ?? [];
    if (raw.length === 0) return null;
    if (mergedFilteredContracts.length > 0) return null;
    if (hideZeroVolume) {
      const allVolZero = raw.every((c) => (getEffectiveVolume(c, iolQuotes) ?? 0) <= 0);
      if (allVolZero) {
        return "No hay contratos con volumen > 0 para estos filtros. Desactivá «Ocultar volumen 0» para ver la cadena.";
      }
    }
    return "Sin resultados con los filtros actuales.";
  }, [loadingChain, errorChain, mergedChain, mergedFilteredContracts.length, hideZeroVolume, iolQuotes]);

  const volumeFilterHidesAllIolRows = useMemo(() => {
    if (!hideZeroVolume) return false;
    const raw = mergedChain?.contracts ?? [];
    if (raw.length === 0) return false;
    return raw.every((c) => (getEffectiveVolume(c, iolQuotes) ?? 0) <= 0);
  }, [hideZeroVolume, mergedChain, iolQuotes]);

  const strategyRows = useMemo((): FlatRow[] => {
    const rows: FlatRow[] = [];
    for (const c of mergedChain?.contracts ?? []) {
      const ot = mergedContractTypeUpper(c);
      const tipo: "CALL" | "PUT" | null = ot.includes("CALL") ? "CALL" : ot.includes("PUT") ? "PUT" : null;
      if (!tipo) continue;
      const strike = typeof c.strike === "number" && Number.isFinite(c.strike) ? c.strike : null;
      if (strike === null) continue;
      const expiryKey = expiryKeyFromMergedContract(c);
      const dte = expiryKey ? daysBetweenTodayAndExpiry(expiryKey) : null;
      rows.push({
        activo: selectedUnderlying,
        tipo,
        strike,
        expiryCode: expiryKey,
        raw: {
          simbolo: c.symbol,
          expiry_date: c.expiry,
          bid: getEffectiveBid(c, iolQuotes),
          ask: getEffectiveAsk(c, iolQuotes),
          ultimo: c.last,
          volumen_float: getEffectiveVolume(c, iolQuotes),
          cantidad_operaciones: getEffectiveOperations(c, iolQuotes),
          days_to_expiry: dte ?? undefined,
          quote_fecha_hora: displayQuoteTime(c, iolQuotes),
          open_interest: c.open_interest,
          source: c.source,
          field_sources: c.field_sources,
        },
      });
    }
    rows.sort((a, b) => a.strike - b.strike);
    return rows;
  }, [mergedChain, selectedUnderlying, iolQuotes]);

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
      ivPct: number | null;
      desacopleIvPct: number | null;
    }[] = [];
    for (const r of calls) {
      const exp = expiryKeyFromRaw(r.raw);
      if (!exp) continue;
      const sym = (typeof r.raw.simbolo === "string" ? r.raw.simbolo : "").trim().toUpperCase();
      const co = sym ? contractBySymbol.get(sym) : undefined;
      const bidEff = co ? getEffectiveBid(co, iolQuotes) : toNumberOrNull(r.raw.bid);
      if (bidEff === null || bidEff <= 0) continue;
      let days = daysToExpiryRaw(r.raw);
      if (days === null) days = daysBetweenTodayAndExpiry(exp);
      const breakEven = effectivePanelSpot !== null ? effectivePanelSpot - bidEff : null;

      const intrinsic =
        effectivePanelSpot !== null && effectivePanelSpot > 0
          ? Math.max(0, effectivePanelSpot - r.strike)
          : null;
      const timeValue =
        intrinsic !== null
          ? bidEff - intrinsic
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

      const ivPct = co
        ? impliedVolAnnualPercentForContract(co, iolQuotes, effectivePanelSpot, days)
        : impliedVolAnnualPercentFromInputs(
            toNumberOrNull(r.raw.bid),
            toNumberOrNull(r.raw.ask),
            toNumberOrNull(r.raw.ultimo),
            effectivePanelSpot,
            typeof r.strike === "number" && Number.isFinite(r.strike) ? r.strike : null,
            days,
            "CALL",
          );

      const desacopleIvPct = desacopleIvPctRelFromMap(ivAvgPctByExpiryType, exp, "CALL", ivPct);

      out.push({
        expiryKey: exp,
        strike: r.strike,
        bid: bidEff,
        intrinsic,
        timeValue,
        days,
        tnaPct,
        breakEven,
        moneyness: moneyStatus(r.raw),
        ivPct,
        desacopleIvPct,
      });
    }
    out.sort((a, b) => a.expiryKey.localeCompare(b.expiryKey) || a.strike - b.strike);
    return out.slice(0, 30);
  }, [calls, effectivePanelSpot, iolQuotes, contractBySymbol, ivAvgPctByExpiryType]);

  const cashSecuredPuts = useMemo(() => {
    const out: {
      expiryKey: string;
      contract: OptionContractRow;
      strike: number;
      prima: number;
      breakEven: number;
      breakEvenVsSpotPct: number | null;
      distStrikePct: number | null;
      capital: number;
      rendSimplePct: number;
      tnaPct: number | null;
      vol: number | null;
      days: number | null;
      ivPct: number | null;
      desacopleIvPct: number | null;
    }[] = [];
    for (const r of puts) {
      const exp = expiryKeyFromRaw(r.raw);
      if (!exp) continue;
      const sym = (typeof r.raw.simbolo === "string" ? r.raw.simbolo : "").trim().toUpperCase();
      const co = sym ? contractBySymbol.get(sym) : undefined;
      if (!co) continue;
      const primaEff = getEffectiveBid(co, iolQuotes);
      if (primaEff === null || primaEff <= 0) continue;
      const strike = r.strike;
      let days = daysToExpiryRaw(r.raw);
      if (days === null) days = daysBetweenTodayAndExpiry(exp);
      const spotOk = effectivePanelSpot !== null && effectivePanelSpot > 0;
      const spotNum = effectivePanelSpot;
      const distStrikePct =
        spotOk && spotNum !== null ? (strike / spotNum - 1) * 100 : null;
      const breakEven = strike - primaEff;
      const breakEvenVsSpotPct =
        spotOk && spotNum !== null && primaEff > 0 && spotNum > 0 && Number.isFinite(breakEven)
          ? ((breakEven / spotNum) - 1) * 100
          : null;
      const capital = strike * OPTIONS_STRATEGY_LOT_SIZE;
      const rendSimplePct = (primaEff / strike) * 100;
      const tnaPct =
        spotOk && days !== null && days > 0 ? rendSimplePct * (365 / days) : null;
      const ivPct = impliedVolAnnualPercentForContract(co, iolQuotes, effectivePanelSpot, days);
      const desacopleIvPct = desacopleIvPctRelFromMap(
        ivAvgPctByExpiryType,
        exp,
        mergedContractTypeUpper(co),
        ivPct,
      );
      out.push({
        expiryKey: exp,
        contract: co,
        strike,
        prima: primaEff,
        breakEven,
        breakEvenVsSpotPct,
        distStrikePct,
        capital,
        rendSimplePct,
        tnaPct,
        vol: getEffectiveVolume(co, iolQuotes),
        days,
        ivPct,
        desacopleIvPct,
      });
    }
    out.sort((a, b) => a.expiryKey.localeCompare(b.expiryKey) || a.strike - b.strike);
    return out.slice(0, 30);
  }, [puts, effectivePanelSpot, iolQuotes, contractBySymbol, ivAvgPctByExpiryType]);

  const nakedShortCalls = useMemo(() => {
    const out: {
      expiryKey: string;
      strike: number;
      prima: number;
      premiumPct: number;
      tnaPct: number;
      breakEven: number;
      distPct: number;
      days: number | null;
      symbol: string | null;
    }[] = [];
    for (const r of calls) {
      const exp = expiryKeyFromRaw(r.raw);
      if (!exp) continue;
      const sym = (typeof r.raw.simbolo === "string" ? r.raw.simbolo : "").trim().toUpperCase();
      const co = sym ? contractBySymbol.get(sym) : undefined;
      const primaEff = co ? getEffectiveBid(co, iolQuotes) : toNumberOrNull(r.raw.bid);
      if (primaEff === null || primaEff <= 0) continue;
      const strike = r.strike;
      if (!(strike > 0)) continue;
      let days = daysToExpiryRaw(r.raw);
      if (days === null) days = daysBetweenTodayAndExpiry(exp);
      if (days === null || days <= 0) continue;
      const spotNum = effectivePanelSpot;
      if (spotNum === null || !(spotNum > 0)) continue;
      const premiumPct = (primaEff / spotNum) * 100;
      const breakEven = strike + primaEff;
      const distPct = ((strike - spotNum) / spotNum) * 100;
      const tnaPct = (primaEff / strike) * (365 / days) * 100;
      out.push({
        expiryKey: exp,
        strike,
        prima: primaEff,
        premiumPct,
        tnaPct,
        breakEven,
        distPct,
        days,
        symbol: typeof r.raw.simbolo === "string" ? r.raw.simbolo.trim() : null,
      });
    }
    out.sort((a, b) => b.tnaPct - a.tnaPct || b.distPct - a.distPct);
    return out.slice(0, 30);
  }, [calls, effectivePanelSpot, iolQuotes, contractBySymbol]);

  /** Collar: acciones + put comprado (ask efectivo) + call vendido (bid efectivo), mismo vencimiento; put K &lt; spot &lt; call K. */
  const collarOpportunities = useMemo(() => {
    type Row = {
      expiryKey: string;
      putSymbol: string;
      callSymbol: string;
      putStrike: number;
      callStrike: number;
      primaPut: number;
      primaCall: number;
      neto: number;
      piso: number;
      techo: number;
      perdidaMax: number;
      gananciaMax: number;
      comentario: string;
      distPutPct: number;
      distCallPct: number;
    };
    const S = effectivePanelSpot;
    if (S === null || !(S > 0) || !Number.isFinite(S)) return [];

    const NEUTRAL_NET = 0.02;
    const pool: Row[] = [];
    const expSet = new Set<string>();
    for (const r of calls) {
      const e = expiryKeyFromRaw(r.raw);
      if (e) expSet.add(e);
    }
    for (const r of puts) {
      const e = expiryKeyFromRaw(r.raw);
      if (e) expSet.add(e);
    }

    for (const exp of [...expSet].sort()) {
      const putRows = puts.filter((r) => {
        const e = expiryKeyFromRaw(r.raw);
        return e === exp && Number.isFinite(r.strike) && r.strike < S;
      });
      const callRows = calls.filter((r) => {
        const e = expiryKeyFromRaw(r.raw);
        return e === exp && Number.isFinite(r.strike) && r.strike > S;
      });

      for (const pr of putRows) {
        const symP = (typeof pr.raw.simbolo === "string" ? pr.raw.simbolo : "").trim().toUpperCase();
        const putCo = symP ? contractBySymbol.get(symP) : undefined;
        if (!putCo) continue;
        const putAsk = getEffectiveAsk(putCo, iolQuotes);
        if (putAsk === null || !(putAsk > 0) || !Number.isFinite(putAsk)) continue;

        for (const cr of callRows) {
          const symC = (typeof cr.raw.simbolo === "string" ? cr.raw.simbolo : "").trim().toUpperCase();
          const callCo = symC ? contractBySymbol.get(symC) : undefined;
          if (!callCo) continue;
          const callBid = getEffectiveBid(callCo, iolQuotes);
          if (callBid === null || !(callBid > 0) || !Number.isFinite(callBid)) continue;

          const putK = pr.strike;
          const callK = cr.strike;
          if (!Number.isFinite(putK) || !Number.isFinite(callK)) continue;

          const neto = callBid - putAsk;
          const perdidaMax = Math.max(0, S - putK + putAsk - callBid);
          const gananciaMax = Math.max(0, callK - S + callBid - putAsk);

          let comentario: string;
          if (Math.abs(neto) <= NEUTRAL_NET) comentario = "Costo neutro";
          else if (neto > 0) comentario = "Crédito neto";
          else comentario = "Débito neto";

          const distPutPct = ((S - putK) / S) * 100;
          const distCallPct = ((callK - S) / S) * 100;

          pool.push({
            expiryKey: exp,
            putSymbol: symP || "—",
            callSymbol: symC || "—",
            putStrike: putK,
            callStrike: callK,
            primaPut: putAsk,
            primaCall: callBid,
            neto,
            piso: putK,
            techo: callK,
            perdidaMax,
            gananciaMax,
            comentario,
            distPutPct,
            distCallPct,
          });
        }
      }
    }

    pool.sort((a, b) => {
      if (a.perdidaMax !== b.perdidaMax) return a.perdidaMax - b.perdidaMax;
      if (b.gananciaMax !== a.gananciaMax) return b.gananciaMax - a.gananciaMax;
      if (a.distPutPct !== b.distPutPct) return a.distPutPct - b.distPutPct;
      return a.distCallPct - b.distCallPct;
    });

    return pool.slice(0, 10);
  }, [calls, puts, effectivePanelSpot, iolQuotes, contractBySymbol]);

  const operationalOpportunityAlerts = useMemo(() => {
    type Sev = "danger" | "warning" | "info";
    type Row = {
      id: string;
      severity: Sev;
      main: string;
      meta?: string;
      sDanger: number;
      sTna: number;
      sCollarNetAbsPct: number;
    };
    const out: Row[] = [];
    const spot = effectivePanelSpot;

    for (const x of coveredCalls) {
      const tp = x.tnaPct;
      if (tp === null || !Number.isFinite(tp) || tp < OP_ALERT_TNA_WARN_PCT) continue;
      const symRow = calls.find(
        (r) => r.tipo === "CALL" && expiryKeyFromRaw(r.raw) === x.expiryKey && r.strike === x.strike,
      );
      const especie =
        symRow && typeof symRow.raw.simbolo === "string" && symRow.raw.simbolo.trim()
          ? String(symRow.raw.simbolo).trim()
          : "CALL";
      const sev: Sev = tp >= OP_ALERT_TNA_DANGER_PCT ? "danger" : "warning";
      out.push({
        id: `op-cc-${x.expiryKey}-${x.strike}-${tp}`,
        severity: sev,
        main: `Covered Call con TNA alta: ${especie} TNA ${formatNumber(tp, 1)}%`,
        meta: `${formatExpiryMonthLabel(x.expiryKey)} · K ${formatNumber(x.strike, 2)}`,
        sDanger: sev === "danger" ? 2 : 1,
        sTna: tp,
        sCollarNetAbsPct: 0,
      });
    }

    for (const x of cashSecuredPuts) {
      const tp = x.tnaPct;
      if (tp === null || !Number.isFinite(tp) || tp < OP_ALERT_TNA_WARN_PCT) continue;
      const especie = (x.contract.symbol ?? "").trim() || "PUT";
      const sev: Sev = tp >= OP_ALERT_TNA_DANGER_PCT ? "danger" : "warning";
      out.push({
        id: `op-csp-${x.expiryKey}-${x.strike}-${tp}`,
        severity: sev,
        main: `CSP con TNA alta: ${especie} TNA ${formatNumber(tp, 1)}%`,
        meta: `${formatExpiryMonthLabel(x.expiryKey)} · K ${formatNumber(x.strike, 2)}`,
        sDanger: sev === "danger" ? 2 : 1,
        sTna: tp,
        sCollarNetAbsPct: 0,
      });
    }

    if (spot !== null && spot > 0 && Number.isFinite(spot)) {
      for (const x of collarOpportunities) {
        const neto = x.neto;
        if (!Number.isFinite(neto)) continue;
        const absPct = (Math.abs(neto) / spot) * 100;
        const cheapBySpot = absPct <= OP_ALERT_COLLAR_NET_ABS_PCT_SPOT;
        const credit = neto > 0;
        if (!cheapBySpot && !credit) continue;

        const lossPct = (x.perdidaMax / spot) * 100;
        const lowLoss = Number.isFinite(lossPct) && lossPct <= OP_ALERT_COLLAR_LOW_LOSS_PCT_SPOT;
        const sev: Sev = lowLoss && (cheapBySpot || credit) ? "warning" : "info";

        const lot = OPTIONS_STRATEGY_LOT_SIZE;
        const netoContrato = neto * lot;
        const perdidaContratoPart = Number.isFinite(x.perdidaMax)
          ? ` · Pérd. máx. aprox. $ ${formatNumber(x.perdidaMax * lot, 2)} por contrato`
          : "";
        const metaCollar = `Neto $ ${formatNumber(neto, 2)} por acción / $ ${formatNumber(netoContrato, 2)} por contrato${perdidaContratoPart} · ${formatExpiryMonthLabel(x.expiryKey)} · ${x.putSymbol} / ${x.callSymbol}`;

        out.push({
          id: `op-collar-${x.expiryKey}-${x.putSymbol}-${x.callSymbol}-${neto}`,
          severity: sev,
          main: `Collar barato/costo cero: PUT ${formatNumber(x.putStrike, 2)} + CALL ${formatNumber(x.callStrike, 2)}`,
          meta: metaCollar,
          sDanger: sev === "warning" ? 1 : 0,
          sTna: 0,
          sCollarNetAbsPct: absPct,
        });
      }
    }

    out.sort((a, b) => {
      if (b.sDanger !== a.sDanger) return b.sDanger - a.sDanger;
      if (b.sTna !== a.sTna) return b.sTna - a.sTna;
      return a.sCollarNetAbsPct - b.sCollarNetAbsPct;
    });
    return out.slice(0, 6);
  }, [coveredCalls, cashSecuredPuts, collarOpportunities, calls, effectivePanelSpot]);

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
    <div className="page options-page options-page--layout">
      <header className="page__header">
        <h1>Opciones</h1>
        <p className="page__subtitle">
          Panel y estrategias comparten la misma cadena.
          {selectedUnderlying.trim() ? (
            <>
              {" "}
              Activo: <strong>{equityUnderlyingDisplayTicker}</strong>
            </>
          ) : (
            <> Elegí un activo abajo.</>
          )}
        </p>
        {chainIsIolPrimary && !loadingChain && !errorChain ? (
          <p className="page__subtitle" style={{ marginTop: "0.35rem", fontWeight: 600 }}>
            Universo operable: IOL
          </p>
        ) : null}
      </header>

      {iolUiNeedsReconnect(iolStatus) ? (
        <div className="options-iol-auth-banner" role="status">
          <span className="options-iol-auth-banner__text">IOL requiere reconexión.</span>
          {iolReconnecting ? (
            <span className="options-iol-auth-banner__status msg-muted">Reconectando…</span>
          ) : null}
          <button
            type="button"
            className="options-filter-toggle"
            onClick={() => void onIolReconnect()}
            disabled={iolReconnecting || !iolStatus?.configured}
          >
            Reconectar IOL
          </button>
        </div>
      ) : null}
      {iolReconnectHint ? (
        <p className="msg-muted" style={{ margin: "-0.35rem 0 0.65rem", fontSize: "0.82rem" }}>
          {iolReconnectHint}
        </p>
      ) : null}

      <section className="options-page-blk options-page-blk--asset" aria-labelledby="options-blk-asset-h">
        <h2 id="options-blk-asset-h" className="options-page-blk__title">
          Activo
        </h2>
        <p className="options-page-blk__lede msg-muted">Elegí el subyacente para cargar la cadena y las métricas.</p>
        <div style={{ marginBottom: "0.85rem" }}>
        {selectedUnderlying.trim() === "" && !loadingChain ? (
          <div className="options-empty-state options-empty-state--compact" role="status">
            Sin cadena: elegí un activo arriba.
          </div>
        ) : null}
        <div
          role="group"
          aria-label="Elegir activo subyacente"
          style={{ display: "flex", flexWrap: "wrap", gap: "0.45rem", alignItems: "center" }}
        >
          {CHAIN_UNDERLYINGS.map((u) => (
            <button
              key={u.value}
              type="button"
              className={`options-filter-toggle${selectedUnderlying === u.value ? " options-filter-toggle-active" : ""}`}
              aria-pressed={selectedUnderlying === u.value}
              onClick={() => pickUnderlying(u.value)}
            >
              {u.label}
            </button>
          ))}
        </div>
        </div>
      </section>

      <section className="options-page-blk options-page-blk--chain" aria-labelledby="options-blk-chain-h">
        <h2 id="options-blk-chain-h" className="options-page-blk__title">
          Cadena de opciones
        </h2>
      <div className="radar-toolbar options-toolbar" role="toolbar" aria-label="Opciones de cadena">
        <label className="radar-toolbar__field">
          <span className="radar-toolbar__label">Vencimiento</span>
          <select
            className="radar-toolbar__select"
            value={selectedExpiry}
            onChange={(ev) => setSelectedExpiry(ev.target.value)}
            disabled={!mergedChain || expiryOptions.length === 0}
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
            <button
              type="button"
              className={`options-filter-toggle${hideZeroVolume ? " options-filter-toggle-active" : ""}`}
              aria-pressed={hideZeroVolume}
              onClick={() => setHideZeroVolume((v) => !v)}
              title="Ocultar filas con volumen efectivo 0"
            >
              Ocultar volumen 0
            </button>
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

      <div style={{ marginTop: "0.5rem", display: "flex", flexDirection: "column", gap: "0.4rem" }}>
        <div className="options-chain-actions" style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center" }}>
          <button
            type="button"
            className="options-filter-toggle"
            onClick={() => void refreshVisibleQuotes()}
            disabled={!mergedChain || loadingChain || loadingIolQuotes || !chainIsIolPrimary || iolQuoteSymbolList.length === 0}
          >
            Actualizar puntas visibles
          </button>
          <span className="msg-muted options-page-blk__hint" title="Actualiza bid, ask, volumen y operaciones de las filas visibles en el panel.">
            Puntas visibles (IOL).
          </span>
        </div>
        {loadingIolQuotes && hasRequestedChain && mergedChain && chainIsIolPrimary && iolQuoteSymbolList.length > 0 ? (
          <p className="msg-muted options-page-blk__hint" style={{ margin: 0 }}>
            Actualizando puntas…
          </p>
        ) : null}
        {activeTab === "panel" ? (
          <p className="msg-muted options-page-blk__hint" style={{ margin: 0 }} title={`Hasta ${IOL_QUOTES_VISIBLE_CAP} especies por consulta.`}>
            En el panel, puntas por filas visibles.
          </p>
        ) : null}
      </div>
      </section>

      <section className="options-page-blk options-page-blk--spot" aria-labelledby="options-blk-spot-h">
        <h2 id="options-blk-spot-h" className="options-page-blk__title">
          Spot y señales
        </h2>
        <p className="options-page-blk__lede msg-muted">Navegación entre panel, estrategias e IV.</p>

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
        <button
          type="button"
          className={`options-tab${activeTab === "ivSmile" ? " options-tab-active" : ""}`}
          role="tab"
          aria-selected={activeTab === "ivSmile"}
          onClick={() => {
            setActiveTab("ivSmile");
            setSelectedExpiry("");
          }}
        >
          SONRISA IV
        </button>
      </div>

      <div className="options-underlying-card" aria-label="Subyacente">
        <div style={{ display: "flex", flexDirection: "column", gap: "0.15rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
            <div className="options-underlying-label" style={{ margin: 0 }}>
              Subyacente
            </div>
            <div className="options-underlying-symbol">
              <code>{equityUnderlyingDisplayTicker}</code>
            </div>
          </div>
          <div className="options-underlying-meta">
            <span className={signalBadgeClass} title="SignalState">
              {loadingUnderlyingContext ? "Signal: …" : `Signal: ${underlyingSignal?.trim() ? underlyingSignal : "-"}`}
            </span>
            <span className={trendBadgeClass} title="Tendencia">
              {loadingUnderlyingContext ? "Tendencia: …" : `Tendencia: ${underlyingTrendLabel}`}
            </span>
            {activeTab === "strategies" || activeTab === "ivSmile" ? (
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
                <div>$ {formatNumber(effectivePanelSpot, 2)}</div>
                <div className="msg-muted options-underlying-spot-foot" style={{ fontSize: "0.72rem", marginTop: "0.28rem" }}>
                  {parsedManualSpot !== null
                    ? "Fuente: ingreso manual"
                    : chainIsIolPrimary
                      ? "Fuente: IOL"
                      : mergedChain?.spot_source?.trim()
                        ? `Fuente: ${mergedChain.spot_source}`
                        : "Fuente: —"}
                </div>
              </>
            ) : (
              <span className="msg-muted">Precio subyacente no disponible</span>
            )}
          </div>
        </div>
      </div>

      <div className="options-page-blk__chain-summary msg-muted">
        {hasRequestedChain && mergedChain && !loadingChain && !errorChain ? (
          <div className="options-page-blk__chain-summary-row">
            <strong>{equityUnderlyingDisplayTicker}</strong>
            <span className="options-page-blk__sep" aria-hidden="true">
              ·
            </span>
            <span>{mergedChain.total} contr.</span>
            {activeTab === "panel" ? (
              <>
                <span className="options-page-blk__sep">·</span>
                <span>{mergedFilteredContracts.length} visibles</span>
              </>
            ) : null}
            <span className="options-page-blk__sep">·</span>
            {effectivePanelSpot !== null && effectivePanelSpot > 0 ? (
              <span
                title={`Fuente spot: ${parsedManualSpot !== null ? "manual" : (mergedChain.spot_source ?? "—")}${mergedChain.spot_symbol ? ` (${mergedChain.spot_symbol})` : ""}`}
              >
                ${formatNumber(effectivePanelSpot, 2)}
              </span>
            ) : (
              <span>Sin spot</span>
            )}
            <span className="options-page-blk__sep">·</span>
            <span
              title={
                chainIsIolPrimary
                  ? "Cadena IOL con referencia Allaria/Rava; puntas por filas visibles."
                  : "Cadena backend Allaria + Rava."
              }
            >
              {chainIsIolPrimary ? "IOL+merge" : "Rava/A"}
            </span>
            {hideZeroVolume && activeTab === "panel" ? (
              <>
                <span className="options-page-blk__sep">·</span>
                <em title="Filtro del panel">Ocult. vol. 0</em>
              </>
            ) : null}
          </div>
        ) : !hasRequestedChain ? (
          <div className="options-empty-state options-empty-state--compact" role="status">
            Sin cadena cargada todavía.
          </div>
        ) : null}
        {activeTab === "strategies" ? (
          <div className="options-page-blk__strategies-note" style={{ marginTop: "0.35rem" }}>
            <span className="msg-muted" title="Misma cadena que el panel.">
              {chainIsIolPrimary ? "Oportunidades: universo IOL" : "Oportunidades: Rava/Allaria"}
            </span>
            {!loadingChain && !errorChain && hasRequestedChain && mergedChain && expirySummary.length > 0 ? (
              <span className="msg-muted">
                {" "}
                · {mergedChain.total} contr. · {expirySummary.length} venc.
              </span>
            ) : null}
          </div>
        ) : null}
      </div>
      </section>

      {loadingChain && hasRequestedChain ? <p>Cargando cadena…</p> : null}
      {errorChain && (
        <p role="alert">
          Error cadena: {errorChain}
        </p>
      )}
      {activeTab === "ivSmile" ? (
        <section
          className="options-section options-page-blk options-page-blk--iv"
          style={{ marginTop: "0.35rem" }}
          aria-labelledby="options-blk-iv-h"
        >
          <h2 id="options-blk-iv-h" className="options-page-blk__title">
            Volatilidad (IV)
          </h2>
          <p className="options-page-blk__lede msg-muted">Curva y rankings con el mismo spot y cadena que el panel.</p>
          <div className="options-section-title">Sonrisa IV</div>
          {!selectedUnderlying.trim() ? (
            <div className="options-empty-state options-empty-state--compact" role="status">
              Sin IV: elegí un activo y abrí esta pestaña.
            </div>
          ) : ivSmileLoading ? (
            <p className="msg-muted options-page-blk__hint">Cargando curva…</p>
          ) : ivSmileErr ? (
            <p role="alert">Error: {ivSmileErr}</p>
          ) : (
            <>
              <div className="radar-toolbar options-toolbar" style={{ marginBottom: "0.65rem" }} role="toolbar" aria-label="Filtros sonrisa IV">
                <label className="radar-toolbar__field">
                  <span className="radar-toolbar__label">Vencimiento</span>
                  <select
                    className="radar-toolbar__select"
                    value={smileExpiry}
                    onChange={(ev) => setSmileExpiry(ev.target.value)}
                    disabled={smileExpiryOptions.length === 0}
                    aria-label="Vencimiento curva IV"
                  >
                    {smileExpiryOptions.length === 0 ? (
                      <option value="">—</option>
                    ) : null}
                    {smileExpiryOptions.map((ex) => (
                      <option key={ex} value={ex}>
                        {formatExpiryMonthLabel(ex)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="radar-toolbar__field">
                  <span className="radar-toolbar__label">Tipo</span>
                  <select
                    className="radar-toolbar__select"
                    value={smileSide}
                    onChange={(ev) => setSmileSide(ev.target.value as "CALL" | "PUT")}
                    aria-label="Tipo opción curva IV"
                  >
                    <option value="CALL">CALL</option>
                    <option value="PUT">PUT</option>
                  </select>
                </label>
              </div>
              <p className="msg-muted options-page-blk__hint" style={{ fontSize: "0.8rem", marginBottom: "0.5rem" }} title="GET /options/iv-smile; sin batch de puntas IOL.">
                IV desde cadena y spot del servidor.
              </p>
              <IvSmileSvgChart points={ivSmileActivePoints} spot={effectivePanelSpot} avgIvPct={ivSmileActiveAvgIvPct} />
              <div className="table-wrap" style={{ marginTop: "0.65rem" }}>
                <table className="strategy-opportunities-table">
                  <thead>
                    <tr>
                      <th style={{ textAlign: "right" }}>Strike</th>
                      <th style={{ textAlign: "right" }}>IV %</th>
                      <th style={{ textAlign: "right" }} title="Cambio relativo de IV vs snapshot anterior (mismo vencimiento/tipo), si hay historial">
                        Δ IV
                      </th>
                      <th style={{ textAlign: "right" }} title="Diferencia relativa vs IV promedio del mismo vencimiento y tipo (±10 % = cara / barata)">
                        Dif. IV
                      </th>
                      <th style={{ width: "8.5rem" }} />
                      <th>Moneyness</th>
                      <th>Especie</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ivSmileActivePoints.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="options-empty-cell msg-muted">
                          Sin filas para este vencimiento/tipo.
                        </td>
                      </tr>
                    ) : (
                      ivSmileActivePoints.map((p) => {
                        const dp = p.iv_diff_vs_avg_pct;
                        const diffCls = ivSmileDiffCellClass(dp);
                        const dIv = p.iv_change_pct;
                        const dIvCls = ivSmileDeltaIvCellClass(dIv);
                        return (
                          <tr key={`${p.symbol}-${p.strike}-${p.iv_pct}`}>
                            <td style={{ textAlign: "right" }}>{formatNumber(p.strike, 2)}</td>
                            <td style={{ textAlign: "right" }}>{`${formatNumber(p.iv_pct, 1)}%`}</td>
                            <td style={{ textAlign: "right" }} className={dIvCls}>
                              {formatIvSmileDiffPct(dIv)}
                            </td>
                            <td style={{ textAlign: "right" }} className={diffCls}>
                              {formatIvSmileDiffPct(dp)}
                            </td>
                            <td>
                              <span style={{ display: "inline-flex", flexWrap: "wrap", gap: "0.2rem", alignItems: "center" }}>
                                {p.rich_iv ? (
                                  <span className="options-iv-smile-pill options-iv-smile-pill--rich">Cara</span>
                                ) : p.cheap_iv ? (
                                  <span className="options-iv-smile-pill options-iv-smile-pill--cheap">Barata</span>
                                ) : null}
                                {p.iv_expanding ? (
                                  <span className="options-iv-smile-pill options-iv-smile-pill--iv-expand options-iv-pill-temporal">
                                    Expansión
                                  </span>
                                ) : null}
                                {p.iv_crushing ? (
                                  <span className="options-iv-smile-pill options-iv-smile-pill--iv-crush options-iv-pill-temporal">
                                    Crush
                                  </span>
                                ) : null}
                              </span>
                            </td>
                            <td>{p.moneyness}</td>
                            <td>
                              <code style={{ fontSize: "0.78rem" }}>{p.symbol?.trim() ? p.symbol : "—"}</code>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
              <div className="options-iv-top-opps" style={{ marginTop: "0.85rem" }}>
                <div className="options-section-title">Top oportunidades IV</div>
                {ivSmileTopIvOpportunities.length === 0 ? (
                  <div className="options-empty-state options-empty-state--compact" role="status">
                    Sin oportunidades IV destacadas por ahora.
                  </div>
                ) : (
                  <ul className="options-iv-top-opps__list" aria-label="Ranking compacto oportunidades IV">
                    {ivSmileTopIvOpportunities.map((r) => (
                      <li key={r.key} className="options-iv-top-opps__row">
                        <div className="options-iv-top-opps__head">
                          <code className="options-iv-top-opps__sym">{r.symbol}</code>
                          <span className="options-iv-top-opps__kind">{r.option_type}</span>
                          <span className="options-iv-top-opps__strike">K {formatNumber(r.strike, 2)}</span>
                          <span className="options-iv-top-opps__exp">{formatExpiryMonthLabel(r.expiration)}</span>
                        </div>
                        <div className="options-iv-top-opps__nums">
                          <span title="IV actual">{`${formatNumber(r.iv_pct, 1)}%`}</span>
                          <span className={ivSmileDeltaIvCellClass(r.iv_change_pct ?? undefined)} title="Δ IV vs snapshot">
                            Δ {formatIvSmileDiffPct(r.iv_change_pct)}
                          </span>
                          <span className="options-iv-top-opps__pills">
                            {r.iv_expanding ? (
                              <span className="options-iv-smile-pill options-iv-smile-pill--iv-expand">Expansión</span>
                            ) : null}
                            {r.iv_crushing ? (
                              <span className="options-iv-smile-pill options-iv-smile-pill--iv-crush">Crush</span>
                            ) : null}
                          </span>
                        </div>
                        <div className="options-iv-top-opps__reason msg-muted">{r.reasonLine}</div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="options-iv-smile-opps" style={{ marginTop: "1rem" }}>
                <div className="options-section-title">Oportunidades IV</div>
                  <p className="msg-muted options-page-blk__hint" style={{ fontSize: "0.78rem", marginBottom: "0.45rem" }} title="rich_iv + volumen y bid &gt; 0; orden por diferencia vs promedio del grupo.">
                    IV cara vs curva (rich), con volumen y bid.
                  </p>
                <div className="table-wrap">
                  <table className="strategy-opportunities-table">
                    <thead>
                      <tr>
                        <th>Vencimiento</th>
                        <th>Especie</th>
                        <th style={{ textAlign: "right" }}>Strike</th>
                        <th style={{ textAlign: "right" }}>IV %</th>
                        <th style={{ textAlign: "right" }}>Dif. vs prom.</th>
                        <th style={{ textAlign: "right" }}>Prima (bid)</th>
                        <th style={{ textAlign: "right" }} title="Distancia strike vs spot (panel / cadena)">
                          Dist. spot %
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {ivSmileRichOpportunities.length === 0 ? (
                        <tr>
                          <td colSpan={7} className="options-empty-cell msg-muted">
                            Sin coincidencias (o cargá sonrisa).
                          </td>
                        </tr>
                      ) : (
                        ivSmileRichOpportunities.map((r, i) => (
                          <tr key={`${r.expiration}-${r.symbol}-${r.strike}-${i}`}>
                            <td>{formatExpiryMonthLabel(r.expiration)}</td>
                            <td>
                              <code style={{ fontSize: "0.78rem" }}>{r.symbol}</code>
                            </td>
                            <td style={{ textAlign: "right" }}>{formatNumber(r.strike, 2)}</td>
                            <td style={{ textAlign: "right" }}>{`${formatNumber(r.iv_pct, 1)}%`}</td>
                            <td style={{ textAlign: "right" }} className="options-iv-smile-diff-rich">
                              {formatIvSmileDiffPct(r.iv_diff_vs_avg_pct)}
                            </td>
                            <td style={{ textAlign: "right" }}>$ {formatNumber(r.bid, 2)}</td>
                            <td style={{ textAlign: "right" }}>
                              {r.distPct !== null ? `${formatNumber(r.distPct, 1)}%` : "—"}
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
              <div className="options-iv-smile-opps" style={{ marginTop: "1rem" }}>
                <div className="options-section-title">Movimientos IV</div>
                <p className="msg-muted options-page-blk__hint" style={{ fontSize: "0.78rem", marginBottom: "0.45rem" }} title="Expansión/crush vs snapshot local; orden por |Δ IV|.">
                  Movimientos IV fuertes (±8 % vs snapshot).
                </p>
                <div className="table-wrap">
                  <table className="strategy-opportunities-table">
                    <thead>
                      <tr>
                        <th>Vencimiento</th>
                        <th>Especie</th>
                        <th style={{ textAlign: "right" }}>Strike</th>
                        <th style={{ textAlign: "right" }}>IV %</th>
                        <th style={{ textAlign: "right" }}>Δ IV</th>
                        <th style={{ textAlign: "right" }}>Dif. vs prom.</th>
                        <th style={{ textAlign: "right" }}>Prima (bid)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ivSmileTemporalMoves.length === 0 ? (
                        <tr>
                          <td colSpan={7} className="options-empty-cell msg-muted">
                            Sin movimientos fuertes o sin historial IV previo.
                          </td>
                        </tr>
                      ) : (
                        ivSmileTemporalMoves.map((r, i) => (
                          <tr key={`${r.expiration}-${r.symbol}-${r.strike}-mov-${i}`}>
                            <td>{formatExpiryMonthLabel(r.expiration)}</td>
                            <td>
                              <code style={{ fontSize: "0.78rem" }}>{r.symbol}</code>
                            </td>
                            <td style={{ textAlign: "right" }}>{formatNumber(r.strike, 2)}</td>
                            <td style={{ textAlign: "right" }}>{`${formatNumber(r.iv_pct, 1)}%`}</td>
                            <td style={{ textAlign: "right" }} className={ivSmileDeltaIvCellClass(r.iv_change_pct)}>
                              {formatIvSmileDiffPct(r.iv_change_pct)}
                            </td>
                            <td style={{ textAlign: "right" }} className={ivSmileDiffCellClass(r.iv_diff_vs_avg_pct ?? undefined)}>
                              {formatIvSmileDiffPct(r.iv_diff_vs_avg_pct)}
                            </td>
                            <td style={{ textAlign: "right" }}>
                              {r.bid !== null ? <>$ {formatNumber(r.bid, 2)}</> : "—"}
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </section>
      ) : null}
      {activeTab === "panel" && emptyHintPanel ? (
        <div className="options-empty-state options-empty-state--compact" role="status">
          {emptyHintPanel}
        </div>
      ) : null}
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
        <>
          <div className="table-wrap">
          <table className="options-panel-chain-table">
            <thead>
              <tr>
                <th>Símbolo</th>
                <th>
                  <button
                    type="button"
                    className="options-panel-sort-th"
                    onClick={onPanelSortHeaderExpiryClick}
                    aria-label={
                      panelHeaderSort.kind === "expiry"
                        ? `Ordenar por vencimiento (${panelHeaderSort.dir === "asc" ? "ascendente" : "descendente"}); clic para cambiar`
                        : "Ordenar por vencimiento"
                    }
                  >
                    Vencimiento
                    {panelHeaderSort.kind === "expiry" ? (panelHeaderSort.dir === "asc" ? " ↑" : " ↓") : ""}
                  </button>
                </th>
                <th>Tipo</th>
                <th style={{ textAlign: "right" }}>
                  <button
                    type="button"
                    className="options-panel-sort-th options-panel-sort-th--end"
                    onClick={onPanelSortHeaderStrikeClick}
                    aria-label={
                      panelHeaderSort.kind === "strike"
                        ? `Ordenar por strike (${panelHeaderSort.dir === "asc" ? "ascendente" : "descendente"}); clic para cambiar`
                        : "Ordenar por strike"
                    }
                  >
                    Strike
                    {panelHeaderSort.kind === "strike" ? (panelHeaderSort.dir === "asc" ? " ↑" : " ↓") : ""}
                  </button>
                </th>
                <th>Moneyness</th>
                <th>Bid</th>
                <th>Ask</th>
                <th className="options-ba-col">Fuente</th>
                <th className="options-quote-status-col" title="Estado de la puntada IOL vs datos de cadena">
                  Estado
                </th>
                <th>Último</th>
                <th style={{ textAlign: "right" }} title={`IV implícita anual aprox. (Black–Scholes; r = ${(IV_RISK_FREE_RATE_ANNUAL * 100).toFixed(0)} %)`}>
                  IV %
                </th>
                <th style={{ textAlign: "right" }} title={OPTIONS_DESACOPLE_IV_COL_TOOLTIP}>
                  Desac. IV
                </th>
                <th title="Volumen (cadena o cotización IOL)">Volumen</th>
                <th>Op.</th>
                <th>OI</th>
              </tr>
            </thead>
            <tbody>
              {(() => {
                void iolQuoteStatusTick;
                const quoteStatusNow = Date.now();
                const quoteResponseSeen = { ...iolQuoteResponseSeenRef.current };
                const quoteLastGood = { ...iolLastGoodQuoteAtRef.current };
                return mergedFilteredContracts.map((c, i) => {
                  const m = getMoneyness(c, effectivePanelSpot);
                  const bid = getEffectiveBid(c, iolQuotes);
                  const ask = getEffectiveAsk(c, iolQuotes);
                  const vol = getEffectiveVolume(c, iolQuotes);
                  const ops = getEffectiveOperations(c, iolQuotes);
                  const qt = displayQuoteTime(c, iolQuotes);
                  const real = iolRealQuoteUsedForRow(c, iolQuotes);
                  const ba = displayBaSourceBadge(c, iolQuotes);
                  const quoteSt = panelRowQuoteStatus(c, {
                    chainIsIolPrimary,
                    quoteFetchSymbolSet: iolQuoteFetchSymbolSet,
                    iolQuotes,
                    loadingIolQuotes,
                    responseSeen: quoteResponseSeen,
                    lastGoodAt: quoteLastGood,
                    nowMs: quoteStatusNow,
                  });
                  const ekIv = expiryKeyFromMergedContract(c);
                  const dteIv = ekIv ? daysBetweenTodayAndExpiry(ekIv) : null;
                  const ivPct = impliedVolAnnualPercentForContract(c, iolQuotes, effectivePanelSpot, dteIv);
                  const desacopleIvPct = ekIv
                    ? desacopleIvPctRelFromMap(ivAvgPctByExpiryType, ekIv, mergedContractTypeUpper(c), ivPct)
                    : null;
                  return (
                    <tr key={`${c.symbol}-${i}`} className={mergedMoneynessRowClass(m)}>
                      <td>{fmtCell(c.symbol)}</td>
                      <td>{expiryKeyFromMergedContract(c) || "—"}</td>
                      <td>{fmtCell(c.option_type)}</td>
                      <td style={{ textAlign: "right" }}>{formatNumber(c.strike, 2)}</td>
                      <td>
                        <span className={mergedMoneynessBadgeClass(m)}>{mergedMoneynessBadgeText(m)}</span>
                      </td>
                      <td style={{ textAlign: "right" }}>{formatNumber(bid, 2)}</td>
                      <td style={{ textAlign: "right" }}>{formatNumber(ask, 2)}</td>
                      <td className="options-ba-col">
                        <span
                          className={`options-ba-badge${real ? " options-ba-badge-iol-live" : ""}`}
                          title={ba.title}
                        >
                          {ba.label}
                        </span>
                      </td>
                      <td className="options-quote-status-col">
                        <span
                          className={`options-quote-status-badge options-quote-status-${quoteSt.toLowerCase()}`}
                          title={PANEL_QUOTE_STATUS_TOOLTIP[quoteSt]}
                        >
                          {PANEL_QUOTE_STATUS_SHORT[quoteSt]}
                        </span>
                      </td>
                      <td style={{ textAlign: "right" }}>{formatNumber(c.last, 2)}</td>
                      <td style={{ textAlign: "right" }}>
                        {ivPct !== null && Number.isFinite(ivPct) ? `${formatNumber(ivPct, 1)}%` : "—"}
                      </td>
                      <td
                        style={{ textAlign: "right" }}
                        className={desacopleIvPctCellClass(desacopleIvPct)}
                      >
                        {formatDesacopleIvPct(desacopleIvPct)}
                      </td>
                      <td style={{ textAlign: "right" }} title={qt ?? undefined}>
                        {formatInteger(vol)}
                      </td>
                      <td style={{ textAlign: "right" }}>{ops === null ? "—" : formatInteger(ops)}</td>
                      <td style={{ textAlign: "right" }}>{formatPanelOpenInterest(c.open_interest)}</td>
                    </tr>
                  );
                });
              })()}
            </tbody>
          </table>
        </div>
        </>
      ) : null}

      {activeTab === "strategies" ? (
        <section className="options-page-blk options-page-blk--strategies" aria-labelledby="options-blk-strat-h">
          <h2 id="options-blk-strat-h" className="options-page-blk__title">
            Estrategias
          </h2>
          <p className="options-page-blk__lede msg-muted">Constructor manual y oportunidades prearmadas sobre la misma cadena.</p>
          {loadingChain && hasRequestedChain ? <p>Cargando cadena…</p> : null}
          {errorChain && (
            <p role="alert">
              Error: {errorChain}
            </p>
          )}
          {emptyHintStrategies && !loadingChain && !errorChain ? (
            <div className="options-empty-state options-empty-state--compact" role="status">
              {emptyHintStrategies}
            </div>
          ) : null}

          <div className="options-op-alerts" role="region" aria-label="Alertas de oportunidades operativas">
            <div className="options-section-title">Alertas de oportunidades</div>
            {operationalOpportunityAlerts.length === 0 ? (
              <div className="options-empty-state options-empty-state--compact" role="status">
                Sin oportunidades destacadas con los datos actuales
              </div>
            ) : (
              <ul className="options-op-alerts__list">
                {operationalOpportunityAlerts.map((a) => (
                  <li key={a.id} className={`options-op-alert-row options-op-alert-row--${a.severity}`}>
                    <div className="options-op-alert-main">{a.main}</div>
                    {a.meta ? <div className="options-op-alert-meta msg-muted">{a.meta}</div> : null}
                  </li>
                ))}
              </ul>
            )}
          </div>

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
                          <strong
                            className={
                              netCost.net < 0
                                ? "options-net-ledger options-net-ledger--debit"
                                : netCost.net > 0
                                  ? "options-net-ledger options-net-ledger--credit"
                                  : "options-net-ledger options-net-ledger--neutral"
                            }
                          >
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
                      <div className="options-empty-state options-empty-state--compact" role="status">
                        Agregá patas con “Agregar” desde las tablas CALL/PUT.
                      </div>
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
                      {strategiesFilter === "Cash Secured Put" ? (
                        <span> En este modo solo se listan PUTs (venta de put cubierta por caja).</span>
                      ) : null}
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
                          {strategiesFilter !== "Cash Secured Put"
                            ? calls.slice(0, 40).map((r, i) => {
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
                          })
                            : null}
                          {puts.slice(0, strategiesFilter === "Cash Secured Put" ? 80 : 40).map((r, i) => {
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
                    <option value="CALL Descubierta">CALL Descubierta</option>
                    <option value="Cash Secured Put">Cash Secured Put</option>
                    <option value="Collar">Collar</option>
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
                <div className="options-strategy-card">
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
                        <div className="options-empty-state options-empty-state--compact" role="status">
                          Sin calls con bid &gt; 0 en el feed actual.
                        </div>
                      ) : (
                        <div className="table-wrap">
                          <table className="strategy-opportunities-table">
                            <thead>
                              <tr>
                                <th>Vencimiento</th>
                                <th style={{ textAlign: "right" }}>Subyacente</th>
                                <th style={{ textAlign: "right" }}>Strike</th>
                                <th style={{ textAlign: "right" }}>Prima</th>
                                <th style={{ textAlign: "right" }} title={`IV implícita anual aprox. (Black–Scholes; r = ${(IV_RISK_FREE_RATE_ANNUAL * 100).toFixed(0)} %)`}>
                                  IV %
                                </th>
                                <th style={{ textAlign: "right" }} title={OPTIONS_DESACOPLE_IV_COL_TOOLTIP}>
                                  Desac. IV
                                </th>
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
                                  <td style={{ textAlign: "right" }}>
                                    {x.ivPct !== null && Number.isFinite(x.ivPct) ? `${formatNumber(x.ivPct, 1)}%` : "—"}
                                  </td>
                                  <td
                                    style={{ textAlign: "right" }}
                                    className={desacopleIvPctCellClass(x.desacopleIvPct)}
                                  >
                                    {formatDesacopleIvPct(x.desacopleIvPct)}
                                  </td>
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

              {strategiesFilter === "" || strategiesFilter === "CALL Descubierta" ? (
                <div className="options-strategy-card">
                  <button
                    type="button"
                    className="strategy-collapsible-header"
                    onClick={() => setShowNakedShortCall((v) => !v)}
                    aria-expanded={showNakedShortCall}
                  >
                    <div className="strategy-collapsible-title">
                      <span style={{ width: "1.15rem", display: "inline-block" }}>
                        {showNakedShortCall ? "−" : "+"}
                      </span>
                      CALL Descubierta
                    </div>
                    <div className="strategy-collapsible-summary">
                      {nakedShortCalls.length} oportunidades
                    </div>
                  </button>
                  {showNakedShortCall ? (
                    <div className="strategy-collapsible-body">
                      <p className="msg-muted options-page-blk__hint" style={{ marginTop: 0, marginBottom: "0.45rem" }} title="Venta de call sin acciones a cubrir; prima = bid efectivo; sin margen ni griegas.">
                        Call descubierta: prima = bid efectivo; métricas orientativas.
                      </p>
                      <span
                        className="options-naked-call-risk-badge options-risk-badge options-risk-badge--unlimited"
                        title={OPTIONS_NAKED_CALL_RISK_TOOLTIP}
                      >
                        Riesgo ilimitado
                      </span>
                      {nakedShortCalls.length === 0 ? (
                        <div className="options-empty-state options-empty-state--compact" role="status">
                          Sin calls con bid, spot y días válidos en el feed actual.
                        </div>
                      ) : (
                        <div className="table-wrap" style={{ marginTop: "0.55rem" }}>
                          <table className="strategy-opportunities-table">
                            <thead>
                              <tr>
                                <th>Vencimiento</th>
                                <th style={{ textAlign: "right" }}>Strike</th>
                                <th style={{ textAlign: "right" }}>Prima</th>
                                <th style={{ textAlign: "right" }} title="Prima / spot × 100">
                                  Prima %
                                </th>
                                <th style={{ textAlign: "right" }} title="(prima/strike)×(365/días)×100">
                                  TNA %
                                </th>
                                <th style={{ textAlign: "right" }} title="Strike + prima">
                                  Break-even
                                </th>
                                <th style={{ textAlign: "right" }} title="(strike − spot) / spot × 100">
                                  Δ vs spot %
                                </th>
                                <th style={{ textAlign: "right" }}>Días</th>
                                <th>Ticker</th>
                              </tr>
                            </thead>
                            <tbody>
                              {nakedShortCalls.map((x, idx) => (
                                <tr key={`nsc-${x.expiryKey}-${x.strike}-${idx}`}>
                                  <td>{formatExpiryMonthLabel(x.expiryKey)}</td>
                                  <td style={{ textAlign: "right" }}>{formatNumber(x.strike, 2)}</td>
                                  <td style={{ textAlign: "right" }}>{formatNumber(x.prima, 2)}</td>
                                  <td style={{ textAlign: "right" }}>{`${formatNumber(x.premiumPct, 2)}%`}</td>
                                  <td style={{ textAlign: "right" }}>{`${formatNumber(x.tnaPct, 2)}%`}</td>
                                  <td style={{ textAlign: "right" }}>{formatNumber(x.breakEven, 2)}</td>
                                  <td style={{ textAlign: "right" }}>{`${formatNumber(x.distPct, 2)}%`}</td>
                                  <td style={{ textAlign: "right" }}>{x.days !== null ? formatInteger(x.days) : "—"}</td>
                                  <td>{fmtCell(x.symbol)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  ) : null}
                </div>
              ) : null}

              {strategiesFilter === "" || strategiesFilter === "Cash Secured Put" ? (
                <div className="options-strategy-card">
                  <button
                    type="button"
                    className="strategy-collapsible-header"
                    onClick={() => setShowCashSecuredPut((v) => !v)}
                    aria-expanded={showCashSecuredPut}
                  >
                    <div className="strategy-collapsible-title">
                      <span style={{ width: "1.15rem", display: "inline-block" }}>
                        {showCashSecuredPut ? "−" : "+"}
                      </span>
                      Cash Secured Put
                    </div>
                    <div className="strategy-collapsible-summary">
                      {cashSecuredPuts.length} oportunidades
                    </div>
                  </button>
                  {showCashSecuredPut ? (
                    <div className="strategy-collapsible-body">
                      <p className="msg-muted options-page-blk__hint" style={{ marginTop: 0, marginBottom: "0.45rem" }} title={`Venta de put cubierta por caja; prima = bid efectivo; capital ≈ strike × ${formatInteger(OPTIONS_STRATEGY_LOT_SIZE)}.`}>
                        CSP: prima = bid; capital ≈ strike × lote ({formatInteger(OPTIONS_STRATEGY_LOT_SIZE)}).
                      </p>
                      {cashSecuredPuts.length === 0 ? (
                        <div className="options-empty-state options-empty-state--compact" role="status">
                          Sin puts con bid &gt; 0 en el feed actual.
                        </div>
                      ) : (
                        <div className="table-wrap">
                          <table className="strategy-opportunities-table">
                            <thead>
                              <tr>
                                <th>Vencimiento</th>
                                <th>Ticker</th>
                                <th style={{ textAlign: "right" }}>Strike</th>
                                <th style={{ textAlign: "right" }}>Prima</th>
                                <th style={{ textAlign: "right" }} title={`IV implícita anual aprox. (Black–Scholes; r = ${(IV_RISK_FREE_RATE_ANNUAL * 100).toFixed(0)} %)`}>
                                  IV %
                                </th>
                                <th style={{ textAlign: "right" }} title={OPTIONS_DESACOPLE_IV_COL_TOOLTIP}>
                                  Desac. IV
                                </th>
                                <th style={{ textAlign: "right" }}>Break-even</th>
                                <th
                                  style={{ textAlign: "right" }}
                                  title="((break-even / spot) − 1) × 100. Negativo: asignación por debajo del spot."
                                >
                                  BE vs Spot
                                </th>
                                <th style={{ textAlign: "right" }} title="(strike / spot − 1) × 100">
                                  Δ strike %
                                </th>
                                <th style={{ textAlign: "right" }}>Capital</th>
                                <th style={{ textAlign: "right" }} title="Prima / strike">
                                  Rend. simple
                                </th>
                                <th
                                  style={{ textAlign: "right" }}
                                  title="Anualización lineal del rendimiento simple; requiere spot y días al vencimiento"
                                >
                                  TNA
                                </th>
                                <th style={{ textAlign: "right" }}>Días</th>
                                <th style={{ textAlign: "right" }}>Volumen</th>
                                <th>Estado</th>
                              </tr>
                            </thead>
                            <tbody>
                              {(() => {
                                void iolQuoteStatusTick;
                                const quoteResponseSeen = { ...iolQuoteResponseSeenRef.current };
                                const quoteLastGood = { ...iolLastGoodQuoteAtRef.current };
                                const nowMs = Date.now();
                                return cashSecuredPuts.map((x, idx) => {
                                  const m = getMoneynessFromValues(x.strike, "PUT", effectivePanelSpot);
                                  const quoteSt = panelRowQuoteStatus(x.contract, {
                                    chainIsIolPrimary,
                                    quoteFetchSymbolSet: iolQuoteFetchSymbolSet,
                                    iolQuotes,
                                    loadingIolQuotes,
                                    responseSeen: quoteResponseSeen,
                                    lastGoodAt: quoteLastGood,
                                    nowMs,
                                  });
                                  return (
                                    <tr
                                      key={`csp-${(x.contract.symbol ?? "").trim()}-${x.expiryKey}-${x.strike}-${idx}`}
                                      className={mergedMoneynessRowClass(m)}
                                    >
                                      <td>{formatExpiryMonthLabel(x.expiryKey)}</td>
                                      <td>{fmtCell(x.contract.symbol)}</td>
                                      <td style={{ textAlign: "right" }}>{formatNumber(x.strike, 2)}</td>
                                      <td style={{ textAlign: "right" }}>{formatNumber(x.prima, 2)}</td>
                                      <td style={{ textAlign: "right" }}>
                                        {x.ivPct !== null && Number.isFinite(x.ivPct) ? `${formatNumber(x.ivPct, 1)}%` : "—"}
                                      </td>
                                      <td
                                        style={{ textAlign: "right" }}
                                        className={desacopleIvPctCellClass(x.desacopleIvPct)}
                                      >
                                        {formatDesacopleIvPct(x.desacopleIvPct)}
                                      </td>
                                      <td style={{ textAlign: "right" }}>{formatNumber(x.breakEven, 2)}</td>
                                      <td style={{ textAlign: "right" }}>
                                        {x.breakEvenVsSpotPct !== null
                                          ? `${formatNumber(x.breakEvenVsSpotPct, 2)}%`
                                          : "-"}
                                      </td>
                                      <td style={{ textAlign: "right" }}>
                                        {x.distStrikePct !== null ? `${formatNumber(x.distStrikePct, 2)}%` : "-"}
                                      </td>
                                      <td style={{ textAlign: "right" }}>${formatNumber(x.capital, 2)}</td>
                                      <td style={{ textAlign: "right" }}>{`${formatNumber(x.rendSimplePct, 2)}%`}</td>
                                      <td style={{ textAlign: "right" }}>
                                        {x.tnaPct !== null ? `${formatNumber(x.tnaPct, 2)}%` : "-"}
                                      </td>
                                      <td style={{ textAlign: "right" }}>
                                        {x.days !== null ? formatInteger(x.days) : "-"}
                                      </td>
                                      <td style={{ textAlign: "right" }}>{formatInteger(x.vol)}</td>
                                      <td>
                                        <span
                                          className={`options-quote-status-badge options-quote-status-${quoteSt.toLowerCase()}`}
                                          title={PANEL_QUOTE_STATUS_TOOLTIP[quoteSt]}
                                        >
                                          {PANEL_QUOTE_STATUS_SHORT[quoteSt]}
                                        </span>
                                      </td>
                                    </tr>
                                  );
                                });
                              })()}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  ) : null}
                </div>
              ) : null}

              {strategiesFilter === "" || strategiesFilter === "Collar" ? (
                <div className="options-strategy-card">
                  <button
                    type="button"
                    className="strategy-collapsible-header"
                    onClick={() => setShowCollar((v) => !v)}
                    aria-expanded={showCollar}
                  >
                    <div className="strategy-collapsible-title">
                      <span style={{ width: "1.15rem", display: "inline-block" }}>{showCollar ? "−" : "+"}</span>
                      Collar
                    </div>
                    <div className="strategy-collapsible-summary">{collarOpportunities.length} combinaciones</div>
                  </button>
                  {showCollar ? (
                    <div className="strategy-collapsible-body">
                      <p className="msg-muted options-strategy-collar-hint options-page-blk__hint" style={{ marginTop: 0, marginBottom: "0.45rem" }} title="Put comprado (ask) + call vendido (bid), mismo vencimiento; put K &lt; spot &lt; call K.">
                        Collar: put protectora + call OTM; mismas fechas; cifras orientativas.
                      </p>
                      <div className="options-strategy-risk-row">
                        <span className="options-risk-badge options-risk-badge--limited" title="Pérdida acotada vs spot con put OTM (aprox.).">
                          Riesgo limitado (aprox.)
                        </span>
                      </div>
                      <p className="msg-muted options-strategy-collar-sub" style={{ marginBottom: "0.45rem" }}>
                        Montos estimados por 1 contrato = 100 acciones, usando spot actual.
                      </p>
                      {collarOpportunities.length === 0 ? (
                        <div className="options-empty-state options-empty-state--compact" role="status">
                          Sin collars válidos para este activo con datos actuales.
                        </div>
                      ) : (
                        <div className="table-wrap">
                          <table className="strategy-opportunities-table options-strategy-collar-table">
                            <thead>
                              <tr>
                                <th>Vencimiento</th>
                                <th>PUT comprado</th>
                                <th>CALL vendido</th>
                                <th style={{ textAlign: "right" }} title="Spot × 100 acciones">
                                  Costo acciones
                                </th>
                                <th style={{ textAlign: "right" }} title="(call_bid − put_ask) × 100">
                                  Prima neta
                                </th>
                                <th style={{ textAlign: "right" }} title="(spot − prima neta por acción) × 100">
                                  Costo total
                                </th>
                                <th style={{ textAlign: "right" }} title="Put strike × 100 / Call strike × 100">
                                  Piso / Techo
                                </th>
                                <th style={{ textAlign: "right" }} title="Pérdida y ganancia máx. aprox. × 100">
                                  Pérd. máx. / Gcia. máx.
                                </th>
                                <th>Comentario</th>
                              </tr>
                            </thead>
                            <tbody>
                              {collarOpportunities.map((x, idx) => {
                                const lot = OPTIONS_STRATEGY_LOT_SIZE;
                                const spotNum = effectivePanelSpot;
                                const hasSpot = spotNum !== null && spotNum > 0 && Number.isFinite(spotNum);
                                const costoAccionesContrato = hasSpot ? spotNum * lot : null;
                                const primaNetaContrato = Number.isFinite(x.neto) ? x.neto * lot : null;
                                const costoTotalCollarContrato =
                                  hasSpot && Number.isFinite(x.neto) ? (spotNum - x.neto) * lot : null;
                                const pisoContrato = Number.isFinite(x.putStrike) ? x.putStrike * lot : null;
                                const techoContrato = Number.isFinite(x.callStrike) ? x.callStrike * lot : null;
                                const perdidaMaxContrato = Number.isFinite(x.perdidaMax) ? x.perdidaMax * lot : null;
                                const gananciaMaxContrato = Number.isFinite(x.gananciaMax) ? x.gananciaMax * lot : null;
                                const netoAcc = x.neto;
                                const costoTotalAcc = hasSpot && Number.isFinite(x.neto) ? spotNum - x.neto : null;
                                return (
                                <tr key={`collar-${x.expiryKey}-${x.putSymbol}-${x.callSymbol}-${idx}`}>
                                  <td>{formatExpiryMonthLabel(x.expiryKey)}</td>
                                  <td>
                                    <div>
                                      <code className="options-strategy-collar-sym">{fmtCell(x.putSymbol)}</code>
                                    </div>
                                    <div className="msg-muted options-strategy-collar-sub">PUT K {formatNumber(x.putStrike, 2)}</div>
                                  </td>
                                  <td>
                                    <div>
                                      <code className="options-strategy-collar-sym">{fmtCell(x.callSymbol)}</code>
                                    </div>
                                    <div className="msg-muted options-strategy-collar-sub">CALL K {formatNumber(x.callStrike, 2)}</div>
                                  </td>
                                  <td style={{ textAlign: "right" }}>
                                    {costoAccionesContrato !== null ? (
                                      <>
                                        <div>$ {formatNumber(costoAccionesContrato, 2)}</div>
                                        <div className="msg-muted options-strategy-collar-sub" title="Por acción">
                                          ×1: {formatNumber(spotNum, 2)}
                                        </div>
                                      </>
                                    ) : (
                                      "—"
                                    )}
                                  </td>
                                  <td style={{ textAlign: "right" }}>
                                    {primaNetaContrato !== null ? (
                                      <>
                                        <div>$ {formatNumber(primaNetaContrato, 2)}</div>
                                        <div className="msg-muted options-strategy-collar-sub" title="Por acción">
                                          ×1: {formatNumber(netoAcc, 2)}
                                        </div>
                                      </>
                                    ) : (
                                      "—"
                                    )}
                                  </td>
                                  <td style={{ textAlign: "right" }}>
                                    {costoTotalCollarContrato !== null && costoTotalAcc !== null ? (
                                      <>
                                        <div>$ {formatNumber(costoTotalCollarContrato, 2)}</div>
                                        <div className="msg-muted options-strategy-collar-sub" title="Por acción">
                                          ×1: {formatNumber(costoTotalAcc, 2)}
                                        </div>
                                      </>
                                    ) : (
                                      "—"
                                    )}
                                  </td>
                                  <td style={{ textAlign: "right" }}>
                                    {pisoContrato !== null && techoContrato !== null ? (
                                      <>
                                        <div>
                                          $ {formatNumber(pisoContrato, 2)} / $ {formatNumber(techoContrato, 2)}
                                        </div>
                                        <div className="msg-muted options-strategy-collar-sub" title="Strikes por acción">
                                          K: {formatNumber(x.putStrike, 2)} / {formatNumber(x.callStrike, 2)}
                                        </div>
                                      </>
                                    ) : (
                                      "—"
                                    )}
                                  </td>
                                  <td style={{ textAlign: "right" }}>
                                    {perdidaMaxContrato !== null && gananciaMaxContrato !== null ? (
                                      <>
                                        <div>
                                          $ {formatNumber(perdidaMaxContrato, 2)} / $ {formatNumber(gananciaMaxContrato, 2)}
                                        </div>
                                        <div className="msg-muted options-strategy-collar-sub" title="Por acción">
                                          ×1: {formatNumber(x.perdidaMax, 2)} / {formatNumber(x.gananciaMax, 2)}
                                        </div>
                                      </>
                                    ) : (
                                      "—"
                                    )}
                                  </td>
                                  <td>
                                    <span className={`options-strategy-collar-comment ${collarNetCommentClass(x.comentario)}`}>
                                      {x.comentario}
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

              <div className="msg-muted" style={{ marginTop: "0.9rem" }}>
                Próximamente: Bear Put Spread, Protective Put.
              </div>
            </section>
        </section>
      ) : null}
    </div>
  );
}
