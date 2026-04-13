import type { RadarRow } from "@/services/api";

import type { ColumnDef, SortCriterion } from "./radarTableModel";

const USD_FORMAT = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
  minimumFractionDigits: 0,
});

const ARS_FORMAT = new Intl.NumberFormat("es-AR", {
  style: "currency",
  currency: "ARS",
  maximumFractionDigits: 0,
  minimumFractionDigits: 0,
});

/** Ratios de valoración (alineado con decimales típicos del radar). */
const RATIO_FORMAT = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

export function getRaw(row: RadarRow, keys: string[]): unknown {
  for (const k of keys) {
    if (!(k in row)) {
      continue;
    }
    const v = row[k];
    if (v === null || v === undefined || v === "") {
      continue;
    }
    return v;
  }
  return undefined;
}

export function parseNumberLoose(raw: unknown): number | null {
  if (raw === null || raw === undefined || raw === "") {
    return null;
  }
  if (typeof raw === "number") {
    return Number.isFinite(raw) ? raw : null;
  }
  const s = String(raw)
    .trim()
    .replace(/\s/g, "")
    .replace(/[$€£]/g, "")
    .replace(/,/g, "");
  const n = parseFloat(s);
  return Number.isFinite(n) ? n : null;
}

export function formatTrend(raw: unknown): { text: string; missing: boolean } {
  if (raw === null || raw === undefined || raw === "") {
    return { text: "—", missing: true };
  }
  if (typeof raw === "boolean") {
    return { text: raw ? "Alcista" : "No alcista", missing: false };
  }
  if (typeof raw === "number") {
    if (!Number.isFinite(raw)) {
      return { text: "—", missing: true };
    }
    if (raw === 1) {
      return { text: "Alcista", missing: false };
    }
    if (raw === 0) {
      return { text: "No alcista", missing: false };
    }
    return { text: raw > 0 ? "Alcista" : "No alcista", missing: false };
  }

  const s = String(raw).trim();
  const lower = s.toLowerCase();

  const positive = new Set([
    "alcista",
    "sí",
    "si",
    "yes",
    "true",
    "bull",
    "bullish",
    "uptrend",
    "up",
    "positive",
  ]);
  const negative = new Set([
    "no alcista",
    "bajista",
    "no",
    "false",
    "bear",
    "bearish",
    "downtrend",
    "down",
    "negative",
  ]);

  if (positive.has(lower)) {
    return { text: "Alcista", missing: false };
  }
  if (negative.has(lower)) {
    return { text: "No alcista", missing: false };
  }
  if (lower.includes("uptrend") || lower.includes("bull")) {
    return { text: "Alcista", missing: false };
  }
  if (lower.includes("downtrend") || lower.includes("bear")) {
    return { text: "No alcista", missing: false };
  }

  return { text: s, missing: false };
}

export function formatEbitdaUsd(raw: unknown): { text: string; missing: boolean } {
  const n = parseNumberLoose(raw);
  if (n === null) {
    return { text: "—", missing: true };
  }
  return { text: USD_FORMAT.format(n), missing: false };
}

export function formatEbitdaArs(raw: unknown): { text: string; missing: boolean } {
  const n = parseNumberLoose(raw);
  if (n === null) {
    return { text: "—", missing: true };
  }
  return { text: ARS_FORMAT.format(n), missing: false };
}

