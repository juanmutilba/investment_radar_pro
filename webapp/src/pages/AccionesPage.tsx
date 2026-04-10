export function AccionesPage() {
  return (
    <>
      <h1 className="page-title">Acciones</h1>
      <p className="page-desc">
        Módulo para listar y analizar acciones con toda la información del radar:
        precio, fundamentales, scores técnicos, señales y evolución. La tabla y
        los filtros se conectarán al API o a exports cuando definamos el
        contrato de datos.
      </p>
      <div className="card">
        <h2>Área de listado</h2>
        <p className="msg-muted" style={{ margin: 0 }}>
          Placeholder: tabla paginada, columnas configurables (Ticker, Sector,
          TotalScore, RSI, Trend, etc.), búsqueda y orden.
        </p>
      </div>
      <div className="card">
        <h2>Detalle de activo</h2>
        <p className="msg-muted" style={{ margin: 0 }}>
          Placeholder: vista lateral o ruta <code>/acciones/:ticker</code> con
          histórico, gráficos y alertas asociadas.
        </p>
      </div>
    </>
  );
}
