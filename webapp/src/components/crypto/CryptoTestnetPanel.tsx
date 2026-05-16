import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import {
  getCryptoTestnetBalances,
  getCryptoTestnetOpenOrders,
  getCryptoTestnetOrders,
  getCryptoTestnetPositions,
  getCryptoTestnetStatus,
  getCryptoTestnetTicker,
  postCryptoTestnetMarketOrder,
  type CryptoTestnetBalancesPayload,
  type CryptoTestnetMarketOrderRow,
  type CryptoTestnetOpenOrdersPayload,
  type CryptoTestnetPositionsPayload,
  type CryptoTestnetStoredOrder,
  type CryptoTestnetStatusPayload,
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
  const [orderBusy, setOrderBusy] = useState(false);
  const [orderFormError, setOrderFormError] = useState<string | null>(null);
  const [lastOrder, setLastOrder] = useState<CryptoTestnetMarketOrderRow | null>(null);
  const [recentOrders, setRecentOrders] = useState<CryptoTestnetStoredOrder[]>([]);
  const [ordersTotal, setOrdersTotal] = useState(0);
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [ordersError, setOrdersError] = useState<string | null>(null);
  const [positionsPayload, setPositionsPayload] = useState<CryptoTestnetPositionsPayload | null>(null);
  const [positionsError, setPositionsError] = useState<string | null>(null);
  const [openOrdersPayload, setOpenOrdersPayload] = useState<CryptoTestnetOpenOrdersPayload | null>(null);
  const [openOrdersError, setOpenOrdersError] = useState<string | null>(null);
  const [openOrdersLoading, setOpenOrdersLoading] = useState(false);

  const prefillQuickSell = useCallback((pair: string | null | undefined) => {
    const p = (pair ?? "").trim();
    if (!p) return;
    setManualSymbol(p);
    setManualSide("sell");
    setSellMode("quote");
    setOrderFormError(null);
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

  useEffect(() => {
    void loadStatus(false);
  }, [loadStatus]);

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

  const submitTestnetMarketOrder = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      setOrderFormError(null);
      setLastOrder(null);
      if (!connected || !manualSymbol.trim()) return;
      const symTrim = manualSymbol.trim();

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
        await Promise.all([loadBalances(), loadOrders()]);
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
      manualQuoteUsdt,
      manualSellQuoteUsdt,
      manualSide,
      manualSymbol,
      pairPrice,
      sellMode,
      loadBalances,
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

  const refreshTestnetDatos = useCallback(() => {
    void loadBalances();
    if (connected) void loadOrders();
  }, [loadBalances, loadOrders, connected]);

  return (
    <div className="crypto-testnet-dashboard">
      <div className="crypto-testnet-page-banner" role="note">
        <strong>Spot Testnet Binance:</strong> saldo ficticio en la red oficial de pruebas; las órdenes son reales sólo
        contra ese sandbox (no contra tu cuenta spot real). Distinto del tab <strong>Bot (Simulador)</strong>, que es
        paper interno de la app.
      </div>

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

      {connected ? (
        <>
          {/* 3 — Abrir orden manual (Spot Testnet) */}
          <section className="card crypto-testnet-section crypto-testnet-manual-card">
            <h3 className="dashboard-section-title crypto-testnet-section-title">Abrir orden manual</h3>
            <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.65rem", fontSize: "0.875rem" }}>
              <strong>Dinero ficticio de Binance</strong>, ejecución real sólo contra <strong>Spot Testnet</strong> (no el
              simulador paper de esta app).
            </p>
            <div className="crypto-testnet-note crypto-testnet-note--blue">
              Límite por orden: hasta {MAX_TESTNET_ORDER_USDT} USDT · pares en whitelist · mercado spot testnet.
            </div>
            <form className="crypto-testnet-order-form" onSubmit={(ev) => void submitTestnetMarketOrder(ev)}>
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

              {manualSide === "buy" ? (
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
                  {orderBusy ? "Enviando…" : manualSide === "buy" ? "Comprar" : "Vender"}
                </button>
              </div>
            </form>
            {orderFormError ? <p className="msg-error crypto-testnet-block-start">{orderFormError}</p> : null}

            <div className="crypto-testnet-manual-footer">
              <h4 className="crypto-testnet-subheading">Última orden ejecutada</h4>
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
                      <span className="crypto-testnet-lo-label">Par</span>
                      <span className="crypto-testnet-lo-value">{lastOrder.symbol}</span>
                    </div>
                    <div>
                      <span className="crypto-testnet-lo-label">Cantidad</span>
                      <span className="crypto-testnet-lo-value">{fmtNum(lastOrder.filled)}</span>
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
              <CryptoRefreshBadge active={ordersLoading} />
            </div>
          </div>
          {ordersError ? <p className="msg-error">{ordersError}</p> : null}
          {recentOrders.length > 0 ? (
            <div className="table-wrap">
              <table className="crypto-testnet-table">
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>Tipo</th>
                    <th>Símbolo</th>
                    <th className="crypto-testnet-num">Cantidad</th>
                    <th className="crypto-testnet-num">Cost</th>
                    <th className="crypto-testnet-num">Avg</th>
                    <th>Estado</th>
                  </tr>
                </thead>
                <tbody>
                  {recentOrders.map((row, idx) => (
                    <tr key={`${row.created_at}-${String(row.order_id)}-${idx}`}>
                      <td style={{ whiteSpace: "nowrap", fontSize: "0.82rem" }}>{fmtIsoLocalShort(row.created_at)}</td>
                      <td>{sideHistoryLabel(row.side)}</td>
                      <td>{row.symbol ?? "—"}</td>
                      <td className="crypto-testnet-num">{fmtNum(row.filled)}</td>
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
  );
}
