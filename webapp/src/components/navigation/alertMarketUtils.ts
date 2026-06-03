/**
 * Normalización de mercado/origen para alertas (filtros y navegación).
 * No altera scoring ni el motor de alertas.
 */

export type MercadoBucket = "usa" | "argentina" | "otro";

/** Campos opcionales presentes en alertas actuales, historial o análisis. */
export type AlertMarketHint = {
  ticker?: string | null;
  mercado?: string | null;
  panel?: unknown;
  universo?: unknown;
  country?: string | null;
  region?: string | null;
  source?: string | null;
  exchange?: string | null;
  asset_type?: string | null;
};

const USA_EXACT = new Set([
  "USA",
  "US",
  "U.S.",
  "U.S.A.",
  "UNITED STATES",
  "UNITED STATES OF AMERICA",
  "NYSE",
  "NASDAQ",
  "NMS",
  "AMEX",
  "ARCA",
  "BATS",
]);

const AR_EXACT = new Set([
  "ARGENTINA",
  "AR",
  "ARG",
  "MERVAL",
  "BYMA",
  "BCBA",
  "BURCAP",
  "ROFEX",
  "GENERAL",
  "PANEL GENERAL",
  "PANEL_GENERAL",
]);

function normToken(raw: unknown): string {
  return String(raw ?? "")
    .trim()
    .toUpperCase()
    .replace(/\s+/g, " ");
}

function pushHintToken(out: string[], raw: unknown): void {
  const s = normToken(raw);
  if (s && s !== "NAN" && s !== "—" && s !== "-") {
    out.push(s);
  }
}

/** Recolecta tokens de mercado/origen para heurísticas. */
export function collectAlertMarketTokens(hint: AlertMarketHint | null | undefined): string[] {
  if (!hint) return [];
  const out: string[] = [];
  pushHintToken(out, hint.mercado);
  pushHintToken(out, hint.panel);
  pushHintToken(out, hint.universo);
  pushHintToken(out, hint.country);
  pushHintToken(out, hint.region);
  pushHintToken(out, hint.source);
  pushHintToken(out, hint.exchange);
  pushHintToken(out, hint.asset_type);
  return out;
}

function tickerSuggestsArgentina(ticker: string | null | undefined): boolean {
  const t = (ticker ?? "").trim().toUpperCase();
  if (!t) return false;
  if (t.endsWith(".BA")) return true;
  return false;
}

function tokenSuggestsUsa(token: string): boolean {
  if (USA_EXACT.has(token)) return true;
  if (token.includes("NASDAQ") || token.includes("NYSE")) return true;
  if (token.startsWith("USA ") || token.endsWith(" USA")) return true;
  return false;
}

function tokenSuggestsArgentina(token: string): boolean {
  if (AR_EXACT.has(token)) return true;
  if (token.includes("ARGENTINA")) return true;
  if (token.includes("MERVAL")) return true;
  if (token.includes("BYMA")) return true;
  if (token.includes("BCBA")) return true;
  if (token === "GENERAL" || token.includes("PANEL GENERAL")) return true;
  return false;
}

/** True si la alerta corresponde a BYMA / Merval / Argentina. */
export function isArgentinaAlert(hint: AlertMarketHint | null | undefined): boolean {
  if (!hint) return false;
  if (tickerSuggestsArgentina(hint.ticker)) return true;
  for (const token of collectAlertMarketTokens(hint)) {
    if (tokenSuggestsArgentina(token)) return true;
  }
  return false;
}

/** True si la alerta corresponde a USA (NYSE/Nasdaq, etc.). */
export function isUsaAlert(hint: AlertMarketHint | null | undefined): boolean {
  if (!hint) return false;
  if (tickerSuggestsArgentina(hint.ticker)) return false;
  for (const token of collectAlertMarketTokens(hint)) {
    if (tokenSuggestsUsa(token)) return true;
  }
  return false;
}

/** Bucket para filtros y rutas; prioriza Argentina si hay señales mixtas locales. */
export function mercadoBucketFromAlert(hint: AlertMarketHint | null | undefined): MercadoBucket {
  if (!hint) return "otro";
  const ar = isArgentinaAlert(hint);
  const us = isUsaAlert(hint);
  if (ar && !us) return "argentina";
  if (us && !ar) return "usa";
  if (ar && us) return "argentina";
  return "otro";
}

/** Etiqueta para TickerRadarLink / radarHref (USA | Argentina). */
export function mercadoLabelForRadarLink(hint: AlertMarketHint | null | undefined): string | null {
  const b = mercadoBucketFromAlert(hint);
  if (b === "usa") return "USA";
  if (b === "argentina") return "Argentina";
  const raw = (hint?.mercado ?? "").trim();
  return raw || null;
}

/** Compat: bucket sólo desde string mercado (usar preferentemente mercadoBucketFromAlert). */
export function mercadoBucket(m: string | null | undefined): MercadoBucket {
  return mercadoBucketFromAlert({ mercado: m });
}
