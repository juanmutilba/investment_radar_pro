import { FormEvent, type ReactNode, useEffect, useState } from "react";
import {
  createCapitalPolicy,
  createFamilyAsset,
  createFamilyLiability,
  createFoSnapshot,
  createHouseProject,
  patchCapitalPolicy,
  patchFamilyAsset,
  patchFamilyLiability,
  patchHouseProject,
  type CapitalPolicy,
  type FamilyAsset,
  type FamilyLiability,
  type FoAssetCategory,
  type FoAssetCurrency,
  type FoHousePriority,
  type FoHouseStatus,
  type FoRateType,
  type FoLiabilityCurrency,
  type FoLiabilityType,
  type FoLiquidity,
  type FoOwnershipStatus,
  type FoPolicyDestination,
  type HouseProject,
} from "@/services/api";
import {
  ASSET_CATEGORY_LABELS,
  HOUSE_PRIORITY_LABELS,
  HOUSE_STATUS_LABELS,
  LIABILITY_TYPE_LABELS,
  LIQUIDITY_LABELS,
  OWNERSHIP_LABELS,
  POLICY_DESTINATION_LABELS,
  currentMonth,
  parseNonNeg,
  todayIsoDate,
} from "./familyOfficeLabels";

type CommonProps = {
  open: boolean;
  onClose: () => void;
  onSuccess?: () => void | Promise<void>;
  onError?: (message: string) => void;
};

