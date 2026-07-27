import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  closeFoMonth,
  createCapitalAllocation,
  createCashflowEntry,
  createCashflowAllocation,
  createFixedExpense,
  createInvestmentCashflow,
  createLeverageRecord,
  deleteCapitalAllocation,
  deleteCashflowEntry,
  deleteCashflowAllocation,
  deleteFixedExpense,
  deleteInvestmentCashflow,
  deleteLeverageRecord,
  fetchCashflowEntries,
  fetchFixedExpenses,
  fetchFoAllocationBoard,
  fetchFoFixedExpenseCoverage,
  fetchFoLeveragePerformance,
  fetchFoMonthlySummary,
  patchCapitalAllocation,
  patchCashflowEntry,
  reopenFoMonth,
  transitionInvestmentCashStatus,
  type FoAllocationDestination,
  type FoAllocationStatus,
  type FoAssetCurrency,
  type FoEntryType,
  type FoFixedExpenseCategory,
  type FoSourceUnit,
  type FoStrategyType,
  type FamilyCashflowEntry,
  type FamilyFixedExpense,
  type FoAllocationBoard,
  type FoCoverageResponse,
  type FoLeveragePerformance,
  type FoMonthlySummary,
  type FoLiabilityCurrency,
} from "@/services/api";
import {
  ALLOCATION_DESTINATION_LABELS,
  ALLOCATION_STATUS_LABELS,
  CLOSURE_STATUS_LABELS,
  EXPENSE_CATEGORIES_UI,
  EXPENSE_CATEGORY_LABELS,
  INCOME_CATEGORIES_UI,
  INCOME_CATEGORY_LABELS,
  SOURCE_UNIT_LABELS,
  SOURCE_UNITS_UI,
  currentMonth,
  fmtMoney,
  labelOrCode,
  parseNonNeg,
  todayIsoDate,
} from "./familyOfficeLabels";

const FIXED_CATS: FoFixedExpenseCategory[] = [
  "education",
  "utilities",
  "insurance",
  "debt_payment",
  "food",
  "transport",
  "health",
  "housing",
  "taxes",
  "other",
];

const DESTINATIONS: FoAllocationDestination[] = [
  "debt",
  "investments",
  "salva",
  "investment_radar",
  "house",
  "emergency_fund",
  "cash",
  "other",
];

const STRATEGIES: FoStrategyType[] = [
  "covered_call",
  "dividend",
  "interest",
  "realized_gain",
  "realized_loss",
  "other",
];

type Props = {
  tab: "flujo" | "asignacion" | "apalancamiento";
  onError: (m: string) => void;
};

type CoverageSource = {
  kind?: string;
  allocation_id?: number;
  source_cashflow_entry_id?: number;
  source_unit?: string;
  source_description?: string;
  amount?: number;
  notes?: string | null;
};

function MonthCurrencyBar({
  month,
  currency,
  onMonth,
  onCurrency,
  status,
}: {
  month: string;
  currency: FoAssetCurrency;
  onMonth: (m: string) => void;
  onCurrency: (c: FoAssetCurrency) => void;
  status?: string;
}) {
  return (
    <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
      <label className="cartera-field">
        <span>Mes</span>
        <input value={month} onChange={(e) => onMonth(e.target.value)} placeholder="YYYY-MM" />
      </label>
      <label className="cartera-field">
        <span>Moneda</span>
        <select value={currency} onChange={(e) => onCurrency(e.target.value as FoAssetCurrency)}>
          <option value="ARS">ARS</option>
          <option value="USD">USD</option>
        </select>
      </label>
      {status ? (
        <div className="cartera-hint" style={{ paddingBottom: "0.35rem" }}>
          Estado del mes: <strong>{labelOrCode(CLOSURE_STATUS_LABELS, status)}</strong>
        </div>
      ) : null}
    </div>
  );
}

function toFixedCategory(cat: string): FoFixedExpenseCategory {
  return FIXED_CATS.includes(cat as FoFixedExpenseCategory) ? (cat as FoFixedExpenseCategory) : "other";
}

function formatSourceLine(src: CoverageSource): string {
  const amt = fmtMoney(Number(src.amount ?? 0));
  const unit = labelOrCode(SOURCE_UNIT_LABELS, src.source_unit);
  const desc = src.source_description ? ` · ${src.source_description}` : "";
  return `${amt} ← ${unit}${desc}`;
}

