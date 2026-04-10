export function DashboardPage() {
  return (
    <>
      <h1 className="page-title">Dashboard</h1>
      <p className="page-desc">
        Vista general del radar. Aquí podrás enlazar resúmenes, KPIs y accesos
        rápidos cuando integremos datos del backend.
      </p>
      <div className="grid-3">
        <div className="stat">
          <div className="stat__label">Radar USA</div>
          <div className="stat__value">—</div>
        </div>
        <div className="stat">
          <div className="stat__label">Radar Argentina</div>
          <div className="stat__value">—</div>
        </div>
        <div className="stat">
          <div className="stat__label">Alertas recientes</div>
          <div className="stat__value">Ver módulo Alertas</div>
        </div>
      </div>
      <div className="card">
        <h2>Próximos pasos</h2>
        <p className="msg-muted" style={{ margin: 0 }}>
          Conectar tarjetas a <code>GET /latest-summary</code>, gráficos y
          filtros por mercado. Estructura lista para añadir widgets sin
          reordenar rutas.
        </p>
      </div>
    </>
  );
}
