import type { PortfolioAssetType, PortfolioOpenRow } from "@/services/api";

export function todayIsoDate(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Número finito y > 0 (cantidad / precio / TC). */
export function parsePositiveNumber(s: string): number | null {
  const t = s.trim();
  if (!t) return null;
  const n = Number(t.replace(",", "."));
  if (!Number.isFinite(n) || n <= 0) return null;
  return n;
}

export type BuyInvalidFlags = { ticker: boolean; date: boolean; qty: boolean; price: boolean; mep: boolean };
export type SellInvalidFlags = { date: boolean; qty: boolean; price: boolean; mep: boolean };

export function computeBuyValidation(
  ticker: string,
  buyDate: string,
  quantity: string,
  assetType: PortfolioAssetType,
  buyPriceArs: string,
  buyPriceUsd: string,
  buyTcMep: string,
): { valid: boolean; message: string; inv: BuyInvalidFlags } {
  const inv: BuyInvalidFlags = { ticker: false, date: false, qty: false, price: false, mep: false };
  const missing: string[] = [];
  if (!ticker.trim()) {
    missing.push("ticker");
    inv.ticker = true;
  }
  if (!buyDate?.trim()) {
    missing.push("fecha de compra");
    inv.date = true;
  }
  if (parsePositiveNumber(quantity) === null) {
    missing.push("cantidad (> 0)");
    inv.qty = true;
  }
  let priceOk = false;
  if (assetType === "USA") {
    priceOk = parsePositiveNumber(buyPriceUsd) !== null;
  } else if (assetType === "Argentina") {
    priceOk = parsePositiveNumber(buyPriceArs) !== null;
  } else {
    priceOk = parsePositiveNumber(buyPriceUsd) !== null;
  }
  if (!priceOk) {
    missing.push(assetType === "Argentina" ? "precio en ARS" : "precio en USD");
    inv.price = true;
  }
  if (assetType === "Argentina" || assetType === "CEDEAR") {
    if (parsePositiveNumber(buyTcMep) === null) {
      missing.push("TC MEP compra");
      inv.mep = true;
    }
  }
  const valid = missing.length === 0;
  return {
    valid,
    message: valid ? "" : `Completá los datos obligatorios: ${missing.join(", ")}.`,
    inv,
  };
}

export function computeSellValidation(
  sellTarget: PortfolioOpenRow | null,
  sellDate: string,
  sellPriceArs: string,
  sellPriceUsd: string,
  sellCedearUsd: string,
  sellTcMep: string,
): { valid: boolean; message: string; inv: SellInvalidFlags } {
  const inv: SellInvalidFlags = { date: false, qty: false, price: false, mep: false };
  if (!sellTarget) {
    return { valid: true, message: "", inv };
  }
  const missing: string[] = [];
  if (!sellDate?.trim()) {
    missing.push("fecha de venta");
    inv.date = true;
  }
  const q = sellTarget.quantity;
  if (!(typeof q === "number" && Number.isFinite(q) && q > 0)) {
    missing.push("cantidad de la posición");
    inv.qty = true;
  }
  const at = sellTarget.asset_type;
  let priceOk = false;
  if (at === "USA") {
    priceOk = parsePositiveNumber(sellPriceUsd) !== null;
  } else if (at === "Argentina") {
    priceOk = parsePositiveNumber(sellPriceArs) !== null;
  } else {
    priceOk = parsePositiveNumber(sellCedearUsd) !== null;
  }
    if (!priceOk) {
      missing.push(
        at === "Argentina" ? "precio de venta ARS" : at === "CEDEAR" ? "precio venta USD (ref USA)" : "precio de venta USD",
      );
    inv.price = true;
  }
  if (at === "Argentina" || at === "CEDEAR") {
    if (parsePositiveNumber(sellTcMep) === null) {
      missing.push("TC MEP venta");
      inv.mep = true;
    }
  }
  const valid = missing.length === 0;
  return {
    valid,
    message: valid ? "" : `Completá los datos obligatorios: ${missing.join(", ")}.`,
    inv,
  };
}

/** Para prellenar inputs de precio desde números del radar. */
export function formatPriceInputArs(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "";
  return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/\.?0+$/, "");
}

export function formatPriceInputUsd(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "";
  const s = n.toFixed(4);
  return s.replace(/\.?0+$/, "") || "0";
}
