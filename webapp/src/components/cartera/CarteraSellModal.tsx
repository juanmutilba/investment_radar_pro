import { FormEvent, useEffect, useMemo, useState } from "react";
import type { PortfolioOpenRow } from "@/services/api";
import { closePortfolioPosition } from "@/services/api";
import { computeSellValidation, todayIsoDate } from "./carteraFormUtils";

export type CarteraSellModalProps = {
  open: boolean;
  position: PortfolioOpenRow | null;
  onClose: () => void;
  /** Tras cerrar posición OK (p. ej. refrescar tablas). */
  onSuccess?: () => void | Promise<void>;
  onError?: (message: string) => void;
  /** Prefill opcional desde fila del radar */
  hintSellArs?: string;
  hintSellUsd?: string;
  hintSellCedearUsd?: string;
};

export function CarteraSellModal({
  open,
  position,
  onClose,
  onSuccess,
  onError,
  hintSellArs = "",
  hintSellUsd = "",
  hintSellCedearUsd = "",
}: CarteraSellModalProps) {
  const [busy, setBusy] = useState(false);
  const [sellDate, setSellDate] = useState(todayIsoDate());
  const [sellPriceArs, setSellPriceArs] = useState("");
  const [sellPriceUsd, setSellPriceUsd] = useState("");
  const [sellNotes, setSellNotes] = useState("");
  const [sellCedearUsd, setSellCedearUsd] = useState("");
  const [sellTcMep, setSellTcMep] = useState("");

  useEffect(() => {
    if (!open || !position) return;
    setSellDate(todayIsoDate());
    setSellPriceArs(hintSellArs);
    setSellPriceUsd(hintSellUsd);
    setSellCedearUsd(hintSellCedearUsd);
    setSellNotes("");
    setSellTcMep("");
  }, [open, position?.id, hintSellArs, hintSellUsd, hintSellCedearUsd]);

  const sellValidation = useMemo(
    () => computeSellValidation(position, sellDate, sellPriceArs, sellPriceUsd, sellCedearUsd, sellTcMep),
    [position, sellDate, sellPriceArs, sellPriceUsd, sellCedearUsd, sellTcMep],
  );

  async function onSubmitSell(ev: FormEvent) {
    ev.preventDefault();
    if (!position) return;
    if (!sellValidation.valid) return;
    setBusy(true);
    try {
      const parseOpt = (s: string) => {
        const t = s.trim();
        if (!t) return undefined;
        const n = Number(t.replace(",", "."));
        if (!Number.isFinite(n)) return undefined;
        return n;
      };
      const cedearUsd = parseOpt(sellCedearUsd);
      await closePortfolioPosition(position.id, {
        sell_date: sellDate,
        sell_price_ars: parseOpt(sellPriceArs),
        sell_price_usd:
          position.asset_type === "CEDEAR" ? cedearUsd : parseOpt(sellPriceUsd),
        sell_notes: sellNotes.trim() || null,
        tc_mep_venta: position.asset_type === "USA" ? undefined : parseOpt(sellTcMep) ?? undefined,
      });
      await onSuccess?.();
      onClose();
    } catch (e) {
      onError?.(e instanceof Error ? e.message : "Error al cerrar posición");
    } finally {
      setBusy(false);
    }
  }

  if (!open || !position) {
    return null;
  }

  return (
    <div className="cartera-modal-backdrop" role="presentation" onMouseDown={() => !busy && onClose()}>
      <div className="cartera-modal card" role="dialog" aria-modal="true" onMouseDown={(e) => e.stopPropagation()}>
        <h2 className="cartera-form__title">
          Vender {position.ticker} ({position.asset_type})
        </h2>
        <form className="cartera-form" onSubmit={onSubmitSell}>
          <div className="cartera-grid">
            <label className={`cartera-field${sellValidation.inv.date ? " cartera-field--invalid" : ""}`}>
              <span>Fecha de venta</span>
              <input type="date" value={sellDate} onChange={(e) => setSellDate(e.target.value)} />
            </label>
            {position.asset_type === "Argentina" ? (
              <label className={`cartera-field${sellValidation.inv.price ? " cartera-field--invalid" : ""}`}>
                <span>Precio venta ARS</span>
                <input
                  value={sellPriceArs}
                  onChange={(e) => setSellPriceArs(e.target.value)}
                  inputMode="decimal"
                  placeholder="obligatorio"
                />
              </label>
            ) : null}
            {position.asset_type === "USA" ? (
              <label className={`cartera-field${sellValidation.inv.price ? " cartera-field--invalid" : ""}`}>
                <span>Precio venta USD</span>
                <input
                  value={sellPriceUsd}
                  onChange={(e) => setSellPriceUsd(e.target.value)}
                  inputMode="decimal"
                  placeholder="obligatorio"
                />
              </label>
            ) : null}
            {position.asset_type === "CEDEAR" ? (
              <label className={`cartera-field${sellValidation.inv.price ? " cartera-field--invalid" : ""}`}>
                <span>Precio venta USD (ref USA)</span>
                <input
                  value={sellCedearUsd}
                  onChange={(e) => setSellCedearUsd(e.target.value)}
                  inputMode="decimal"
                  placeholder="obligatorio"
                />
              </label>
            ) : null}
            {position.asset_type === "Argentina" || position.asset_type === "CEDEAR" ? (
              <label className={`cartera-field${sellValidation.inv.mep ? " cartera-field--invalid" : ""}`}>
                <span>TC MEP venta (ARS por USD)</span>
                <input value={sellTcMep} onChange={(e) => setSellTcMep(e.target.value)} inputMode="decimal" placeholder="obligatorio" />
              </label>
            ) : null}
            <label className="cartera-field cartera-field--full">
              <span>Notas</span>
              <textarea value={sellNotes} onChange={(e) => setSellNotes(e.target.value)} rows={2} />
            </label>
          </div>
          {!sellValidation.valid && sellValidation.message ? (
            <div className="cartera-validation-hint" role="status">
              {sellValidation.message}
            </div>
          ) : null}
          <div className="cartera-modal-actions">
            <button type="button" className="cartera-btn" onClick={onClose} disabled={busy}>
              Cancelar
            </button>
            <button type="submit" className="cartera-btn cartera-btn--primary" disabled={busy || !sellValidation.valid}>
              {busy ? "Guardando…" : "Confirmar venta"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
