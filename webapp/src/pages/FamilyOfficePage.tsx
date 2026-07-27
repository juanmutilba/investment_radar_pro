import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AssetFormModal,
  HouseProjectFormModal,
  LiabilityFormModal,
  PolicyFormModal,
  SnapshotFormModal,
} from "@/components/familyoffice/FamilyOfficeModals";
import { FamilyOfficeStage2Panel } from "@/components/familyoffice/FamilyOfficeStage2Panel";
import { FamilyOfficeStage3Panel } from "@/components/familyoffice/FamilyOfficeStage3Panel";
import {
  ASSET_CATEGORY_LABELS,
  HOUSE_PRIORITY_LABELS,
  HOUSE_STATUS_LABELS,
  LIABILITY_TYPE_LABELS,
  LIQUIDITY_LABELS,
  OWNERSHIP_LABELS,
  POLICY_DESTINATION_LABELS,
  currentMonth,
  fmtMoney,
} from "@/components/familyoffice/familyOfficeLabels";
import {
  deleteCapitalPolicy,
  deleteFamilyAsset,
  deleteFamilyLiability,
  deleteHouseProject,
  fetchCapitalPolicies,
  fetchFamilyAssets,
  fetchFamilyLiabilities,
  fetchFamilyOfficeDashboard,
  fetchFoAllocationBoard,
  fetchHouseProjects,
  type CapitalPolicy,
  type FamilyAsset,
  type FamilyLiability,
  type FamilyOfficeDashboard,
  type FoAssetCurrency,
  type FoHousePriority,
  type FoHouseStatus,
  type HouseProject,
} from "@/services/api";

type Tab =
  | "resumen"
  | "flujo"
  | "cobertura"
  | "asignacion"
  | "apalancamiento"
  | "fuentes"
  | "deudas-analisis"
  | "negocios"
  | "planificacion"
  | "activos"
  | "deudas"
  | "casa"
  | "politicas";

const STAGE2_TABS = new Set(["flujo", "cobertura", "asignacion", "apalancamiento"]);
const STAGE3_TABS = new Set(["fuentes", "deudas-analisis", "negocios", "planificacion"]);

