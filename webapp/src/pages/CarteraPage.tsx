import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CarteraSellModal } from "@/components/cartera/CarteraSellModal";
import { usePortfolioOpenPositions } from "@/context/PortfolioOpenPositionsContext";
import {
  computeBuyValidation,
  parsePositiveNumber,
  todayIsoDate,
  type BuyInvalidFlags,
} from "@/components/cartera/carteraFormUtils";
import type { PortfolioAssetType, PortfolioHistoryRow, PortfolioOpenRow } from "@/services/api";
import {
  createPortfolioPosition,
  fetchPortfolioHistory,
  fetchPortfolioOpen,
  fetchPortfolioTickersAutocomplete,
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

export function CarteraPage() {
  const { refresh: refreshOpenPositionsIndex } = usePortfolioOpenPositions();
  const [tab, setTab] = useState<"compra" | "cartera" | "historial">("compra");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [openRows, setOpenRows] = useState<PortfolioOpenRow[]>([]);
  const [histRows, setHistRows] = useState<PortfolioHistoryRow[]>([]);

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

  const loadOpen = useCallback(async () => {
    const rows = await fetchPortfolioOpen();
    setOpenRows(rows);
  }, []);

  const loadHist = useCallback(async () => {
    const rows = await fetchPortfolioHistory();
    setHistRows(rows);
  }, []);

  useEffect(() => {
    if (tab !== "cartera" && tab !== "historial") return;
    setErr(null);
    void (async () => {
      try {
        if (tab === "cartera") await loadOpen();
        else await loadHist();
      } catch (e) {
        setErr(e instanceof Error ? e.message : "Error al cargar cartera");
      }
    })();
  }, [tab, loadOpen, loadHist]);

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

  return (
    <>
      <h1 className="page-title">Cartera</h1>
      <p className="page-desc">
        Compras manuales, seguimiento y cierre total. Persistencia en SQLite. En CEDEAR, precios y retornos en USD
        usan la acción subyacente listada en USA (no el precio local ni la línea CCL).
      </p>

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
        <div className="card cartera-table-wrap">
          <h2 className="cartera-form__title">Posiciones abiertas</h2>
          {openRows.some((r) => r.asset_type === "CEDEAR") ? (
            <p className="cartera-hint" style={{ marginTop: 0 }}>
              Filas CEDEAR: &quot;precio compra&quot; y &quot;precio actual&quot; en USD (USA) = subyacente; no es cotización cable CCL.
            </p>
          ) : null}
          {openRows.length === 0 ? (
            <p className="cartera-empty">No hay posiciones abiertas.</p>
          ) : (
            <div className="table-scroll">
              <table className="cartera-table">
                <thead>
                  <tr>
                    <th>ticker</th>
                    <th>tipo</th>
                    <th>f compra</th>
                    <th>señal compra</th>
                    <th>señal actual</th>
                    <th>score compra</th>
                    <th>score actual</th>
                    <th>alerta compra</th>
                    <th>cant compra</th>
                    <th title="CEDEAR: USD del subyacente USA. Argentina: ARS. USA: USD.">
                      precio compra
                    </th>
                    <th title="CEDEAR: USD mercado del subyacente USA (no CCL local). USA: USD. Argentina: ARS.">
                      precio actual
                    </th>
                    <th title="CEDEAR y USA: % vs precio compra en USD (misma moneda / referencia).">retorno</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {openRows.map((r) => (
                    <tr key={r.id}>
                      <td className="nowrap">{r.ticker}</td>
                      <td className="nowrap table-cell--nowrap cartera-type-cell" title={r.asset_type}>
                        {fmtAssetTypeShort(r.asset_type)}
                      </td>
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
                        <button type="button" className="cartera-btn cartera-btn--sell" onClick={() => openSellModal(r)}>
                          Vender
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
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
            <div className="table-scroll">
              <table className="cartera-table">
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th>Tipo</th>
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
                  {histRows.map((r) => (
                    <tr key={r.id}>
                      <td className="nowrap">{r.ticker}</td>
                      <td className="nowrap table-cell--nowrap cartera-type-cell" title={r.asset_type}>
                        {fmtAssetTypeShort(r.asset_type)}
                      </td>
                      <td className="nowrap">{r.buy_date ?? "—"}</td>
                      <td className="nowrap">{r.sell_date ?? "—"}</td>
                      <td>{fmtNum(r.buy_price_ars, 2)}</td>
                      <td title={r.asset_type === "CEDEAR" ? "Subyacente USA" : undefined}>{histUsdCell(r, r.buy_price_usd)}</td>
                      <td>{fmtNum(r.sell_price_ars, 2)}</td>
                      <td title={r.asset_type === "CEDEAR" ? "Subyacente USA al cierre" : undefined}>{histUsdCell(r, r.sell_price_usd)}</td>
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
          )}
        </div>
      ) : null}

      <CarteraSellModal
        open={sellTarget !== null}
        position={sellTarget}
        onClose={() => setSellTarget(null)}
        onSuccess={async () => {
          await loadOpen();
          await loadHist();
          void refreshOpenPositionsIndex({ silent: true });
          setTab("historial");
        }}
        onError={(m) => setErr(m)}
      />
    </>
  );
}