const PRECIO_AR_DISPLAY = new Intl.NumberFormat("es-AR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** Precio con prefijo $ y separadores locales (ej. $1.234,56). Solo presentación. */
export function formatPrecioDolarAr(raw: unknown): { text: string; missing: boolean } {
  const n = parseNumberLoose(raw);
  if (n === null) {
    return { text: "—", missing: true };
  }
  return { text: `$${PRECIO_AR_DISPLAY.format(n)}`, missing: false };
}

export function formatRatioMetric(raw: unknown): { text: string; missing: boolean } {
  const n = parseNumberLoose(raw);
  if (n === null) {
    return { text: "—", missing: true };
  }
  return { text: RATIO_FORMAT.format(n), missing: false };
}

/**
 * Yahoo Finance devuelve debtToEquity como porcentaje (p. ej. 102.63 = 102.63%).
 * El ratio deuda/patrimonio es valor/100 para mostrar y ordenar de forma coherente.
 */
export function debtToEquityPercentToRatio(raw: unknown): number | null {
  const pct = parseNumberLoose(raw);
  if (pct === null) {
    return null;
  }
  return pct / 100;
}

/** Muestra el ratio (post normalización desde % Yahoo), no moneda. */
export function formatDebtEquityRatio(raw: unknown): { text: string; missing: boolean } {
  const ratio = debtToEquityPercentToRatio(raw);
  if (ratio === null) {
    return { text: "—", missing: true };
  }
  return { text: `${RATIO_FORMAT.format(ratio)}x`, missing: false };
}

/** MACD alcista: solo lectura / presentación; mismas claves que el backend. */
export function formatMacdAlcista(raw: unknown): { text: string; missing: boolean } {
  if (raw === null || raw === undefined || raw === "") {
    return { text: "—", missing: true };
  }
  if (typeof raw === "boolean") {
    return { text: raw ? "Sí" : "No", missing: false };
  }
  if (typeof raw === "number") {
    if (!Number.isFinite(raw)) {
      return { text: "—", missing: true };
    }
    if (raw === 1) {
      return { text: "Sí", missing: false };
    }
    if (raw === 0) {
      return { text: "No", missing: false };
    }
    return { text: raw > 0 ? "Sí" : "No", missing: false };
  }
  const s = String(raw).trim();
  const lower = s.toLowerCase();
  const yes = new Set([
    "true",
    "1",
    "yes",
    "y",
    "si",
    "sí",
    "t",
    "bull",
    "bullish",
  ]);
  const no = new Set(["false", "0", "no", "n", "f", "bear", "bearish"]);
  if (yes.has(lower)) {
    return { text: "Sí", missing: false };
  }
  if (no.has(lower)) {
    return { text: "No", missing: false };
  }
  if (lower.includes("bull")) {
    return { text: "Sí", missing: false };
  }
  if (lower.includes("bear")) {
    return { text: "No", missing: false };
  }
  return { text: "—", missing: true };
}

export function formatScalar(raw: unknown): { text: string; missing: boolean } {
  if (raw === null || raw === undefined || raw === "") {
    return { text: "—", missing: true };
  }
  if (typeof raw === "boolean") {
    return { text: raw ? "Sí" : "No", missing: false };
  }
  if (typeof raw === "number") {
    return Number.isFinite(raw)
      ? { text: String(raw), missing: false }
      : { text: "—", missing: true };
  }
  return { text: String(raw), missing: false };
}

export type CellFormatOptions = {
  formatEbitda: (raw: unknown) => { text: string; missing: boolean };
  formatPrecio?: (raw: unknown) => { text: string; missing: boolean };
};

export function cellForColumn(
  col: ColumnDef,
  row: RadarRow,
  opts: CellFormatOptions,
): { text: string; missing: boolean } {
  const raw = getRaw(row, col.keys);
  if (col.id === "trend") {
    return formatTrend(raw);
  }
  if (col.id === "ebitda") {
    return opts.formatEbitda(raw);
  }
  if (col.id === "precio" && opts.formatPrecio) {
    return opts.formatPrecio(raw);
  }
  if (col.id === "priceToBook") {
    return formatRatioMetric(raw);
  }
  if (col.id === "leverage") {
    return formatDebtEquityRatio(raw);
  }
  if (col.id === "debtToEbitda") {
    return formatRatioMetric(raw);
  }
  if (col.id === "macd") {
    return formatMacdAlcista(raw);
  }
  return formatScalar(raw);
}

/** Valor para ordenar (null = ausente, va al final en asc). */
export function sortableValue(row: RadarRow, col: ColumnDef): string | number | null {
  if (col.sortKind === null || col.sortKind === undefined) {
    return null;
  }
  const raw = getRaw(row, col.keys);
  if (col.sortKind === "trend") {
    const t = formatTrend(raw);
    if (t.missing) {
      return null;
    }
    return t.text === "Alcista" ? 1 : 0;
  }
  if (col.sortKind === "flag") {
    const f = formatMacdAlcista(raw);
    if (f.missing) {
      return null;
    }
    return f.text === "Sí" ? 1 : 0;
  }
  if (col.sortKind === "number") {
    if (col.id === "leverage") {
      return debtToEquityPercentToRatio(raw);
    }
    return parseNumberLoose(raw);
  }
  if (raw === null || raw === undefined || raw === "") {
    return null;
  }
  return String(raw).trim().toLowerCase();
}

export function compareNullable(
  a: string | number | null,
  b: string | number | null,
): number {
  const aMissing = a === null;
  const bMissing = b === null;
  if (aMissing && bMissing) {
    return 0;
  }
  if (aMissing) {
    return 1;
  }
  if (bMissing) {
    return -1;
  }
  if (typeof a === "number" && typeof b === "number") {
    return a - b;
  }
  return String(a).localeCompare(String(b), "es", { numeric: true });
}

export function compareRowsByCriteria(
  a: RadarRow,
  b: RadarRow,
  criteria: SortCriterion[],
  columnById: Record<string, ColumnDef>,
  tickerCol: ColumnDef,
): number {
  for (const { columnId, dir } of criteria) {
    const col = columnById[columnId];
    if (!col || col.sortKind === null || col.sortKind === undefined) {
      continue;
    }
    const va = sortableValue(a, col);
    const vb = sortableValue(b, col);
    const base = compareNullable(va, vb);
    if (base !== 0) {
      return dir === "asc" ? base : -base;
    }
  }
  const ta = String(sortableValue(a, tickerCol) ?? "");
  const tb = String(sortableValue(b, tickerCol) ?? "");
  return ta.localeCompare(tb, "es", { numeric: true });
}

export function initialColWidths(columns: ColumnDef[]): Record<string, number> {
  return Object.fromEntries(columns.map((c) => [c.id, c.minWidth]));
}

export function totalScoreToneClass(row: RadarRow, totalKeys: string[]): string | undefined {
  const v = parseNumberLoose(getRaw(row, totalKeys));
  if (v === null) {
    return undefined;
  }
  if (v >= 10) {
    return "radar-cell--score-high";
  }
  if (v >= 8) {
    return "radar-cell--score-mid";
  }
  if (v >= 5) {
    return "radar-cell--score-low";
  }
  return "radar-cell--score-very-low";
}

export function rsiToneClass(row: RadarRow, rsiKeys: string[]): string | undefined {
  const v = parseNumberLoose(getRaw(row, rsiKeys));
  if (v === null) {
    return undefined;
  }
  if (v <= 35) {
    return "radar-cell--rsi-oversold";
  }
  if (v >= 70) {
    return "radar-cell--rsi-hot";
  }
  return undefined;
}
