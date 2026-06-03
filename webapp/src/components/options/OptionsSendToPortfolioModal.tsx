import { FormEvent, useEffect, useRef, useState } from "react";
import type { PortfolioManagementEvent, PortfolioTradeCreatePayload, PortfolioTradeLeg } from "@/services/api";

export type OptionsSendToPortfolioModalProps = {
  open: boolean;
  onClose: () => void;
  onConfirm: (payload: PortfolioTradeCreatePayload) => Promise<void>;
  busy: boolean;
  strategyLabel: string;
  underlyingLabel: string;
  expiryLabel: string;
  /** Snapshot al abrir (1 contrato y montos base). */
  initialPayload: PortfolioTradeCreatePayload | null;
  /** Tamaño de lote por contrato (p. ej. 100 acciones). */
  optionLotSize: number;
};

function clonePayload(p: PortfolioTradeCreatePayload): PortfolioTradeCreatePayload {
  return JSON.parse(JSON.stringify(p)) as PortfolioTradeCreatePayload;
}

function parseOptionalNumber(s: string): number | null {
  const t = s.trim().replace(",", ".");
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

function parseRequiredNumber(s: string): number | null {
  const n = parseOptionalNumber(s);
  return n;
}

function parseContracts(s: string): number {
  const t = s.trim().replace(",", ".");
  if (!t) return 1;
  const n = Number(t);
  if (!Number.isFinite(n) || n <= 0) return 1;
  return Math.floor(n);
}

function applyContractQuantityToLegs(
  legs: PortfolioTradeLeg[] | undefined,
  contracts: number,
  optionLotSize: number,
): PortfolioTradeLeg[] {
  const q = Math.max(1e-6, contracts);
  return (legs ?? []).map((leg) => {
    if (leg.leg_type === "stock") {
      return { ...leg, quantity: optionLotSize * q };
    }
    return { ...leg, quantity: q };
  });
}

export function OptionsSendToPortfolioModal({
  open,
  onClose,
  onConfirm,
  busy,
  strategyLabel,
  underlyingLabel,
  expiryLabel,
  initialPayload,
  optionLotSize,
}: OptionsSendToPortfolioModalProps) {
  const snapshotRef = useRef<PortfolioTradeCreatePayload | null>(null);
  const [contractsStr, setContractsStr] = useState("1");
  const [tcMepStr, setTcMepStr] = useState("");
  const [buyDate, setBuyDate] = useState("");
  const [tradeNotes, setTradeNotes] = useState("");
  const [debitCreditStr, setDebitCreditStr] = useState("");
  const [committedStr, setCommittedStr] = useState("");
  const [maxRiskStr, setMaxRiskStr] = useState("");
  const [maxProfitStr, setMaxProfitStr] = useState("");
  const [displayLegs, setDisplayLegs] = useState<PortfolioTradeLeg[]>([]);

  useEffect(() => {
    if (!open || !initialPayload) return;
    const snap = clonePayload(initialPayload);
    snapshotRef.current = snap;
    const q0 = snap.quantity > 0 ? snap.quantity : 1;
    setContractsStr(String(Math.max(1, Math.round(q0))));
    setTcMepStr(snap.tc_mep_compra != null && Number.isFinite(snap.tc_mep_compra) ? String(snap.tc_mep_compra) : "");
    setBuyDate((snap.buy_date || "").trim().slice(0, 10));
    const ev0Init = snap.management_events?.[0];
    setTradeNotes(((ev0Init?.notes ?? snap.notes) ?? "").trim());
    const ev0 = snap.management_events?.[0];
    setDebitCreditStr(ev0?.debit_credit != null && Number.isFinite(ev0.debit_credit) ? String(ev0.debit_credit) : "0");
    setCommittedStr(snap.committed_capital != null && Number.isFinite(snap.committed_capital) ? String(snap.committed_capital) : "");
    setMaxRiskStr(snap.max_risk != null && Number.isFinite(snap.max_risk) ? String(snap.max_risk) : "");
    setMaxProfitStr(snap.max_profit != null && Number.isFinite(snap.max_profit) ? String(snap.max_profit) : "");
    setDisplayLegs(applyContractQuantityToLegs(snap.legs, q0, optionLotSize));
  }, [open, initialPayload, optionLotSize]);

  useEffect(() => {
    if (!open || !snapshotRef.current) return;
    const q = parseContracts(contractsStr);
    setDisplayLegs(applyContractQuantityToLegs(snapshotRef.current.legs, q, optionLotSize));
  }, [contractsStr, open, optionLotSize]);

  async function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    const snap = snapshotRef.current;
    if (!snap) return;
    const contracts = parseContracts(contractsStr);
    const debit = parseRequiredNumber(debitCreditStr);
    if (debit === null) {
      return;
    }
    const legs = applyContractQuantityToLegs(snap.legs, contracts, optionLotSize);
    const ev0: PortfolioManagementEvent = { ...(snap.management_events?.[0] ?? { date: buyDate, event_type: "open" }) };
    const me: PortfolioManagementEvent = {
      ...ev0,
      date: buyDate.trim().slice(0, 10),
      debit_credit: debit,
      notes: tradeNotes.trim() || null,
    };
    const payload: PortfolioTradeCreatePayload = {
      ...snap,
      quantity: contracts,
      buy_date: buyDate.trim().slice(0, 10),
      notes: tradeNotes.trim() || null,
      tc_mep_compra: parseOptionalNumber(tcMepStr),
      committed_capital: parseOptionalNumber(committedStr),
      max_risk: parseOptionalNumber(maxRiskStr),
      max_profit: parseOptionalNumber(maxProfitStr),
      legs,
      management_events: [me, ...(snap.management_events?.slice(1) ?? [])],
    };
    await onConfirm(payload);
  }

  if (!open || !initialPayload) return null;

  return (
    <div
      className="cartera-modal-backdrop"
      role="presentation"
      onMouseDown={() => !busy && onClose()}
    >
      <div
        className="cartera-modal card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="options-send-cartera-title"
        onMouseDown={(e) => e.stopPropagation()}
        style={{ maxWidth: "min(34rem, 96vw)", maxHeight: "90vh", overflow: "auto" }}
      >
        <h2 id="options-send-cartera-title" className="cartera-form__title">
          Enviar estrategia a Cartera Real
        </h2>
        <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.65rem" }}>
          <strong>Estrategia:</strong> {strategyLabel}
          {" · "}
          <strong>Subyacente:</strong> {underlyingLabel}
          {" · "}
          <strong>Vencimiento:</strong> {expiryLabel}
        </p>
        <p className="msg-muted" style={{ fontSize: "0.82rem", marginBottom: "0.5rem" }}>
          Flujo inicial: débito (pagás) = negativo; crédito (cobrás) = positivo.
        </p>

        <div className="table-wrap" style={{ marginBottom: "0.75rem" }}>
          <table className="cartera-table">
            <thead>
              <tr>
                <th>Pata</th>
                <th>Acción</th>
                <th>Símbolo</th>
                <th className="nowrap">Strike</th>
                <th>Venc.</th>
                <th className="nowrap">Prima</th>
                <th className="nowrap">Cant.</th>
                <th className="nowrap">Mult.</th>
              </tr>
            </thead>
            <tbody>
              {displayLegs.map((leg, i) => (
                <tr key={`${leg.symbol}-${i}`}>
                  <td>{leg.leg_type}</td>
                  <td>{leg.action}</td>
                  <td className="nowrap">
                    <code>{leg.symbol}</code>
                  </td>
                  <td>{leg.strike != null ? leg.strike : "—"}</td>
                  <td className="nowrap">{leg.expiration ?? "—"}</td>
                  <td>{leg.premium != null && Number.isFinite(leg.premium) ? leg.premium : "—"}</td>
                  <td>{leg.quantity}</td>
                  <td>{leg.multiplier}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <form className="cartera-form" onSubmit={(e) => void onSubmit(e)}>
          <div className="cartera-grid">
            <label className="cartera-field">
              <span>Cantidad de contratos</span>
              <input
                value={contractsStr}
                onChange={(e) => setContractsStr(e.target.value)}
                inputMode="numeric"
                min={1}
                disabled={busy}
              />
            </label>
            <label className="cartera-field">
              <span>TC MEP compra (ARS/USD)</span>
              <input value={tcMepStr} onChange={(e) => setTcMepStr(e.target.value)} inputMode="decimal" disabled={busy} />
            </label>
            <label className="cartera-field">
              <span>Fecha de apertura</span>
              <input type="date" value={buyDate} onChange={(e) => setBuyDate(e.target.value)} disabled={busy} />
            </label>
            <label className="cartera-field cartera-field--full">
              <span>Nota (operación)</span>
              <textarea value={tradeNotes} onChange={(e) => setTradeNotes(e.target.value)} rows={2} disabled={busy} />
            </label>
            <label className="cartera-field">
              <span>Flujo inicial (debit_credit ARS)</span>
              <input value={debitCreditStr} onChange={(e) => setDebitCreditStr(e.target.value)} inputMode="decimal" disabled={busy} />
            </label>
            <label className="cartera-field">
              <span>Capital comprometido</span>
              <input value={committedStr} onChange={(e) => setCommittedStr(e.target.value)} inputMode="decimal" disabled={busy} />
            </label>
            <label className="cartera-field">
              <span>Riesgo máximo</span>
              <input value={maxRiskStr} onChange={(e) => setMaxRiskStr(e.target.value)} inputMode="decimal" disabled={busy} />
            </label>
            <label className="cartera-field">
              <span>Ganancia máxima</span>
              <input value={maxProfitStr} onChange={(e) => setMaxProfitStr(e.target.value)} inputMode="decimal" disabled={busy} />
            </label>
          </div>
          <p className="msg-muted" style={{ fontSize: "0.8rem", marginTop: "0.35rem" }}>
            Ticker enviado: <code>{initialPayload.ticker}</code>
          </p>
          <div className="cartera-modal-actions" style={{ marginTop: "0.75rem" }}>
            <button type="button" className="cartera-btn" onClick={onClose} disabled={busy}>
              Cancelar
            </button>
            <button type="submit" className="cartera-btn cartera-btn--primary" disabled={busy}>
              {busy ? "Enviando…" : "Confirmar envío"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
