import { useEffect, useState } from "react";
import { fetchLatestAlerts, type LatestAlert } from "@/services/api";

export function AlertasPage() {
  const [alerts, setAlerts] = useState<LatestAlert[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchLatestAlerts()
      .then((data) => {
        if (!cancelled) setAlerts(data);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Error al cargar alertas");
          setAlerts(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      <h1 className="page-title">Alertas</h1>
      <p className="page-desc">
        Últimas alertas según el export más reciente del backend (
        <code>GET /latest-alerts</code> vía proxy <code>/api</code>).
      </p>
      <div className="card">
        <h2>Listado</h2>
        {loading && <p className="msg-muted">Cargando…</p>}
        {error && <p className="msg-error">{error}</p>}
        {!loading && !error && alerts && alerts.length === 0 && (
          <p className="msg-muted">No hay alertas en el último export.</p>
        )}
        {!loading && !error && alerts && alerts.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Tipo</th>
                  <th>Score</th>
                  <th>Score ant.</th>
                  <th>Δ</th>
                  <th>Mercado</th>
                </tr>
              </thead>
              <tbody>
                {alerts.map((a, i) => (
                  <tr key={`${a.ticker ?? "x"}-${i}`}>
                    <td>{a.ticker ?? "—"}</td>
                    <td>{a.tipo_alerta ?? "—"}</td>
                    <td>{a.score ?? "—"}</td>
                    <td>{a.score_anterior ?? "—"}</td>
                    <td>{a.cambio_score ?? "—"}</td>
                    <td>{a.mercado ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
