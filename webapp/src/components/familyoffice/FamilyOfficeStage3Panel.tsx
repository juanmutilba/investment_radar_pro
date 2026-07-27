import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  compareAllocationScenarios,
  confirmFoPortfolioImport,
  createAllocationScenario,
  createBusinessInvestmentCase,
  createBusinessMetric,
  createBusinessProduct,
  createBusinessUnit,
  deleteAllocationScenario,
  fetchAllocationScenarios,
  fetchBusinessInvestmentCases,
  fetchBusinessMetrics,
  fetchBusinessProducts,
  fetchBusinessUnitSummary,
  fetchBusinessUnits,
  fetchFoDebtAnalysis,
  fetchFoPortfolioSummary,
  fetchInvestmentCashStatusHistory,
  fetchInvestmentCashflows,
  previewFoPortfolioImport,
  simulateFoDebtScenario,
  transitionInvestmentCashStatus,
  type FoAllocationScenario,
  type FoAssetCurrency,
  type FoBusinessProduct,
  type FoBusinessSummary,
  type FoBusinessUnit,
  type FoCashStatus,
  type FoDebtAnalysis,
  type FoDebtScenarioResult,
  type FoImportCandidate,
  type FoImportPreview,
  type FoInvestmentCase,
  type FoPortfolioSummary,
  type FoScenarioCompare,
  type InvestmentCashflowRecord,
} from "@/services/api";
import {
  CONFIDENCE_LABELS,
  SCENARIO_DESTINATION_LABELS,
  SCENARIO_DESTINATIONS_UI,
  currentMonth,
  fmtMoney,
  labelOrCode,
  parseNonNeg,
} from "./familyOfficeLabels";

type Stage3Tab = "fuentes" | "deudas-analisis" | "negocios" | "planificacion";

type Props = {
  tab: Stage3Tab;
  onError: (m: string) => void;
};

function warnList(items?: string[] | null) {
  if (!items?.length) return null;
  return (
    <ul style={{ margin: "0.5rem 0 0", paddingLeft: "1.2rem" }}>
      {items.map((w) => (
        <li key={w} className="cartera-hint">
          {w}
        </li>
      ))}
    </ul>
  );
}

export function FamilyOfficeStage3Panel({ tab, onError }: Props) {
  if (tab === "fuentes") return <FuentesTab onError={onError} />;
  if (tab === "deudas-analisis") return <DeudasAnalisisTab onError={onError} />;
  if (tab === "negocios") return <NegociosTab onError={onError} />;
  if (tab === "planificacion") return <PlanificacionTab onError={onError} />;
  return null;
}