function CurrencyGrid({
  title,
  values,
  currencies,
}: {
  title: string;
  values: Record<string, number> | undefined;
  currencies: string[];
}) {
  return (
    <div className="card" style={{ padding: "1rem" }}>
      <h3 className="cartera-form__title" style={{ marginBottom: "0.75rem", fontSize: "1rem" }}>
        {title}
      </h3>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
          gap: "0.75rem",
        }}
      >
        {currencies.map((c) => (
          <div key={c}>
            <div className="cartera-hint" style={{ marginBottom: "0.2rem" }}>
              {c}
            </div>
            <div className="cartera-mono" style={{ fontSize: "1.02rem" }}>
              {c} {fmtMoney(values?.[c] ?? 0)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function FamilyOfficePage() {
  const [tab, setTab] = useState<Tab>("resumen");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [dash, setDash] = useState<FamilyOfficeDashboard | null>(null);
  const [assets, setAssets] = useState<FamilyAsset[]>([]);
  const [liabilities, setLiabilities] = useState<FamilyLiability[]>([]);
  const [projects, setProjects] = useState<HouseProject[]>([]);
  const [policies, setPolicies] = useState<CapitalPolicy[]>([]);
  const [houseFilterPriority, setHouseFilterPriority] = useState<FoHousePriority | "all">("all");
  const [houseFilterStatus, setHouseFilterStatus] = useState<FoHouseStatus | "all">("all");
  const [houseReserveArs, setHouseReserveArs] = useState(0);
  const [houseReserveUsd, setHouseReserveUsd] = useState(0);

  const [assetModal, setAssetModal] = useState<{ open: boolean; row: FamilyAsset | null }>({
    open: false,
    row: null,
  });
  const [liabilityModal, setLiabilityModal] = useState<{
    open: boolean;
    row: FamilyLiability | null;
  }>({ open: false, row: null });
  const [houseModal, setHouseModal] = useState<{ open: boolean; row: HouseProject | null }>({
    open: false,
    row: null,
  });
  const [policyModal, setPolicyModal] = useState<{ open: boolean; row: CapitalPolicy | null }>({
    open: false,
    row: null,
  });
  const [snapshotOpen, setSnapshotOpen] = useState(false);

  const loadResumen = useCallback(async () => {
    setDash(await fetchFamilyOfficeDashboard());
  }, []);

  const loadAssets = useCallback(async () => {
    setAssets(await fetchFamilyAssets(true));
  }, []);

  const loadLiabilities = useCallback(async () => {
    setLiabilities(await fetchFamilyLiabilities(true));
  }, []);

  const loadProjects = useCallback(async () => {
    setProjects(await fetchHouseProjects(true));
    const m = currentMonth();
    try {
      const [ars, usd] = await Promise.all([
        fetchFoAllocationBoard(m, "ARS" as FoAssetCurrency),
        fetchFoAllocationBoard(m, "USD" as FoAssetCurrency),
      ]);
      setHouseReserveArs(ars.house_monthly_reserve);
      setHouseReserveUsd(usd.house_monthly_reserve);
    } catch {
      setHouseReserveArs(0);
      setHouseReserveUsd(0);
    }
  }, []);

  const loadPolicies = useCallback(async () => {
    setPolicies(await fetchCapitalPolicies(true));
  }, []);

  const refreshTab = useCallback(async () => {
    if (STAGE2_TABS.has(tab) || STAGE3_TABS.has(tab)) {
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      if (tab === "resumen") await loadResumen();
      else if (tab === "activos") await loadAssets();
      else if (tab === "deudas") await Promise.all([loadLiabilities(), loadAssets()]);
      else if (tab === "casa") await loadProjects();
      else if (tab === "politicas") await loadPolicies();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error al cargar Family Office");
    } finally {
      setBusy(false);
    }
  }, [tab, loadResumen, loadAssets, loadLiabilities, loadProjects, loadPolicies]);

  useEffect(() => {
    void refreshTab();
  }, [refreshTab]);

  async function onSaved() {
    await refreshTab();
  }

  const filteredProjects = useMemo(() => {
    return projects.filter((p) => {
      if (houseFilterPriority !== "all" && p.priority !== houseFilterPriority) return false;
      if (houseFilterStatus !== "all" && p.status !== houseFilterStatus) return false;
      return true;
    });
  }, [projects, houseFilterPriority, houseFilterStatus]);

  const houseBudget = useMemo(() => {
    const byCur: Record<string, { estimated: number; paid: number }> = {
      ARS: { estimated: 0, paid: 0 },
      USD: { estimated: 0, paid: 0 },
    };
    for (const p of filteredProjects) {
      const c = p.currency in byCur ? p.currency : "ARS";
      byCur[c].estimated += Number(p.estimated_cost || 0);
      byCur[c].paid += Number(p.paid_amount || 0);
    }
    return byCur;
  }, [filteredProjects]);

  const tabs: { id: Tab; label: string }[] = [
    { id: "resumen", label: "Resumen" },
    { id: "flujo", label: "Flujo mensual" },
    { id: "cobertura", label: "Cobertura" },
    { id: "asignacion", label: "Asignación de capital" },
    { id: "apalancamiento", label: "Apalancamiento" },
    { id: "activos", label: "Activos" },
    { id: "deudas", label: "Deudas" },
    { id: "deudas-analisis", label: "Análisis de deudas" },
    { id: "casa", label: "Casa" },
    { id: "politicas", label: "Políticas" },
    { id: "fuentes", label: "Fuentes de datos" },
    { id: "negocios", label: "Negocios" },
    { id: "planificacion", label: "Planificación" },
  ];

  return (
    <div className="page">
      <header style={{ marginBottom: "1rem" }}>
        <h1 className="page-title">Family Office</h1>
        <p className="page-desc">
          Administración patrimonial familiar. ARS, USD y UVA por separado. El flujo mensual es la
          fuente de ingresos, egresos y asignaciones.
        </p>
      </header>

      <div className="cartera-tabs" role="tablist" aria-label="Secciones Family Office">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={tab === t.id ? "cartera-tab cartera-tab--active" : "cartera-tab"}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {err ? (
        <div className="cartera-alert" role="alert" style={{ marginTop: "0.75rem" }}>
          {err}
        </div>
      ) : null}

      {busy ? <p className="cartera-hint" style={{ marginTop: "0.75rem" }}>Cargando…</p> : null}

      {STAGE2_TABS.has(tab) ? (
        <FamilyOfficeStage2Panel
          tab={tab as "flujo" | "cobertura" | "asignacion" | "apalancamiento"}
          onError={(m) => setErr(m)}
        />
      ) : null}

      {STAGE3_TABS.has(tab) ? (
        <FamilyOfficeStage3Panel
          tab={tab as "fuentes" | "deudas-analisis" | "negocios" | "planificacion"}
          onError={(m) => setErr(m)}
        />
      ) : null}

      {tab === "resumen" ? (
        <section style={{ marginTop: "1rem", display: "grid", gap: "1rem" }}>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <button
              type="button"
              className="cartera-btn cartera-btn--primary"
              onClick={() => setSnapshotOpen(true)}
            >
              Cargar snapshot mensual
            </button>
            <button type="button" className="cartera-btn" onClick={() => void refreshTab()}>
              Actualizar
            </button>
          </div>
          {!busy && !dash ? <p className="cartera-empty">Sin datos de resumen.</p> : null}
          {dash ? (
            <>
              <CurrencyGrid title="Activos por moneda" values={dash.assets_by_currency} currencies={["ARS", "USD"]} />
              <CurrencyGrid title="Pasivos por moneda" values={dash.liabilities_by_currency} currencies={["ARS", "USD", "UVA"]} />
              <CurrencyGrid title="Patrimonio neto por moneda" values={dash.net_worth_by_currency} currencies={["ARS", "USD", "UVA"]} />
              <CurrencyGrid title="Activos líquidos" values={dash.liquid_assets_by_currency} currencies={["ARS", "USD"]} />
              <CurrencyGrid title="Activos generadores de flujo" values={dash.cashflow_assets_by_currency} currencies={["ARS", "USD"]} />
              <CurrencyGrid title="Flujo mensual generado" values={dash.monthly_cashflow_by_currency} currencies={["ARS", "USD"]} />
              <div className="card" style={{ padding: "1rem" }}>
                <h3 className="cartera-form__title" style={{ fontSize: "1rem" }}>Último snapshot</h3>
                {dash.latest_free_cashflow === null ? (
                  <p className="cartera-empty">Todavía no hay snapshot mensual.</p>
                ) : (
                  <p className="cartera-mono" style={{ marginTop: "0.5rem" }}>
                    {dash.latest_snapshot_month} · {dash.latest_snapshot_currency}{" "}
                    {fmtMoney(dash.latest_free_cashflow)} flujo libre
                  </p>
                )}
              </div>
              {dash.alerts.length > 0 ? (
                <div className="card" style={{ padding: "1rem" }}>
                  <h3 className="cartera-form__title" style={{ fontSize: "1rem" }}>Alertas de datos</h3>
                  <ul style={{ margin: "0.5rem 0 0", paddingLeft: "1.2rem" }}>
                    {dash.alerts.map((a) => (
                      <li key={a} className="cartera-hint">{a}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </>
          ) : null}
        </section>
      ) : null}

      {tab === "activos" ? (
        <section style={{ marginTop: "1rem" }}>
          <button type="button" className="cartera-btn cartera-btn--primary" onClick={() => setAssetModal({ open: true, row: null })}>
            Nuevo activo
          </button>
          {!busy && assets.length === 0 ? (
            <p className="cartera-empty">No hay activos activos.</p>
          ) : (
            <div className="table-scroll" style={{ marginTop: "0.75rem" }}>
              <table className="cartera-table">
                <thead>
                  <tr>
                    <th>Nombre</th><th>Categoría</th><th>Titularidad</th><th>Moneda</th><th>Valor</th><th>Liquidez</th><th>Flujo</th><th>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {assets.map((a) => (
                    <tr key={a.id}>
                      <td>{a.name}</td>
                      <td>{ASSET_CATEGORY_LABELS[a.category]}</td>
                      <td>{OWNERSHIP_LABELS[a.ownership_status]}</td>
                      <td>{a.currency}</td>
                      <td className="cartera-mono">{fmtMoney(a.estimated_value)}</td>
                      <td>{LIQUIDITY_LABELS[a.liquidity]}</td>
                      <td className="cartera-mono">{a.generates_cashflow ? fmtMoney(a.monthly_cashflow) : "—"}</td>
                      <td>
                        <button type="button" className="cartera-btn" onClick={() => setAssetModal({ open: true, row: a })}>Editar</button>{" "}
                        <button
                          type="button"
                          className="cartera-btn cartera-btn--danger"
                          onClick={() => {
                            if (!window.confirm(`¿Desactivar el activo "${a.name}"?`)) return;
                            void deleteFamilyAsset(a.id).then(onSaved).catch((e) => setErr(String(e)));
                          }}
                        >
                          Desactivar
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

      {tab === "deudas" ? (
        <section style={{ marginTop: "1rem" }}>
          <button type="button" className="cartera-btn cartera-btn--primary" onClick={() => setLiabilityModal({ open: true, row: null })}>
            Nueva deuda
          </button>
          {!busy && liabilities.length === 0 ? (
            <p className="cartera-empty">No hay deudas activas.</p>
          ) : (
            <div className="table-scroll" style={{ marginTop: "0.75rem" }}>
              <table className="cartera-table">
                <thead>
                  <tr>
                    <th>Nombre</th><th>Tipo</th><th>Moneda</th><th>Saldo</th><th>Cuota</th><th>Restantes</th><th>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {liabilities.map((li) => (
                    <tr key={li.id}>
                      <td>{li.name}</td>
                      <td>{LIABILITY_TYPE_LABELS[li.liability_type]}</td>
                      <td>{li.currency}</td>
                      <td className="cartera-mono">{fmtMoney(li.outstanding_balance)}</td>
                      <td className="cartera-mono">{fmtMoney(li.installment_amount)}</td>
                      <td>{li.installments_remaining}</td>
                      <td>
                        <button type="button" className="cartera-btn" onClick={() => setLiabilityModal({ open: true, row: li })}>Editar</button>{" "}
                        <button
                          type="button"
                          className="cartera-btn cartera-btn--danger"
                          onClick={() => {
                            if (!window.confirm(`¿Desactivar la deuda "${li.name}"?`)) return;
                            void deleteFamilyLiability(li.id).then(onSaved).catch((e) => setErr(String(e)));
                          }}
                        >
                          Desactivar
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

      {tab === "casa" ? (
        <section style={{ marginTop: "1rem", display: "grid", gap: "0.75rem" }}>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "end" }}>
            <button type="button" className="cartera-btn cartera-btn--primary" onClick={() => setHouseModal({ open: true, row: null })}>
              Nuevo proyecto
            </button>
            <label className="cartera-field">
              <span>Prioridad</span>
              <select value={houseFilterPriority} onChange={(e) => setHouseFilterPriority(e.target.value as FoHousePriority | "all")}>
                <option value="all">Todas</option>
                {Object.entries(HOUSE_PRIORITY_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </label>
            <label className="cartera-field">
              <span>Estado</span>
              <select value={houseFilterStatus} onChange={(e) => setHouseFilterStatus(e.target.value as FoHouseStatus | "all")}>
                <option value="all">Todos</option>
                {Object.entries(HOUSE_STATUS_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="card" style={{ padding: "1rem" }}>
            <h3 className="cartera-form__title" style={{ fontSize: "1rem" }}>Presupuesto</h3>
            <p className="cartera-mono">
              ARS est. {fmtMoney(houseBudget.ARS.estimated)} · pagado {fmtMoney(houseBudget.ARS.paid)} · pend.{" "}
              {fmtMoney(houseBudget.ARS.estimated - houseBudget.ARS.paid)}
            </p>
            <p className="cartera-mono">
              USD est. {fmtMoney(houseBudget.USD.estimated)} · pagado {fmtMoney(houseBudget.USD.paid)} · pend.{" "}
              {fmtMoney(houseBudget.USD.estimated - houseBudget.USD.paid)}
            </p>
            <p className="cartera-hint" style={{ marginTop: "0.5rem" }}>
              Reserva mensual asignada a casa: ARS {fmtMoney(houseReserveArs)} · USD {fmtMoney(houseReserveUsd)}
            </p>
          </div>
          {!busy && filteredProjects.length === 0 ? (
            <p className="cartera-empty">No hay proyectos activos con ese filtro.</p>
          ) : (
            <div className="table-scroll">
              <table className="cartera-table">
                <thead>
                  <tr>
                    <th>Nombre</th><th>Prioridad</th><th>Estado</th><th>Moneda</th><th>Estimado</th><th>Pagado</th><th>Pendiente</th><th>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredProjects.map((p) => (
                    <tr key={p.id}>
                      <td>{p.name}</td>
                      <td>{HOUSE_PRIORITY_LABELS[p.priority]}</td>
                      <td>{HOUSE_STATUS_LABELS[p.status]}</td>
                      <td>{p.currency}</td>
                      <td className="cartera-mono">{fmtMoney(p.estimated_cost)}</td>
                      <td className="cartera-mono">{fmtMoney(p.paid_amount)}</td>
                      <td className="cartera-mono">{fmtMoney(Number(p.estimated_cost) - Number(p.paid_amount))}</td>
                      <td>
                        <button type="button" className="cartera-btn" onClick={() => setHouseModal({ open: true, row: p })}>Editar</button>{" "}
                        <button
                          type="button"
                          className="cartera-btn cartera-btn--danger"
                          onClick={() => {
                            if (!window.confirm(`¿Desactivar el proyecto "${p.name}"? (soft delete)`)) return;
                            void deleteHouseProject(p.id).then(onSaved).catch((e) => setErr(String(e)));
                          }}
                        >
                          Desactivar
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

      {tab === "politicas" ? (
        <section style={{ marginTop: "1rem" }}>
          <button type="button" className="cartera-btn cartera-btn--primary" onClick={() => setPolicyModal({ open: true, row: null })}>
            Nueva política
          </button>
          {!busy && policies.length === 0 ? (
            <p className="cartera-empty">No hay políticas activas.</p>
          ) : (
            <div className="table-scroll" style={{ marginTop: "0.75rem" }}>
              <table className="cartera-table">
                <thead>
                  <tr>
                    <th>Nombre</th><th>Destino</th><th>Mín</th><th>Máx</th><th>Prioridad</th><th>Oblig.</th><th>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {policies.map((p) => (
                    <tr key={p.id}>
                      <td>{p.name}</td>
                      <td>{POLICY_DESTINATION_LABELS[p.destination]}</td>
                      <td className="cartera-mono">{fmtMoney(p.minimum_monthly_amount)}</td>
                      <td className="cartera-mono">{fmtMoney(p.maximum_monthly_amount)}</td>
                      <td>{p.priority}</td>
                      <td>{p.is_mandatory ? "Sí" : "No"}</td>
                      <td>
                        <button type="button" className="cartera-btn" onClick={() => setPolicyModal({ open: true, row: p })}>Editar</button>{" "}
                        <button
                          type="button"
                          className="cartera-btn cartera-btn--danger"
                          onClick={() => {
                            if (!window.confirm(`¿Desactivar la política "${p.name}"?`)) return;
                            void deleteCapitalPolicy(p.id).then(onSaved).catch((e) => setErr(String(e)));
                          }}
                        >
                          Desactivar
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

      <AssetFormModal open={assetModal.open} initial={assetModal.row} onClose={() => setAssetModal({ open: false, row: null })} onSuccess={onSaved} onError={(m) => setErr(m)} />
      <LiabilityFormModal open={liabilityModal.open} initial={liabilityModal.row} assets={assets} onClose={() => setLiabilityModal({ open: false, row: null })} onSuccess={onSaved} onError={(m) => setErr(m)} />
      <HouseProjectFormModal open={houseModal.open} initial={houseModal.row} onClose={() => setHouseModal({ open: false, row: null })} onSuccess={onSaved} onError={(m) => setErr(m)} />
      <PolicyFormModal open={policyModal.open} initial={policyModal.row} onClose={() => setPolicyModal({ open: false, row: null })} onSuccess={onSaved} onError={(m) => setErr(m)} />
      <SnapshotFormModal open={snapshotOpen} onClose={() => setSnapshotOpen(false)} onSuccess={onSaved} onError={(m) => setErr(m)} />
    </div>
  );
}
