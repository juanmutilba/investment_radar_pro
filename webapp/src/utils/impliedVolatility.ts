/**
 * Volatilidad implícita aproximada (Black–Scholes europeo, sin dividendos).
 * Uso: comparación relativa entre contratos; no precisión de mercado.
 */

/** Tasa libre de riesgo anual (constante) en el descuento BS; ajustable acá sin tocar el resto del módulo. */
export const IV_RISK_FREE_RATE_ANNUAL = 0.45;

function erfApprox(x: number): number {
  const sign = x < 0 ? -1 : 1;
  const ax = Math.abs(x);
  const a1 = 0.254829592;
  const a2 = -0.284496736;
  const a3 = 1.421413741;
  const a4 = -1.453152027;
  const a5 = 1.061405429;
  const p = 0.3275911;
  const t = 1 / (1 + p * ax);
  const y = 1 - ((((a5 * t + a4) * t + a3) * t + a2) * t + a1) * t * Math.exp(-ax * ax);
  return sign * y;
}

function normCdf(x: number): number {
  if (x < -10) return 0;
  if (x > 10) return 1;
  return 0.5 * (1 + erfApprox(x / Math.SQRT2));
}

function blackScholesEuropean(
  spot: number,
  strike: number,
  timeYears: number,
  riskFree: number,
  sigma: number,
  call: boolean,
): number {
  if (!(spot > 0) || !(strike > 0) || !(sigma > 0)) return Number.NaN;
  if (timeYears <= 0) {
    return call ? Math.max(spot - strike, 0) : Math.max(strike - spot, 0);
  }
  const sqrtT = Math.sqrt(timeYears);
  const d1 = (Math.log(spot / strike) + (riskFree + 0.5 * sigma * sigma) * timeYears) / (sigma * sqrtT);
  const d2 = d1 - sigma * sqrtT;
  const disc = Math.exp(-riskFree * timeYears);
  if (call) {
    return spot * normCdf(d1) - strike * disc * normCdf(d2);
  }
  return strike * disc * normCdf(-d2) - spot * normCdf(-d1);
}

/**
 * Prioridad de precio para marcar IV (no modifica getEffective* del resto de la app).
 * midpoint bid/ask si ambos > 0; si no bid > 0; si no ask > 0; si no último > 0.
 */
export function optionMarkPriceForIv(
  bid: number | null,
  ask: number | null,
  last: number | null,
): number | null {
  const b = bid !== null && Number.isFinite(bid) && bid > 0 ? bid : null;
  const a = ask !== null && Number.isFinite(ask) && ask > 0 ? ask : null;
  const l = last !== null && Number.isFinite(last) && last > 0 ? last : null;
  if (b !== null && a !== null) return (b + a) / 2;
  if (b !== null) return b;
  if (a !== null) return a;
  return l;
}

/**
 * IV anual en puntos porcentuales (ej. 42.5 → 42,5 %).
 * `null` si no hay bracket, no converge o precio incompatible con el modelo.
 */
export function impliedVolatilityAnnualPercent(opts: {
  spot: number;
  strike: number;
  markPrice: number;
  timeYears: number;
  call: boolean;
  riskFreeAnnual?: number;
}): number | null {
  const { spot, strike, markPrice, timeYears, call } = opts;
  const r = opts.riskFreeAnnual ?? IV_RISK_FREE_RATE_ANNUAL;
  if (!(spot > 0) || !(strike > 0) || !(markPrice > 0) || !(timeYears > 0) || !(r >= 0)) return null;

  const intrinsic = call ? Math.max(spot - strike, 0) : Math.max(strike - spot, 0);
  if (markPrice + 1e-10 < intrinsic) return null;

  if (call && markPrice > spot * 1.001) return null;
  if (!call && markPrice > strike * 1.001) return null;

  const price = (sig: number) => blackScholesEuropean(spot, strike, timeYears, r, sig, call);
  const f = (sig: number) => price(sig) - markPrice;

  let lo = 1e-5;
  let hi = 4.0;
  let flo = f(lo);
  let fhi = f(hi);
  if (!Number.isFinite(flo) || !Number.isFinite(fhi)) return null;

  let guard = 0;
  while (fhi < 0 && hi < 80 && guard < 25) {
    hi *= 1.6;
    fhi = f(hi);
    guard += 1;
  }
  if (flo > 0 || fhi < 0) return null;

  const tol = 1e-5;
  const maxIt = 90;
  for (let it = 0; it < maxIt; it++) {
    const mid = 0.5 * (lo + hi);
    const fm = f(mid);
    if (!Number.isFinite(fm)) return null;
    if (Math.abs(fm) < tol || hi - lo < 1e-7) {
      const sigma = mid;
      if (!(sigma > 0) || sigma > 79) return null;
      return sigma * 100;
    }
    if (fm > 0) hi = mid;
    else lo = mid;
  }
  return null;
}
