import { FormEvent, Fragment, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CarteraSellModal } from "@/components/cartera/CarteraSellModal";
import {
  CarteraStrategyManagementModal,
  type CarteraStrategyMgmtMode,
} from "@/components/cartera/CarteraStrategyManagementModal";
import { usePortfolioOpenPositions } from "@/context/PortfolioOpenPositionsContext";
import {
  computeBuyValidation,
  parsePositiveNumber,
  todayIsoDate,
  type BuyInvalidFlags,
} from "@/components/cartera/carteraFormUtils";
import type {
  PortfolioAssetType,
  PortfolioHistoryRow,
  PortfolioInstrumentType,
  PortfolioManagementEvent,
  PortfolioOpenRow,
  PortfolioTradeCreatePayload,
  PortfolioTypeQuery,
} from "@/services/api";
import {
  appendPortfolioTradeEvent,
  createPortfolioPosition,
  createPortfolioTrade,
  fetchPortfolioHistory,
  fetchPortfolioOpen,
  fetchPortfolioTickersAutocomplete,
  fetchPortfolioTradesMetrics,
} from "@/services/api";

function fmtNum(n: number | null | undefined, maxFrac = 4): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString("es-AR", { maximumFractionDigits: maxFrac });
}

/** Etiqueta corta para columna Tipo (viene de API `asset_type`). */
function fmtAssetTypeShort(t: PortfolioAssetType): string {
  if (t === "Argentina") return "ARG";
  if (t === "USA") return "USA";
  return "CEDEAR";
}

type OpenInstrumentFilter = "all" | PortfolioInstrumentType;

function rowInstrumentType(r: { instrument_type?: PortfolioInstrumentType }): PortfolioInstrumentType {
  const it = r.instrument_type;
  if (it === "option" || it === "option_strategy") return it;
  return "stock";
}

function fmtInstrumentShort(it: PortfolioInstrumentType): string {
  if (it === "option") return "OPT";
  if (it === "option_strategy") return "EST";
  return "ACC";
}

function fmtPortfolioKindLabel(pk: string | undefined): string {
  if (pk === "real") return "Real";
  return "Radar";
}

function sortMgmtEventsAsc(evs: PortfolioManagementEvent[]): PortfolioManagementEvent[] {
  return [...evs].sort((a, b) => {
    const da = (a.date || "").slice(0, 10);
    const db = (b.date || "").slice(0, 10);
    const c = da.localeCompare(db);
    if (c !== 0) return c;
    return String(a.event_type || "").localeCompare(String(b.event_type || ""));
  });
}

function eventTypeBadgeLabel(t: string): string {
  const u = t.toLowerCase();
  const m: Record<string, string> = {
    open: "Apertura",
    adjustment: "Ajuste",
    roll: "Roll",
    partial_close: "Cierre parcial",
    full_close: "Cierre total",
    note: "Nota",
  };
  return m[u] ?? t;
}

function eventTypeBadgeClassName(t: string): string {
  const u = t.toLowerCase();
  if (u === "open") return "cartera-ev-badge cartera-ev-badge--open";
  if (u === "adjustment") return "cartera-ev-badge cartera-ev-badge--adj";
  if (u === "roll") return "cartera-ev-badge cartera-ev-badge--roll";
  if (u === "partial_close") return "cartera-ev-badge cartera-ev-badge--partial";
  if (u === "full_close") return "cartera-ev-badge cartera-ev-badge--full";
  if (u === "note") return "cartera-ev-badge cartera-ev-badge--note";
  return "cartera-ev-badge";
}

function histStrategyMoneyFmt(r: PortfolioHistoryRow, v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (r.asset_type === "Argentina") return `ARS ${fmtNum(v, 2)}`;
  return `USD ${fmtNum(v, 4)}`;
}

/** Días calendario entre compra y venta (solo frontend). */
function histStrategyDaysInTrade(r: PortfolioHistoryRow): number | null {
  const b = (r.buy_date ?? "").toString().trim().slice(0, 10);
  const s = (r.sell_date ?? "").toString().trim().slice(0, 10);
  if (!b || !s) return null;
  const d0 = new Date(`${b}T12:00:00`);
  const d1 = new Date(`${s}T12:00:00`);
  if (Number.isNaN(d0.getTime()) || Number.isNaN(d1.getTime())) return null;
  const days = Math.round((d1.getTime() - d0.getTime()) / 86400000);
  if (!Number.isFinite(days) || days < 0) return null;
  return days;
}

/** PnL realizado / días en cartera; null si no hay PnL o días ≤ 0. */
function histStrategyPnLPerDay(r: PortfolioHistoryRow): number | null {
  const days = histStrategyDaysInTrade(r);
  if (days === null || days <= 0) return null;
  const pnl = r.strategy_realized_pnl;
  if (pnl === null || pnl === undefined || !Number.isFinite(pnl)) return null;
  return pnl / days;
}

