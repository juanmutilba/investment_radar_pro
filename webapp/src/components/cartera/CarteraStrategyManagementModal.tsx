import { FormEvent, useEffect, useMemo, useState } from "react";
import type { PortfolioManagementEvent, PortfolioOpenRow } from "@/services/api";
import { appendPortfolioTradeEvent, closePortfolioTrade } from "@/services/api";
import { todayIsoDate } from "./carteraFormUtils";

export type CarteraStrategyMgmtMode = "adjustment" | "partial_close" | "full_close";

export type CarteraStrategyManagementModalProps = {
  open: boolean;
  onClose: () => void;
  mode: CarteraStrategyMgmtMode | null;
  position: PortfolioOpenRow | null;
  onSaved: () => void | Promise<void>;
  onError: (message: string) => void;
};

function parseOptNum(s: string): number | null {
  const t = s.trim().replace(",", ".");
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

function modeTitle(mode: CarteraStrategyMgmtMode): string {
  if (mode === "adjustment") return "Agregar ajuste";
  if (mode === "partial_close") return "Cerrar parcial";
  return "Cerrar total";
}

function eventTypeLabelEs(mode: CarteraStrategyMgmtMode): string {
  if (mode === "adjustment") return "Ajuste (adjustment)";
  if (mode === "partial_close") return "Cierre parcial (partial_close)";
  return "Cierre total (full_close)";
}

function modeHint(mode: CarteraStrategyMgmtMode): string {
  if (mode === "adjustment") return "Registrá un ajuste de posición (roll, cambio de prima, comisiones, etc.).";
  if (mode === "partial_close") return "Registrá un cierre parcial; la posición sigue abierta en cartera.";
  return "Se registra el evento full_close y se marca la posición como cerrada en cartera (sell_date = fecha del evento).";
}

export function CarteraStrategyManagementModal({
  open,
  onClose,
  mode,
  position,
  onSaved,
  onError,
}: CarteraStrategyManagementModalProps) {
  const [busy, setBusy] = useState(false);
  const [evDate, setEvDate] = useState(todayIsoDate());
  const [description, setDescription] = useState("");
  const [debitCredit, setDebitCredit] = useState("");
  const [underlyingPrice, setUnderlyingPrice] = useState("");
  const [iv, setIv] = useState("");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    if (!open || !position || !mode) return;
    setEvDate(todayIsoDate());
    setDescription("");
    setDebitCredit("");
    setUnderlyingPrice(
      position.opening_underlying_price != null && Number.isFinite(position.opening_underlying_price)
        ? String(position.opening_underlying_price)
        : "",
    );
    setIv(position.opening_iv != null && Number.isFinite(position.opening_iv) ? String(position.opening_iv) : "");
    setNotes("");
  }, [open, position?.id, mode]);

  const title = useMemo(() => (mode ? modeTitle(mode) : "Gestión"), [mode]);

  async function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    if (!position || !mode) return;
    const dc = parseOptNum(debitCredit);
    if (debitCredit.trim() !== "" && dc === null) {
      onError("Débito / crédito: ingresá un número válido o dejá vacío.");
      return;
    }
    const up = parseOptNum(underlyingPrice);
    if (underlyingPrice.trim() !== "" && up === null) {
      onError("Precio subyacente: número inválido.");
      return;
    }
    const ivN = parseOptNum(iv);
    if (iv.trim() !== "" && ivN === null) {
      onError("IV: número inválido.");
      return;
    }
    const payload: PortfolioManagementEvent = {
      date: evDate.trim().slice(0, 10),
      event_type: mode,
      description: description.trim(),
      debit_credit: dc,
      underlying_price: up,
      iv: ivN,
      notes: notes.trim() || null,
    };
    setBusy(true);
    try {
      await appendPortfolioTradeEvent(position.id, payload);
      if (mode === "full_close") {
        await closePortfolioTrade(position.id, {
          sell_date: payload.date,
          sell_notes: notes.trim() || description.trim() || null,
          sell_price_ars: null,
          sell_price_usd: null,
          tc_mep_venta: null,
        });
      }
      await onSaved();
      onClose();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error al guardar");
    } finally {
      setBusy(false);
    }
  }

  if (!open || !position || !mode) return null;

  return (
    <div className="cartera-modal-backdrop" role="presentation" onMouseDown={() => !busy && onClose()}>
      <div
        className="cartera-modal card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cartera-strategy-mgmt-title"
        onMouseDown={(e) => e.stopPropagation()}
        style={{ maxWidth: "min(36rem, 96vw)" }}
      >
        <h2 id="cartera-strategy-mgmt-title" className="cartera-form__title">
          {title} — {position.ticker}
        </h2>
        <p className="cartera-hint" style={{ marginTop: 0 }}>
          {modeHint(mode)} Débito (pagás) = negativo; crédito (cobrás) = positivo.
        </p>
        <form className="cartera-form" onSubmit={(e) => void onSubmit(e)}>
          <div className="cartera-grid">
            <label className="cartera-field">
              <span>Fecha</span>
              <input type="date" value={evDate} onChange={(e) => setEvDate(e.target.value)} disabled={busy} required />
            </label>
            <label className="cartera-field">
              <span>Tipo de evento</span>
              <input
                value={eventTypeLabelEs(mode)}
                readOnly
                disabled
                className="cartera-input-readonly"
                title="Fijado por la acción elegida"
              />
            </label>
            <label className="cartera-field cartera-field--full">
              <span>Descripción</span>
              <input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Ej. Roll call, comisión broker…"
                disabled={busy}
              />
            </label>
            <label className="cartera-field">
              <span>Débito / crédito (flujo de caja)</span>
              <input
                value={debitCredit}
                onChange={(e) => setDebitCredit(e.target.value)}
                inputMode="decimal"
                placeholder="negativo = débito, positivo = crédito"
                disabled={busy}
              />
            </label>
            <label className="cartera-field">
              <span>Precio subyacente</span>
              <input value={underlyingPrice} onChange={(e) => setUnderlyingPrice(e.target.value)} inputMode="decimal" disabled={busy} />
            </label>
            <label className="cartera-field">
              <span>IV</span>
              <input value={iv} onChange={(e) => setIv(e.target.value)} inputMode="decimal" placeholder="opcional" disabled={busy} />
            </label>
            <label className="cartera-field cartera-field--full">
              <span>Nota</span>
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} disabled={busy} placeholder="opcional" />
            </label>
          </div>
          <div className="cartera-modal-actions">
            <button type="button" className="cartera-btn" onClick={onClose} disabled={busy}>
              Cancelar
            </button>
            <button type="submit" className="cartera-btn cartera-btn--primary" disabled={busy}>
              {busy ? "Guardando…" : "Guardar"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
