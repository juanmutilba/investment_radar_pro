import { useEffect, useMemo, useState } from "react";

import { fetchRavaOptionChain } from "@/services/api";

const UNDERLYING_CHOICES = ["GFG", "COM", "ALU", "BYM"] as const;

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

function getUnderlyingPriceRaw(raw: Record<string, unknown>): number | null {
  const candidates = [
    raw.underlying_price,
    raw.spot,
    raw.spot_price,
    raw.precio_subyacente,
    raw.underlying_last,
    raw.last_underlying,
  ];
  for (const c of candidates) {
    const n = toNumberOrNull(c);
    if (n !== null && n > 0) return n;
  }
  return null;
}

function spreadAbs(raw: Record<string, unknown>): number | null {
  const fromApi = toNumberOrNull(raw.spread_abs);
  if (fromApi !== null) return fromApi;
  const bid = toNumberOrNull(raw.bid);
  const ask = toNumberOrNull(raw.ask);
  if (bid === null || ask === null) return null;
  return ask - bid;
}

function moneyStatus(raw: Record<string, unknown>): string | null {
  const ms = raw.money_status;
  if (typeof ms === "string" && ms.trim()) return ms.trim();
  // fallback suave si el backend cambia el nombre
  const m = raw.moneyness_status;
  if (typeof m === "string" && m.trim()) return m.trim();
  return null;
}

function isAtmMoneyStatus(ms: string | null): boolean {
  if (!ms) return false;
  const up = ms.trim().toUpperCase();
  return up === "ATM" || up.includes("ATM");
}

