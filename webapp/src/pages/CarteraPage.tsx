import { FormEvent, useCallback, useEffect, useState } from "react";
import type { PortfolioAssetType, PortfolioHistoryRow, PortfolioOpenRow } from "@/services/api";
import {
  closePortfolioPosition,
  createPortfolioPosition,
  fetchPortfolioHistory,
  fetchPortfolioOpen,
} from "@/services/api";

function fmtNum(n: number | null | undefined, maxFrac = 4): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString("es-AR", { maximumFractionDigits: maxFrac });
}

function todayIsoDate(): string {
  return new Date().toISOString().slice(0, 10);
}

export function CarteraPage() {
  const [tab, setTab] = useState<"compra" | "cartera" | "historial">("compra");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [openRows, setOpenRows] = useState<PortfolioOpenRow[]>([]);
  const [histRows, setHistRows] = useState<PortfolioHistoryRow[]>([]);

  const [ticker, setTicker] = useState("");
  const [assetType, setAssetType] = useState<PortfolioAssetType>("USA");
  const [quantity, setQuantity] = useState("1");
  const [buyDate, setBuyDate] = useState(todayIsoDate());
  const [buyPriceArs, setBuyPriceArs] = useState("");
  const [buyPriceUsd, setBuyPriceUsd] = useState("");
  const [buyNotes, setBuyNotes] = useState("");

  const [sellTarget, setSellTarget] = useState<PortfolioOpenRow | null>(null);
  const [sellDate, setSellDate] = useState(todayIsoDate());
  const [sellPriceArs, setSellPriceArs] = useState("");
  const [sellPriceUsd, setSellPriceUsd] = useState("");
  const [sellNotes, setSellNotes] = useState("");
  const [sellCedearUsd, setSellCedearUsd] = useState("");
  const [sellUsa, setSellUsa] = useState("");
  const [sellGap, setSellGap] = useState("");

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

  async function onSubmitBuy(ev: FormEvent) {
    ev.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const q = Number(quantity.replace(",", "."));
      if (!Number.isFinite(q) || q <= 0) {
        throw new Error("Cantidad inválida");
      }
      const parseOpt = (s: string) => {
        const t = s.trim();
        if (!t) return null;
        const n = Number(t.replace(",", "."));
        return Number.isFinite(n) ? n : null;
      };
      await createPortfolioPosition({
        ticker: ticker.trim(),
        asset_type: assetType,
        quantity: q,
        buy_date: buyDate,
        buy_price_ars: parseOpt(buyPriceArs),
        buy_price_usd: parseOpt(buyPriceUsd),
        notes: buyNotes.trim() || null,
      });
      setTicker("");
      setQuantity("1");
      setBuyNotes("");
      setTab("cartera");
      await loadOpen();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error al guardar");
    } finally {
      setBusy(false);
    }
  }

  function openSellModal(row: PortfolioOpenRow) {
    setSellTarget(row);
    setSellDate(todayIsoDate());
    setSellPriceArs("");
    setSellPriceUsd("");
    setSellNotes("");
    setSellCedearUsd("");
    setSellUsa("");
    setSellGap("");
    setErr(null);
  }

  async function onSubmitSell(ev: FormEvent) {
    ev.preventDefault();
    if (!sellTarget) return;
    setErr(null);
    setBusy(true);
    try {
      const parseOpt = (s: string) => {
        const t = s.trim();
        if (!t) return undefined;
        const n = Number(t.replace(",", "."));
        if (!Number.isFinite(n)) return undefined;
        return n;
      };
      await closePortfolioPosition(sellTarget.id, {
        sell_date: sellDate,
        sell_price_ars: parseOpt(sellPriceArs),
        sell_price_usd: parseOpt(sellPriceUsd),
        sell_notes: sellNotes.trim() || null,
        sell_price_cedear_usd: parseOpt(sellCedearUsd),
        sell_price_usa: parseOpt(sellUsa),
        sell_gap: parseOpt(sellGap),
      });
      setSellTarget(null);
      await loadOpen();
      await loadHist();
      setTab("historial");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error al cerrar posición");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1 className="page-title">Cartera</h1>
      <p className="page-desc">Compras manuales, seguimiento y cierre total. Persistencia en SQLite.</p>

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
            <label className="cartera-field">
              <span>Ticker</span>
              <input value={ticker} onChange={(e) => setTicker(e.target.value)} required placeholder="ej. AAPL" />
            </label>
            <label className="cartera-field">
              <span>Tipo de activo</span>
              <select value={assetType} onChange={(e) => setAssetType(e.target.value as PortfolioAssetType)}>
                <option value="USA">USA</option>
                <option value="Argentina">Argentina</option>
                <option value="CEDEAR">CEDEAR</option>
              </select>
            </label>
            <label className="cartera-field">
              <span>Cantidad</span>
              <input value={quantity} onChange={(e) => setQuantity(e.target.value)} required inputMode="decimal" />
            </label>
            <label className="cartera-field">
              <span>Fecha de compra</span>
              <input type="date" value={buyDate} onChange={(e) => setBuyDate(e.target.value)} required />
            </label>
            <label className="cartera-field">
              <span>Precio compra ARS</span>
              <input value={buyPriceArs} onChange={(e) => setBuyPriceArs(e.target.value)} inputMode="decimal" placeholder="opcional" />
            </label>
            <label className="cartera-field">
              <span>Precio compra USD</span>
              <input value={buyPriceUsd} onChange={(e) => setBuyPriceUsd(e.target.value)} inputMode="decimal" placeholder="opcional" />
            </label>
            <label className="cartera-field cartera-field--full">
              <span>Notas</span>
              <textarea value={buyNotes} onChange={(e) => setBuyNotes(e.target.value)} rows={2} placeholder="opcional" />
            </label>
          </div>
          <p className="cartera-hint">
            Al guardar, el backend intenta capturar score y señal del último export radar; en CEDEAR también precio cable / USA y gap si el snapshot está disponible.
          </p>
          <button type="submit" className="cartera-btn cartera-btn--primary" disabled={busy}>
            {busy ? "Guardando…" : "Guardar compra"}
          </button>
        </form>
      ) : null}

      {tab === "cartera" ? (
        <div className="card cartera-table-wrap">
          <h2 className="cartera-form__title">Posiciones abiertas</h2>
          {openRows.length === 0 ? (
            <p className="cartera-empty">No hay posiciones abiertas.</p>
          ) : (
            <div className="table-scroll">
              <table className="cartera-table">
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th>Cant.</th>
                    <th>Compra</th>
                    <th>Precio ARS</th>
                    <th>Precio USD</th>
                    <th>Score compra</th>
                    <th>Señal compra</th>
                    <th>Score actual</th>
                    <th>Señal actual</th>
                    <th>Precio ARS act.</th>
                    <th>Precio USD act.</th>
                    <th>Retorno %</th>
                    <th>Días</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {openRows.map((r) => (
                    <tr key={r.id}>
                      <td className="nowrap">{r.ticker}</td>
                      <td>{fmtNum(r.quantity, 6)}</td>
                      <td className="nowrap">{r.buy_date}</td>
                      <td>{fmtNum(r.buy_price_ars, 2)}</td>
                      <td>{fmtNum(r.buy_price_usd, 4)}</td>
                      <td>{fmtNum(r.score_at_buy, 2)}</td>
                      <td>{r.signalstate_at_buy ?? "—"}</td>
                      <td>{fmtNum(r.current_score, 2)}</td>
                      <td>{r.current_signalstate ?? "—"}</td>
                      <td>{fmtNum(r.current_price_ars, 2)}</td>
                      <td>{fmtNum(r.current_price_usd, 4)}</td>
                      <td>{fmtNum(r.return_pct, 2)}%</td>
                      <td>{r.days_in_position ?? "—"}</td>
                      <td>
                        <button type="button" className="cartera-btn cartera-btn--danger" onClick={() => openSellModal(r)}>
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
          {histRows.length === 0 ? (
            <p className="cartera-empty">No hay posiciones cerradas.</p>
          ) : (
            <div className="table-scroll">
              <table className="cartera-table">
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th>Compra</th>
                    <th>Venta</th>
                    <th>Precio ARS compra</th>
                    <th>Precio USD compra</th>
                    <th>Precio ARS venta</th>
                    <th>Precio USD venta</th>
                    <th>Score compra</th>
                    <th>Score venta</th>
                    <th>Señal compra</th>
                    <th>Señal venta</th>
                    <th>Retorno real. %</th>
                    <th>Días tenencia</th>
                  </tr>
                </thead>
                <tbody>
                  {histRows.map((r) => (
                    <tr key={r.id}>
                      <td className="nowrap">{r.ticker}</td>
                      <td className="nowrap">{r.buy_date ?? "—"}</td>
                      <td className="nowrap">{r.sell_date ?? "—"}</td>
                      <td>{fmtNum(r.buy_price_ars, 2)}</td>
                      <td>{fmtNum(r.buy_price_usd, 4)}</td>
                      <td>{fmtNum(r.sell_price_ars, 2)}</td>
                      <td>{fmtNum(r.sell_price_usd, 4)}</td>
                      <td>{fmtNum(r.score_at_buy, 2)}</td>
                      <td>{fmtNum(r.score_at_sell, 2)}</td>
                      <td>{r.signalstate_at_buy ?? "—"}</td>
                      <td>{r.signalstate_at_sell ?? "—"}</td>
                      <td>{fmtNum(r.realized_return_pct, 2)}%</td>
                      <td>{r.holding_days ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : null}

      {sellTarget ? (
        <div className="cartera-modal-backdrop" role="presentation" onMouseDown={() => !busy && setSellTarget(null)}>
          <div className="cartera-modal card" role="dialog" aria-modal="true" onMouseDown={(e) => e.stopPropagation()}>
            <h2 className="cartera-form__title">
              Vender {sellTarget.ticker} ({sellTarget.asset_type})
            </h2>
            <form className="cartera-form" onSubmit={onSubmitSell}>
              <div className="cartera-grid">
                <label className="cartera-field">
                  <span>Fecha de venta</span>
                  <input type="date" value={sellDate} onChange={(e) => setSellDate(e.target.value)} required />
                </label>
                <label className="cartera-field">
                  <span>Precio venta ARS</span>
                  <input value={sellPriceArs} onChange={(e) => setSellPriceArs(e.target.value)} inputMode="decimal" />
                </label>
                <label className="cartera-field">
                  <span>Precio venta USD</span>
                  <input value={sellPriceUsd} onChange={(e) => setSellPriceUsd(e.target.value)} inputMode="decimal" />
                </label>
                {sellTarget.asset_type === "CEDEAR" ? (
                  <>
                    <label className="cartera-field">
                      <span>Precio CEDEAR USD (cable)</span>
                      <input value={sellCedearUsd} onChange={(e) => setSellCedearUsd(e.target.value)} inputMode="decimal" placeholder="opcional; si vacío usa snapshot" />
                    </label>
                    <label className="cartera-field">
                      <span>Precio acción USA</span>
                      <input value={sellUsa} onChange={(e) => setSellUsa(e.target.value)} inputMode="decimal" placeholder="opcional" />
                    </label>
                    <label className="cartera-field">
                      <span>Gap %</span>
                      <input value={sellGap} onChange={(e) => setSellGap(e.target.value)} inputMode="decimal" placeholder="opcional" />
                    </label>
                  </>
                ) : null}
                <label className="cartera-field cartera-field--full">
                  <span>Notas</span>
                  <textarea value={sellNotes} onChange={(e) => setSellNotes(e.target.value)} rows={2} />
                </label>
              </div>
              <div className="cartera-modal-actions">
                <button type="button" className="cartera-btn" onClick={() => setSellTarget(null)} disabled={busy}>
                  Cancelar
                </button>
                <button type="submit" className="cartera-btn cartera-btn--primary" disabled={busy}>
                  {busy ? "Guardando…" : "Confirmar venta"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </>
  );
}
