import { FormEvent, useEffect, useId, useMemo, useRef, useState } from "react";
import type { PortfolioAssetType } from "@/services/api";
import { createPortfolioPosition, fetchPortfolioTickersAutocomplete } from "@/services/api";
import {
  computeBuyValidation,
  formatPriceInputArs,
  formatPriceInputUsd,
  parsePositiveNumber,
  todayIsoDate,
} from "./carteraFormUtils";

export type CarteraBuyPreset = {
  ticker: string;
  assetType: PortfolioAssetType;
  suggestedPriceArs?: number | null;
  suggestedPriceUsd?: number | null;
};

export type CarteraBuyModalProps = {
  open: boolean;
  onClose: () => void;
  onSuccess?: () => void | Promise<void>;
  onError?: (message: string) => void;
  preset: CarteraBuyPreset | null;
  /** Si true, no se puede cambiar el tipo de activo (desde radar). */
  lockAssetType?: boolean;
};

export function CarteraBuyModal({
  open,
  onClose,
  onSuccess,
  onError,
  preset,
  lockAssetType = false,
}: CarteraBuyModalProps) {
  const datalistId = useId();
  const [busy, setBusy] = useState(false);
  const [ticker, setTicker] = useState("");
  const [assetType, setAssetType] = useState<PortfolioAssetType>("USA");
  const [quantity, setQuantity] = useState("1");
  const [buyDate, setBuyDate] = useState(todayIsoDate());
  const [buyPriceArs, setBuyPriceArs] = useState("");
  const [buyPriceUsd, setBuyPriceUsd] = useState("");
  const [buyTcMep, setBuyTcMep] = useState("");
  const [buyNotes, setBuyNotes] = useState("");
  const [tickerSug, setTickerSug] = useState<string[]>([]);
  const [tickerSugError, setTickerSugError] = useState(false);
  const tickerAbortRef = useRef<AbortController | null>(null);
  const tickerReqSeq = useRef(0);

  useEffect(() => {
    if (!open || !preset) return;
    setTicker(preset.ticker.trim());
    setAssetType(preset.assetType);
    setQuantity("1");
    setBuyDate(todayIsoDate());
    setBuyPriceArs(formatPriceInputArs(preset.suggestedPriceArs));
    setBuyPriceUsd(formatPriceInputUsd(preset.suggestedPriceUsd));
    setBuyTcMep("");
    setBuyNotes("");
    setTickerSug([]);
    setTickerSugError(false);
  }, [open, preset]);

  useEffect(() => {
    if (!open) return;
    const q = ticker.trim();
    if (!q) {
      setTickerSug([]);
      setTickerSugError(false);
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
          if (tickerReqSeq.current !== seq) return;
          setTickerSug(items);
          setTickerSugError(false);
        } catch (e) {
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
  }, [open, ticker, assetType]);

  useEffect(() => {
    return () => {
      try {
        tickerAbortRef.current?.abort();
      } catch {
        // ignore
      }
    };
  }, []);

  const buyValidation = useMemo(
    () => computeBuyValidation(ticker, buyDate, quantity, assetType, buyPriceArs, buyPriceUsd, buyTcMep),
    [ticker, buyDate, quantity, assetType, buyPriceArs, buyPriceUsd, buyTcMep],
  );

  async function onSubmitBuy(ev: FormEvent) {
    ev.preventDefault();
    if (!buyValidation.valid) return;
    setBusy(true);
    try {
      const q = parsePositiveNumber(quantity);
      if (q === null) {
        throw new Error("Cantidad inválida");
      }
      const parseOpt = (s: string) => {
        const t0 = s.trim();
        if (!t0) return null;
        const n = Number(t0.replace(",", "."));
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
      await onSuccess?.();
      onClose();
    } catch (e) {
      onError?.(e instanceof Error ? e.message : "Error al guardar");
    } finally {
      setBusy(false);
    }
  }

  if (!open || !preset) {
    return null;
  }

  return (
    <div className="cartera-modal-backdrop" role="presentation" onMouseDown={() => !busy && onClose()}>
      <div className="cartera-modal card" role="dialog" aria-modal="true" onMouseDown={(e) => e.stopPropagation()}>
        <h2 className="cartera-form__title">Registrar compra</h2>
        <form className="cartera-form" onSubmit={onSubmitBuy}>
          <div className="cartera-grid">
            <label className={`cartera-field${buyValidation.inv.ticker ? " cartera-field--invalid" : ""}`}>
              <span>Ticker</span>
              <input
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
                placeholder="ej. AAPL"
                list={datalistId}
                autoComplete="off"
              />
              <datalist id={datalistId}>
                {tickerSug.map((x) => (
                  <option key={x} value={x} />
                ))}
              </datalist>
              {tickerSugError ? <small className="cartera-hint">Sugerencias no disponibles (podés seguir escribiendo).</small> : null}
            </label>
            <label className="cartera-field">
              <span>Tipo de activo</span>
              {lockAssetType ? (
                <input readOnly value={assetType} aria-readonly />
              ) : (
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
              )}
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
                <span>Precio compra USD</span>
                <input
                  value={buyPriceUsd}
                  onChange={(e) => setBuyPriceUsd(e.target.value)}
                  inputMode="decimal"
                  placeholder={assetType === "CEDEAR" ? "precio CEDEAR USD (cable), obligatorio" : "obligatorio"}
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
            USA: precio en USD. Argentina: precio en ARS + TC MEP. CEDEAR: precio en USD + TC MEP de referencia.
          </p>
          {!buyValidation.valid && buyValidation.message ? (
            <div className="cartera-validation-hint" role="status">
              {buyValidation.message}
            </div>
          ) : null}
          <div className="cartera-modal-actions">
            <button type="button" className="cartera-btn" onClick={onClose} disabled={busy}>
              Cancelar
            </button>
            <button type="submit" className="cartera-btn cartera-btn--primary" disabled={busy || !buyValidation.valid}>
              {busy ? "Guardando…" : "Guardar compra"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
