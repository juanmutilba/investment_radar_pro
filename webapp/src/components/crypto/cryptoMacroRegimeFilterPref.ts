/**
 * Preferencia UI compartida: filtro macro BTC 4h EMA200 en paper y auto testnet.
 * Default false; no activa el filtro hasta que el usuario lo marque en la pestaña Bot.
 */
const STORAGE_KEY = "crypto_bot_macro_regime_filter_v1";

export function loadCryptoMacroRegimeFilterPref(): boolean {
  if (typeof localStorage === "undefined") return false;
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "1" || v === "true";
  } catch {
    return false;
  }
}

export function persistCryptoMacroRegimeFilterPref(enabled: boolean): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, enabled ? "1" : "0");
  } catch {
    /* localStorage opcional */
  }
}
