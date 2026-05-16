import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  getCryptoTestnetBalances,
  getCryptoTestnetOrders,
  getCryptoTestnetStatus,
  getCryptoTestnetTicker,
  postCryptoTestnetMarketOrder,
  type CryptoTestnetBalancesPayload,
  type CryptoTestnetMarketOrderRow,
  type CryptoTestnetStoredOrder,
  type CryptoTestnetStatusPayload,
  type CryptoTestnetTickerPayload,
} from "@/services/api";

const HIGHLIGHT_ASSETS = ["USDT", "BTC", "ETH", "BNB", "SOL"] as const;
const DEMO_SYMBOL = "BTC/USDT";
const TESTNET_WHITELIST_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"] as const;
const MAX_TESTNET_ORDER_USDT = 25;

const numFmt2 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 8, minimumFractionDigits: 2 });

function fmtNum(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return numFmt2.format(v);
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${numFmt2.format(v)}%`;
}

function fmtIsoLocalShort(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("es-AR", { dateStyle: "short", timeStyle: "medium" });
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

function CryptoRefreshBadge({ active, label = "Actualizando…" }: { active: boolean; label?: string }) {
  if (!active) return null;
  return (
    <span className="radar-badge radar-badge--conv-media crypto-refresh-badge" role="status" aria-live="polite">
      <span className="crypto-inline-spinner" aria-hidden />
      {label}
    </span>
  );
}

export function CryptoTestnetPanel() {
  const [status, setStatus] = useState<CryptoTestnetStatusPayload | null>(null);
  const [balances, setBalances] = useState<CryptoTestnetBalancesPayload | null>(null);
  const [ticker, setTicker] = useState<CryptoTestnetTickerPayload | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [balancesLoading, setBalancesLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [manualSymbol, setManualSymbol] = useState<string>(TESTNET_WHITELIST_SYMBOLS[0]);
  const [manualSide, setManualSide] = useState<"buy" | "sell">("buy");
  const [manualQuoteUsdt, setManualQuoteUsdt] = useState<string>("10");
  const [manualAmountBase, setManualAmountBase] = useState<string>("0.0001");
  const [orderBusy, setOrderBusy] = useState(false);
  const [orderFormError, setOrderFormError] = useState<string | null>(null);
  const [lastOrder, setLastOrder] = useState<CryptoTestnetMarketOrderRow | null>(null);
  const [recentOrders, setRecentOrders] = useState<CryptoTestnetStoredOrder[]>([]);
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [ordersError, setOrdersError] = useState<string | null>(null);

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
      const [b, t] = await Promise.all([
        getCryptoTestnetBalances(),
        getCryptoTestnetTicker(DEMO_SYMBOL).catch(() => null),
      ]);
      setBalances(b);
      if (t) setTicker(t);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error al leer balances testnet");
    } finally {
      setBalancesLoading(false);
    }
  }, []);

  const loadOrders = useCallback(async () => {
    setOrdersLoading(true);
    try {
      const rows = await getCryptoTestnetOrders(50);
      setRecentOrders(rows);
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

  const connected =
    Boolean(status?.configured && status?.enabled && status?.can_read_balance);
  const showEnvHelp = status && !status.configured;

  useEffect(() => {
    if (connected) void loadOrders();
  }, [connected, loadOrders]);

  const baseAssetHint = baseAssetFromPair(manualSymbol);

  const submitTestnetMarketOrder = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      setOrderFormError(null);
      setLastOrder(null);
      if (!connected || !manualSymbol.trim()) return;
      const symTrim = manualSymbol.trim();

      if (manualSide === "buy") {
        const q = Number.parseFloat(manualQuoteUsdt.replace(",", "."));
        if (!Number.isFinite(q) || q < 0.01) {
          setOrderFormError("Ingresá un monto USDT válido (mín. 0.01).");
          return;
        }
        if (q > MAX_TESTNET_ORDER_USDT + 1e-9) {
          setOrderFormError(`El monto no puede superar ${MAX_TESTNET_ORDER_USDT} USDT.`);
          return;
        }
        const freeUsdt = lookupFreeBalance(balances, "USDT");
        if (freeUsdt !== null && freeUsdt + 1e-9 < q) {
          setOrderFormError(`USDT disponible (${fmtNum(freeUsdt)}) insuficiente para comprar por ~${fmtNum(q)} USDT.`);
          return;
        }
      } else {
        const amt = Number.parseFloat(manualAmountBase.replace(",", "."));
        if (!Number.isFinite(amt) || amt <= 0) {
          setOrderFormError("Ingresá una cantidad positiva del activo base.");
          return;
        }
        const freeBase = lookupFreeBalance(balances, baseAssetFromPair(symTrim));
        if (freeBase !== null && freeBase + 1e-12 < amt) {
          const b = baseAssetFromPair(symTrim);
          setOrderFormError(`${b} disponible (${fmtNum(freeBase)}) insuficiente para vender ~${amt}.`);
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
            : await postCryptoTestnetMarketOrder({
                symbol: symTrim,
                side: "sell",
                amount_base: Number.parseFloat(manualAmountBase.replace(",", ".")),
              });
        if (res.order) setLastOrder(res.order);
        await Promise.all([loadBalances(), loadOrders()]);
        setError(null);
      } catch (err: unknown) {
        setOrderFormError(err instanceof Error ? err.message : "Error al enviar orden testnet");
      } finally {
        setOrderBusy(false);
      }
    },
    [
      balances,
      connected,
      manualAmountBase,
      manualQuoteUsdt,
      manualSide,
      manualSymbol,
      loadBalances,
      loadOrders,
    ],
  );

  return (
    <>
      <div
        className="crypto-testnet-banner"
        role="note"
        style={{
          marginBottom: "1rem",
          padding: "0.75rem 1rem",
          borderRadius: "var(--radius, 8px)",
          border: "1px solid rgba(194, 65, 12, 0.45)",
          background: "rgba(194, 65, 12, 0.08)",
          fontSize: "0.9rem",
        }}
      >
        <strong>Modo Testnet:</strong> dinero ficticio. No opera dinero real.
      </div>

      <div className="card" style={{ marginBottom: "1rem" }}>
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: "0.75rem",
            marginBottom: "0.75rem",
          }}
        >
          <h2 className="dashboard-section-title" style={{ margin: 0, flex: "1 1 auto" }}>
            Testnet Binance
          </h2>
          <button type="button" className="radar-refresh-btn" onClick={() => void loadStatus(false)} disabled={statusLoading}>
            {statusLoading ? "Refrescando…" : "Refrescar estado"}
          </button>
          <button
            type="button"
            className="radar-refresh-btn"
            onClick={() => void loadBalances()}
            disabled={balancesLoading || !status?.enabled || !status?.configured}
          >
            {balancesLoading ? "Cargando…" : "Refrescar balances"}
          </button>
          <CryptoRefreshBadge active={statusLoading} label="Actualizando estado…" />
          <CryptoRefreshBadge active={balancesLoading} label="Actualizando balances…" />
        </div>

        {error ? <p className="msg-error" style={{ marginBottom: "0.75rem" }}>{error}</p> : null}

        {showEnvHelp ? (
          <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.75rem", fontSize: "0.9rem" }}>
            Faltan <code>BINANCE_TESTNET_API_KEY</code> / <code>BINANCE_TESTNET_API_SECRET</code> en{" "}
            <code>.env</code>. Opcional: <code>BINANCE_TESTNET_ENABLED=true</code> para activar lectura.
          </p>
        ) : null}

        {statusLoading && !status ? <p className="msg-muted">Cargando estado testnet…</p> : null}

        {status ? (
          <>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginBottom: "0.85rem" }}>
              <span
                className={`radar-badge ${connected ? "radar-badge--conv-alta" : "radar-badge--conv-baja"}`}
                title="Conexión testnet"
              >
                {connected ? "Conectado" : "Sin conexión"}
              </span>
              <span className={`radar-badge ${status.configured ? "radar-badge--conv-alta" : "radar-badge--conv-baja"}`}>
                Configurado: {status.configured ? "sí" : "no"}
              </span>
              <span className={`radar-badge ${status.enabled ? "radar-badge--conv-alta" : "radar-badge--conv-media"}`}>
                Habilitado: {status.enabled ? "sí" : "no"}
              </span>
              <span className="radar-badge radar-badge--conv-media">Red: testnet</span>
            </div>
            <p className="msg-muted" style={{ margin: 0, fontSize: "0.9rem" }}>
              {status.message}
            </p>
          </>
        ) : null}
      </div>

      {balances ? (
        <div className="card" style={{ marginBottom: "1rem" }}>
          <h3 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.65rem" }}>
            Balances principales
          </h3>
          {!balances.ok ? (
            <p className="msg-error" style={{ fontSize: "0.875rem" }}>
              {balances.error ?? "No se pudieron leer balances"}
            </p>
          ) : (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
                gap: "0.65rem",
                marginBottom: "1rem",
              }}
            >
              {HIGHLIGHT_ASSETS.map((asset) => (
                <div key={asset} className="stat dashboard-stat" style={{ margin: 0 }}>
                  <div className="stat__label">{asset}</div>
                  <div className="stat__value">{fmtNum(balances.highlights?.[asset] ?? 0)}</div>
                </div>
              ))}
            </div>
          )}
          {balances.balances.length > 0 ? (
            <details className="crypto-history-details">
              <summary className="msg-muted" style={{ cursor: "pointer", marginBottom: "0.5rem" }}>
                Todos los activos con saldo ({balances.balances.length})
              </summary>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Activo</th>
                      <th style={{ textAlign: "right" }}>Libre</th>
                      <th style={{ textAlign: "right" }}>En uso</th>
                      <th style={{ textAlign: "right" }}>Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {balances.balances.map((row) => (
                      <tr key={row.asset}>
                        <td>{row.asset}</td>
                        <td style={{ textAlign: "right" }}>{fmtNum(row.free)}</td>
                        <td style={{ textAlign: "right" }}>{fmtNum(row.used)}</td>
                        <td style={{ textAlign: "right" }}>{fmtNum(row.total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          ) : balances.ok ? (
            <p className="msg-muted" style={{ margin: 0 }}>Sin saldos en la cuenta testnet.</p>
          ) : null}
        </div>
      ) : null}

      {connected ? (
        <div className="card" style={{ marginBottom: "1rem" }}>
          <h3 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.65rem" }}>
            Orden manual Testnet
          </h3>
          <div
            role="note"
            style={{
              marginBottom: "0.85rem",
              padding: "0.65rem 0.85rem",
              borderRadius: "var(--radius, 8px)",
              border: "1px solid rgba(59, 130, 246, 0.4)",
              background: "rgba(59, 130, 246, 0.08)",
              fontSize: "0.88rem",
            }}
          >
            <strong>Dinero ficticio.</strong> Las órdenes se envían a <strong>Binance Spot Testnet</strong>. No cuenta real,
            sin paper trading ni auto-run. BUY: hasta {MAX_TESTNET_ORDER_USDT} USDT por orden. SELL: indicá una cantidad
            explícita del activo base (no se vende todo el saldo por defecto).
          </div>
          <form
            onSubmit={(ev) => {
              void submitTestnetMarketOrder(ev);
            }}
            style={{ display: "flex", flexDirection: "column", gap: "0.75rem", maxWidth: "420px" }}
          >
            <label className="msg-muted" style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
              Par (whitelist)
              <select
                className="radar-input"
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
            <fieldset style={{ border: "none", margin: 0, padding: 0 }}>
              <legend className="msg-muted" style={{ fontSize: "0.82rem", marginBottom: "0.4rem" }}>
                Lado
              </legend>
              <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
                <label style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem", cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="testnet-order-side"
                    checked={manualSide === "buy"}
                    onChange={() => setManualSide("buy")}
                    disabled={orderBusy}
                  />
                  Comprar (BUY)
                </label>
                <label style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem", cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="testnet-order-side"
                    checked={manualSide === "sell"}
                    onChange={() => setManualSide("sell")}
                    disabled={orderBusy}
                  />
                  Vender (SELL)
                </label>
              </div>
            </fieldset>

            {balances?.ok ? (
              <p className="msg-muted" style={{ margin: 0, fontSize: "0.82rem" }}>
                {manualSide === "buy" ? (
                  <>
                    <strong>USDT libre:</strong> {fmtNum(lookupFreeBalance(balances, "USDT") ?? null)}
                  </>
                ) : (
                  <>
                    <strong>{baseAssetHint || "Base"} libre:</strong>{" "}
                    {fmtNum(
                      baseAssetHint ? lookupFreeBalance(balances, baseAssetHint) : null,
                    )}
                    {baseAssetHint ? ` ${baseAssetHint}` : null}
                  </>
                )}
              </p>
            ) : (
              <p className="msg-muted" style={{ margin: 0, fontSize: "0.82rem" }}>
                Refrescá balances para ver el disponible antes de operar.
              </p>
            )}

            {manualSide === "buy" ? (
              <label className="msg-muted" style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
                Monto en USDT (máx. {MAX_TESTNET_ORDER_USDT})
                <input
                  type="number"
                  className="radar-input"
                  min={0.01}
                  max={MAX_TESTNET_ORDER_USDT}
                  step="0.01"
                  value={manualQuoteUsdt}
                  onChange={(ev) => setManualQuoteUsdt(ev.target.value)}
                  disabled={orderBusy}
                  required={manualSide === "buy"}
                />
              </label>
            ) : (
              <>
                <p className="msg-muted" style={{ margin: 0, fontSize: "0.82rem" }}>
                  Indicá una cantidad pequeña del activo disponible en testnet (ej. BTC en BTC/USDT). No se permite vender
                  sin especificar cantidad.
                </p>
                <label className="msg-muted" style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
                  Cantidad en {baseAssetHint || "base"}
                  <input
                    type="number"
                    className="radar-input"
                    min={0}
                    step="any"
                    value={manualAmountBase}
                    onChange={(ev) => setManualAmountBase(ev.target.value)}
                    disabled={orderBusy}
                    required={manualSide === "sell"}
                  />
                </label>
              </>
            )}
            <div>
              <button type="submit" className="radar-refresh-btn" disabled={orderBusy}>
                {orderBusy ? "Enviando…" : manualSide === "buy" ? "Comprar Testnet" : "Vender Testnet"}
              </button>
            </div>
          </form>
          {orderFormError ? <p className="msg-error" style={{ marginTop: "0.75rem", fontSize: "0.875rem" }}>{orderFormError}</p> : null}
          {lastOrder ? (
            <div
              style={{
                marginTop: "0.85rem",
                padding: "0.55rem 0.65rem",
                borderRadius: "var(--radius, 8px)",
                border: "1px solid var(--border-subtle, rgba(255,255,255,0.12))",
                fontSize: "0.88rem",
              }}
            >
              <strong>Última orden enviada:</strong>{" "}
              <span className="msg-muted">
                {lastOrder.symbol} · <strong>{String(lastOrder.side)}</strong> · estado{" "}
                <strong>{lastOrder.status ?? "—"}</strong> · filled {fmtNum(lastOrder.filled)} · cost{" "}
                {fmtNum(lastOrder.cost)} · avg {fmtNum(lastOrder.average)}
              </span>
              <span className="msg-muted" style={{ display: "block", marginTop: "0.35rem", fontSize: "0.8rem" }}>
                Order ID {String(lastOrder.order_id ?? "—")}
              </span>
            </div>
          ) : null}
        </div>
      ) : null}

      {connected ? (
        <div className="card" style={{ marginBottom: "1rem" }}>
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              gap: "0.65rem",
              marginBottom: "0.65rem",
            }}
          >
            <h3 className="dashboard-section-title" style={{ margin: 0, flex: "1 1 auto" }}>
              Órdenes Testnet recientes
            </h3>
            <button type="button" className="radar-refresh-btn" onClick={() => void loadOrders()} disabled={ordersLoading}>
              {ordersLoading ? "Refrescando…" : "Refrescar órdenes"}
            </button>
            <CryptoRefreshBadge active={ordersLoading} label="Órdenes locales…" />
          </div>
          <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.75rem", fontSize: "0.85rem" }}>
            <strong>Historial local</strong>: sólo muestra órdenes enviadas desde esta app (archivo JSON en el servidor). No es
            el historial completo de Binance.
          </p>
          {ordersError ? <p className="msg-error" style={{ fontSize: "0.875rem" }}>{ordersError}</p> : null}
          {recentOrders.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>Símbolo</th>
                    <th>Lado</th>
                    <th>Estado</th>
                    <th style={{ textAlign: "right" }}>Filled</th>
                    <th style={{ textAlign: "right" }}>Cost</th>
                    <th style={{ textAlign: "right" }}>Average</th>
                    <th>Order ID</th>
                  </tr>
                </thead>
                <tbody>
                  {recentOrders.map((row, idx) => (
                    <tr key={`${row.created_at}-${String(row.order_id)}-${idx}`}>
                      <td style={{ whiteSpace: "nowrap", fontSize: "0.82rem" }}>{fmtIsoLocalShort(row.created_at)}</td>
                      <td>{row.symbol ?? "—"}</td>
                      <td>{row.side ?? "—"}</td>
                      <td>{row.status ?? row.raw_status ?? "—"}</td>
                      <td style={{ textAlign: "right" }}>{fmtNum(row.filled)}</td>
                      <td style={{ textAlign: "right" }}>{fmtNum(row.cost)}</td>
                      <td style={{ textAlign: "right" }}>{fmtNum(row.average)}</td>
                      <td style={{ fontSize: "0.8rem", wordBreak: "break-all" }}>{String(row.order_id ?? "—")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : ordersLoading ? (
            <p className="msg-muted" style={{ margin: 0, fontSize: "0.9rem" }}>Cargando historial…</p>
          ) : (
            <p className="msg-muted" style={{ margin: 0, fontSize: "0.9rem" }}>
              Todavía no hay órdenes guardadas. Tras comprar o vender desde acá aparecerán en la tabla.
            </p>
          )}
        </div>
      ) : null}

      {ticker ? (
        <div className="card" style={{ marginBottom: "1rem" }}>
          <h3 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
            Ticker {DEMO_SYMBOL} (testnet)
          </h3>
          <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
            <div className="stat__label">Último</div>
            <div className="stat__value">{fmtNum(ticker.last)}</div>
          </div>
          <div className="stat dashboard-stat">
            <div className="stat__label">Variación (24h ref.)</div>
            <div className="stat__value">{fmtPct(ticker.percentage)}</div>
          </div>
        </div>
      ) : null}
    </>
  );
}