export function FamilyOfficeStage2Panel({ tab, onError }: Props) {
  const [month, setMonth] = useState(currentMonth());
  const [currency, setCurrency] = useState<FoAssetCurrency>("ARS");
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState<FoMonthlySummary | null>(null);
  const [entries, setEntries] = useState<FamilyCashflowEntry[]>([]);
  const [coverage, setCoverage] = useState<FoCoverageResponse | null>(null);
  const [fixed, setFixed] = useState<FamilyFixedExpense[]>([]);
  const [board, setBoard] = useState<FoAllocationBoard | null>(null);
  const [lev, setLev] = useState<FoLeveragePerformance | null>(null);

  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      if (tab === "flujo") {
        const [s, e, f, c] = await Promise.all([
          fetchFoMonthlySummary(month, currency),
          fetchCashflowEntries(month, currency),
          fetchFixedExpenses(true, currency),
          fetchFoFixedExpenseCoverage(month, currency),
        ]);
        setSummary(s);
        setEntries(e);
        setFixed(f);
        setCoverage(c);
      } else if (tab === "asignacion") {
        setBoard(await fetchFoAllocationBoard(month, currency));
      } else if (tab === "apalancamiento") {
        setLev(await fetchFoLeveragePerformance(month));
      }
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error Family Office etapa 2");
    } finally {
      setBusy(false);
    }
  }, [tab, month, currency, onError]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const fixedName = useCallback(
    (id: number | null | undefined) => {
      if (!id) return "—";
      return fixed.find((f) => f.id === id)?.name ?? `#${id}`;
    },
    [fixed]
  );

  const incomeWithAvailable = entries.filter(
    (e) => e.entry_type === "income" && (e.available_amount ?? e.amount) > 0
  );

  const [entryType, setEntryType] = useState<FoEntryType>("income");
  const [entryCat, setEntryCat] = useState<string>("salary");
  const [entryUnit, setEntryUnit] = useState<FoSourceUnit>("employment");
  const [entryAmt, setEntryAmt] = useState("");
  const [entryDesc, setEntryDesc] = useState("");
  const [entryFixedId, setEntryFixedId] = useState("");
  const [entryIsFixedExpense, setEntryIsFixedExpense] = useState(false);
  const [linkFixedEntryId, setLinkFixedEntryId] = useState<number | null>(null);
  const [linkFixedSelectId, setLinkFixedSelectId] = useState("");

  const [assignOpenFor, setAssignOpenFor] = useState<number | null>(null);
  const [assignEntryId, setAssignEntryId] = useState("");
  const [assignAmt, setAssignAmt] = useState("");

  const [feName, setFeName] = useState("");
  const [feCat, setFeCat] = useState<FoFixedExpenseCategory>("education");
  const [feAmt, setFeAmt] = useState("");
  const [feOrder, setFeOrder] = useState("1");

  const [allocAmt, setAllocAmt] = useState("");
  const [allocDest, setAllocDest] = useState<FoAllocationDestination>("investments");
  const [allocStatus, setAllocStatus] = useState<FoAllocationStatus>("proposed");
  const [allocRationale, setAllocRationale] = useState("");
  const [allocExpected, setAllocExpected] = useState("");

  const [levBal, setLevBal] = useState("");
  const [levRate, setLevRate] = useState("18.5");
  const [levInterest, setLevInterest] = useState("");
  const [levFees, setLevFees] = useState("0");
  const [invGross, setInvGross] = useState("");
  const [invComm, setInvComm] = useState("0");
  const [invTax, setInvTax] = useState("0");
  const [invFin, setInvFin] = useState("0");
  const [invAccount, setInvAccount] = useState("Veta");
  const [invStrategy, setInvStrategy] = useState<FoStrategyType>("covered_call");

  function onEntryTypeChange(next: FoEntryType) {
    setEntryType(next);
    setEntryCat(next === "income" ? "salary" : "housing");
    setEntryFixedId("");
    setEntryIsFixedExpense(false);
  }

  async function submitEntry(ev: FormEvent) {
    ev.preventDefault();
    const amount = parseNonNeg(entryAmt);
    if (amount === null) {
      onError("Monto inválido (positivo).");
      return;
    }
    try {
      await createCashflowEntry({
        date: todayIsoDate(),
        month,
        entry_type: entryType,
        category: entryCat.trim() || "other",
        source_unit: entryUnit,
        currency,
        amount,
        description: entryDesc.trim() || null,
        fixed_expense_id:
          entryType === "expense" && entryFixedId ? Number(entryFixedId) : null,
        is_fixed_expense: entryType === "expense" ? entryIsFixedExpense : false,
        asset_id: null,
        liability_id: null,
        notes: null,
      });
      setEntryAmt("");
      setEntryDesc("");
      setEntryFixedId("");
      setEntryIsFixedExpense(false);
      await refresh();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error al guardar entrada");
    }
  }

  async function onCloseMonth() {
    if (!window.confirm(`¿Cerrar ${month} en ${currency}? No se podrá sobreasignar después sin reabrir.`)) {
      return;
    }
    try {
      await closeFoMonth(month, currency);
      await refresh();
    } catch (e) {
      onError(e instanceof Error ? e.message : "No se pudo cerrar el mes");
    }
  }

  async function onReopenMonth() {
    if (!window.confirm(`¿Reabrir ${month} en ${currency}?`)) return;
    try {
      await reopenFoMonth(month, currency);
      await refresh();
    } catch (e) {
      onError(e instanceof Error ? e.message : "No se pudo reabrir el mes");
    }
  }

  async function linkExpenseToFixed(entryId: number) {
    if (!linkFixedSelectId) {
      onError("Elegí un gasto fijo.");
      return;
    }
    try {
      await patchCashflowEntry(entryId, { fixed_expense_id: Number(linkFixedSelectId) });
      setLinkFixedEntryId(null);
      setLinkFixedSelectId("");
      await refresh();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error al asociar gasto fijo");
    }
  }

  async function createTemplateFromExpense(entry: FamilyCashflowEntry) {
    const name =
      entry.description?.trim() ||
      `${labelOrCode(EXPENSE_CATEGORY_LABELS, entry.category)} ${fmtMoney(entry.amount)}`;
    if (!window.confirm(`¿Crear plantilla "${name}" y vincular este egreso?`)) return;
    try {
      const created = await createFixedExpense({
        name,
        category: toFixedCategory(entry.category),
        currency,
        expected_monthly_amount: entry.amount,
        priority: 1,
        coverage_order: 1,
        is_essential: true,
        notes: null,
      });
      await patchCashflowEntry(entry.id, {
        fixed_expense_id: created.id,
        is_fixed_expense: true,
      });
      await refresh();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error al crear plantilla");
    }
  }

  async function submitFixed(ev: FormEvent) {
    ev.preventDefault();
    const expected_monthly_amount = parseNonNeg(feAmt);
    const coverage_order = parseNonNeg(feOrder);
    if (!feName.trim() || expected_monthly_amount === null || coverage_order === null) {
      onError("Completá nombre, monto y orden.");
      return;
    }
    try {
      await createFixedExpense({
        name: feName.trim(),
        category: feCat,
        currency,
        expected_monthly_amount,
        priority: Math.floor(coverage_order),
        coverage_order: Math.floor(coverage_order),
        is_essential: true,
        notes: null,
      });
      setFeName("");
      setFeAmt("");
      await refresh();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error gasto fijo");
    }
  }

  async function submitAssignIncome(fixedExpenseId: number) {
    const allocated_amount = parseNonNeg(assignAmt);
    const sourceId = Number(assignEntryId);
    if (!sourceId || allocated_amount === null) {
      onError("Elegí ingreso y monto válido.");
      return;
    }
    try {
      await createCashflowAllocation({
        month,
        currency,
        source_cashflow_entry_id: sourceId,
        destination_type: "fixed_expense",
        destination_id: fixedExpenseId,
        allocated_amount,
        notes: null,
      });
      setAssignOpenFor(null);
      setAssignEntryId("");
      setAssignAmt("");
      await refresh();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error al asignar ingreso");
    }
  }

  async function submitAlloc(ev: FormEvent) {
    ev.preventDefault();
    const allocated_amount = parseNonNeg(allocAmt);
    if (allocated_amount === null || !board) {
      onError("Monto inválido.");
      return;
    }
    try {
      await createCapitalAllocation({
        month,
        currency,
        available_amount: Math.max(board.free_cashflow, 0),
        destination: allocDest,
        allocated_amount,
        status: allocStatus,
        rationale:
          (allocRationale.trim() || "Asignación manual.") +
          (allocExpected.trim()
            ? ` Proyección orientativa (NO segura): ${allocExpected}.`
            : ""),
        expected_return: allocExpected.trim() ? Number(allocExpected.replace(",", ".")) : null,
        expected_monthly_cashflow: null,
        expected_hours_saved: null,
        executed_date: allocStatus === "executed" ? todayIsoDate() : null,
        policy_id: null,
        asset_id: null,
        liability_id: null,
        house_project_id: null,
      });
      setAllocAmt("");
      setAllocRationale("");
      setAllocExpected("");
      await refresh();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error asignación");
    }
  }

  async function submitLeverage(ev: FormEvent) {
    ev.preventDefault();
    const average_balance_used = parseNonNeg(levBal);
    const nominal_annual_rate = parseNonNeg(levRate);
    const interest_paid = parseNonNeg(levInterest);
    const taxes_and_fees = parseNonNeg(levFees);
    if (
      average_balance_used === null ||
      nominal_annual_rate === null ||
      interest_paid === null ||
      taxes_and_fees === null
    ) {
      onError("Montos de apalancamiento inválidos.");
      return;
    }
    try {
      await createLeverageRecord({
        month,
        currency: currency as FoLiabilityCurrency,
        average_balance_used,
        days_used: 30,
        nominal_annual_rate,
        interest_paid,
        taxes_and_fees,
        liability_id: null,
        linked_asset_id: null,
        notes: "Registro de financiamiento real. TNA informativa, no comparable a proyección.",
      });
      setLevBal("");
      setLevInterest("");
      await refresh();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error leverage");
    }
  }

  async function submitInv(ev: FormEvent) {
    ev.preventDefault();
    const gross_income = parseNonNeg(invGross);
    const commissions = parseNonNeg(invComm);
    const taxes = parseNonNeg(invTax);
    const financing_cost = parseNonNeg(invFin);
    if (
      gross_income === null ||
      commissions === null ||
      taxes === null ||
      financing_cost === null ||
      !invAccount.trim()
    ) {
      onError("Completá el cashflow de inversiones (montos ≥ 0).");
      return;
    }
    try {
      await createInvestmentCashflow({
        month,
        account_name: invAccount.trim(),
        strategy_type: invStrategy,
        currency,
        gross_income,
        commissions,
        taxes,
        financing_cost,
        linked_asset_id: null,
        fixed_expense_id: null,
        notes:
          "Resultado realizado registrado. Una proyección (p.ej. covered call 55%) NO es resultado seguro.",
      });
      setInvGross("");
      await refresh();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error investment cashflow");
    }
  }

  if (tab === "flujo") {
    return (
      <section style={{ marginTop: "1rem", display: "grid", gap: "1rem" }}>
        <MonthCurrencyBar
          month={month}
          currency={currency}
          onMonth={setMonth}
          onCurrency={setCurrency}
          status={summary?.closure_status}
        />
        {busy ? <p className="cartera-hint">Cargando…</p> : null}

        {summary ? (
          <div className="card" style={{ padding: "1rem" }}>
            <h3 className="cartera-form__title" style={{ fontSize: "1rem" }}>
              Resumen {month} · {currency}
            </h3>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                gap: "0.75rem",
                marginTop: "0.75rem",
              }}
            >
              <div>
                <div className="cartera-hint">Ingresos</div>
                <div className="cartera-mono">{fmtMoney(summary.total_income)}</div>
              </div>
              <div>
                <div className="cartera-hint">Egresos</div>
                <div className="cartera-mono">{fmtMoney(summary.total_expenses)}</div>
              </div>
              <div>
                <div className="cartera-hint">Flujo libre</div>
                <div className="cartera-mono">{fmtMoney(summary.free_cashflow)}</div>
              </div>
              <div>
                <div className="cartera-hint">Total asignado</div>
                <div className="cartera-mono">{fmtMoney(summary.cashflow_allocated ?? 0)}</div>
              </div>
              <div>
                <div className="cartera-hint">Saldo sin asignar</div>
                <div className="cartera-mono">
                  {fmtMoney(summary.income_unallocated ?? summary.total_income)}
                </div>
              </div>
              <div>
                <div className="cartera-hint">Estado</div>
                <div>{labelOrCode(CLOSURE_STATUS_LABELS, summary.closure_status)}</div>
              </div>
            </div>
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem", flexWrap: "wrap" }}>
              <button type="button" className="cartera-btn cartera-btn--primary" onClick={() => void onCloseMonth()}>
                Cerrar mes
              </button>
              <button type="button" className="cartera-btn" onClick={() => void onReopenMonth()}>
                Reabrir mes
              </button>
              <button type="button" className="cartera-btn" onClick={() => void refresh()}>
                Actualizar
              </button>
            </div>
            <p className="cartera-hint" style={{ marginTop: "0.5rem" }}>
              Pagado ≠ Cubierto. Asignaciones desde ingresos; pagos son egresos vinculados.
            </p>
          </div>
        ) : null}

        <div className="card" style={{ padding: "0.75rem 1rem" }}>
          <h3 className="cartera-form__title" style={{ fontSize: "1rem" }}>
            Movimientos
          </h3>

          <details style={{ marginTop: "0.75rem" }}>
            <summary className="cartera-form__title" style={{ fontSize: "0.95rem", cursor: "pointer" }}>
              Registrar movimiento
            </summary>
            <form className="cartera-form" style={{ marginTop: "0.75rem" }} onSubmit={submitEntry}>
              <div className="cartera-grid">
                <label className="cartera-field">
                  <span>Tipo</span>
                  <select
                    value={entryType}
                    onChange={(e) => onEntryTypeChange(e.target.value as FoEntryType)}
                  >
                    <option value="income">Ingreso</option>
                    <option value="expense">Gasto</option>
                  </select>
                </label>
                <label className="cartera-field">
                  <span>Unidad</span>
                  <select value={entryUnit} onChange={(e) => setEntryUnit(e.target.value as FoSourceUnit)}>
                    {SOURCE_UNITS_UI.map((u) => (
                      <option key={u} value={u}>
                        {labelOrCode(SOURCE_UNIT_LABELS, u)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="cartera-field">
                  <span>Categoría</span>
                  <select value={entryCat} onChange={(e) => setEntryCat(e.target.value)}>
                    {(entryType === "income" ? INCOME_CATEGORIES_UI : EXPENSE_CATEGORIES_UI).map((c) => (
                      <option key={c} value={c}>
                        {labelOrCode(
                          entryType === "income" ? INCOME_CATEGORY_LABELS : EXPENSE_CATEGORY_LABELS,
                          c
                        )}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="cartera-field">
                  <span>Monto (+)</span>
                  <input value={entryAmt} onChange={(e) => setEntryAmt(e.target.value)} />
                </label>
                {entryType === "expense" ? (
                  <>
                    <label className="cartera-field">
                      <span>Asociar a gasto fijo</span>
                      <select value={entryFixedId} onChange={(e) => setEntryFixedId(e.target.value)}>
                        <option value="">— Ninguno —</option>
                        {fixed.map((f) => (
                          <option key={f.id} value={String(f.id)}>
                            {f.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="cartera-field" style={{ display: "flex", alignItems: "end", gap: "0.5rem" }}>
                      <input
                        type="checkbox"
                        checked={entryIsFixedExpense}
                        onChange={(e) => setEntryIsFixedExpense(e.target.checked)}
                      />
                      <span>Marcar como pago de gasto fijo</span>
                    </label>
                  </>
                ) : null}
                <label className="cartera-field cartera-field--full">
                  <span>Descripción</span>
                  <input value={entryDesc} onChange={(e) => setEntryDesc(e.target.value)} />
                </label>
              </div>
              <button type="submit" className="cartera-btn cartera-btn--primary">
                Guardar movimiento
              </button>
            </form>
          </details>

          {!busy && entries.length === 0 ? (
            <p className="cartera-empty">Sin movimientos en este mes/moneda.</p>
          ) : (
            <div className="table-scroll" style={{ marginTop: "0.75rem" }}>
              <table className="cartera-table">
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>Tipo</th>
                    <th>Unidad</th>
                    <th>Categoría</th>
                    <th>Monto</th>
                    <th>Disponible</th>
                    <th>Gasto fijo asociado</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((e) => (
                    <tr key={e.id}>
                      <td>{e.date}</td>
                      <td>{e.entry_type === "income" ? "Ingreso" : "Gasto"}</td>
                      <td>{labelOrCode(SOURCE_UNIT_LABELS, e.source_unit)}</td>
                      <td>
                        {labelOrCode(
                          e.entry_type === "income" ? INCOME_CATEGORY_LABELS : EXPENSE_CATEGORY_LABELS,
                          e.category
                        )}
                      </td>
                      <td className="cartera-mono">{fmtMoney(e.amount)}</td>
                      <td className="cartera-mono">
                        {e.entry_type === "income"
                          ? fmtMoney(e.available_amount ?? e.amount)
                          : "—"}
                      </td>
                      <td>{fixedName(e.fixed_expense_id)}</td>
                      <td>
                        <div style={{ display: "flex", gap: "0.25rem", flexWrap: "wrap" }}>
                          {e.entry_type === "expense" && !e.fixed_expense_id ? (
                            linkFixedEntryId === e.id ? (
                              <>
                                <select
                                  value={linkFixedSelectId}
                                  onChange={(ev) => setLinkFixedSelectId(ev.target.value)}
                                >
                                  <option value="">Elegir…</option>
                                  {fixed.map((f) => (
                                    <option key={f.id} value={String(f.id)}>
                                      {f.name}
                                    </option>
                                  ))}
                                </select>
                                <button
                                  type="button"
                                  className="cartera-btn"
                                  onClick={() => void linkExpenseToFixed(e.id)}
                                >
                                  OK
                                </button>
                                <button
                                  type="button"
                                  className="cartera-btn"
                                  onClick={() => {
                                    setLinkFixedEntryId(null);
                                    setLinkFixedSelectId("");
                                  }}
                                >
                                  Cancelar
                                </button>
                              </>
                            ) : (
                              <button
                                type="button"
                                className="cartera-btn"
                                onClick={() => setLinkFixedEntryId(e.id)}
                              >
                                Asociar a gasto fijo
                              </button>
                            )
                          ) : null}
                          {e.entry_type === "expense" ? (
                            <button
                              type="button"
                              className="cartera-btn"
                              onClick={() => void createTemplateFromExpense(e)}
                            >
                              Crear plantilla
                            </button>
                          ) : null}
                          <button
                            type="button"
                            className="cartera-btn cartera-btn--danger"
                            onClick={() => {
                              if (!window.confirm("¿Eliminar movimiento?")) return;
                              void (async () => {
                                try {
                                  await deleteCashflowEntry(e.id);
                                  await refresh();
                                } catch (err) {
                                  onError(err instanceof Error ? err.message : "Error");
                                }
                              })();
                            }}
                          >
                            Eliminar
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="card" style={{ padding: "1rem" }}>
          <h3 className="cartera-form__title" style={{ fontSize: "1rem" }}>
            Gastos fijos y cobertura
          </h3>

          <form className="cartera-form" style={{ marginTop: "0.75rem" }} onSubmit={submitFixed}>
            <h4 className="cartera-form__title" style={{ fontSize: "0.95rem" }}>
              Nueva plantilla de gasto fijo
            </h4>
            <div className="cartera-grid">
              <label className="cartera-field">
                <span>Nombre</span>
                <input value={feName} onChange={(e) => setFeName(e.target.value)} placeholder="Jardín de los niños" />
              </label>
              <label className="cartera-field">
                <span>Categoría</span>
                <select value={feCat} onChange={(e) => setFeCat(e.target.value as FoFixedExpenseCategory)}>
                  {FIXED_CATS.map((c) => (
                    <option key={c} value={c}>
                      {labelOrCode(EXPENSE_CATEGORY_LABELS, c)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="cartera-field">
                <span>Compromiso mensual</span>
                <input value={feAmt} onChange={(e) => setFeAmt(e.target.value)} />
              </label>
              <label className="cartera-field">
                <span>Orden</span>
                <input value={feOrder} onChange={(e) => setFeOrder(e.target.value)} />
              </label>
            </div>
            <button type="submit" className="cartera-btn cartera-btn--primary">
              Guardar plantilla
            </button>
          </form>

          {!busy && (coverage?.items.length ?? 0) === 0 ? (
            <p className="cartera-empty">Sin gastos fijos activos en esta moneda.</p>
          ) : (
            <div className="table-scroll" style={{ marginTop: "0.75rem" }}>
              <table className="cartera-table">
                <thead>
                  <tr>
                    <th>Gasto fijo</th>
                    <th>Compromiso</th>
                    <th>Pagado</th>
                    <th>Cubierto</th>
                    <th>Falta pagar</th>
                    <th>Falta cubrir</th>
                    <th>Fuentes</th>
                    <th>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {(coverage?.items ?? []).map((it) => {
                    const commitment = it.commitment ?? it.expected_monthly_amount;
                    const paid = it.paid ?? it.assigned_cashflow;
                    const covered = it.covered ?? 0;
                    const remainingPay = it.remaining_to_pay ?? Math.max(0, commitment - paid);
                    const remainingCover = it.remaining_to_cover ?? Math.max(0, commitment - covered);
                    const sources = (it.sources ?? []) as CoverageSource[];

                    return (
                      <tr key={it.fixed_expense_id}>
                        <td>{it.name}</td>
                        <td className="cartera-mono">{fmtMoney(commitment)}</td>
                        <td className="cartera-mono">{fmtMoney(paid)}</td>
                        <td className="cartera-mono">{fmtMoney(covered)}</td>
                        <td className="cartera-mono">{fmtMoney(remainingPay)}</td>
                        <td className="cartera-mono">{fmtMoney(remainingCover)}</td>
                        <td>
                          {sources.length === 0 ? (
                            "—"
                          ) : (
                            <div style={{ display: "grid", gap: "0.25rem" }}>
                              {sources.map((src, idx) => (
                                <div
                                  key={src.allocation_id ?? idx}
                                  style={{ display: "flex", gap: "0.25rem", alignItems: "center", flexWrap: "wrap" }}
                                >
                                  <span className="cartera-hint">{formatSourceLine(src)}</span>
                                  {src.allocation_id ? (
                                    <button
                                      type="button"
                                      className="cartera-btn cartera-btn--danger"
                                      title="Quitar asignación"
                                      onClick={() => {
                                        if (!window.confirm("¿Eliminar esta asignación de ingreso?")) return;
                                        void (async () => {
                                          try {
                                            await deleteCashflowAllocation(src.allocation_id!);
                                            await refresh();
                                          } catch (err) {
                                            onError(err instanceof Error ? err.message : "Error");
                                          }
                                        })();
                                      }}
                                    >
                                      ×
                                    </button>
                                  ) : null}
                                </div>
                              ))}
                            </div>
                          )}
                        </td>
                        <td>
                          <div style={{ display: "grid", gap: "0.35rem" }}>
                            <button
                              type="button"
                              className="cartera-btn cartera-btn--danger"
                              onClick={() => {
                                if (!window.confirm(`¿Desactivar "${it.name}"?`)) return;
                                void (async () => {
                                  try {
                                    await deleteFixedExpense(it.fixed_expense_id);
                                    await refresh();
                                  } catch (err) {
                                    onError(err instanceof Error ? err.message : "Error");
                                  }
                                })();
                              }}
                            >
                              Desactivar
                            </button>
                            {remainingCover > 0 ? (
                              assignOpenFor === it.fixed_expense_id ? (
                                <div style={{ display: "grid", gap: "0.25rem" }}>
                                  <select
                                    value={assignEntryId}
                                    onChange={(e) => setAssignEntryId(e.target.value)}
                                  >
                                    <option value="">Ingreso con saldo…</option>
                                    {incomeWithAvailable.map((inc) => (
                                      <option key={inc.id} value={String(inc.id)}>
                                        {inc.date} · {labelOrCode(SOURCE_UNIT_LABELS, inc.source_unit)} · disp.{" "}
                                        {fmtMoney(inc.available_amount ?? inc.amount)}
                                      </option>
                                    ))}
                                  </select>
                                  <input
                                    value={assignAmt}
                                    onChange={(e) => setAssignAmt(e.target.value)}
                                    placeholder="Monto a asignar"
                                  />
                                  <div style={{ display: "flex", gap: "0.25rem", flexWrap: "wrap" }}>
                                    <button
                                      type="button"
                                      className="cartera-btn cartera-btn--primary"
                                      onClick={() => void submitAssignIncome(it.fixed_expense_id)}
                                    >
                                      Asignar
                                    </button>
                                    <button
                                      type="button"
                                      className="cartera-btn"
                                      onClick={() => {
                                        setAssignOpenFor(null);
                                        setAssignEntryId("");
                                        setAssignAmt("");
                                      }}
                                    >
                                      Cancelar
                                    </button>
                                  </div>
                                </div>
                              ) : (
                                <button
                                  type="button"
                                  className="cartera-btn"
                                  onClick={() => {
                                    setAssignOpenFor(it.fixed_expense_id);
                                    setAssignEntryId("");
                                    setAssignAmt(String(remainingCover));
                                  }}
                                >
                                  Asignar ingreso
                                </button>
                              )
                            ) : null}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="card" style={{ padding: "1rem" }}>
          <h3 className="cartera-form__title" style={{ fontSize: "1rem" }}>
            Asignación del flujo (F1)
          </h3>
          <p className="cartera-hint" style={{ marginTop: "0.5rem" }}>
            En F1 solo se asignan ingresos a gastos fijos. Destinos futuros: deuda, ahorro, inversión,
            proyecto de casa.
          </p>
        </div>
      </section>
    );
  }

  if (tab === "asignacion") {
    return (
      <section style={{ marginTop: "1rem", display: "grid", gap: "1rem" }}>
        <MonthCurrencyBar
          month={month}
          currency={currency}
          onMonth={setMonth}
          onCurrency={setCurrency}
          status={board?.closure_status}
        />
        {board ? (
          <div className="card" style={{ padding: "1rem" }}>
            <h3 className="cartera-form__title" style={{ fontSize: "1rem" }}>
              Capital libre {currency}
            </h3>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                gap: "0.75rem",
                marginTop: "0.5rem",
              }}
            >
              <div>
                <div className="cartera-hint">Flujo libre</div>
                <div className="cartera-mono">{fmtMoney(board.free_cashflow)}</div>
              </div>
              <div>
                <div className="cartera-hint">Asignado</div>
                <div className="cartera-mono">{fmtMoney(board.amount_allocated)}</div>
              </div>
              <div>
                <div className="cartera-hint">Pendiente</div>
                <div className="cartera-mono">{fmtMoney(board.unallocated_cash)}</div>
              </div>
              <div>
                <div className="cartera-hint">Reserva casa</div>
                <div className="cartera-mono">{fmtMoney(board.house_monthly_reserve)}</div>
              </div>
            </div>
            <p className="cartera-hint" style={{ marginTop: "0.5rem" }}>
              Asignación 100% manual. Las proyecciones (p.ej. covered call) son orientativas, no seguras.
            </p>
          </div>
        ) : null}

        <form className="card cartera-form" onSubmit={submitAlloc}>
          <h2 className="cartera-form__title">Repartir excedente</h2>
          <div className="cartera-grid">
            <label className="cartera-field">
              <span>Monto</span>
              <input value={allocAmt} onChange={(e) => setAllocAmt(e.target.value)} />
            </label>
            <label className="cartera-field">
              <span>Destino</span>
              <select
                value={allocDest}
                onChange={(e) => setAllocDest(e.target.value as FoAllocationDestination)}
              >
                {DESTINATIONS.map((d) => (
                  <option key={d} value={d}>
                    {labelOrCode(ALLOCATION_DESTINATION_LABELS, d)}
                  </option>
                ))}
              </select>
            </label>
            <label className="cartera-field">
              <span>Estado</span>
              <select
                value={allocStatus}
                onChange={(e) => setAllocStatus(e.target.value as FoAllocationStatus)}
              >
                <option value="proposed">{labelOrCode(ALLOCATION_STATUS_LABELS, "proposed")}</option>
                <option value="approved">{labelOrCode(ALLOCATION_STATUS_LABELS, "approved")}</option>
                <option value="executed">{labelOrCode(ALLOCATION_STATUS_LABELS, "executed")}</option>
              </select>
            </label>
            <label className="cartera-field">
              <span>Proyección (opcional, NO segura)</span>
              <input
                value={allocExpected}
                onChange={(e) => setAllocExpected(e.target.value)}
                placeholder="ej. 0.55"
              />
            </label>
            <label className="cartera-field cartera-field--full">
              <span>Fundamento</span>
              <input value={allocRationale} onChange={(e) => setAllocRationale(e.target.value)} />
            </label>
          </div>
          <button type="submit" className="cartera-btn cartera-btn--primary">
            Guardar asignación
          </button>
        </form>

        <div className="table-scroll">
          <table className="cartera-table">
            <thead>
              <tr>
                <th>Destino</th>
                <th>Monto</th>
                <th>Estado</th>
                <th>Fundamento</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(board?.allocations ?? [])
                .filter((a) => a.status !== "cancelled")
                .map((a) => (
                  <tr key={a.id}>
                    <td>{labelOrCode(ALLOCATION_DESTINATION_LABELS, a.destination)}</td>
                    <td className="cartera-mono">{fmtMoney(a.allocated_amount)}</td>
                    <td>{labelOrCode(ALLOCATION_STATUS_LABELS, a.status)}</td>
                    <td>{a.rationale ?? "—"}</td>
                    <td>
                      {a.status === "proposed" ? (
                        <button
                          type="button"
                          className="cartera-btn"
                          onClick={() => {
                            void (async () => {
                              try {
                                await patchCapitalAllocation(a.id, { status: "approved" });
                                await refresh();
                              } catch (e) {
                                onError(e instanceof Error ? e.message : "Error");
                              }
                            })();
                          }}
                        >
                          Aprobar
                        </button>
                      ) : null}{" "}
                      <button
                        type="button"
                        className="cartera-btn cartera-btn--danger"
                        onClick={() => {
                          if (!window.confirm("¿Cancelar asignación?")) return;
                          void (async () => {
                            try {
                              await deleteCapitalAllocation(a.id);
                              await refresh();
                            } catch (e) {
                              onError(e instanceof Error ? e.message : "Error");
                            }
                          })();
                        }}
                      >
                        Cancelar
                      </button>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </section>
    );
  }

  return (
    <section style={{ marginTop: "1rem", display: "grid", gap: "1rem" }}>
      <MonthCurrencyBar month={month} currency={currency} onMonth={setMonth} onCurrency={setCurrency} />
      {lev ? (
        <>
          {lev.warnings.length > 0 ? (
            <div className="cartera-alert" role="status">
              {lev.warnings.map((w) => (
                <div key={w}>⚠ {w}</div>
              ))}
            </div>
          ) : null}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: "0.75rem",
            }}
          >
            {["ARS", "USD"].map((c) => {
              const b = lev.by_currency[c];
              if (!b) return null;
              return (
                <div key={c} className="card" style={{ padding: "1rem" }}>
                  <h3 className="cartera-form__title" style={{ fontSize: "1rem" }}>
                    {c}
                    {Number(b.financed_capital) > 0 ? (
                      <span className="cartera-hint"> · deuda para invertir</span>
                    ) : null}
                  </h3>
                  <div className="cartera-hint">Capital financiado</div>
                  <div className="cartera-mono">{fmtMoney(b.financed_capital)}</div>
                  <div className="cartera-hint" style={{ marginTop: "0.4rem" }}>
                    Bruto / Neto
                  </div>
                  <div className="cartera-mono">
                    {fmtMoney(b.gross_income)} / {fmtMoney(b.net_cashflow)}
                  </div>
                  <div className="cartera-hint" style={{ marginTop: "0.4rem" }}>
                    Costo financiero
                  </div>
                  <div className="cartera-mono">{fmtMoney(b.financing_cost + b.taxes_and_fees)}</div>
                  <div className="cartera-hint" style={{ marginTop: "0.4rem" }}>
                    Rend. neto / capital financiado
                  </div>
                  <div className="cartera-mono">
                    {b.net_return_on_financed_capital === null
                      ? "—"
                      : `${(b.net_return_on_financed_capital * 100).toFixed(2)}%`}
                  </div>
                  <p className="cartera-hint" style={{ marginTop: "0.5rem" }}>
                    {b.own_capital_note}
                  </p>
                </div>
              );
            })}
          </div>
        </>
      ) : null}

      <form className="card cartera-form" onSubmit={submitLeverage}>
        <h2 className="cartera-form__title">Registro de apalancamiento</h2>
        <div className="cartera-grid">
          <label className="cartera-field">
            <span>Saldo promedio usado</span>
            <input value={levBal} onChange={(e) => setLevBal(e.target.value)} placeholder="800000" />
          </label>
          <label className="cartera-field">
            <span>TNA %</span>
            <input value={levRate} onChange={(e) => setLevRate(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Intereses pagados</span>
            <input value={levInterest} onChange={(e) => setLevInterest(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Impuestos/comisiones</span>
            <input value={levFees} onChange={(e) => setLevFees(e.target.value)} />
          </label>
        </div>
        <button type="submit" className="cartera-btn cartera-btn--primary">
          Guardar apalancamiento
        </button>
      </form>

      <form className="card cartera-form" onSubmit={submitInv}>
        <h2 className="cartera-form__title">Cashflow de inversiones (realizado)</h2>
        <div className="cartera-grid">
          <label className="cartera-field">
            <span>Cuenta</span>
            <input value={invAccount} onChange={(e) => setInvAccount(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Estrategia</span>
            <select
              value={invStrategy}
              onChange={(e) => setInvStrategy(e.target.value as FoStrategyType)}
            >
              {STRATEGIES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="cartera-field">
            <span>Bruto</span>
            <input value={invGross} onChange={(e) => setInvGross(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Comisiones</span>
            <input value={invComm} onChange={(e) => setInvComm(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Impuestos</span>
            <input value={invTax} onChange={(e) => setInvTax(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Costo financiamiento</span>
            <input value={invFin} onChange={(e) => setInvFin(e.target.value)} />
          </label>
        </div>
        <p className="cartera-hint">
          Para cubrir un gasto fijo, registrá el retiro como ingreso en Flujo o usá Aplicar (legacy) con
          fixed_expense_id. Una estimación de covered call (p.ej. 55%) es proyección, no gross_income.
        </p>
        <button type="submit" className="cartera-btn cartera-btn--primary">
          Guardar cashflow inversión
        </button>
      </form>

      <div className="table-scroll">
        <table className="cartera-table">
          <thead>
            <tr>
              <th>Tipo</th>
              <th>Detalle</th>
              <th>Moneda</th>
              <th>Monto</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {(lev?.leverage_records ?? []).map((r) => (
              <tr key={`l-${r.id}`}>
                <td>Apalancamiento</td>
                <td>
                  saldo {fmtMoney(r.average_balance_used)} · TNA {r.nominal_annual_rate}%
                </td>
                <td>{r.currency}</td>
                <td className="cartera-mono">costo {fmtMoney(r.total_financing_cost)}</td>
                <td>
                  <button
                    type="button"
                    className="cartera-btn cartera-btn--danger"
                    onClick={() => {
                      if (!window.confirm("¿Eliminar?")) return;
                      void deleteLeverageRecord(r.id).then(refresh).catch((e) => onError(String(e)));
                    }}
                  >
                    Eliminar
                  </button>
                </td>
              </tr>
            ))}
            {(lev?.investment_records ?? []).map((r) => (
              <tr key={`i-${r.id}`}>
                <td>Inversión</td>
                <td>
                  {r.account_name} · {r.strategy_type} · {r.cash_status ?? "generated"}
                </td>
                <td>{r.currency}</td>
                <td className="cartera-mono">neto {fmtMoney(r.net_cashflow)}</td>
                <td style={{ display: "flex", gap: "0.25rem", flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className="cartera-btn"
                    onClick={() => {
                      void transitionInvestmentCashStatus(r.id, { to_status: "withdrawn" })
                        .then(refresh)
                        .catch((e) => onError(String(e)));
                    }}
                  >
                    Retiro
                  </button>
                  <button
                    type="button"
                    className="cartera-btn"
                    title="Legacy: vincula fixed_expense_id y suma a assigned_cashflow en Flujo mensual"
                    onClick={() => {
                      const fe = r.fixed_expense_id;
                      if (!fe) {
                        onError("Estado applied legacy requiere fixed_expense_id en el registro.");
                        return;
                      }
                      void transitionInvestmentCashStatus(r.id, {
                        to_status: "applied",
                        fixed_expense_id: fe,
                      })
                        .then(refresh)
                        .catch((e) => onError(String(e)));
                    }}
                  >
                    Aplicar (legacy)
                  </button>
                  <button
                    type="button"
                    className="cartera-btn cartera-btn--danger"
                    onClick={() => {
                      if (!window.confirm("¿Eliminar?")) return;
                      void deleteInvestmentCashflow(r.id)
                        .then(refresh)
                        .catch((e) => onError(String(e)));
                    }}
                  >
                    Eliminar
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="cartera-hint">
        Cobertura de gastos fijos: vinculá movimientos con fixed_expense_id en Flujo mensual o usá
        Aplicar (legacy) desde aquí.
      </p>
    </section>
  );
}