function histStrategyMoneyPerDayFmt(r: PortfolioHistoryRow, v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${histStrategyMoneyFmt(r, v)}/día`;
}

function strategyEventTableRows(sortedEvs: PortfolioManagementEvent[], rowKey: string | number): ReactNode {
  return sortedEvs.map((ev, ei) => (
    <tr key={`${rowKey}-ev-${ei}-${String(ev.date)}-${ev.event_type}`}>
      <td className="nowrap">{(ev.date || "").slice(0, 10)}</td>
      <td>
        <span className={eventTypeBadgeClassName(ev.event_type || "")} title={ev.event_type ?? ""}>
          {eventTypeBadgeLabel(ev.event_type || "")}
        </span>
      </td>
      <td>{ev.description?.trim() ? ev.description : "—"}</td>
      <td className="cartera-mono">
        {ev.debit_credit != null && Number.isFinite(ev.debit_credit) ? fmtNum(ev.debit_credit, 4) : "—"}
      </td>
      <td>
        {ev.underlying_price != null && Number.isFinite(ev.underlying_price) ? fmtNum(ev.underlying_price, 4) : "—"}
      </td>
      <td>{ev.iv != null && Number.isFinite(ev.iv) ? fmtNum(ev.iv, 4) : "—"}</td>
      <td>{ev.notes?.trim() ? ev.notes : "—"}</td>
    </tr>
  ));
}

const histStrategyEvThead = (
  <thead>
    <tr>
      <th>Fecha</th>
      <th>Tipo</th>
      <th>Descripción</th>
      <th className="nowrap">debit_credit</th>
      <th className="nowrap">Spot</th>
      <th>IV</th>
      <th>Nota</th>
    </tr>
  </thead>
);

function HistStrategyChronologyTable({ r, sorted }: { r: PortfolioHistoryRow; sorted: PortfolioManagementEvent[] }) {
  if (sorted.length === 0) {
    return <p className="cartera-hint">Sin eventos de gestión registrados.</p>;
  }
  return (
    <div className="table-wrap cartera-ev-table-wrap">
      <table className="cartera-table">
        {histStrategyEvThead}
        <tbody>
          {sorted.map((ev, ei) => {
            const prev = ei > 0 ? sorted[ei - 1] : null;
            const t = (ev.event_type || "").toLowerCase();
            const prevT = prev ? String(prev.event_type || "").toLowerCase() : "";
            const showGroup = prevT === "" || prevT !== t;
            return (
              <Fragment key={`${r.id}-ch-${ei}-${String(ev.date)}-${ev.event_type}`}>
                {showGroup ? (
                  <tr className="cartera-ev-group-sep">
                    <td colSpan={7} style={{ paddingTop: ei > 0 ? "0.45rem" : 0, borderTop: ei > 0 ? "1px solid var(--border)" : undefined }}>
                      <span className={eventTypeBadgeClassName(ev.event_type || "")} title={ev.event_type ?? ""}>
                        {eventTypeBadgeLabel(ev.event_type || "")}
                      </span>
                    </td>
                  </tr>
                ) : null}
                {strategyEventTableRows([ev], `${r.id}-ev-${ei}`)}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function HistStrategyExpandedDetail({ r }: { r: PortfolioHistoryRow }) {
  const legs = r.legs ?? [];
  const sorted = sortMgmtEventsAsc(r.management_events ?? []);
  const days = histStrategyDaysInTrade(r);
  const pnlDay = histStrategyPnLPerDay(r);
  const hasTradeNotes = Boolean((r.notes || "").trim() || (r.sell_notes || "").trim());
  const pnl = r.strategy_realized_pnl;
  const pnlClass =
    pnl != null && Number.isFinite(pnl) && pnl > 0
      ? "cartera-ret--pos"
      : pnl != null && Number.isFinite(pnl) && pnl < 0
        ? "cartera-ret--neg"
        : "";

  return (
    <div style={{ padding: "0.5rem 0" }}>
      <div
        className="cartera-strategy-hist-summary"
        style={{
          marginBottom: "1rem",
          padding: "0.65rem 0.85rem",
          border: "1px solid var(--border)",
          borderRadius: "8px",
          background: "var(--table-row-alt, rgba(127, 127, 127, 0.06))",
        }}
      >
        <h4 className="cartera-form__title" style={{ fontSize: "1rem", marginTop: 0, marginBottom: "0.5rem" }}>
          Resumen
        </h4>
        <dl className="cartera-strategy-hist-dl">
          <dt>Resultado final (PnL)</dt>
          <dd className={pnlClass}>{histStrategyMoneyFmt(r, r.strategy_realized_pnl ?? null)}</dd>
          <dt>Cashflow total</dt>
          <dd>{histStrategyMoneyFmt(r, r.strategy_cashflow_total ?? null)}</dd>
          <dt>Días en cartera</dt>
          <dd>{days !== null ? String(days) : "—"}</dd>
          <dt>PnL por día</dt>
          <dd>{histStrategyMoneyPerDayFmt(r, pnlDay)}</dd>
          <dt>Accounting</dt>
          <dd>
            {r.strategy_pnl_accounting != null
              ? `${r.strategy_pnl_accounting} · ${
                  r.strategy_pnl_accounting === "cashflow" ? "Σ debit_credit" : "legacy buy/sell"
                }`
              : "—"}
          </dd>
        </dl>
      </div>

      <p className="cartera-form__title" style={{ fontSize: "1rem", marginBottom: "0.35rem" }}>
        Legs ({legs.length})
      </p>
      <pre className="cartera-json-block" style={{ maxHeight: 220, overflow: "auto" }}>
        {legs.length ? JSON.stringify(legs, null, 2) : "Sin legs."}
      </pre>

      <p className="cartera-form__title" style={{ fontSize: "1rem", margin: "0.75rem 0 0.35rem" }}>
        Cronología de eventos
      </p>
      <p className="cartera-hint" style={{ marginTop: 0, marginBottom: "0.45rem" }}>
        Una sola línea de tiempo ordenada por fecha; la fila de badge marca cambio de tipo de evento (sin repetir filas).
      </p>
      <HistStrategyChronologyTable r={r} sorted={sorted} />

      {hasTradeNotes ? (
        <div style={{ marginTop: "0.85rem" }}>
          <h4 className="cartera-form__title" style={{ fontSize: "0.95rem", marginBottom: "0.35rem" }}>
            Notas (operación / cierre)
          </h4>
          {(r.notes || "").trim() ? (
            <p className="cartera-hint" style={{ marginTop: 0 }}>
              <strong>Operación:</strong> {r.notes}
            </p>
          ) : null}
          {(r.sell_notes || "").trim() ? (
            <p className="cartera-hint" style={{ marginTop: 0 }}>
              <strong>Cierre:</strong> {r.sell_notes}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function CarteraPage() {
  const { refresh: refreshOpenPositionsIndex } = usePortfolioOpenPositions();
  const [tab, setTab] = useState<"compra" | "cartera" | "historial">("compra");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [openRows, setOpenRows] = useState<PortfolioOpenRow[]>([]);
  const [histRows, setHistRows] = useState<PortfolioHistoryRow[]>([]);
  const [portfolioScope, setPortfolioScope] = useState<PortfolioTypeQuery>("radar");

  const [ticker, setTicker] = useState(""); // único estado: form.ticker
  const [assetType, setAssetType] = useState<PortfolioAssetType>("USA");
  const [quantity, setQuantity] = useState("1");
  const [buyDate, setBuyDate] = useState(todayIsoDate());
  const [buyPriceArs, setBuyPriceArs] = useState("");
  const [buyPriceUsd, setBuyPriceUsd] = useState("");
  /** TC MEP (ARS por USD) al comprar; Argentina y CEDEAR. */
  const [buyTcMep, setBuyTcMep] = useState("");
  const [buyNotes, setBuyNotes] = useState("");

  const [tickerSug, setTickerSug] = useState<string[]>([]);
  const [tickerSugError, setTickerSugError] = useState(false);
  const tickerAbortRef = useRef<AbortController | null>(null);
  const tickerReqSeq = useRef(0);

  const [sellTarget, setSellTarget] = useState<PortfolioOpenRow | null>(null);

  const [openInstrumentFilter, setOpenInstrumentFilter] = useState<OpenInstrumentFilter>("all");
  const [expandedOpenIds, setExpandedOpenIds] = useState<number[]>([]);
  const [expandedHistIds, setExpandedHistIds] = useState<number[]>([]);
  const [histStratTypeFilter, setHistStratTypeFilter] = useState("");
  const [histStratUnderlyingFilter, setHistStratUnderlyingFilter] = useState("");
  const [histStratResultFilter, setHistStratResultFilter] = useState<"all" | "win" | "loss">("all");
  const [tradeMetrics, setTradeMetrics] = useState<Awaited<ReturnType<typeof fetchPortfolioTradesMetrics>> | null>(null);

  const [mgmtOpenForId, setMgmtOpenForId] = useState<number | null>(null);
  const [mgmtDate, setMgmtDate] = useState(todayIsoDate());
  const [mgmtEventType, setMgmtEventType] = useState<
    "open" | "adjustment" | "roll" | "partial_close" | "full_close" | "note"
  >("note");
  const [mgmtDescription, setMgmtDescription] = useState("");
  const [mgmtDebitCredit, setMgmtDebitCredit] = useState("");
  const [mgmtBusy, setMgmtBusy] = useState(false);

  const [strategyMgmt, setStrategyMgmt] = useState<{
    row: PortfolioOpenRow;
    mode: CarteraStrategyMgmtMode;
  } | null>(null);

  const [ntInstrument, setNtInstrument] = useState<"option" | "option_strategy">("option_strategy");
  const [ntTicker, setNtTicker] = useState("");
  const [ntUnderlying, setNtUnderlying] = useState("");
  const [ntAssetType, setNtAssetType] = useState<PortfolioAssetType>("USA");
  const [ntQuantity, setNtQuantity] = useState("1");
  const [ntBuyDate, setNtBuyDate] = useState(todayIsoDate());
  const [ntBuyUsd, setNtBuyUsd] = useState("");
  const [ntBuyArs, setNtBuyArs] = useState("");
  const [ntStrategy, setNtStrategy] = useState<PortfolioTradeCreatePayload["strategy_type"]>("custom");
  const [ntTcMep, setNtTcMep] = useState("");
  const [ntNotes, setNtNotes] = useState("");
  const [ntBusy, setNtBusy] = useState(false);

  const loadMetrics = useCallback(async () => {
    try {
      const m = await fetchPortfolioTradesMetrics({ portfolio_type: portfolioScope });
      setTradeMetrics(m);
    } catch {
      setTradeMetrics(null);
    }
  }, [portfolioScope]);

  const loadOpen = useCallback(async () => {
    const rows = await fetchPortfolioOpen({ portfolio_type: portfolioScope });
    setOpenRows(rows);
  }, [portfolioScope]);

  const loadHist = useCallback(async () => {
    const rows = await fetchPortfolioHistory({ portfolio_type: portfolioScope });
    setHistRows(rows);
  }, [portfolioScope]);

  const onStrategyMgmtSaved = useCallback(async () => {
    await loadOpen();
    await loadMetrics();
    void refreshOpenPositionsIndex({ silent: true });
  }, [loadOpen, loadMetrics, refreshOpenPositionsIndex]);

  useEffect(() => {
    if (tab !== "cartera" && tab !== "historial") return;
    setErr(null);
    void (async () => {
      try {
        if (tab === "cartera") {
          await loadOpen();
          await loadMetrics();
        } else {
          await loadHist();
        }
      } catch (e) {
        setErr(e instanceof Error ? e.message : "Error al cargar cartera");
      }
    })();
  }, [tab, loadOpen, loadHist, loadMetrics, portfolioScope]);

  // Autocomplete ticker (datalist) — debounce + cancelación + fallback silencioso.
  useEffect(() => {
    if (tab !== "compra") return;
    const q = ticker.trim();
    if (!q) {
      setTickerSug([]);
      setTickerSugError(false);
      return;
    }
    if (q.length < 1) {
      setTickerSug([]);
      return;
    }

    const seq = ++tickerReqSeq.current;
    const t = window.setTimeout(() => {
      try {
        tickerAbortRef.current?.abort();
      } catch {
        // ignore
      }
      const ac = new AbortController();
      tickerAbortRef.current = ac;

      void (async () => {
        try {
          const items = await fetchPortfolioTickersAutocomplete(assetType, q, { limit: 30, signal: ac.signal });
          if (tickerReqSeq.current !== seq) return; // llegó tarde
          setTickerSug(items);
          setTickerSugError(false);
        } catch (e) {
          // Fallback silencioso: no bloquear el formulario si falla el endpoint.
          if (ac.signal.aborted) return;
          if (tickerReqSeq.current !== seq) return;
          setTickerSug([]);
          setTickerSugError(true);
        }
      })();
    }, 250);

    return () => {
      window.clearTimeout(t);
    };
  }, [ticker, assetType, tab]);

  useEffect(() => {
    return () => {
      try {
        tickerAbortRef.current?.abort();
      } catch {
        // ignore
      }
    };
  }, []);

  const tickerDatalistId = useMemo(() => "cartera-ticker-suggestions", []);

  const buyValidation = useMemo((): { valid: boolean; message: string; inv: BuyInvalidFlags } => {
    return computeBuyValidation(ticker, buyDate, quantity, assetType, buyPriceArs, buyPriceUsd, buyTcMep);
  }, [ticker, buyDate, quantity, assetType, buyPriceArs, buyPriceUsd, buyTcMep]);

  const filteredOpenRows = useMemo(() => {
    if (openInstrumentFilter === "all") return openRows;
    return openRows.filter((r) => rowInstrumentType(r) === openInstrumentFilter);
  }, [openRows, openInstrumentFilter]);

  const histStrategyRowsAll = useMemo(
    () => histRows.filter((r) => rowInstrumentType(r) === "option_strategy"),
    [histRows],
  );

  const histStratUnderlyingOptions = useMemo(() => {
    const s = new Set<string>();
    for (const r of histStrategyRowsAll) {
      const u = (r.underlying_symbol || "").trim().toUpperCase();
      if (u) s.add(u);
    }
    return [...s].sort((a, b) => a.localeCompare(b));
  }, [histStrategyRowsAll]);

  const histStratTypeOptions = useMemo(() => {
    const s = new Set<string>();
    for (const r of histStrategyRowsAll) {
      const t = (r.strategy_type || "").trim();
      if (t) s.add(t);
    }
    return [...s].sort((a, b) => a.localeCompare(b));
  }, [histStrategyRowsAll]);

  const histFilteredStrategyRows = useMemo(() => {
    if (portfolioScope !== "real") return histStrategyRowsAll;
    let rows = histStrategyRowsAll;
    const uSel = histStratUnderlyingFilter.trim().toUpperCase();
    if (uSel) {
      rows = rows.filter((r) => (r.underlying_symbol || "").trim().toUpperCase() === uSel);
    }
    const stSel = histStratTypeFilter.trim();
    if (stSel) {
      rows = rows.filter((r) => (r.strategy_type || "").trim() === stSel);
    }
    if (histStratResultFilter === "win") {
      rows = rows.filter(
        (r) => r.strategy_realized_pnl != null && Number.isFinite(r.strategy_realized_pnl) && r.strategy_realized_pnl > 0,
      );
    } else if (histStratResultFilter === "loss") {
      rows = rows.filter(
        (r) => r.strategy_realized_pnl != null && Number.isFinite(r.strategy_realized_pnl) && r.strategy_realized_pnl < 0,
      );
    }
    return rows;
  }, [
    histStrategyRowsAll,
    portfolioScope,
    histStratUnderlyingFilter,
    histStratTypeFilter,
    histStratResultFilter,
  ]);

  const histNonStrategyRows = useMemo(
    () => histRows.filter((r) => rowInstrumentType(r) !== "option_strategy"),
    [histRows],
  );

  const stockPortfolioTypeForCreate = useMemo((): "radar" | "real" => {
    if (portfolioScope === "real") return "real";
    return "radar";
  }, [portfolioScope]);

  const showRealPortfolioMetrics = portfolioScope === "real" || portfolioScope === "all";

  const classifyReturn = (pct: number | null | undefined): string => {
    if (pct === null || pct === undefined || Number.isNaN(pct)) return "";
    if (pct > 0) return "cartera-ret--pos";
    if (pct < 0) return "cartera-ret--neg";
    return "";
  };

  const extractAlertLabel = (row: unknown): string | null => {
    // Compat best-effort: si algún día el backend lo agrega, lo tomamos.
    const r = row as Record<string, unknown> | null;
    if (!r) return null;
    const direct =
      typeof r.buy_alert_label === "string"
        ? r.buy_alert_label
        : typeof r.sell_alert_label === "string"
          ? r.sell_alert_label
          : typeof r.alerta === "string"
        ? r.alerta
        : typeof r.buy_alerta === "string"
          ? r.buy_alerta
          : typeof r.alert_at_buy === "string"
            ? r.alert_at_buy
            : typeof r.motivo === "string"
              ? r.motivo
              : null;
    if (direct && direct.trim()) return direct.trim();

    // Heurística mínima: parsear notas si incluyen un tag tipo "stop_loss", "toma_ganancia", etc.
    const notes = typeof r.sell_notes === "string" ? r.sell_notes : typeof r.notes === "string" ? r.notes : "";
    const s = (notes || "").toLowerCase();
    const known = ["venta", "toma_ganancia", "take_profit", "stop_loss", "manual"];
    for (const k of known) {
      if (s.includes(k)) return k;
    }
    return null;
  };

  const isSinAlerta = (label: string | null | undefined): boolean => {
    return (label ?? "").trim().toLowerCase() === "sin alerta";
  };

  function histRetUsdPct(r: PortfolioHistoryRow): number | null {
    if (r.asset_type === "Argentina") {
      return r.realized_return_usd_pct ?? null;
    }
    if (r.asset_type === "CEDEAR" || r.asset_type === "USA") {
      return r.realized_return_usd_pct ?? r.realized_return_pct ?? null;
    }
    return null;
  }

  function openBuyPriceCompraCell(r: PortfolioOpenRow): string {
    if (r.asset_type === "Argentina") {
      return r.buy_price_ars != null ? `ARS ${fmtNum(r.buy_price_ars, 2)}` : "—";
    }
    if (r.asset_type === "CEDEAR") {
      return r.buy_price_usd != null ? `USD (USA) ${fmtNum(r.buy_price_usd, 4)}` : "—";
    }
    return r.buy_price_usd != null ? `USD ${fmtNum(r.buy_price_usd, 4)}` : r.buy_price_ars != null ? `ARS ${fmtNum(r.buy_price_ars, 2)}` : "—";
  }

  function histUsdCell(r: PortfolioHistoryRow, v: number | null | undefined): string {
    if (v === null || v === undefined) return "—";
    const s = fmtNum(v, 4);
    return r.asset_type === "CEDEAR" ? `USD (USA) ${s}` : s;
  }

  function openPrecioActualCell(r: PortfolioOpenRow): string {
    if (r.asset_type === "CEDEAR") {
      return r.current_price_usd != null ? `USD (USA) ${fmtNum(r.current_price_usd, 4)}` : "—";
    }
    if (r.asset_type === "USA") {
      return r.current_price_usd != null ? `USD ${fmtNum(r.current_price_usd, 4)}` : "—";
    }
    return r.current_price_ars != null
      ? `ARS ${fmtNum(r.current_price_ars, 2)}`
      : r.current_price_usd != null
        ? `USD ${fmtNum(r.current_price_usd, 4)}`
        : "—";
  }

  async function onSubmitBuy(ev: FormEvent) {
    ev.preventDefault();
    if (!buyValidation.valid) {
      return;
    }
    setErr(null);
    setBusy(true);
    try {
      const q = parsePositiveNumber(quantity);
      if (q === null) {
        throw new Error("Cantidad inválida");
      }
      const parseOpt = (s: string) => {
        const t = s.trim();
        if (!t) return null;
        const n = Number(t.replace(",", "."));
        return Number.isFinite(n) ? n : null;
      };
      const tcCompra = parseOpt(buyTcMep);
      await createPortfolioPosition({
        ticker: ticker.trim(),
        asset_type: assetType,
        portfolio_type: stockPortfolioTypeForCreate,
        quantity: q,
        buy_date: buyDate,
        buy_price_ars: assetType === "CEDEAR" ? null : parseOpt(buyPriceArs),
        buy_price_usd: assetType === "Argentina" ? null : parseOpt(buyPriceUsd),
        tc_mep_compra: assetType === "USA" ? null : tcCompra,
        notes: buyNotes.trim() || null,
      });
      setTicker("");
      setTickerSug([]);
      setTickerSugError(false);
      setQuantity("1");
      setBuyPriceArs("");
      setBuyPriceUsd("");
      setBuyTcMep("");
      setBuyNotes("");
      setTab("cartera");
      await loadOpen();
      await loadMetrics();
      void refreshOpenPositionsIndex({ silent: true });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error al guardar");
    } finally {
      setBusy(false);
    }
  }

  function openSellModal(row: PortfolioOpenRow) {
    setSellTarget(row);
    setErr(null);
  }

  const onSellModalSuccess = useCallback(async () => {
    await loadOpen();
    await loadHist();
    await loadMetrics();
    void refreshOpenPositionsIndex({ silent: true });
    setTab("historial");
  }, [loadOpen, loadHist, loadMetrics, refreshOpenPositionsIndex]);

  function toggleExpandedOpen(id: number) {
    setExpandedOpenIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  function toggleExpandedHist(id: number) {
    setExpandedHistIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  function openMgmtModal(row: PortfolioOpenRow) {
    if (rowInstrumentType(row) === "stock" || rowInstrumentType(row) === "option_strategy") return;
    setMgmtOpenForId(row.id);
    setMgmtDate(todayIsoDate());
    setMgmtEventType("note");
    setMgmtDescription("");
    setMgmtDebitCredit("");
    setErr(null);
  }

  async function onSubmitMgmtEvent(ev: FormEvent) {
    ev.preventDefault();
    if (mgmtOpenForId === null) return;
    setMgmtBusy(true);
    setErr(null);
    try {
      const parseOptNum = (s: string) => {
        const t = s.trim();
        if (!t) return null;
        const n = Number(t.replace(",", "."));
        return Number.isFinite(n) ? n : null;
      };
      await appendPortfolioTradeEvent(mgmtOpenForId, {
        date: mgmtDate,
        event_type: mgmtEventType,
        description: mgmtDescription.trim(),
        debit_credit: parseOptNum(mgmtDebitCredit),
      });
      setMgmtOpenForId(null);
      await loadOpen();
      await loadMetrics();
      void refreshOpenPositionsIndex({ silent: true });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error al guardar evento");
    } finally {
      setMgmtBusy(false);
    }
  }

  async function onSubmitNewTrade(ev: FormEvent) {
    ev.preventDefault();
    const q = parsePositiveNumber(ntQuantity);
    if (q === null) {
      setErr("Cantidad inválida");
      return;
    }
    const parseOpt = (s: string) => {
      const t = s.trim();
      if (!t) return null;
      const n = Number(t.replace(",", "."));
      return Number.isFinite(n) ? n : null;
    };
    if (!ntTicker.trim()) {
      setErr("Completá ticker de la operación.");
      return;
    }
    if (ntInstrument === "option_strategy" && !ntUnderlying.trim()) {
      setErr("Para estrategias el símbolo subyacente es obligatorio.");
      return;
    }
    let buyUsd: number | null = null;
    let buyArs: number | null = null;
    if (ntAssetType === "Argentina") {
      const ars = parseOpt(ntBuyArs);
      if (ars === null || ars <= 0) {
        setErr("Precio / prima en ARS obligatorio (> 0) para Argentina.");
        return;
      }
      if (parseOpt(ntTcMep) === null) {
        setErr("TC MEP obligatorio para Argentina.");
        return;
      }
      buyArs = ars;
    } else {
      const usd = parseOpt(ntBuyUsd);
      if (usd === null || usd <= 0) {
        setErr("Precio / prima en USD obligatorio (> 0) para registrar el costo en cartera.");
        return;
      }
      buyUsd = usd;
      if (ntAssetType === "CEDEAR" && parseOpt(ntTcMep) === null) {
        setErr("TC MEP obligatorio para CEDEAR.");
        return;
      }
    }
    setNtBusy(true);
    setErr(null);
    try {
      await createPortfolioTrade({
        instrument_type: ntInstrument,
        ticker: ntTicker.trim().toUpperCase(),
        asset_type: ntAssetType,
        portfolio_type: "real",
        quantity: q,
        buy_date: ntBuyDate,
        buy_price_usd: buyUsd,
        buy_price_ars: buyArs,
        tc_mep_compra: ntAssetType === "USA" ? null : parseOpt(ntTcMep),
        notes: ntNotes.trim() || null,
        underlying_symbol:
          ntUnderlying.trim() !== ""
            ? ntUnderlying.trim().toUpperCase()
            : ntInstrument === "option"
              ? null
              : undefined,
        strategy_type: ntStrategy,
        legs: [],
        management_events: [],
      });
      setNtTicker("");
      setNtUnderlying("");
      setNtQuantity("1");
      setNtBuyUsd("");
      setNtBuyArs("");
      setNtTcMep("");
      setNtNotes("");
      await loadOpen();
      await loadMetrics();
      void refreshOpenPositionsIndex({ silent: true });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error al crear operación");
    } finally {
      setNtBusy(false);
    }
  }

  return (
    <>
      <h1 className="page-title">Cartera</h1>
      <p className="page-desc">
        {portfolioScope === "real"
          ? "Cartera Real: operaciones reales, opciones y estrategias con PnL y gestión. El tipo de activo (USA / Argentina / CEDEAR) sigue siendo el mercado."
          : portfolioScope === "radar"
            ? "Cartera Radar: seguimiento de compras por alertas y evolución posterior (comportamiento histórico). Las posiciones ya guardadas quedan como radar salvo que las muevas por API."
            : "Vista Todas: listado consolidado de cartera radar y real."}{" "}
        En CEDEAR, precios y retornos en USD usan el subyacente USA (no cable CCL local).
      </p>
      <div className="cartera-tabs" role="tablist" aria-label="Cartera radar o real" style={{ marginTop: "0.35rem" }}>
        {(
          [
            ["radar", "Cartera Radar"],
            ["real", "Cartera Real"],
            ["all", "Todas"],
          ] as const
        ).map(([val, label]) => (
          <button
            key={val}
            type="button"
            role="tab"
            aria-selected={portfolioScope === val}
            className={portfolioScope === val ? "cartera-tab cartera-tab--active" : "cartera-tab"}
            onClick={() => setPortfolioScope(val)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="cartera-tabs" role="tablist" aria-label="Secciones cartera">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "compra"}
          className={tab === "compra" ? "cartera-tab cartera-tab--active" : "cartera-tab"}
          onClick={() => setTab("compra")}
        >
          Cargar compra
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "cartera"}
          className={tab === "cartera" ? "cartera-tab cartera-tab--active" : "cartera-tab"}
          onClick={() => setTab("cartera")}
        >
          Cartera abierta
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "historial"}
          className={tab === "historial" ? "cartera-tab cartera-tab--active" : "cartera-tab"}
          onClick={() => setTab("historial")}
        >
          Historial
        </button>
      </div>

      {err ? (
        <div className="cartera-alert" role="alert">
          {err}
        </div>
      ) : null}

      {tab === "compra" ? (
        <form className="card cartera-form" onSubmit={onSubmitBuy}>
          <h2 className="cartera-form__title">Registrar compra</h2>
          <div className="cartera-grid">
            <label className={`cartera-field${buyValidation.inv.ticker ? " cartera-field--invalid" : ""}`}>
              <span>Ticker</span>
              <input
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
                placeholder="ej. AAPL"
                list={tickerDatalistId}
                autoComplete="off"
              />
              <datalist id={tickerDatalistId}>
                {tickerSug.map((t) => (
                  <option key={t} value={t} />
                ))}
              </datalist>
              {tickerSugError ? <small className="cartera-hint">Sugerencias no disponibles (podés seguir escribiendo).</small> : null}
            </label>
            <label className="cartera-field">
              <span>Tipo de activo</span>
              <select
                value={assetType}
                onChange={(e) => {
                  const v = e.target.value as PortfolioAssetType;
                  setAssetType(v);
                  setBuyPriceArs("");
                  setBuyPriceUsd("");
                  setBuyTcMep("");
                }}
              >
                <option value="USA">USA</option>
                <option value="Argentina">Argentina</option>
                <option value="CEDEAR">CEDEAR</option>
              </select>
            </label>
            <label className={`cartera-field${buyValidation.inv.qty ? " cartera-field--invalid" : ""}`}>
              <span>Cantidad</span>
              <input value={quantity} onChange={(e) => setQuantity(e.target.value)} inputMode="decimal" />
            </label>
            <label className={`cartera-field${buyValidation.inv.date ? " cartera-field--invalid" : ""}`}>
              <span>Fecha de compra</span>
              <input type="date" value={buyDate} onChange={(e) => setBuyDate(e.target.value)} />
            </label>
            {assetType === "Argentina" || assetType === "USA" ? (
              <label
                className={`cartera-field${
                  buyValidation.inv.price && assetType === "Argentina" ? " cartera-field--invalid" : ""
                }`}
              >
                <span>Precio compra ARS</span>
                <input
                  value={buyPriceArs}
                  onChange={(e) => setBuyPriceArs(e.target.value)}
                  inputMode="decimal"
                  placeholder={assetType === "USA" ? "opcional" : "obligatorio"}
                />
              </label>
            ) : null}
            {assetType === "USA" || assetType === "CEDEAR" ? (
              <label
                className={`cartera-field${
                  buyValidation.inv.price && (assetType === "USA" || assetType === "CEDEAR") ? " cartera-field--invalid" : ""
                }`}
              >
                <span>{assetType === "CEDEAR" ? "Precio compra USD (subyacente USA)" : "Precio compra USD"}</span>
                <input
                  value={buyPriceUsd}
                  onChange={(e) => setBuyPriceUsd(e.target.value)}
                  inputMode="decimal"
                  placeholder={
                    assetType === "CEDEAR" ? "USD por acción USA — costo/tu referencia (obligatorio)" : "obligatorio"
                  }
                />
              </label>
            ) : null}
            {assetType === "Argentina" || assetType === "CEDEAR" ? (
              <label className={`cartera-field${buyValidation.inv.mep ? " cartera-field--invalid" : ""}`}>
                <span>TC MEP compra (ARS por USD)</span>
                <input value={buyTcMep} onChange={(e) => setBuyTcMep(e.target.value)} inputMode="decimal" placeholder="obligatorio" />
              </label>
            ) : null}
            <label className="cartera-field cartera-field--full">
              <span>Notas</span>
              <textarea value={buyNotes} onChange={(e) => setBuyNotes(e.target.value)} rows={2} placeholder="opcional" />
            </label>
          </div>
          <p className="cartera-hint">
            USA: precio en USD. Argentina: precio en ARS + TC MEP de la compra (para retorno USD al cerrar). CEDEAR: el
            precio en USD es el del subyacente listado en USA (no ARS ni cable CCL) + TC MEP de referencia. El backend
            toma score del último radar / snapshot CEDEAR.
          </p>
          <p className="cartera-hint" style={{ marginTop: "0.35rem" }}>
            Esta compra se guarda como <strong>{stockPortfolioTypeForCreate === "real" ? "cartera real" : "cartera radar"}</strong>{" "}
            según el selector superior (en &quot;Todas&quot; se usa radar para no mezclar con operaciones reales por defecto).
          </p>
          {!buyValidation.valid && buyValidation.message ? (
            <div className="cartera-validation-hint" role="status">
              {buyValidation.message}
            </div>
          ) : null}
          <button type="submit" className="cartera-btn cartera-btn--primary" disabled={busy || !buyValidation.valid}>
            {busy ? "Guardando…" : "Guardar compra"}
          </button>
        </form>
      ) : null}

      {tab === "cartera" ? (
        <>
          <div className="card cartera-table-wrap" style={{ marginBottom: "1rem" }}>
            <h2 className="cartera-form__title">Resumen opciones / estrategias</h2>
            {tradeMetrics ? (
              <>
                {showRealPortfolioMetrics ? (
                  <>
                    <div className="cartera-grid" style={{ marginTop: "0.5rem" }}>
                      <p>
                        <strong>PnL realizado:</strong> {fmtNum(tradeMetrics.realized_pnl_usd_approx_closed_non_stock, 2)}{" "}
                        <span className="cartera-hint">
                          (estrategias con debit_credit usan suma de cashflows; si no, buy/sell × cantidad)
                        </span>
                      </p>
                      <p>
                        <strong>Suma cashflows (estrategias con eventos monetizados):</strong>{" "}
                        {fmtNum(tradeMetrics.total_realized_pnl_cashflow ?? 0, 2)}
                      </p>
                      <p>
                        <strong>Capital comprometido abierto:</strong>{" "}
                        {fmtNum(tradeMetrics.open_committed_capital ?? tradeMetrics.committed_capital_total_non_stock_open, 2)}
                      </p>
                      <p>
                        <strong>Riesgo máximo abierto:</strong>{" "}
                        {fmtNum(tradeMetrics.open_max_risk ?? tradeMetrics.max_risk_total_non_stock_open, 2)}
                      </p>
                      <p>
                        <strong>Estrategias abiertas:</strong> {tradeMetrics.open_option_strategies_count}
                      </p>
                      <p>
                        <strong>Win rate estrategias cerradas:</strong>{" "}
                        {(tradeMetrics.win_rate_closed_strategies ?? tradeMetrics.closed_option_strategies_win_rate) != null &&
                        (tradeMetrics.closed_option_strategies_total ?? 0) > 0
                          ? `${fmtNum(((tradeMetrics.win_rate_closed_strategies ?? tradeMetrics.closed_option_strategies_win_rate) as number) * 100, 2)}% (${tradeMetrics.closed_option_strategies_wins ?? 0} ganadas / ${tradeMetrics.closed_option_strategies_losses ?? 0} pérdidas, n=${tradeMetrics.closed_option_strategies_total})`
                          : "— (sin estrategias cerradas con PnL estimable)"}
                      </p>
                      <p>
                        <strong>Opciones simples abiertas:</strong> {tradeMetrics.open_options_count}
                      </p>
                    </div>
                    <h3 className="cartera-form__title" style={{ fontSize: "1rem", marginTop: "1rem" }}>
                      PnL realizado por tipo de estrategia
                    </h3>
                    <table className="cartera-table" style={{ marginTop: "0.35rem" }}>
                      <thead>
                        <tr>
                          <th>Tipo</th>
                          <th className="nowrap">PnL</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(
                          tradeMetrics.realized_pnl_by_strategy ??
                            tradeMetrics.realized_pnl_by_strategy_type_usd_approx ??
                            {},
                        )
                          .sort((a, b) => a[0].localeCompare(b[0]))
                          .map(([k, v]) => (
                            <tr key={k}>
                              <td>{k}</td>
                              <td className="cartera-mono">{fmtNum(v, 2)}</td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                    <h3 className="cartera-form__title" style={{ fontSize: "1rem", marginTop: "1rem" }}>
                      PnL realizado por subyacente
                    </h3>
                    <table className="cartera-table" style={{ marginTop: "0.35rem" }}>
                      <thead>
                        <tr>
                          <th>Subyacente</th>
                          <th className="nowrap">PnL</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(
                          tradeMetrics.realized_pnl_by_underlying ??
                            tradeMetrics.realized_pnl_by_underlying_usd_approx ??
                            {},
                        )
                          .sort((a, b) => a[0].localeCompare(b[0]))
                          .map(([k, v]) => (
                            <tr key={k}>
                              <td>{k}</td>
                              <td className="cartera-mono">{fmtNum(v, 2)}</td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </>
                ) : (
                  <div className="cartera-grid" style={{ marginTop: "0.5rem" }}>
                    <p>
                      <strong>Estrategias abiertas:</strong> {tradeMetrics.open_option_strategies_count}
                    </p>
                    <p>
                      <strong>Opciones simples abiertas:</strong> {tradeMetrics.open_options_count}
                    </p>
                    <p>
                      <strong>Capital comprometido (no acciones, abierto):</strong> USD{" "}
                      {fmtNum(tradeMetrics.committed_capital_total_non_stock_open, 2)}
                    </p>
                    <p>
                      <strong>Riesgo máximo declarado (no acciones, abierto):</strong> USD{" "}
                      {fmtNum(tradeMetrics.max_risk_total_non_stock_open, 2)}
                    </p>
                    <p>
                      <strong>PnL realizado aprox. (cerrado, no acciones):</strong> USD{" "}
                      {fmtNum(tradeMetrics.realized_pnl_usd_approx_closed_non_stock, 2)}
                    </p>
                    <p>
                      <strong>Win rate estrategias cerradas (aprox.):</strong>{" "}
                      {tradeMetrics.closed_option_strategies_win_rate != null &&
                      tradeMetrics.closed_option_strategies_total != null &&
                      tradeMetrics.closed_option_strategies_total > 0
                        ? `${fmtNum((tradeMetrics.closed_option_strategies_win_rate as number) * 100, 2)}% (${tradeMetrics.closed_option_strategies_wins ?? 0} ganadas / ${tradeMetrics.closed_option_strategies_losses ?? 0} pérdidas, n=${tradeMetrics.closed_option_strategies_total})`
                        : "— (sin estrategias cerradas con PnL estimable)"}
                    </p>
                  </div>
                )}
              </>
            ) : (
              <p className="cartera-hint">Métricas no disponibles.</p>
            )}
            <p className="cartera-hint" style={{ marginBottom: 0 }}>
              {showRealPortfolioMetrics
                ? "Métricas filtradas por cartera seleccionada (radar / real / todas). Detalle en GET /portfolio/trades/metrics."
                : "Para métricas de contabilidad por cashflows y tablas por estrategia / subyacente, elegí Cartera real o Todas arriba."}
            </p>
            {showRealPortfolioMetrics ? (
              <p className="cartera-hint" style={{ marginTop: "0.5rem" }}>
                <strong>Prueba contable Galicia ARS (bull_call_spread GGAL):</strong> apertura −15000, ajuste +3000, cierre
                +25000 → PnL esperado <strong>+13000</strong> (suma de cashflows).
              </p>
            ) : null}
          </div>

          <div className="card cartera-table-wrap" style={{ marginBottom: "1rem" }}>
            <h2 className="cartera-form__title">Alta rápida opción o estrategia</h2>
            <p className="cartera-hint">
              Registro mínimo (sin legs en UI; podés editar vía API PATCH). Siempre se guarda como{" "}
              <strong>cartera real</strong>. Mercado USA, Argentina (ARS + TC MEP) o CEDEAR (USD subyacente + TC MEP).
            </p>
            <form className="cartera-form" onSubmit={onSubmitNewTrade}>
              <div className="cartera-grid">
                <label className="cartera-field">
                  <span>Instrumento</span>
                  <select value={ntInstrument} onChange={(e) => setNtInstrument(e.target.value as "option" | "option_strategy")}>
                    <option value="option">Opción</option>
                    <option value="option_strategy">Estrategia</option>
                  </select>
                </label>
                <label className="cartera-field">
                  <span>Ticker operación</span>
                  <input value={ntTicker} onChange={(e) => setNtTicker(e.target.value)} placeholder="ej. estrategia / OCC" />
                </label>
                <label className="cartera-field">
                  <span>Subyacente {ntInstrument === "option_strategy" ? "(obligatorio)" : "(opcional)"}</span>
                  <input value={ntUnderlying} onChange={(e) => setNtUnderlying(e.target.value)} placeholder="ej. AAPL / GGAL" />
                </label>
                <label className="cartera-field">
                  <span>Mercado</span>
                  <select
                    value={ntAssetType}
                    onChange={(e) => {
                      const v = e.target.value as PortfolioAssetType;
                      setNtAssetType(v);
                      if (v === "USA") setNtTcMep("");
                      setNtBuyUsd("");
                      setNtBuyArs("");
                    }}
                  >
                    <option value="USA">USA</option>
                    <option value="Argentina">Argentina</option>
                    <option value="CEDEAR">CEDEAR</option>
                  </select>
                </label>
                <label className="cartera-field">
                  <span>Cantidad</span>
                  <input value={ntQuantity} onChange={(e) => setNtQuantity(e.target.value)} inputMode="decimal" />
                </label>
                <label className="cartera-field">
                  <span>Fecha apertura</span>
                  <input type="date" value={ntBuyDate} onChange={(e) => setNtBuyDate(e.target.value)} />
                </label>
                <label className="cartera-field">
                  <span>
                    {ntAssetType === "Argentina"
                      ? "Prima / costo neto (ARS)"
                      : "Costo / crédito neto (USD en fila)"}
                  </span>
                  <input
                    value={ntAssetType === "Argentina" ? ntBuyArs : ntBuyUsd}
                    onChange={(e) =>
                      ntAssetType === "Argentina" ? setNtBuyArs(e.target.value) : setNtBuyUsd(e.target.value)
                    }
                    inputMode="decimal"
                    placeholder="obligatorio"
                  />
                </label>
                <label className="cartera-field">
                  <span>Tipo estrategia</span>
                  <select
                    value={ntStrategy}
                    onChange={(e) => setNtStrategy(e.target.value as PortfolioTradeCreatePayload["strategy_type"])}
                  >
                    <option value="custom">custom</option>
                    <option value="covered_call">covered_call</option>
                    <option value="csp">csp</option>
                    <option value="bull_call_spread">bull_call_spread</option>
                    <option value="bear_put_spread">bear_put_spread</option>
                    <option value="collar">collar</option>
                    <option value="long_call">long_call</option>
                    <option value="long_put">long_put</option>
                  </select>
                </label>
                {ntAssetType === "CEDEAR" || ntAssetType === "Argentina" ? (
                  <label className="cartera-field">
                    <span>TC MEP compra</span>
                    <input value={ntTcMep} onChange={(e) => setNtTcMep(e.target.value)} inputMode="decimal" placeholder="obligatorio" />
                  </label>
                ) : null}
                <label className="cartera-field cartera-field--full">
                  <span>Notas</span>
                  <textarea value={ntNotes} onChange={(e) => setNtNotes(e.target.value)} rows={2} />
                </label>
              </div>
              <button type="submit" className="cartera-btn cartera-btn--primary" disabled={ntBusy}>
                {ntBusy ? "Guardando…" : "Crear operación"}
              </button>
            </form>
          </div>

          <div className="card cartera-table-wrap">
            <h2 className="cartera-form__title">Posiciones abiertas</h2>
            <div className="cartera-tabs" role="tablist" aria-label="Filtro tipo instrumento" style={{ marginTop: "0.75rem" }}>
              {(
                [
                  ["all", "Todos"],
                  ["stock", "Acciones"],
                  ["option", "Opciones"],
                  ["option_strategy", "Estrategias"],
                ] as const
              ).map(([val, label]) => (
                <button
                  key={val}
                  type="button"
                  role="tab"
                  aria-selected={openInstrumentFilter === val}
                  className={openInstrumentFilter === val ? "cartera-tab cartera-tab--active" : "cartera-tab"}
                  onClick={() => setOpenInstrumentFilter(val)}
                >
                  {label}
                </button>
              ))}
            </div>
            {openRows.some((r) => r.asset_type === "CEDEAR") ? (
              <p className="cartera-hint" style={{ marginTop: "0.75rem" }}>
                Filas CEDEAR: &quot;precio compra&quot; y &quot;precio actual&quot; en USD (USA) = subyacente; no es cotización cable CCL.
              </p>
            ) : null}
            {openRows.length === 0 ? (
              <p className="cartera-empty">No hay posiciones abiertas.</p>
            ) : filteredOpenRows.length === 0 ? (
              <p className="cartera-empty">Ninguna posición coincide con el filtro.</p>
            ) : (
              <div className="table-scroll">
                <table className="cartera-table">
                  <thead>
                    <tr>
                      <th>ticker</th>
                      <th>merc.</th>
                      <th>cartera</th>
                      <th>inst.</th>
                      <th>suby.</th>
                      <th>estrategia</th>
                      <th>f compra</th>
                      <th>señal compra</th>
                      <th>señal actual</th>
                      <th>score compra</th>
                      <th>score actual</th>
                      <th>alerta compra</th>
                      <th>cant</th>
                      <th title="CEDEAR: USD del subyacente USA. Argentina: ARS. USA: USD.">precio compra</th>
                      <th title="CEDEAR: USD mercado del subyacente USA (no CCL local). USA: USD. Argentina: ARS.">
                        precio actual
                      </th>
                      <th title="CEDEAR y USA: % vs precio compra en USD (misma moneda / referencia).">retorno</th>
                      <th>acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredOpenRows.map((r) => {
                      const inst = rowInstrumentType(r);
                      const expanded = expandedOpenIds.includes(r.id);
                      const legs = r.legs ?? [];
                      const evs = r.management_events ?? [];
                      const sortedEvs = sortMgmtEventsAsc(evs);
                      return (
                        <Fragment key={r.id}>
                          <tr>
                            <td className="nowrap">{r.ticker}</td>
                            <td className="nowrap table-cell--nowrap cartera-type-cell" title={r.asset_type}>
                              {fmtAssetTypeShort(r.asset_type)}
                            </td>
                            <td className="nowrap" title={r.portfolio_type ?? "radar"}>
                              {fmtPortfolioKindLabel(r.portfolio_type)}
                            </td>
                            <td className="nowrap" title={inst}>
                              {fmtInstrumentShort(inst)}
                            </td>
                            <td className="nowrap">{r.underlying_symbol ?? "—"}</td>
                            <td className="nowrap">{r.strategy_type ?? "—"}</td>
                            <td className="nowrap">{r.buy_date}</td>
                            <td>{r.signalstate_at_buy ?? "—"}</td>
                            <td>{r.current_signalstate ?? "—"}</td>
                            <td>{fmtNum(r.score_at_buy, 2)}</td>
                            <td>{fmtNum(r.current_score, 2)}</td>
                            {(() => {
                              const lab = extractAlertLabel(r) ?? "sin alerta";
                              return <td className={isSinAlerta(lab) ? "cartera-alert--none" : ""}>{lab}</td>;
                            })()}
                            <td>{fmtNum(r.quantity, 6)}</td>
                            <td title={r.asset_type === "CEDEAR" ? "Costo en USD del subyacente USA" : undefined}>
                              {openBuyPriceCompraCell(r)}
                            </td>
                            <td
                              title={
                                r.asset_type === "CEDEAR"
                                  ? "Mercado actual USD del subyacente USA (no CCL local)"
                                  : r.asset_type === "USA"
                                    ? "Precio actual en USD"
                                    : undefined
                              }
                            >
                              {openPrecioActualCell(r)}
                            </td>
                            <td
                              className={classifyReturn(r.return_pct)}
                              title={
                                r.asset_type === "CEDEAR"
                                  ? "Retorno vs costo en USD (subyacente USA)"
                                  : r.asset_type === "USA"
                                    ? "Retorno vs costo en USD"
                                    : undefined
                              }
                            >
                              {r.return_pct === null || r.return_pct === undefined ? "—" : `${fmtNum(r.return_pct, 2)}%`}
                            </td>
                            <td>
                              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.35rem" }}>
                                <button
                                  type="button"
                                  className="cartera-btn"
                                  onClick={() => toggleExpandedOpen(r.id)}
                                  aria-expanded={expanded}
                                >
                                  {expanded ? "Ocultar" : "Detalle"}
                                </button>
                                {inst === "option_strategy" ? (
                                  <>
                                    <button
                                      type="button"
                                      className="cartera-btn"
                                      disabled={Boolean(r.strategy_is_closed)}
                                      title={r.strategy_is_closed ? "Ya hay cierre total registrado en eventos" : undefined}
                                      onClick={() => setStrategyMgmt({ row: r, mode: "adjustment" })}
                                    >
                                      Agregar ajuste
                                    </button>
                                    <button
                                      type="button"
                                      className="cartera-btn"
                                      disabled={Boolean(r.strategy_is_closed)}
                                      onClick={() => setStrategyMgmt({ row: r, mode: "partial_close" })}
                                    >
                                      Cerrar parcial
                                    </button>
                                    <button
                                      type="button"
                                      className="cartera-btn"
                                      disabled={Boolean(r.strategy_is_closed)}
                                      onClick={() => setStrategyMgmt({ row: r, mode: "full_close" })}
                                    >
                                      Cerrar total
                                    </button>
                                  </>
                                ) : null}
                                {inst === "option" ? (
                                  <button type="button" className="cartera-btn" onClick={() => openMgmtModal(r)}>
                                    Agregar gestión
                                  </button>
                                ) : null}
                                <button type="button" className="cartera-btn cartera-btn--sell" onClick={() => openSellModal(r)}>
                                  {inst === "stock" ? "Vender" : "Cerrar"}
                                </button>
                              </div>
                            </td>
                          </tr>
                          {expanded ? (
                            <tr className="cartera-expand-row">
                              <td colSpan={17}>
                                <div style={{ padding: "0.5rem 0" }}>
                                  {inst === "option_strategy" ? (
                                    <>
                                      <div className="cartera-strategy-detail-summary" role="region" aria-label="Resumen contable">
                                        <span>
                                          <strong>Cashflow total acumulado:</strong>{" "}
                                          {typeof r.strategy_cashflow_total === "number" && Number.isFinite(r.strategy_cashflow_total)
                                            ? fmtNum(r.strategy_cashflow_total, 4)
                                            : "—"}
                                        </span>
                                        <span>
                                          <strong>PnL realizado:</strong>{" "}
                                          {r.strategy_realized_pnl != null && Number.isFinite(r.strategy_realized_pnl)
                                            ? fmtNum(r.strategy_realized_pnl, 4)
                                            : "— (posición abierta o sin cierre contable)"}
                                        </span>
                                        <span>
                                          <strong>Accounting:</strong>{" "}
                                          {r.strategy_pnl_accounting != null
                                            ? `${r.strategy_pnl_accounting} · ${
                                                r.strategy_pnl_accounting === "cashflow"
                                                  ? "PnL = Σ debit_credit"
                                                  : "PnL legacy buy/sell"
                                              }`
                                            : r.strategy_is_closed
                                              ? "—"
                                              : "al cerrar: cashflow / legacy según eventos"}
                                        </span>
                                      </div>
                                      {r.strategy_is_closed ? (
                                        <p className="cartera-hint" style={{ marginTop: 0 }}>
                                          Evento <code>full_close</code> detectado. Si la fila sigue en abierta, usá &quot;Cerrar&quot;
                                          o revisá el estado en el backend.
                                        </p>
                                      ) : null}
                                      <p className="cartera-form__title" style={{ fontSize: "1rem", marginBottom: "0.35rem" }}>
                                        Legs ({legs.length})
                                      </p>
                                      <pre className="cartera-json-block" style={{ maxHeight: 220, overflow: "auto" }}>
                                        {legs.length
                                          ? JSON.stringify(legs, null, 2)
                                          : "Sin legs (PATCH /portfolio/trades con el id de la fila)."}
                                      </pre>
                                      <p className="cartera-form__title" style={{ fontSize: "1rem", margin: "0.75rem 0 0.35rem" }}>
                                        Eventos de gestión ({evs.length}), ordenados por fecha
                                      </p>
                                      {sortedEvs.length === 0 ? (
                                        <p className="cartera-hint">Sin eventos todavía.</p>
                                      ) : (
                                        <div className="table-wrap cartera-ev-table-wrap">
                                          <table className="cartera-table">
                                            <thead>
                                              <tr>
                                                <th>Fecha</th>
                                                <th>Tipo</th>
                                                <th>Descripción</th>
                                                <th className="nowrap">debit_credit</th>
                                                <th className="nowrap">Spot</th>
                                                <th>IV</th>
                                                <th>Nota</th>
                                              </tr>
                                            </thead>
                                            <tbody>{strategyEventTableRows(sortedEvs, r.id)}</tbody>
                                          </table>
                                        </div>
                                      )}
                                    </>
                                  ) : (
                                    <>
                                      <p className="cartera-form__title" style={{ fontSize: "1rem", marginBottom: "0.35rem" }}>
                                        Legs ({legs.length})
                                      </p>
                                      <pre className="cartera-json-block" style={{ maxHeight: 220, overflow: "auto" }}>
                                        {legs.length
                                          ? JSON.stringify(legs, null, 2)
                                          : "Sin legs (PATCH /portfolio/trades con el id de la fila)."}
                                      </pre>
                                      <p className="cartera-form__title" style={{ fontSize: "1rem", margin: "0.75rem 0 0.35rem" }}>
                                        Eventos de gestión ({evs.length})
                                      </p>
                                      <pre className="cartera-json-block" style={{ maxHeight: 220, overflow: "auto" }}>
                                        {evs.length ? JSON.stringify(evs, null, 2) : "Sin eventos todavía."}
                                      </pre>
                                    </>
                                  )}
                                </div>
                              </td>
                            </tr>
                          ) : null}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      ) : null}

      {tab === "historial" ? (
        <div className="card cartera-table-wrap">
          <h2 className="cartera-form__title">Historial de ventas</h2>
          {histRows.some((r) => r.asset_type === "CEDEAR") ? (
            <p className="cartera-hint" style={{ marginTop: 0 }}>
              CEDEAR: columnas &quot;Precio USD&quot; compra/venta y &quot;Retorno USD %&quot; = subyacente USA (misma base que al operar).
            </p>
          ) : null}
          {histRows.length === 0 ? (
            <p className="cartera-empty">No hay posiciones cerradas.</p>
          ) : (
            <>
              {histStrategyRowsAll.length > 0 ? (
                <div style={{ marginBottom: histNonStrategyRows.length > 0 ? "1.5rem" : 0 }}>
                  <h3 className="cartera-form__title" style={{ fontSize: "1.05rem", marginTop: "0.5rem" }}>
                    Estrategias cerradas (option_strategy)
                  </h3>
                  {portfolioScope === "real" ? (
                    <div
                      className="cartera-grid"
                      style={{ marginTop: "0.5rem", marginBottom: "0.65rem", alignItems: "end" }}
                    >
                      <label className="cartera-field">
                        <span>Estrategia</span>
                        <select
                          value={histStratTypeFilter}
                          onChange={(e) => setHistStratTypeFilter(e.target.value)}
                          aria-label="Filtrar historial por tipo de estrategia"
                        >
                          <option value="">Todas</option>
                          {histStratTypeOptions.map((t) => (
                            <option key={t} value={t}>
                              {t}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="cartera-field">
                        <span>Subyacente</span>
                        <select
                          value={histStratUnderlyingFilter}
                          onChange={(e) => setHistStratUnderlyingFilter(e.target.value)}
                          aria-label="Filtrar historial por subyacente"
                        >
                          <option value="">Todos</option>
                          {histStratUnderlyingOptions.map((u) => (
                            <option key={u} value={u}>
                              {u}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="cartera-field">
                        <span>Resultado</span>
                        <select
                          value={histStratResultFilter}
                          onChange={(e) => setHistStratResultFilter(e.target.value as "all" | "win" | "loss")}
                          aria-label="Filtrar por PnL realizado"
                        >
                          <option value="all">Todas</option>
                          <option value="win">Ganadoras</option>
                          <option value="loss">Perdedoras</option>
                        </select>
                      </label>
                    </div>
                  ) : (
                    <p className="cartera-hint" style={{ marginBottom: "0.5rem" }}>
                      Filtros por estrategia / subyacente / resultado disponibles con la cartera <strong>Real</strong> arriba.
                    </p>
                  )}
                  {portfolioScope === "real" &&
                  histStrategyRowsAll.length > 0 &&
                  histFilteredStrategyRows.length === 0 ? (
                    <p className="cartera-hint" role="status">
                      Ninguna estrategia cerrada coincide con los filtros.
                    </p>
                  ) : (
                    <div className="table-scroll">
                      <table className="cartera-table">
                        <thead>
                          <tr>
                            <th>Ticker</th>
                            <th>Mercado</th>
                            <th>Cartera</th>
                            <th>Inst.</th>
                            <th>Subyacente</th>
                            <th>Estrategia</th>
                            <th>Compra</th>
                            <th>Venta</th>
                            <th className="nowrap">Días</th>
                            <th className="nowrap">PnL / día</th>
                            <th className="nowrap">Cashflow total</th>
                            <th className="nowrap">PnL realizado</th>
                            <th>Accounting</th>
                            <th>Detalle</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(portfolioScope === "real" ? histFilteredStrategyRows : histStrategyRowsAll).map((r) => {
                            const expanded = expandedHistIds.includes(r.id);
                            const pnl = r.strategy_realized_pnl;
                            const days = histStrategyDaysInTrade(r);
                            const pnlDay = histStrategyPnLPerDay(r);
                            const pnlDayClass =
                              pnlDay != null && Number.isFinite(pnlDay) && pnlDay > 0
                                ? "cartera-ret--pos"
                                : pnlDay != null && Number.isFinite(pnlDay) && pnlDay < 0
                                  ? "cartera-ret--neg"
                                  : "";
                            const pnlClass =
                              pnl != null && Number.isFinite(pnl) && pnl > 0
                                ? "cartera-ret--pos"
                                : pnl != null && Number.isFinite(pnl) && pnl < 0
                                  ? "cartera-ret--neg"
                                  : "";
                            return (
                              <Fragment key={r.id}>
                                <tr>
                                  <td className="nowrap">{r.ticker}</td>
                                  <td className="nowrap table-cell--nowrap cartera-type-cell" title={r.asset_type}>
                                    {fmtAssetTypeShort(r.asset_type)}
                                  </td>
                                  <td className="nowrap" title={r.portfolio_type ?? "radar"}>
                                    {fmtPortfolioKindLabel(r.portfolio_type)}
                                  </td>
                                  <td className="nowrap" title="option_strategy">
                                    {fmtInstrumentShort("option_strategy")}
                                  </td>
                                  <td className="nowrap">{r.underlying_symbol ?? "—"}</td>
                                  <td className="nowrap">{r.strategy_type ?? "—"}</td>
                                  <td className="nowrap">{r.buy_date ?? "—"}</td>
                                  <td className="nowrap">{r.sell_date ?? "—"}</td>
                                  <td className="cartera-mono">{days !== null ? String(days) : "—"}</td>
                                  <td className={`cartera-mono ${pnlDayClass}`}>{histStrategyMoneyPerDayFmt(r, pnlDay)}</td>
                                  <td className="cartera-mono">
                                    {histStrategyMoneyFmt(r, r.strategy_cashflow_total ?? null)}
                                  </td>
                                  <td className={`cartera-mono ${pnlClass}`}>
                                    {histStrategyMoneyFmt(r, r.strategy_realized_pnl ?? null)}
                                  </td>
                                  <td className="nowrap" title={r.strategy_pnl_accounting ?? ""}>
                                    {r.strategy_pnl_accounting === "cashflow"
                                      ? "cashflow"
                                      : r.strategy_pnl_accounting === "legacy"
                                        ? "legacy"
                                        : "—"}
                                  </td>
                                  <td>
                                    <button
                                      type="button"
                                      className="cartera-btn"
                                      onClick={() => toggleExpandedHist(r.id)}
                                      aria-expanded={expanded}
                                    >
                                      {expanded ? "Ocultar" : "Detalle"}
                                    </button>
                                  </td>
                                </tr>
                                {expanded ? (
                                  <tr className="cartera-expand-row">
                                    <td colSpan={14}>
                                      <HistStrategyExpandedDetail r={r} />
                                    </td>
                                  </tr>
                                ) : null}
                              </Fragment>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              ) : null}

              {histNonStrategyRows.length > 0 ? (
                <div>
                  {histStrategyRowsAll.length > 0 ? (
                    <h3 className="cartera-form__title" style={{ fontSize: "1.05rem", marginTop: "0.25rem" }}>
                      Acciones y opciones simples
                    </h3>
                  ) : null}
                  <div className="table-scroll">
                    <table className="cartera-table">
                      <thead>
                        <tr>
                          <th>Ticker</th>
                          <th>Tipo</th>
                          <th>Cartera</th>
                          <th>Inst.</th>
                          <th>Compra</th>
                          <th>Venta</th>
                          <th>Precio ARS compra</th>
                          <th title="En CEDEAR: USD del subyacente USA (no CCL).">Precio USD compra</th>
                          <th>Precio ARS venta</th>
                          <th title="En CEDEAR: USD del subyacente USA al cierre (no CCL).">Precio USD venta</th>
                          <th>Score compra</th>
                          <th>Score venta</th>
                          <th>Señal compra</th>
                          <th>Señal venta</th>
                          <th>Retorno % (ARS)</th>
                          <th title="CEDEAR y USA: % en USD. CEDEAR = subyacente USA.">Retorno USD %</th>
                          <th>Días tenencia</th>
                          <th>Alerta</th>
                        </tr>
                      </thead>
                      <tbody>
                        {histNonStrategyRows.map((r) => (
                          <tr key={r.id}>
                            <td className="nowrap">{r.ticker}</td>
                            <td className="nowrap table-cell--nowrap cartera-type-cell" title={r.asset_type}>
                              {fmtAssetTypeShort(r.asset_type)}
                            </td>
                            <td className="nowrap" title={r.portfolio_type ?? "radar"}>
                              {fmtPortfolioKindLabel(r.portfolio_type)}
                            </td>
                            <td className="nowrap" title={r.instrument_type ?? "stock"}>
                              {fmtInstrumentShort((r.instrument_type ?? "stock") as PortfolioInstrumentType)}
                            </td>
                            <td className="nowrap">{r.buy_date ?? "—"}</td>
                            <td className="nowrap">{r.sell_date ?? "—"}</td>
                            <td>{fmtNum(r.buy_price_ars, 2)}</td>
                            <td title={r.asset_type === "CEDEAR" ? "Subyacente USA" : undefined}>
                              {histUsdCell(r, r.buy_price_usd)}
                            </td>
                            <td>{fmtNum(r.sell_price_ars, 2)}</td>
                            <td title={r.asset_type === "CEDEAR" ? "Subyacente USA al cierre" : undefined}>
                              {histUsdCell(r, r.sell_price_usd)}
                            </td>
                            <td>{fmtNum(r.score_at_buy, 2)}</td>
                            <td>{fmtNum(r.score_at_sell, 2)}</td>
                            <td>{r.signalstate_at_buy ?? "—"}</td>
                            <td>{r.signalstate_at_sell ?? "—"}</td>
                            <td>
                              {r.asset_type === "Argentina"
                                ? r.realized_return_pct == null
                                  ? "—"
                                  : `${fmtNum(r.realized_return_pct, 2)}%`
                                : "—"}
                            </td>
                            <td
                              className={classifyReturn(histRetUsdPct(r))}
                              title={r.asset_type === "CEDEAR" ? "Retorno en USD del subyacente USA" : undefined}
                            >
                              {histRetUsdPct(r) === null ? "—" : `${fmtNum(histRetUsdPct(r), 2)}%`}
                            </td>
                            <td>{r.holding_days ?? "—"}</td>
                            {(() => {
                              const lab = extractAlertLabel(r) ?? "sin alerta";
                              return <td className={isSinAlerta(lab) ? "cartera-alert--none" : ""}>{lab}</td>;
                            })()}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : null}
            </>
          )}
        </div>
      ) : null}

      {mgmtOpenForId !== null ? (
        <div
          className="cartera-modal-backdrop"
          role="presentation"
          onMouseDown={() => !mgmtBusy && setMgmtOpenForId(null)}
        >
          <div className="cartera-modal card" role="dialog" aria-modal="true" onMouseDown={(e) => e.stopPropagation()}>
            <h2 className="cartera-form__title">Agregar gestión (operación #{mgmtOpenForId})</h2>
            <form className="cartera-form" onSubmit={onSubmitMgmtEvent}>
              <div className="cartera-grid">
                <label className="cartera-field">
                  <span>Fecha</span>
                  <input type="date" value={mgmtDate} onChange={(e) => setMgmtDate(e.target.value)} />
                </label>
                <label className="cartera-field">
                  <span>Tipo</span>
                  <select
                    value={mgmtEventType}
                    onChange={(e) =>
                      setMgmtEventType(e.target.value as typeof mgmtEventType)
                    }
                  >
                    <option value="note">note</option>
                    <option value="adjustment">adjustment</option>
                    <option value="roll">roll</option>
                    <option value="partial_close">partial_close</option>
                    <option value="full_close">full_close</option>
                    <option value="open">open</option>
                  </select>
                </label>
                <label className="cartera-field cartera-field--full">
                  <span>Descripción</span>
                  <input value={mgmtDescription} onChange={(e) => setMgmtDescription(e.target.value)} placeholder="opcional" />
                </label>
                <label className="cartera-field">
                  <span>Débito / crédito (USD)</span>
                  <input value={mgmtDebitCredit} onChange={(e) => setMgmtDebitCredit(e.target.value)} inputMode="decimal" placeholder="opcional" />
                </label>
              </div>
              <div className="cartera-modal-actions">
                <button type="button" className="cartera-btn" onClick={() => setMgmtOpenForId(null)} disabled={mgmtBusy}>
                  Cancelar
                </button>
                <button type="submit" className="cartera-btn cartera-btn--primary" disabled={mgmtBusy}>
                  {mgmtBusy ? "Guardando…" : "Guardar evento"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      <CarteraStrategyManagementModal
        open={strategyMgmt !== null}
        onClose={() => setStrategyMgmt(null)}
        mode={strategyMgmt?.mode ?? null}
        position={strategyMgmt?.row ?? null}
        onSaved={onStrategyMgmtSaved}
        onError={(m) => setErr(m)}
      />

      <CarteraSellModal
        open={sellTarget !== null}
        position={sellTarget}
        onClose={() => setSellTarget(null)}
        onSuccess={onSellModalSuccess}
        onError={(m) => setErr(m)}
      />
    </>
  );
}
