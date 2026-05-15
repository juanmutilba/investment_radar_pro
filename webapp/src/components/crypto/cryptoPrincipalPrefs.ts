import { DEFAULT_FAVORITE_SYMBOLS, normalizeFavoriteSymbolInput } from "@/components/crypto/CryptoPrincipalMarket";

export const CRYPTO_FAVORITE_SYMBOLS_KEY = "crypto.favoriteSymbols";
export const CRYPTO_USE_FAVORITES_FOR_SIGNALS_KEY = "crypto.useFavoritesForSignals";

function safeParseJson(raw: string | null): unknown {
  if (raw === null || raw === "") return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function normalizeSymbolList(symbols: unknown): string[] {
  if (!Array.isArray(symbols)) return [];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const item of symbols) {
    if (typeof item !== "string") continue;
    const trimmed = item.trim();
    if (!trimmed) continue;
    const norm = normalizeFavoriteSymbolInput(trimmed);
    if (!norm || seen.has(norm)) continue;
    seen.add(norm);
    out.push(norm);
  }
  return out;
}

export function loadFavoriteSymbols(): string[] {
  if (typeof window === "undefined") {
    return [...DEFAULT_FAVORITE_SYMBOLS];
  }
  const parsed = safeParseJson(localStorage.getItem(CRYPTO_FAVORITE_SYMBOLS_KEY));
  const list = normalizeSymbolList(parsed);
  return list.length > 0 ? list : [...DEFAULT_FAVORITE_SYMBOLS];
}

export function saveFavoriteSymbols(symbols: string[]): void {
  if (typeof window === "undefined") return;
  const list = normalizeSymbolList(symbols);
  if (list.length === 0) return;
  try {
    localStorage.setItem(CRYPTO_FAVORITE_SYMBOLS_KEY, JSON.stringify(list));
  } catch {
    /* quota / private mode */
  }
}

export function loadUseFavoritesForSignals(): boolean {
  if (typeof window === "undefined") return true;
  const raw = localStorage.getItem(CRYPTO_USE_FAVORITES_FOR_SIGNALS_KEY);
  if (raw === null) return true;
  if (raw === "true") return true;
  if (raw === "false") return false;
  const parsed = safeParseJson(raw);
  if (typeof parsed === "boolean") return parsed;
  return true;
}

export function saveUseFavoritesForSignals(value: boolean): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(CRYPTO_USE_FAVORITES_FOR_SIGNALS_KEY, JSON.stringify(value));
  } catch {
    /* quota / private mode */
  }
}