function rowMoneynessClass(raw: Record<string, unknown>): string {
  const ms = (moneyStatus(raw) ?? "").toUpperCase();
  if (ms.includes("ATM")) return "option-row-atm";
  if (ms.includes("ITM")) return "option-row-itm";
  if (ms.includes("OTM")) return "option-row-otm";
  return "";
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

function flattenChain(chain: Record<string, unknown>, activo: string): FlatRow[] {
  const out: FlatRow[] = [];
  for (const [expiryCode, bucket] of Object.entries(chain)) {
    if (bucket === null || typeof bucket !== "object") continue;
    const b = bucket as { calls?: Record<string, unknown>; puts?: Record<string, unknown> };
    const calls = b.calls ?? {};
    const puts = b.puts ?? {};
    for (const [strikeKey, row] of Object.entries(calls)) {
      if (row === null || typeof row !== "object") continue;
      const strike = Number(strikeKey);
      if (!Number.isFinite(strike)) continue;
      out.push({ activo, tipo: "CALL", strike, expiryCode, raw: row as Record<string, unknown> });
    }
    for (const [strikeKey, row] of Object.entries(puts)) {
      if (row === null || typeof row !== "object") continue;
      const strike = Number(strikeKey);
      if (!Number.isFinite(strike)) continue;
      out.push({ activo, tipo: "PUT", strike, expiryCode, raw: row as Record<string, unknown> });
    }
  }
  out.sort((a, b) => a.strike - b.strike);
  return out;
}

export function OptionsPage() {
  const [selectedUnderlying, setSelectedUnderlying] = useState<string>("GFG");
  const [selectedExpiry, setSelectedExpiry] = useState<string>("");
  const [onlyWithVolume, setOnlyWithVolume] = useState(false);
  const [onlyWithTrades, setOnlyWithTrades] = useState(false);
  const [onlyAtm, setOnlyAtm] = useState(false);
  const [activeTab, setActiveTab] = useState<ActiveTab>("panel");
  const [strategyType, setStrategyType] = useState<StrategyType>("Bull Call Spread");
  const [strategiesFilter, setStrategiesFilter] = useState<StrategiesFilter>("");
  const [selectedLegs, setSelectedLegs] = useState<StrategyLeg[]>([]);
  const [rows, setRows] = useState<FlatRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchRavaOptionChain(selectedUnderlying)
      .then((chain) => {
        if (cancelled) return;
        setRows(flattenChain(chain, selectedUnderlying));
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
        setRows([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedUnderlying]);

  const emptyHint = useMemo(() => {
    if (loading || error) return null;
    if (rows.length === 0) return "Sin filas (cadena vacía o sin opciones para este subyacente).";
    return null;
  }, [loading, error, rows.length]);

  const expiryOptions = useMemo(() => {
    const set = new Set<string>();
    for (const r of rows) {
      const k = expiryKeyFromRaw(r.raw);
      if (k) set.add(k);
    }
    return Array.from(set).sort();
  }, [rows]);

  const expirySummary = useMemo(() => {
    const counts = new Map<string, number>();
    for (const r of rows) {
      const k = expiryKeyFromRaw(r.raw);
      if (!k) continue;
      counts.set(k, (counts.get(k) ?? 0) + 1);
    }
    const items = Array.from(counts.entries()).sort(([a], [b]) => a.localeCompare(b));
    return items.map(([k, count]) => ({ key: k, label: formatExpiryMonthLabel(k), count }));
  }, [rows]);

  const underlyingPrice = useMemo(() => {
    for (const r of rows) {
      const p = getUnderlyingPriceRaw(r.raw);
      if (p !== null) return p;
    }
    return null;
  }, [rows]);

  const filterCounts = useMemo(() => {
    let withVolume = 0;
    let withTrades = 0;
    let withAtm = 0;
    for (const r of rows) {
      const o = r.raw;
      const hv = o.has_volume;
      const vf = toNumberOrNull(o.volumen_float);
      if (hv === true || (vf !== null && vf > 0)) withVolume += 1;

      const ht = o.has_trades;
      const ops = toNumberOrNull(o.operaciones_int);
      if (ht === true || (ops !== null && ops > 0)) withTrades += 1;

      if (isAtmMoneyStatus(moneyStatus(o))) withAtm += 1;
    }
    return { withVolume, withTrades, withAtm };
  }, [rows]);

  const filteredRows = useMemo(() => {
    return rows.filter((r) => {
      const o = r.raw;
      if (selectedExpiry) {
        const k = expiryKeyFromRaw(o);
        if (!k) return false; // si no tiene vencimiento parseado, solo se ve en "Todos"
        if (k !== selectedExpiry) return false;
      }
      if (onlyWithVolume) {
        const hv = o.has_volume;
        const vf = toNumberOrNull(o.volumen_float);
        if (hv === true) {
          // ok
        } else if (vf !== null && vf > 0) {
          // ok
        } else {
          return false;
        }
      }
      if (onlyWithTrades) {
        const ht = o.has_trades;
        const ops = toNumberOrNull(o.operaciones_int);
        if (ht === true) {
          // ok
        } else if (ops !== null && ops > 0) {
          // ok
        } else {
          return false;
        }
      }
      if (onlyAtm) {
        if (!isAtmMoneyStatus(moneyStatus(o))) return false;
      }
      return true;
    });
  }, [rows, selectedExpiry, onlyWithVolume, onlyWithTrades, onlyAtm]);

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
      const breakEven = underlyingPrice !== null ? underlyingPrice - bid : null;

      const intrinsic =
        underlyingPrice !== null && underlyingPrice > 0
          ? Math.max(0, underlyingPrice - r.strike)
          : null;
      const timeValue =
        intrinsic !== null
          ? bid - intrinsic
          : null;

      const tnaPct =
        underlyingPrice !== null &&
          underlyingPrice > 0 &&
          days !== null &&
          days > 0 &&
          timeValue !== null &&
          timeValue > 0
          ? (timeValue / underlyingPrice) * (365 / days) * 100
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
  }, [calls, underlyingPrice]);

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
        <h1>Opciones Rava</h1>
        <p className="page__subtitle">
          Activo: <strong>{selectedUnderlying}</strong>
        </p>
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
            {UNDERLYING_CHOICES.map((u) => (
              <option key={u} value={u}>
                {u}
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
        <div className="radar-toolbar__field" style={{ gap: "0.45rem" }}>
          <span className="radar-toolbar__label">Filtros</span>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
            <button
              type="button"
              className={`options-filter-toggle${onlyWithVolume ? " options-filter-toggle-active" : ""}`}
              aria-pressed={onlyWithVolume}
              onClick={() => setOnlyWithVolume((v) => !v)}
            >
              Con volumen{rows.length ? ` (${formatInteger(filterCounts.withVolume)})` : ""}
            </button>
            <button
              type="button"
              className={`options-filter-toggle${onlyWithTrades ? " options-filter-toggle-active" : ""}`}
              aria-pressed={onlyWithTrades}
              onClick={() => setOnlyWithTrades((v) => !v)}
            >
              Con operaciones{rows.length ? ` (${formatInteger(filterCounts.withTrades)})` : ""}
            </button>
            <button
              type="button"
              className={`options-filter-toggle${onlyAtm ? " options-filter-toggle-active" : ""}`}
              aria-pressed={onlyAtm}
              onClick={() => setOnlyAtm((v) => !v)}
            >
              Solo ATM{rows.length ? ` (${formatInteger(filterCounts.withAtm)})` : ""}
            </button>
          </div>
        </div>
      </div>

      <div className="options-tabs" role="tablist" aria-label="Secciones de opciones">
        <button
          type="button"
          className={`options-tab${activeTab === "panel" ? " options-tab-active" : ""}`}
          role="tab"
          aria-selected={activeTab === "panel"}
          onClick={() => setActiveTab("panel")}
        >
          PANEL
        </button>
        <button
          type="button"
          className={`options-tab${activeTab === "strategies" ? " options-tab-active" : ""}`}
          role="tab"
          aria-selected={activeTab === "strategies"}
          onClick={() => setActiveTab("strategies")}
        >
          ESTRATEGIAS
        </button>
      </div>

      <div className="options-underlying-card" aria-label="Subyacente">
        <div style={{ display: "flex", flexDirection: "column", gap: "0.15rem" }}>
          <div className="options-underlying-label">Subyacente</div>
          <div className="options-underlying-symbol">
            <code>{selectedUnderlying}</code>
          </div>
        </div>
        <div className="options-underlying-price">
          {underlyingPrice !== null ? `$ ${formatNumber(underlyingPrice, 2)}` : "sin dato"}
        </div>
      </div>

      <div className="msg-muted" style={{ marginTop: "0.25rem" }}>
        <div>Mostrando opciones con datos disponibles (Rava). Algunas series pueden no aparecer si no tienen actividad.</div>
        {!loading && !error && rows.length > 0 ? (
          <div style={{ marginTop: "0.35rem" }}>
            <strong>Total opciones:</strong> {rows.length}
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

      {loading && <p>Cargando…</p>}
      {error && (
        <p role="alert">
          Error: {error}
        </p>
      )}
      {emptyHint && <p>{emptyHint}</p>}

      {!loading && !error ? (
        activeTab === "panel" ? (
          filteredRows.length > 0 ? (
            <div className="options-sections">
              <section className="options-section" aria-label="Calls">
                <h2 className="options-section-title">CALLS</h2>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Tipo</th>
                        <th>Activo</th>
                        <th>Ticker opción</th>
                        <th>Vencimiento</th>
                        <th>Strike</th>
                        <th>Último</th>
                        <th>Compra</th>
                        <th>Venta</th>
                        <th>Spread</th>
                        <th>Volumen</th>
                        <th>Operaciones</th>
                        <th>Moneyness</th>
                      </tr>
                    </thead>
                    <tbody>
                      {calls.map((r, i) => {
                        const o = r.raw;
                        const key = `calls-${r.expiryCode}-${r.strike}-${i}`;
                        const cls = rowMoneynessClass(o);
                        return (
                          <tr key={key} className={cls}>
                            <td>{r.tipo}</td>
                            <td>{r.activo}</td>
                            <td>{fmtCell(o.simbolo)}</td>
                            <td>{fmtCell(o.expiry_date)}</td>
                            <td style={{ textAlign: "right" }}>{formatNumber(r.strike, 2)}</td>
                            <td style={{ textAlign: "right" }}>{formatNumber(toNumberOrNull(o.ultimo), 2)}</td>
                            <td style={{ textAlign: "right" }}>{formatNumber(toNumberOrNull(o.bid), 2)}</td>
                            <td style={{ textAlign: "right" }}>{formatNumber(toNumberOrNull(o.ask), 2)}</td>
                            <td style={{ textAlign: "right" }}>{formatNumber(spreadAbs(o), 2)}</td>
                            <td style={{ textAlign: "right" }}>{formatInteger(toNumberOrNull(o.volumen_float))}</td>
                            <td style={{ textAlign: "right" }}>{formatInteger(toNumberOrNull(o.operaciones_int))}</td>
                            <td>{fmtCell(moneyStatus(o) ?? o.money_status)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="options-section" aria-label="Puts">
                <h2 className="options-section-title">PUTS</h2>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Tipo</th>
                        <th>Activo</th>
                        <th>Ticker opción</th>
                        <th>Vencimiento</th>
                        <th>Strike</th>
                        <th>Último</th>
                        <th>Compra</th>
                        <th>Venta</th>
                        <th>Spread</th>
                        <th>Volumen</th>
                        <th>Operaciones</th>
                        <th>Moneyness</th>
                      </tr>
                    </thead>
                    <tbody>
                      {puts.map((r, i) => {
                        const o = r.raw;
                        const key = `puts-${r.expiryCode}-${r.strike}-${i}`;
                        const cls = rowMoneynessClass(o);
                        return (
                          <tr key={key} className={cls}>
                            <td>{r.tipo}</td>
                            <td>{r.activo}</td>
                            <td>{fmtCell(o.simbolo)}</td>
                            <td>{fmtCell(o.expiry_date)}</td>
                            <td style={{ textAlign: "right" }}>{formatNumber(r.strike, 2)}</td>
                            <td style={{ textAlign: "right" }}>{formatNumber(toNumberOrNull(o.ultimo), 2)}</td>
                            <td style={{ textAlign: "right" }}>{formatNumber(toNumberOrNull(o.bid), 2)}</td>
                            <td style={{ textAlign: "right" }}>{formatNumber(toNumberOrNull(o.ask), 2)}</td>
                            <td style={{ textAlign: "right" }}>{formatNumber(spreadAbs(o), 2)}</td>
                            <td style={{ textAlign: "right" }}>{formatInteger(toNumberOrNull(o.volumen_float))}</td>
                            <td style={{ textAlign: "right" }}>{formatInteger(toNumberOrNull(o.operaciones_int))}</td>
                            <td>{fmtCell(moneyStatus(o) ?? o.money_status)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </section>
            </div>
          ) : null
        ) : (
          <div>
            <section className="options-strategy-panel" aria-label="Crear estrategia manual">
              <div
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  justifyContent: "space-between",
                  gap: "0.75rem",
                  flexWrap: "wrap",
                }}
              >
                <div>
                  <h2 style={{ margin: 0 }}>Crear estrategia manual</h2>
                  <div className="msg-muted" style={{ marginTop: "0.25rem" }}>
                    {strategyHelpText(strategyType)}
                  </div>
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
                  <div className="msg-muted">Agregá patas desde la tabla del PANEL con el botón “Agregar”.</div>
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
                        return (
                          <tr key={key} className={rowMoneynessClass(o)}>
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
                            <td>{fmtCell(moneyStatus(o) ?? o.money_status)}</td>
                          </tr>
                        );
                      })}
                      {puts.slice(0, 40).map((r, i) => {
                        const o = r.raw;
                        const key = `add-puts-${r.expiryCode}-${r.strike}-${i}`;
                        const canAdd = typeof o.simbolo === "string" && o.simbolo.trim();
                        return (
                          <tr key={key} className={rowMoneynessClass(o)}>
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
                            <td>{fmtCell(moneyStatus(o) ?? o.money_status)}</td>
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
                  <div className="options-section-title">Bull Call Spread</div>
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
                          </tr>
                        </thead>
                        <tbody>
                          {bullCallSpreads.map((x, idx) => (
                            <tr key={`${x.expiryKey}-${x.buyStrike}-${x.sellStrike}-${idx}`}>
                              <td>{formatExpiryMonthLabel(x.expiryKey)}</td>
                              <td style={{ textAlign: "right" }}>{formatNumber(x.buyStrike, 2)}</td>
                              <td style={{ textAlign: "right" }}>{formatNumber(x.sellStrike, 2)}</td>
                              <td style={{ textAlign: "right" }}>{formatNumber(x.buyAsk, 2)}</td>
                              <td style={{ textAlign: "right" }}>{formatNumber(x.sellBid, 2)}</td>
                              <td style={{ textAlign: "right" }}>{formatNumber(x.debit, 2)}</td>
                              <td style={{ textAlign: "right" }}>{formatNumber(x.maxGain, 2)}</td>
                              <td style={{ textAlign: "right" }}>{formatNumber(x.maxLoss, 2)}</td>
                              <td style={{ textAlign: "right" }}>{formatNumber(x.breakEven, 2)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              ) : null}

              {strategiesFilter === "" || strategiesFilter === "Covered Call" ? (
                <div style={{ marginTop: "0.95rem" }}>
                  <div className="options-section-title">Covered Call</div>
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
                          {coveredCalls.map((x, idx) => (
                            <tr key={`${x.expiryKey}-${x.strike}-${idx}`}>
                              <td>{formatExpiryMonthLabel(x.expiryKey)}</td>
                              <td style={{ textAlign: "right" }}>
                                {underlyingPrice !== null ? formatNumber(underlyingPrice, 2) : "-"}
                              </td>
                              <td style={{ textAlign: "right" }}>{formatNumber(x.strike, 2)}</td>
                              <td style={{ textAlign: "right" }}>{formatNumber(x.bid, 2)}</td>
                              <td style={{ textAlign: "right", color: "var(--text-muted)" }}>
                                {x.intrinsic !== null && x.intrinsic > 0 ? formatNumber(x.intrinsic, 2) : "-"}
                              </td>
                              <td
                                style={{
                                  textAlign: "right",
                                  color: x.timeValue !== null && x.timeValue > 0 ? "rgba(22, 163, 74, 0.9)" : "var(--text-muted)",
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
                              <td>{x.moneyness ?? "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              ) : null}

              <div className="msg-muted" style={{ marginTop: "0.9rem" }}>
                Próximamente: Bear Put Spread, Protective Put, Collar.
              </div>
            </section>
          </div>
        )
      ) : null}
    </div>
  );
}