function FuentesTab({ onError }: { onError: (m: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState<FoPortfolioSummary | null>(null);
  const [preview, setPreview] = useState<FoImportPreview | null>(null);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [invRows, setInvRows] = useState<InvestmentCashflowRecord[]>([]);
  const [historyId, setHistoryId] = useState<number | null>(null);
  const [history, setHistory] = useState<Array<Record<string, unknown>>>([]);
  const [applyFixedId, setApplyFixedId] = useState("");
  const [month, setMonth] = useState(currentMonth());

  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      const [s, inv] = await Promise.all([
        fetchFoPortfolioSummary("real"),
        fetchInvestmentCashflows(month),
      ]);
      setSummary(s);
      setInvRows(inv);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error fuentes de datos");
    } finally {
      setBusy(false);
    }
  }, [month, onError]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function runPreview() {
    setBusy(true);
    try {
      const p = await previewFoPortfolioImport({ portfolio_type: "real" });
      setPreview(p);
      setExcluded(new Set());
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error vista previa");
    } finally {
      setBusy(false);
    }
  }

  async function runConfirm() {
    if (!preview?.candidates?.length) {
      onError("Generá primero la vista previa.");
      return;
    }
    const include = preview.candidates
      .filter((c) => !c.already_imported && !excluded.has(`${c.source_type}::${c.source_id}`))
      .map((c) => c.source_id);
    if (!include.length) {
      onError("No hay registros seleccionados para importar.");
      return;
    }
    if (!window.confirm(`¿Importar ${include.length} registro(s) a Family Office?`)) return;
    setBusy(true);
    try {
      const exclude_source_ids = preview.candidates
        .filter((c) => excluded.has(`${c.source_type}::${c.source_id}`))
        .map((c) => c.source_id);
      await confirmFoPortfolioImport({
        portfolio_type: "real",
        include_source_ids: include,
        exclude_source_ids,
      });
      await refresh();
      await runPreview();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error confirmación");
    } finally {
      setBusy(false);
    }
  }

  function toggleExclude(c: FoImportCandidate) {
    const key = `${c.source_type}::${c.source_id}`;
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function setStatus(row: InvestmentCashflowRecord, to_status: FoCashStatus) {
    try {
      const fixed =
        to_status === "applied"
          ? Number(applyFixedId || row.fixed_expense_id || 0) || null
          : row.fixed_expense_id ?? null;
      if (to_status === "applied" && !fixed) {
        onError("Para applied indicá fixed_expense_id.");
        return;
      }
      await transitionInvestmentCashStatus(row.id, {
        to_status,
        fixed_expense_id: fixed,
        notes: `Transición manual a ${to_status}`,
      });
      await refresh();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error estado cashflow");
    }
  }

  async function showHistory(id: number) {
    try {
      setHistoryId(id);
      setHistory(await fetchInvestmentCashStatusHistory(id));
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error historial");
    }
  }

  const currencies = useMemo(() => Object.keys(summary?.by_currency ?? {}), [summary]);

  return (
    <section style={{ marginTop: "1rem", display: "grid", gap: "1rem" }}>
      <div className="card" style={{ padding: "1rem" }}>
        <h3 className="cartera-form__title" style={{ fontSize: "1rem" }}>
          Fuentes de datos · Cartera (solo lectura)
        </h3>
        <p className="cartera-hint">
          Pantalla de sincronización y diagnóstico — no es el uso diario. Las primas de Cartera y el
          PnL realizado no son caja familiar hasta registrar el ingreso correspondiente en Flujo
          mensual (retiro o aplicación).
        </p>
        <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem", flexWrap: "wrap" }}>
          <button type="button" className="cartera-btn" disabled={busy} onClick={() => void refresh()}>
            Actualizar
          </button>
          <button type="button" className="cartera-btn cartera-btn--primary" disabled={busy} onClick={() => void runPreview()}>
            Vista previa de importación
          </button>
          <button type="button" className="cartera-btn" disabled={busy || !preview} onClick={() => void runConfirm()}>
            Confirmar importación
          </button>
        </div>
        {warnList(summary?.warnings)}
      </div>

      {currencies.map((cur) => {
        const row = summary?.by_currency?.[cur];
        if (!row) return null;
        return (
          <div key={cur} className="card" style={{ padding: "1rem" }}>
            <h3 className="cartera-form__title" style={{ fontSize: "1rem" }}>
              {cur}
            </h3>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                gap: "0.75rem",
                marginTop: "0.5rem",
              }}
            >
              <Metric label="Activos" value={fmtMoney(row.asset_value)} />
              <Metric label="Caja" value={fmtMoney(row.cash)} />
              <Metric label="Capital comprometido" value={fmtMoney(row.committed_capital)} />
              <Metric label="PnL realizado" value={fmtMoney(row.realized_pnl)} />
              <Metric label="Primas cobradas" value={fmtMoney(row.premiums_collected)} />
              <Metric label="Estrategias abiertas" value={String(row.open_strategies)} />
              <Metric label="Estrategias cerradas" value={String(row.closed_strategies)} />
            </div>
            <p className="cartera-hint" style={{ marginTop: "0.5rem" }}>
              Fuente: {row.data_source ?? "Cartera"} · Actualizado: {row.updated_at ?? "—"}
            </p>
            {warnList(row.missing_spot_warnings)}
          </div>
        );
      })}

      {preview ? (
        <div className="card" style={{ padding: "1rem" }}>
          <h3 className="cartera-form__title" style={{ fontSize: "1rem" }}>
            Candidatos a importar
          </h3>
          {warnList(preview.warnings)}
          <div className="table-scroll" style={{ marginTop: "0.75rem" }}>
            <table className="cartera-table">
              <thead>
                <tr>
                  <th>Incluir</th>
                  <th>Fuente</th>
                  <th>Mes</th>
                  <th>Moneda</th>
                  <th>Tipo</th>
                  <th>Neto</th>
                  <th>Estado</th>
                </tr>
              </thead>
              <tbody>
                {(preview.candidates ?? []).map((c) => {
                  const key = `${c.source_type}::${c.source_id}`;
                  const off = excluded.has(key) || !!c.already_imported;
                  return (
                    <tr key={key}>
                      <td>
                        <input
                          type="checkbox"
                          checked={!off}
                          disabled={!!c.already_imported}
                          onChange={() => toggleExclude(c)}
                        />
                      </td>
                      <td className="cartera-mono">
                        {c.source_type}/{c.source_id}
                      </td>
                      <td>{c.month}</td>
                      <td>{c.currency}</td>
                      <td>{c.strategy_type ?? "—"}</td>
                      <td className="cartera-mono">{fmtMoney(Number(c.net_cashflow ?? c.gross_income ?? 0))}</td>
                      <td>{c.already_imported ? "ya importado" : off ? "excluido" : "pendiente"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {(preview.excluded_unrealized?.length ?? 0) > 0 ? (
            <p className="cartera-hint" style={{ marginTop: "0.75rem" }}>
              Excluidos por PnL no realizado: {preview.excluded_unrealized!.length} (no son caja).
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="card" style={{ padding: "1rem", display: "grid", gap: "0.75rem" }}>
        <h3 className="cartera-form__title" style={{ fontSize: "1rem" }}>
          Estados de flujo de inversión
        </h3>
        <label className="cartera-field" style={{ maxWidth: 180 }}>
          <span>Mes</span>
          <input value={month} onChange={(e) => setMonth(e.target.value)} placeholder="YYYY-MM" />
        </label>
        <label className="cartera-field" style={{ maxWidth: 220 }}>
          <span>fixed_expense_id para applied</span>
          <input value={applyFixedId} onChange={(e) => setApplyFixedId(e.target.value)} placeholder="id" />
        </label>
        <p className="cartera-hint">
          Solo withdrawn/applied cuentan como caja familiar. Solo applied cubre un gasto fijo.
        </p>
        <div className="table-scroll">
          <table className="cartera-table">
            <thead>
              <tr>
                <th>Cuenta</th>
                <th>Estrategia</th>
                <th>Moneda</th>
                <th>Neto</th>
                <th>Estado</th>
                <th>Fuente</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {invRows.map((r) => (
                <tr key={r.id}>
                  <td>{r.account_name}</td>
                  <td>{r.strategy_type}</td>
                  <td>{r.currency}</td>
                  <td className="cartera-mono">{fmtMoney(r.net_cashflow)}</td>
                  <td>{r.cash_status ?? "generated"}</td>
                  <td className="cartera-mono">
                    {r.source_type ? `${r.source_type}/${r.source_id}` : "manual"}
                  </td>
                  <td style={{ display: "flex", gap: "0.25rem", flexWrap: "wrap" }}>
                    <button type="button" className="cartera-btn" onClick={() => void setStatus(r, "settled")}>
                      Settled
                    </button>
                    <button type="button" className="cartera-btn" onClick={() => void setStatus(r, "withdrawn")}>
                      Retiro
                    </button>
                    <button type="button" className="cartera-btn" onClick={() => void setStatus(r, "applied")}>
                      Aplicar
                    </button>
                    <button type="button" className="cartera-btn" onClick={() => void showHistory(r.id)}>
                      Historial
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {historyId != null ? (
          <div>
            <p className="cartera-hint">Historial #{historyId}</p>
            <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
              {history.map((h, i) => (
                <li key={i} className="cartera-mono">
                  {String(h.from_status ?? "—")} → {String(h.to_status)} · {String(h.changed_at ?? "")}{" "}
                  {h.notes ? `· ${String(h.notes)}` : ""}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="cartera-hint">{label}</div>
      <div className="cartera-mono">{value}</div>
    </div>
  );
}

function DeudasAnalisisTab({ onError }: { onError: (m: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [analysis, setAnalysis] = useState<FoDebtAnalysis | null>(null);
  const [liabilityId, setLiabilityId] = useState("");
  const [amount, setAmount] = useState("");
  const [scenarioType, setScenarioType] = useState<"reduce_term" | "reduce_installment" | "full_cancel">(
    "reduce_term",
  );
  const [result, setResult] = useState<FoDebtScenarioResult | null>(null);

  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      setAnalysis(await fetchFoDebtAnalysis());
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error análisis deudas");
    } finally {
      setBusy(false);
    }
  }, [onError]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function runSim(ev: FormEvent) {
    ev.preventDefault();
    const prepayment_amount = parseNonNeg(amount);
    const liability_id = Number(liabilityId);
    if (prepayment_amount === null || !liability_id) {
      onError("Indicá deuda y monto de precancelación.");
      return;
    }
    try {
      setResult(
        await simulateFoDebtScenario({
          liability_id,
          prepayment_amount,
          scenario_type: scenarioType,
        }),
      );
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error simulación");
    }
  }

  return (
    <section style={{ marginTop: "1rem", display: "grid", gap: "1rem" }}>
      <div style={{ display: "flex", gap: "0.5rem" }}>
        <button type="button" className="cartera-btn" disabled={busy} onClick={() => void refresh()}>
          Actualizar análisis
        </button>
      </div>
      <p className="cartera-hint">
        Score informativo — no es una orden de cancelar. No se suman deudas en monedas distintas.
      </p>
      {warnList(analysis?.warnings)}
      {Object.entries(analysis?.by_currency ?? {}).map(([cur, block]) => {
        const items = Array.isArray(block) ? block : block.items ?? [];
        if (!items.length) return null;
        return (
        <div key={cur} className="card" style={{ padding: "1rem" }}>
          <h3 className="cartera-form__title" style={{ fontSize: "1rem" }}>
            Deudas {cur}
          </h3>
          <div className="table-scroll" style={{ marginTop: "0.5rem" }}>
            <table className="cartera-table">
              <thead>
                <tr>
                  <th>Id</th>
                  <th>Nombre</th>
                  <th>Saldo</th>
                  <th>Cuota</th>
                  <th>Tasa</th>
                  <th>Meses</th>
                  <th>Flujo mes</th>
                  <th>Ret. equiv.</th>
                  <th>Liquidez</th>
                  <th>Score</th>
                  <th>Faltantes</th>
                </tr>
              </thead>
              <tbody>
                {items.map((d) => (
                  <tr key={d.liability_id}>
                    <td>{d.liability_id}</td>
                    <td>{d.name}</td>
                    <td className="cartera-mono">{fmtMoney(d.outstanding_balance)}</td>
                    <td className="cartera-mono">{fmtMoney(Number(d.installment ?? 0))}</td>
                    <td>
                      {(d.informed_rate ?? d.nominal_annual_rate) != null
                        ? `${d.informed_rate ?? d.nominal_annual_rate}%`
                        : "—"}
                    </td>
                    <td>{d.months_remaining ?? "—"}</td>
                    <td className="cartera-mono">
                      {fmtMoney(
                        Number(d.committed_monthly_cashflow ?? d.monthly_committed_cashflow ?? 0),
                      )}
                    </td>
                    <td>
                      {d.cancel_equivalent_return ?? d.cancel_equivalent_return_pct ?? "—"}
                    </td>
                    <td className="cartera-mono">
                      {fmtMoney(Number(d.liquidity_needed ?? d.liquidity_needed_to_cancel ?? 0))}
                    </td>
                    <td>{d.informative_score ?? d.informational_score ?? "—"}</td>
                    <td className="cartera-hint">{(d.missing_data ?? []).join(", ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        );
      })}

      <form className="card cartera-form" onSubmit={runSim}>
        <h2 className="cartera-form__title">Simulador de precancelación</h2>
        <div className="cartera-grid">
          <label className="cartera-field">
            <span>liability_id</span>
            <input value={liabilityId} onChange={(e) => setLiabilityId(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Monto</span>
            <input value={amount} onChange={(e) => setAmount(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Escenario</span>
            <select
              value={scenarioType}
              onChange={(e) => setScenarioType(e.target.value as typeof scenarioType)}
            >
              <option value="reduce_term">Reducir plazo</option>
              <option value="reduce_installment">Reducir cuota</option>
              <option value="full_cancel">Cancelación total</option>
            </select>
          </label>
        </div>
        <button type="submit" className="cartera-btn cartera-btn--primary">
          Simular
        </button>
      </form>

      {result ? (
        <div className="card" style={{ padding: "1rem" }}>
          <h3 className="cartera-form__title" style={{ fontSize: "1rem" }}>
            Resultado {result.approximate ? "(aproximado)" : ""}
          </h3>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
              gap: "0.75rem",
              marginTop: "0.5rem",
            }}
          >
            <Metric label="Saldo posterior" value={fmtMoney(Number(result.balance_after ?? result.outstanding_after ?? 0))} />
            <Metric
              label="Interés evitado est."
              value={fmtMoney(Number(result.interest_avoided_estimate ?? 0))}
            />
            <Metric
              label="Cuotas/plazo est."
              value={String(
                result.months_after ??
                  result.estimated_remaining_installments ??
                  result.estimated_term_months ??
                  "—",
              )}
            />
            <Metric
              label="Flujo mensual liberado"
              value={fmtMoney(Number(result.monthly_cashflow_freed ?? 0))}
            />
          </div>
          {warnList(result.warnings)}
          {result.assumptions_used ? (
            <pre className="cartera-hint" style={{ whiteSpace: "pre-wrap", marginTop: "0.75rem" }}>
              {JSON.stringify(result.assumptions_used, null, 2)}
            </pre>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function NegociosTab({ onError }: { onError: (m: string) => void }) {
  const [units, setUnits] = useState<FoBusinessUnit[]>([]);
  const [unitId, setUnitId] = useState<number | null>(null);
  const [summary, setSummary] = useState<FoBusinessSummary | null>(null);
  const [products, setProducts] = useState<FoBusinessProduct[]>([]);
  const [cases, setCases] = useState<FoInvestmentCase[]>([]);
  const [metricsMonth, setMetricsMonth] = useState(currentMonth());

  const [newUnitName, setNewUnitName] = useState("Salva Foods");
  const [newUnitType, setNewUnitType] = useState<FoBusinessUnit["unit_type"]>("salva");
  const [prodName, setProdName] = useState("Pasta de maní 360 g");
  const [prodPrice, setProdPrice] = useState("2600");
  const [prodCost, setProdCost] = useState("1878");
  const [rev, setRev] = useState("");
  const [varCost, setVarCost] = useState("");
  const [fixCost, setFixCost] = useState("");
  const [ownerHours, setOwnerHours] = useState("");
  const [caseName, setCaseName] = useState("");
  const [caseAmt, setCaseAmt] = useState("");
  const [caseProfit, setCaseProfit] = useState("");
  const [caseBottleneck, setCaseBottleneck] = useState("production");

  const refreshUnits = useCallback(async () => {
    try {
      const list = await fetchBusinessUnits(true);
      setUnits(list);
      if (unitId == null && list[0]) setUnitId(list[0].id);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error unidades");
    }
  }, [onError, unitId]);

  const refreshUnit = useCallback(async () => {
    if (unitId == null) return;
    try {
      const [s, p, c] = await Promise.all([
        fetchBusinessUnitSummary(unitId),
        fetchBusinessProducts(unitId),
        fetchBusinessInvestmentCases(unitId),
      ]);
      setSummary(s);
      setProducts(p);
      setCases(c);
      await fetchBusinessMetrics(unitId);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error negocio");
    }
  }, [unitId, onError]);

  useEffect(() => {
    void refreshUnits();
  }, [refreshUnits]);

  useEffect(() => {
    void refreshUnit();
  }, [refreshUnit]);

  async function createUnit(ev: FormEvent) {
    ev.preventDefault();
    try {
      const u = await createBusinessUnit({
        name: newUnitName.trim(),
        unit_type: newUnitType,
        currency: "ARS",
        notes: "Carga manual desde UI. Sin valuación automática.",
      });
      setUnitId(u.id);
      await refreshUnits();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error alta unidad");
    }
  }

  async function addProduct(ev: FormEvent) {
    ev.preventDefault();
    if (unitId == null) return;
    const sale_price = parseNonNeg(prodPrice);
    const variable_cost = parseNonNeg(prodCost);
    if (sale_price === null || variable_cost === null || !prodName.trim()) {
      onError("Producto inválido.");
      return;
    }
    try {
      await createBusinessProduct(unitId, {
        name: prodName.trim(),
        unit: "jar",
        sale_price,
        variable_cost,
        notes: "Valores de referencia cargados en UI (no hardcodeados en migración).",
      });
      await refreshUnit();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error producto");
    }
  }

  async function addMetric(ev: FormEvent) {
    ev.preventDefault();
    if (unitId == null) return;
    const revenue = parseNonNeg(rev);
    const variable_costs = parseNonNeg(varCost);
    const fixed_costs = parseNonNeg(fixCost);
    const owner_hours = parseNonNeg(ownerHours);
    if (
      revenue === null ||
      variable_costs === null ||
      fixed_costs === null ||
      owner_hours === null
    ) {
      onError("Métricas inválidas.");
      return;
    }
    try {
      await createBusinessMetric(unitId, {
        month: metricsMonth,
        currency: "ARS",
        revenue,
        variable_costs,
        fixed_costs,
        owner_hours,
        outsourced_hours: 0,
      });
      setRev("");
      await refreshUnit();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error métricas");
    }
  }

  async function addCase(ev: FormEvent) {
    ev.preventDefault();
    if (unitId == null) return;
    const investment_amount = parseNonNeg(caseAmt);
    const expected_monthly_profit_increment = parseNonNeg(caseProfit);
    if (investment_amount === null || expected_monthly_profit_increment === null || !caseName.trim()) {
      onError("Caso de inversión inválido.");
      return;
    }
    try {
      await createBusinessInvestmentCase(unitId, {
        name: caseName.trim(),
        currency: "ARS",
        investment_amount,
        investment_type: "machinery",
        bottleneck: caseBottleneck,
        expected_monthly_revenue_increment: expected_monthly_profit_increment,
        expected_monthly_cost_increment: 0,
        expected_monthly_profit_increment,
        expected_hours_saved: 0,
        expected_start_month: metricsMonth,
        status: "draft",
        assumptions: "Proyección manual. No equivale a valuación de la unidad.",
      });
      setCaseName("");
      await refreshUnit();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error caso");
    }
  }

  return (
    <section style={{ marginTop: "1rem", display: "grid", gap: "1rem" }}>
      <form className="card cartera-form" onSubmit={createUnit}>
        <h2 className="cartera-form__title">Unidad económica</h2>
        <div className="cartera-grid">
          <label className="cartera-field">
            <span>Nombre</span>
            <input value={newUnitName} onChange={(e) => setNewUnitName(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Tipo</span>
            <select
              value={newUnitType}
              onChange={(e) => setNewUnitType(e.target.value as FoBusinessUnit["unit_type"])}
            >
              <option value="salva">Salva</option>
              <option value="consulting">Consulting</option>
              <option value="investment_radar">Investment Radar</option>
              <option value="other">Otra</option>
            </select>
          </label>
        </div>
        <button type="submit" className="cartera-btn cartera-btn--primary">
          Crear unidad
        </button>
      </form>

      <label className="cartera-field" style={{ maxWidth: 320 }}>
        <span>Selector</span>
        <select
          value={unitId ?? ""}
          onChange={(e) => setUnitId(e.target.value ? Number(e.target.value) : null)}
        >
          <option value="">—</option>
          {units.map((u) => (
            <option key={u.id} value={u.id}>
              {u.name} ({u.unit_type})
            </option>
          ))}
        </select>
      </label>

      {summary ? (
        <div className="card" style={{ padding: "1rem" }}>
          <h3 className="cartera-form__title" style={{ fontSize: "1rem" }}>
            Resumen {(summary.unit as FoBusinessUnit | undefined)?.name ?? ""}
          </h3>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
              gap: "0.75rem",
              marginTop: "0.5rem",
            }}
          >
            <Metric
              label="Ingresos"
              value={fmtMoney(
                Number(
                  summary.revenue ??
                    (summary.latest_metrics as { revenue?: number } | undefined)?.revenue ??
                    0,
                ),
              )}
            />
            <Metric label="Margen bruto" value={fmtMoney(Number(summary.gross_profit ?? 0))} />
            <Metric label="Utilidad operativa" value={fmtMoney(Number(summary.operating_profit ?? 0))} />
            <Metric
              label="Utilidad / hora dueño"
              value={
                summary.profit_per_owner_hour != null
                  ? fmtMoney(Number(summary.profit_per_owner_hour))
                  : "—"
              }
            />
            <Metric
              label="Unidades / hora dueño"
              value={
                summary.units_per_owner_hour != null ? String(summary.units_per_owner_hour) : "—"
              }
            />
            <Metric
              label="Dep. fundador"
              value={
                summary.founder_dependency_index != null
                  ? String(summary.founder_dependency_index)
                  : "—"
              }
            />
            <Metric
              label="Cuello de botella"
              value={String(summary.current_bottleneck_hint ?? summary.bottleneck ?? "—")}
            />
            <Metric
              label="CT aproximado"
              value={
                (summary.working_capital_approx ?? summary.approx_working_capital) != null
                  ? fmtMoney(
                      Number(summary.working_capital_approx ?? summary.approx_working_capital),
                    )
                  : "—"
              }
            />
          </div>
          <p className="cartera-hint" style={{ marginTop: "0.5rem" }}>
            No se valúa la unidad automáticamente. Facturación ≠ rentabilidad.
          </p>
          {warnList(summary.notes)}
        </div>
      ) : null}

      <form className="card cartera-form" onSubmit={addMetric}>
        <h2 className="cartera-form__title">Métricas mensuales</h2>
        <div className="cartera-grid">
          <label className="cartera-field">
            <span>Mes</span>
            <input value={metricsMonth} onChange={(e) => setMetricsMonth(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Revenue</span>
            <input value={rev} onChange={(e) => setRev(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Costos variables</span>
            <input value={varCost} onChange={(e) => setVarCost(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Costos fijos</span>
            <input value={fixCost} onChange={(e) => setFixCost(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Horas dueño</span>
            <input value={ownerHours} onChange={(e) => setOwnerHours(e.target.value)} />
          </label>
        </div>
        <button type="submit" className="cartera-btn cartera-btn--primary">
          Guardar métricas
        </button>
      </form>

      <form className="card cartera-form" onSubmit={addProduct}>
        <h2 className="cartera-form__title">Producto</h2>
        <div className="cartera-grid">
          <label className="cartera-field">
            <span>Nombre</span>
            <input value={prodName} onChange={(e) => setProdName(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Precio</span>
            <input value={prodPrice} onChange={(e) => setProdPrice(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Costo variable</span>
            <input value={prodCost} onChange={(e) => setProdCost(e.target.value)} />
          </label>
        </div>
        <button type="submit" className="cartera-btn cartera-btn--primary">
          Alta producto
        </button>
      </form>

      <div className="table-scroll">
        <table className="cartera-table">
          <thead>
            <tr>
              <th>Producto</th>
              <th>Precio</th>
              <th>Costo var.</th>
              <th>Margen bruto</th>
            </tr>
          </thead>
          <tbody>
            {products.map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td className="cartera-mono">{fmtMoney(p.sale_price)}</td>
                <td className="cartera-mono">{fmtMoney(p.variable_cost)}</td>
                <td className="cartera-mono">{fmtMoney(p.gross_margin)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <form className="card cartera-form" onSubmit={addCase}>
        <h2 className="cartera-form__title">Caso de inversión</h2>
        <div className="cartera-grid">
          <label className="cartera-field">
            <span>Nombre</span>
            <input value={caseName} onChange={(e) => setCaseName(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Monto</span>
            <input value={caseAmt} onChange={(e) => setCaseAmt(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Δ utilidad mensual</span>
            <input value={caseProfit} onChange={(e) => setCaseProfit(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Cuello de botella</span>
            <select value={caseBottleneck} onChange={(e) => setCaseBottleneck(e.target.value)}>
              <option value="production">production</option>
              <option value="sales">sales</option>
              <option value="logistics">logistics</option>
              <option value="administration">administration</option>
              <option value="working_capital">working_capital</option>
              <option value="founder_dependency">founder_dependency</option>
              <option value="other">other</option>
            </select>
          </label>
        </div>
        <button type="submit" className="cartera-btn cartera-btn--primary">
          Crear caso
        </button>
      </form>

      <div className="table-scroll">
        <table className="cartera-table">
          <thead>
            <tr>
              <th>Caso</th>
              <th>Monto</th>
              <th>Δ utilidad</th>
              <th>Payback</th>
              <th>Bottleneck</th>
              <th>Estado</th>
            </tr>
          </thead>
          <tbody>
            {cases.map((c) => (
              <tr key={c.id}>
                <td>{c.name}</td>
                <td className="cartera-mono">{fmtMoney(c.investment_amount)}</td>
                <td className="cartera-mono">{fmtMoney(c.expected_monthly_profit_increment)}</td>
                <td>{c.payback_months ?? "—"}</td>
                <td>{c.bottleneck}</td>
                <td>{c.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function PlanificacionTab({ onError }: { onError: (m: string) => void }) {
  const [month, setMonth] = useState(currentMonth());
  const [currency, setCurrency] = useState<FoAssetCurrency>("ARS");
  const [rows, setRows] = useState<FoAllocationScenario[]>([]);
  const [compare, setCompare] = useState<FoScenarioCompare | null>(null);
  const [name, setName] = useState("Cubrir jardín vía Veta");
  const [available, setAvailable] = useState("");
  const [alloc, setAlloc] = useState("");
  const [dest, setDest] = useState("house");
  const [monthlyCf, setMonthlyCf] = useState("");
  const [annRet, setAnnRet] = useState("0.55");
  const [liq, setLiq] = useState("50");
  const [risk, setRisk] = useState("50");
  const [hours, setHours] = useState("0");
  const [confidence, setConfidence] = useState<"low" | "medium" | "high">("low");

  const refresh = useCallback(async () => {
    try {
      setRows(await fetchAllocationScenarios(month, currency));
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error planificación");
    }
  }, [month, currency, onError]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function createSc(ev: FormEvent) {
    ev.preventDefault();
    const available_capital = parseNonNeg(available);
    const allocation_amount = parseNonNeg(alloc);
    const expected_monthly_cashflow = parseNonNeg(monthlyCf);
    const expected_annual_return = parseNonNeg(annRet);
    const liquidity_score = parseNonNeg(liq);
    const risk_score = parseNonNeg(risk);
    const expected_hours_saved = parseNonNeg(hours);
    if (
      available_capital === null ||
      allocation_amount === null ||
      expected_monthly_cashflow === null ||
      expected_annual_return === null ||
      liquidity_score === null ||
      risk_score === null ||
      expected_hours_saved === null ||
      !name.trim()
    ) {
      onError("Completá el escenario con montos válidos.");
      return;
    }
    try {
      await createAllocationScenario({
        name: name.trim(),
        month,
        currency,
        available_capital,
        destination_type: dest,
        allocation_amount,
        expected_monthly_cashflow,
        expected_annual_return,
        expected_hours_saved,
        liquidity_score,
        risk_score,
        confidence,
        assumptions:
          dest === "portfolio"
            ? "Covered call 55% es proyección, no resultado realizado. Objetivo Veta: cubrir jardín primero."
            : "Escenario manual comparativo — no es orden automática.",
        is_selected: false,
      });
      await refresh();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error crear escenario");
    }
  }

  async function runCompare() {
    try {
      setCompare(await compareAllocationScenarios({ month, currency }));
    } catch (e) {
      onError(e instanceof Error ? e.message : "Error comparación");
    }
  }

  return (
    <section style={{ marginTop: "1rem", display: "grid", gap: "1rem" }}>
      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
        <label className="cartera-field">
          <span>Mes</span>
          <input value={month} onChange={(e) => setMonth(e.target.value)} />
        </label>
        <label className="cartera-field">
          <span>Moneda</span>
          <select value={currency} onChange={(e) => setCurrency(e.target.value as FoAssetCurrency)}>
            <option value="ARS">ARS</option>
            <option value="USD">USD</option>
          </select>
        </label>
        <button type="button" className="cartera-btn" onClick={() => void refresh()}>
          Actualizar
        </button>
        <button type="button" className="cartera-btn cartera-btn--primary" onClick={() => void runCompare()}>
          Comparar lado a lado
        </button>
      </div>
      <p className="cartera-hint">
        Planificación: escenarios de asignación de capital. Metas y proyecciones se agregarán
        aquí. Comparación explicativa — no selecciona automáticamente una alternativa.
      </p>

      <form className="card cartera-form" onSubmit={createSc}>
        <h2 className="cartera-form__title">Nueva alternativa</h2>
        <div className="cartera-grid">
          <label className="cartera-field">
            <span>Nombre</span>
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Capital disponible</span>
            <input value={available} onChange={(e) => setAvailable(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Asignación</span>
            <input value={alloc} onChange={(e) => setAlloc(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Destino</span>
            <select value={dest} onChange={(e) => setDest(e.target.value)}>
              {SCENARIO_DESTINATIONS_UI.map((d) => (
                <option key={d} value={d}>
                  {labelOrCode(SCENARIO_DESTINATION_LABELS, d)}
                </option>
              ))}
            </select>
          </label>
          <label className="cartera-field">
            <span>Caja mensual esperada</span>
            <input value={monthlyCf} onChange={(e) => setMonthlyCf(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Retorno anual esp. (ej. 0.55)</span>
            <input value={annRet} onChange={(e) => setAnnRet(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Liquidez (0-100)</span>
            <input value={liq} onChange={(e) => setLiq(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Riesgo (0-100)</span>
            <input value={risk} onChange={(e) => setRisk(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Horas liberadas</span>
            <input value={hours} onChange={(e) => setHours(e.target.value)} />
          </label>
          <label className="cartera-field">
            <span>Confianza</span>
            <select
              value={confidence}
              onChange={(e) => setConfidence(e.target.value as typeof confidence)}
            >
              <option value="low">{labelOrCode(CONFIDENCE_LABELS, "low")}</option>
              <option value="medium">{labelOrCode(CONFIDENCE_LABELS, "medium")}</option>
              <option value="high">{labelOrCode(CONFIDENCE_LABELS, "high")}</option>
            </select>
          </label>
        </div>
        <button type="submit" className="cartera-btn cartera-btn--primary">
          Crear escenario
        </button>
      </form>

      <div className="table-scroll">
        <table className="cartera-table">
          <thead>
            <tr>
              <th>Nombre</th>
              <th>Destino</th>
              <th>Asignación</th>
              <th>Caja mes</th>
              <th>Retorno</th>
              <th>Riesgo</th>
              <th>Liquidez</th>
              <th>Confianza</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.name}</td>
                <td>{labelOrCode(SCENARIO_DESTINATION_LABELS, r.destination_type)}</td>
                <td className="cartera-mono">{fmtMoney(r.allocation_amount)}</td>
                <td className="cartera-mono">{fmtMoney(Number(r.expected_monthly_cashflow ?? 0))}</td>
                <td>{r.expected_annual_return ?? "—"}</td>
                <td>{r.risk_score}</td>
                <td>{r.liquidity_score}</td>
                <td>{labelOrCode(CONFIDENCE_LABELS, r.confidence)}</td>
                <td>
                  <button
                    type="button"
                    className="cartera-btn cartera-btn--danger"
                    onClick={() => {
                      if (!window.confirm("¿Eliminar escenario?")) return;
                      void deleteAllocationScenario(r.id).then(refresh).catch((e) => onError(String(e)));
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

      {compare ? (
        <div className="card" style={{ padding: "1rem" }}>
          <h3 className="cartera-form__title" style={{ fontSize: "1rem" }}>
            Comparación
          </h3>
          <pre className="cartera-hint" style={{ whiteSpace: "pre-wrap" }}>
            {JSON.stringify(
              {
                highlights: compare.highlights,
                missing_data: compare.missing_data,
                projection_vs_realized: compare.projection_vs_realized,
                notes: compare.notes,
              },
              null,
              2,
            )}
          </pre>
        </div>
      ) : null}
    </section>
  );
}