function ModalShell({
  open,
  title,
  busy,
  onClose,
  onSubmit,
  children,
  submitLabel,
}: {
  open: boolean;
  title: string;
  busy: boolean;
  onClose: () => void;
  onSubmit: (ev: FormEvent) => void;
  children: ReactNode;
  submitLabel: string;
}) {
  if (!open) return null;
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
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2 className="cartera-form__title">{title}</h2>
        <form className="cartera-form" onSubmit={onSubmit}>
          <div className="cartera-grid">{children}</div>
          <div className="cartera-modal-actions">
            <button type="button" className="cartera-btn" disabled={busy} onClick={onClose}>
              Cancelar
            </button>
            <button type="submit" className="cartera-btn cartera-btn--primary" disabled={busy}>
              {busy ? "Guardando…" : submitLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export function AssetFormModal({
  open,
  initial,
  onClose,
  onSuccess,
  onError,
}: CommonProps & { initial?: FamilyAsset | null }) {
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [category, setCategory] = useState<FoAssetCategory>("cash");
  const [ownership, setOwnership] = useState<FoOwnershipStatus>("owned");
  const [currency, setCurrency] = useState<FoAssetCurrency>("ARS");
  const [valueStr, setValueStr] = useState("");
  const [valuationDate, setValuationDate] = useState(todayIsoDate());
  const [liquidity, setLiquidity] = useState<FoLiquidity>("medium");
  const [generates, setGenerates] = useState(false);
  const [cfStr, setCfStr] = useState("0");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    if (!open) return;
    if (initial) {
      setName(initial.name);
      setCategory(initial.category);
      setOwnership(initial.ownership_status);
      setCurrency(initial.currency);
      setValueStr(String(initial.estimated_value));
      setValuationDate(initial.valuation_date.slice(0, 10));
      setLiquidity(initial.liquidity);
      setGenerates(Boolean(initial.generates_cashflow));
      setCfStr(String(initial.monthly_cashflow ?? 0));
      setNotes(initial.notes ?? "");
    } else {
      setName("");
      setCategory("cash");
      setOwnership("owned");
      setCurrency("ARS");
      setValueStr("");
      setValuationDate(todayIsoDate());
      setLiquidity("medium");
      setGenerates(false);
      setCfStr("0");
      setNotes("");
    }
  }, [open, initial]);

  async function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    const estimated_value = parseNonNeg(valueStr);
    const monthly_cashflow = parseNonNeg(cfStr);
    if (!name.trim()) {
      onError?.("Ingresá un nombre.");
      return;
    }
    if (estimated_value === null) {
      onError?.("Valor estimado inválido (no negativo).");
      return;
    }
    if (monthly_cashflow === null) {
      onError?.("Flujo mensual inválido (no negativo).");
      return;
    }
    setBusy(true);
    try {
      const payload = {
        name: name.trim(),
        category,
        ownership_status: ownership,
        currency,
        estimated_value,
        valuation_date: valuationDate,
        liquidity,
        generates_cashflow: generates,
        monthly_cashflow,
        notes: notes.trim() || null,
      };
      if (initial) await patchFamilyAsset(initial.id, payload);
      else await createFamilyAsset(payload);
      await onSuccess?.();
      onClose();
    } catch (e) {
      onError?.(e instanceof Error ? e.message : "Error al guardar activo");
    } finally {
      setBusy(false);
    }
  }

  return (
    <ModalShell
      open={open}
      title={initial ? "Editar activo" : "Nuevo activo"}
      busy={busy}
      onClose={onClose}
      onSubmit={onSubmit}
      submitLabel="Guardar"
    >
      <label className="cartera-field">
        <span>Nombre</span>
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </label>
      <label className="cartera-field">
        <span>Categoría</span>
        <select value={category} onChange={(e) => setCategory(e.target.value as FoAssetCategory)}>
          {Object.entries(ASSET_CATEGORY_LABELS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <label className="cartera-field">
        <span>Titularidad</span>
        <select
          value={ownership}
          onChange={(e) => setOwnership(e.target.value as FoOwnershipStatus)}
        >
          {Object.entries(OWNERSHIP_LABELS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <label className="cartera-field">
        <span>Moneda</span>
        <select
          value={currency}
          onChange={(e) => setCurrency(e.target.value as FoAssetCurrency)}
        >
          <option value="ARS">ARS</option>
          <option value="USD">USD</option>
        </select>
      </label>
      <label className="cartera-field">
        <span>Valor estimado</span>
        <input value={valueStr} onChange={(e) => setValueStr(e.target.value)} inputMode="decimal" />
      </label>
      <label className="cartera-field">
        <span>Fecha valuación</span>
        <input
          type="date"
          value={valuationDate}
          onChange={(e) => setValuationDate(e.target.value)}
        />
      </label>
      <label className="cartera-field">
        <span>Liquidez</span>
        <select value={liquidity} onChange={(e) => setLiquidity(e.target.value as FoLiquidity)}>
          {Object.entries(LIQUIDITY_LABELS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <label className="cartera-field">
        <span>Genera flujo</span>
        <select
          value={generates ? "yes" : "no"}
          onChange={(e) => setGenerates(e.target.value === "yes")}
        >
          <option value="no">No</option>
          <option value="yes">Sí</option>
        </select>
      </label>
      <label className="cartera-field">
        <span>Flujo mensual</span>
        <input value={cfStr} onChange={(e) => setCfStr(e.target.value)} inputMode="decimal" />
      </label>
      <label className="cartera-field cartera-field--full">
        <span>Notas</span>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />
      </label>
    </ModalShell>
  );
}

export function LiabilityFormModal({
  open,
  initial,
  assets,
  onClose,
  onSuccess,
  onError,
}: CommonProps & { initial?: FamilyLiability | null; assets: FamilyAsset[] }) {
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [liabilityType, setLiabilityType] = useState<FoLiabilityType>("personal_loan");
  const [currency, setCurrency] = useState<FoLiabilityCurrency>("ARS");
  const [originalStr, setOriginalStr] = useState("");
  const [outstandingStr, setOutstandingStr] = useState("");
  const [installmentStr, setInstallmentStr] = useState("0");
  const [remainingStr, setRemainingStr] = useState("0");
  const [rateStr, setRateStr] = useState("0");
  const [eacStr, setEacStr] = useState("");
  const [nextDue, setNextDue] = useState("");
  const [linkedAssetId, setLinkedAssetId] = useState<string>("");
  const [notes, setNotes] = useState("");
  const [rateType, setRateType] = useState<FoRateType>("unknown");
  const [maturity, setMaturity] = useState("");
  const [allowsPartial, setAllowsPartial] = useState(true);

  useEffect(() => {
    if (!open) return;
    if (initial) {
      setName(initial.name);
      setLiabilityType(initial.liability_type);
      setCurrency(initial.currency);
      setOriginalStr(String(initial.original_amount));
      setOutstandingStr(String(initial.outstanding_balance));
      setInstallmentStr(String(initial.installment_amount ?? 0));
      setRemainingStr(String(initial.installments_remaining ?? 0));
      setRateStr(String(initial.nominal_annual_rate ?? 0));
      setEacStr(
        initial.effective_annual_cost === null || initial.effective_annual_cost === undefined
          ? ""
          : String(initial.effective_annual_cost),
      );
      setNextDue(initial.next_due_date ? initial.next_due_date.slice(0, 10) : "");
      setLinkedAssetId(
        initial.linked_asset_id === null || initial.linked_asset_id === undefined
          ? ""
          : String(initial.linked_asset_id),
      );
      setNotes(initial.notes ?? "");
      setRateType((initial.rate_type as FoRateType | null) ?? "unknown");
      setMaturity(initial.maturity_date ? String(initial.maturity_date).slice(0, 10) : "");
      setAllowsPartial(initial.allows_partial_prepayment !== false);
    } else {
      setName("");
      setLiabilityType("personal_loan");
      setCurrency("ARS");
      setOriginalStr("");
      setOutstandingStr("");
      setInstallmentStr("0");
      setRemainingStr("0");
      setRateStr("0");
      setEacStr("");
      setNextDue("");
      setLinkedAssetId("");
      setNotes("");
      setRateType("unknown");
      setMaturity("");
      setAllowsPartial(true);
    }
  }, [open, initial]);

  async function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    const original_amount = parseNonNeg(originalStr);
    const outstanding_balance = parseNonNeg(outstandingStr);
    const installment_amount = parseNonNeg(installmentStr);
    const nominal_annual_rate = parseNonNeg(rateStr);
    const remaining = parseNonNeg(remainingStr);
    const eac = eacStr.trim() === "" ? null : parseNonNeg(eacStr);
    if (!name.trim()) {
      onError?.("Ingresá un nombre.");
      return;
    }
    if (
      original_amount === null ||
      outstanding_balance === null ||
      installment_amount === null ||
      nominal_annual_rate === null ||
      remaining === null
    ) {
      onError?.("Montos inválidos (no negativos).");
      return;
    }
    if (eacStr.trim() && eac === null) {
      onError?.("Costo efectivo anual inválido.");
      return;
    }
    setBusy(true);
    try {
      const payload = {
        name: name.trim(),
        liability_type: liabilityType,
        currency,
        original_amount,
        outstanding_balance,
        installment_amount,
        installments_remaining: Math.floor(remaining),
        nominal_annual_rate,
        effective_annual_cost: eac,
        next_due_date: nextDue.trim() || null,
        linked_asset_id: linkedAssetId ? Number(linkedAssetId) : null,
        notes: notes.trim() || null,
        rate_type: rateType,
        current_installment: installment_amount,
        allows_partial_prepayment: allowsPartial,
        maturity_date: maturity.trim() || null,
      };
      if (initial) await patchFamilyLiability(initial.id, payload);
      else await createFamilyLiability(payload);
      await onSuccess?.();
      onClose();
    } catch (e) {
      onError?.(e instanceof Error ? e.message : "Error al guardar pasivo");
    } finally {
      setBusy(false);
    }
  }

  return (
    <ModalShell
      open={open}
      title={initial ? "Editar deuda" : "Nueva deuda"}
      busy={busy}
      onClose={onClose}
      onSubmit={onSubmit}
      submitLabel="Guardar"
    >
      <label className="cartera-field">
        <span>Nombre</span>
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </label>
      <label className="cartera-field">
        <span>Tipo</span>
        <select
          value={liabilityType}
          onChange={(e) => setLiabilityType(e.target.value as FoLiabilityType)}
        >
          {Object.entries(LIABILITY_TYPE_LABELS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <label className="cartera-field">
        <span>Moneda</span>
        <select
          value={currency}
          onChange={(e) => setCurrency(e.target.value as FoLiabilityCurrency)}
        >
          <option value="ARS">ARS</option>
          <option value="USD">USD</option>
          <option value="UVA">UVA</option>
        </select>
      </label>
      <label className="cartera-field">
        <span>Monto original</span>
        <input value={originalStr} onChange={(e) => setOriginalStr(e.target.value)} />
      </label>
      <label className="cartera-field">
        <span>Saldo pendiente</span>
        <input value={outstandingStr} onChange={(e) => setOutstandingStr(e.target.value)} />
      </label>
      <label className="cartera-field">
        <span>Cuota</span>
        <input value={installmentStr} onChange={(e) => setInstallmentStr(e.target.value)} />
      </label>
      <label className="cartera-field">
        <span>Cuotas restantes</span>
        <input value={remainingStr} onChange={(e) => setRemainingStr(e.target.value)} />
      </label>
      <label className="cartera-field">
        <span>Tasa nominal anual %</span>
        <input value={rateStr} onChange={(e) => setRateStr(e.target.value)} />
      </label>
      <label className="cartera-field">
        <span>Tipo de tasa</span>
        <select value={rateType} onChange={(e) => setRateType(e.target.value as FoRateType)}>
          <option value="fixed">Fija</option>
          <option value="variable">Variable</option>
          <option value="uva">UVA</option>
          <option value="family">Familiar</option>
          <option value="unknown">Desconocida</option>
        </select>
      </label>
      <label className="cartera-field">
        <span>CFT / TEA (opcional)</span>
        <input value={eacStr} onChange={(e) => setEacStr(e.target.value)} />
      </label>
      <label className="cartera-field">
        <span>Próximo vencimiento</span>
        <input type="date" value={nextDue} onChange={(e) => setNextDue(e.target.value)} />
      </label>
      <label className="cartera-field">
        <span>Vencimiento final</span>
        <input type="date" value={maturity} onChange={(e) => setMaturity(e.target.value)} />
      </label>
      <label className="cartera-field">
        <span>Prepago parcial</span>
        <select
          value={allowsPartial ? "yes" : "no"}
          onChange={(e) => setAllowsPartial(e.target.value === "yes")}
        >
          <option value="yes">Sí</option>
          <option value="no">No</option>
        </select>
      </label>
      <label className="cartera-field">
        <span>Activo vinculado</span>
        <select value={linkedAssetId} onChange={(e) => setLinkedAssetId(e.target.value)}>
          <option value="">— Ninguno —</option>
          {assets.map((a) => (
            <option key={a.id} value={a.id}>
              #{a.id} {a.name} ({a.currency})
            </option>
          ))}
        </select>
      </label>
      <label className="cartera-field cartera-field--full">
        <span>Notas</span>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />
      </label>
    </ModalShell>
  );
}

export function HouseProjectFormModal({
  open,
  initial,
  onClose,
  onSuccess,
  onError,
}: CommonProps & { initial?: HouseProject | null }) {
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [priority, setPriority] = useState<FoHousePriority>("necessary");
  const [estimatedStr, setEstimatedStr] = useState("");
  const [paidStr, setPaidStr] = useState("0");
  const [currency, setCurrency] = useState<FoAssetCurrency>("ARS");
  const [targetDate, setTargetDate] = useState("");
  const [status, setStatus] = useState<FoHouseStatus>("planned");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    if (!open) return;
    if (initial) {
      setName(initial.name);
      setPriority(initial.priority);
      setEstimatedStr(String(initial.estimated_cost));
      setPaidStr(String(initial.paid_amount ?? 0));
      setCurrency(initial.currency);
      setTargetDate(initial.target_date ? initial.target_date.slice(0, 10) : "");
      setStatus(initial.status);
      setNotes(initial.notes ?? "");
    } else {
      setName("");
      setPriority("necessary");
      setEstimatedStr("");
      setPaidStr("0");
      setCurrency("ARS");
      setTargetDate("");
      setStatus("planned");
      setNotes("");
    }
  }, [open, initial]);

  async function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    const estimated_cost = parseNonNeg(estimatedStr);
    const paid_amount = parseNonNeg(paidStr);
    if (!name.trim() || estimated_cost === null || paid_amount === null) {
      onError?.("Completá nombre y montos no negativos.");
      return;
    }
    setBusy(true);
    try {
      const payload = {
        name: name.trim(),
        priority,
        estimated_cost,
        paid_amount,
        currency,
        target_date: targetDate.trim() || null,
        status,
        notes: notes.trim() || null,
      };
      if (initial) await patchHouseProject(initial.id, payload);
      else await createHouseProject(payload);
      await onSuccess?.();
      onClose();
    } catch (e) {
      onError?.(e instanceof Error ? e.message : "Error al guardar proyecto");
    } finally {
      setBusy(false);
    }
  }

  return (
    <ModalShell
      open={open}
      title={initial ? "Editar proyecto" : "Nuevo proyecto de casa"}
      busy={busy}
      onClose={onClose}
      onSubmit={onSubmit}
      submitLabel="Guardar"
    >
      <label className="cartera-field">
        <span>Nombre</span>
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </label>
      <label className="cartera-field">
        <span>Prioridad</span>
        <select
          value={priority}
          onChange={(e) => setPriority(e.target.value as FoHousePriority)}
        >
          {Object.entries(HOUSE_PRIORITY_LABELS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <label className="cartera-field">
        <span>Costo estimado</span>
        <input value={estimatedStr} onChange={(e) => setEstimatedStr(e.target.value)} />
      </label>
      <label className="cartera-field">
        <span>Pagado</span>
        <input value={paidStr} onChange={(e) => setPaidStr(e.target.value)} />
      </label>
      <label className="cartera-field">
        <span>Moneda</span>
        <select
          value={currency}
          onChange={(e) => setCurrency(e.target.value as FoAssetCurrency)}
        >
          <option value="ARS">ARS</option>
          <option value="USD">USD</option>
        </select>
      </label>
      <label className="cartera-field">
        <span>Fecha objetivo</span>
        <input type="date" value={targetDate} onChange={(e) => setTargetDate(e.target.value)} />
      </label>
      <label className="cartera-field">
        <span>Estado</span>
        <select value={status} onChange={(e) => setStatus(e.target.value as FoHouseStatus)}>
          {Object.entries(HOUSE_STATUS_LABELS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <label className="cartera-field cartera-field--full">
        <span>Notas</span>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />
      </label>
    </ModalShell>
  );
}

export function PolicyFormModal({
  open,
  initial,
  onClose,
  onSuccess,
  onError,
}: CommonProps & { initial?: CapitalPolicy | null }) {
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [destination, setDestination] = useState<FoPolicyDestination>("emergency_fund");
  const [minStr, setMinStr] = useState("");
  const [maxStr, setMaxStr] = useState("");
  const [priorityStr, setPriorityStr] = useState("1");
  const [mandatory, setMandatory] = useState(false);
  const [notes, setNotes] = useState("");

  useEffect(() => {
    if (!open) return;
    if (initial) {
      setName(initial.name);
      setDestination(initial.destination);
      setMinStr(
        initial.minimum_monthly_amount === null || initial.minimum_monthly_amount === undefined
          ? ""
          : String(initial.minimum_monthly_amount),
      );
      setMaxStr(
        initial.maximum_monthly_amount === null || initial.maximum_monthly_amount === undefined
          ? ""
          : String(initial.maximum_monthly_amount),
      );
      setPriorityStr(String(initial.priority ?? 0));
      setMandatory(Boolean(initial.is_mandatory));
      setNotes(initial.notes ?? "");
    } else {
      setName("");
      setDestination("emergency_fund");
      setMinStr("");
      setMaxStr("");
      setPriorityStr("1");
      setMandatory(false);
      setNotes("");
    }
  }, [open, initial]);

  async function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    if (!name.trim()) {
      onError?.("Ingresá un nombre.");
      return;
    }
    const min =
      minStr.trim() === "" ? null : parseNonNeg(minStr);
    const max =
      maxStr.trim() === "" ? null : parseNonNeg(maxStr);
    const priority = parseNonNeg(priorityStr);
    if ((minStr.trim() && min === null) || (maxStr.trim() && max === null) || priority === null) {
      onError?.("Montos/prioridad inválidos.");
      return;
    }
    if (min !== null && max !== null && min > max) {
      onError?.("El mínimo no puede superar el máximo.");
      return;
    }
    setBusy(true);
    try {
      const payload = {
        name: name.trim(),
        destination,
        minimum_monthly_amount: min,
        maximum_monthly_amount: max,
        priority: Math.floor(priority),
        is_mandatory: mandatory,
        notes: notes.trim() || null,
      };
      if (initial) await patchCapitalPolicy(initial.id, payload);
      else await createCapitalPolicy(payload);
      await onSuccess?.();
      onClose();
    } catch (e) {
      onError?.(e instanceof Error ? e.message : "Error al guardar política");
    } finally {
      setBusy(false);
    }
  }

  return (
    <ModalShell
      open={open}
      title={initial ? "Editar política" : "Nueva política de capital"}
      busy={busy}
      onClose={onClose}
      onSubmit={onSubmit}
      submitLabel="Guardar"
    >
      <label className="cartera-field">
        <span>Nombre</span>
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </label>
      <label className="cartera-field">
        <span>Destino</span>
        <select
          value={destination}
          onChange={(e) => setDestination(e.target.value as FoPolicyDestination)}
        >
          {Object.entries(POLICY_DESTINATION_LABELS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <label className="cartera-field">
        <span>Mínimo mensual</span>
        <input value={minStr} onChange={(e) => setMinStr(e.target.value)} placeholder="opcional" />
      </label>
      <label className="cartera-field">
        <span>Máximo mensual</span>
        <input value={maxStr} onChange={(e) => setMaxStr(e.target.value)} placeholder="opcional" />
      </label>
      <label className="cartera-field">
        <span>Prioridad</span>
        <input value={priorityStr} onChange={(e) => setPriorityStr(e.target.value)} />
      </label>
      <label className="cartera-field">
        <span>Obligatoria</span>
        <select
          value={mandatory ? "yes" : "no"}
          onChange={(e) => setMandatory(e.target.value === "yes")}
        >
          <option value="no">No</option>
          <option value="yes">Sí</option>
        </select>
      </label>
      <label className="cartera-field cartera-field--full">
        <span>Notas</span>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />
      </label>
    </ModalShell>
  );
}

export function SnapshotFormModal({
  open,
  onClose,
  onSuccess,
  onError,
}: CommonProps) {
  const [busy, setBusy] = useState(false);
  const [month, setMonth] = useState(currentMonth());
  const [currency, setCurrency] = useState<FoAssetCurrency>("ARS");
  const [active, setActive] = useState("0");
  const [consulting, setConsulting] = useState("0");
  const [scalable, setScalable] = useState("0");
  const [fixed, setFixed] = useState("0");
  const [debt, setDebt] = useState("0");
  const [house, setHouse] = useState("0");
  const [invest, setInvest] = useState("0");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    if (!open) return;
    setMonth(currentMonth());
    setCurrency("ARS");
    setActive("0");
    setConsulting("0");
    setScalable("0");
    setFixed("0");
    setDebt("0");
    setHouse("0");
    setInvest("0");
    setNotes("");
  }, [open]);

  async function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    const vals = [active, consulting, scalable, fixed, debt, house, invest].map(parseNonNeg);
    if (vals.some((v) => v === null) || !/^\d{4}-\d{2}$/.test(month)) {
      onError?.("Revisá mes (YYYY-MM) y montos no negativos.");
      return;
    }
    const [
      active_income,
      consulting_income,
      scalable_income,
      fixed_expenses,
      debt_payments,
      house_spending,
      investment_contributions,
    ] = vals as number[];
    setBusy(true);
    try {
      await createFoSnapshot({
        month,
        currency,
        active_income,
        consulting_income,
        scalable_income,
        fixed_expenses,
        debt_payments,
        house_spending,
        investment_contributions,
        notes: notes.trim() || null,
      });
      await onSuccess?.();
      onClose();
    } catch (e) {
      onError?.(e instanceof Error ? e.message : "Error al guardar snapshot");
    } finally {
      setBusy(false);
    }
  }

  return (
    <ModalShell
      open={open}
      title="Snapshot mensual"
      busy={busy}
      onClose={onClose}
      onSubmit={onSubmit}
      submitLabel="Guardar"
    >
      <label className="cartera-field">
        <span>Mes (YYYY-MM)</span>
        <input value={month} onChange={(e) => setMonth(e.target.value)} placeholder="2026-07" />
      </label>
      <label className="cartera-field">
        <span>Moneda del snapshot</span>
        <select
          value={currency}
          onChange={(e) => setCurrency(e.target.value as FoAssetCurrency)}
        >
          <option value="ARS">ARS</option>
          <option value="USD">USD</option>
        </select>
      </label>
      <label className="cartera-field">
        <span>Ingreso activo</span>
        <input value={active} onChange={(e) => setActive(e.target.value)} />
      </label>
      <label className="cartera-field">
        <span>Ingreso consultoría</span>
        <input value={consulting} onChange={(e) => setConsulting(e.target.value)} />
      </label>
      <label className="cartera-field">
        <span>Ingreso escalable</span>
        <input value={scalable} onChange={(e) => setScalable(e.target.value)} />
      </label>
      <label className="cartera-field">
        <span>Gastos fijos</span>
        <input value={fixed} onChange={(e) => setFixed(e.target.value)} />
      </label>
      <label className="cartera-field">
        <span>Pagos de deuda</span>
        <input value={debt} onChange={(e) => setDebt(e.target.value)} />
      </label>
      <label className="cartera-field">
        <span>Gasto casa</span>
        <input value={house} onChange={(e) => setHouse(e.target.value)} />
      </label>
      <label className="cartera-field">
        <span>Aportes inversión</span>
        <input value={invest} onChange={(e) => setInvest(e.target.value)} />
      </label>
      <label className="cartera-field cartera-field--full">
        <span>Notas</span>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />
      </label>
    </ModalShell>
  );
}
