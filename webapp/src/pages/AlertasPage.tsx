import { useEffect, useMemo, useState } from "react";
import {
  fetchAlertHistory,
  fetchLatestAlerts,
  type AlertHistoryEvent,
  type LatestAlert,
} from "@/services/api";

type AlertasTab = "actuales" | "historial";

const HISTORY_FETCH_LIMIT = 800;

const scanAtFormatter = new Intl.DateTimeFormat("es-AR", {
  dateStyle: "short",
  timeStyle: "short",
});

function formatScanAt(iso: string): string {
  const d = Date.parse(iso);
  if (Number.isNaN(d)) {
    return iso;
  }
  return scanAtFormatter.format(new Date(d));
}

function shortenScanId(id: string | undefined): string {
  if (!id) return "—";
  if (id.length <= 14) return id;
  return `${id.slice(0, 10)}…`;
}

/** Clave interna o etiqueta humana → clase de badge suave (reutiliza convicción del tema). */
function classForTipoAlerta(
  tipoKey: string | null | undefined,
  tipoLabel: string | null | undefined,
): string {
  const raw = `${tipoKey ?? ""} ${tipoLabel ?? ""}`.toLowerCase();
  if (raw.includes("compra_fuerte") || raw.includes("compra fuerte")) {
    return "radar-badge radar-badge--conv-alta";
  }
  if (raw.includes("compra_potencial") || raw.includes("compra potencial")) {
    return "radar-badge radar-badge--conv-alta";
  }
  if (raw.includes("venta")) {
    return "radar-badge radar-badge--conv-baja";
  }
  if (raw.includes("toma") || raw.includes("ganancia")) {
    return "radar-badge radar-badge--conv-media";
  }
  return "radar-badge";
}

function classForConviccion(conv: unknown): string {
  const s = String(conv ?? "")
    .trim()
    .toUpperCase();
  if (s === "ALTA") return "radar-badge radar-badge--conv-alta";
  if (s === "MEDIA") return "radar-badge radar-badge--conv-media";
  if (s === "BAJA" || s === "NULA") return "radar-badge radar-badge--conv-baja";
  return "radar-badge";
}

function classForPrioridadNum(p: number | null | undefined): string {
  if (p === null || p === undefined) return "radar-badge";
  if (p >= 3) return "radar-badge radar-badge--conv-baja";
  if (p >= 2) return "radar-badge radar-badge--conv-media";
  return "radar-badge radar-badge--conv-alta";
}

function segmentLabel(h: AlertHistoryEvent): string {
  if (h.mercado === "Argentina") {
    return String(h.panel ?? "—");
  }
  return String(h.universo ?? "—");
}

/** Agrupa mercado de /latest-alerts para conteos USA vs Argentina. */
function mercadoBucket(
  m: string | null | undefined,
): "usa" | "argentina" | "otro" {
  const s = (m ?? "").trim().toUpperCase();
  if (!s) return "otro";
  if (s === "USA" || s === "US" || s === "UNITED STATES") return "usa";
  if (s === "ARGENTINA" || s === "AR" || s === "ARG") return "argentina";
  if (s.includes("ARGENTINA")) return "argentina";
  if (s.includes("USA")) return "usa";
  return "otro";
}

export function AlertasPage() {
  const [tab, setTab] = useState<AlertasTab>("actuales");
  const [alerts, setAlerts] = useState<LatestAlert[] | null>(null);
  const [history, setHistory] = useState<AlertHistoryEvent[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const [filterMercado, setFilterMercado] = useState("");
  const [filterTicker, setFilterTicker] = useState("");
  const [filterTipo, setFilterTipo] = useState("");

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

  useEffect(() => {
    let cancelled = false;
    setHistoryLoading(true);
    setHistoryError(null);
    fetchAlertHistory(HISTORY_FETCH_LIMIT)
      .then((data) => {
        if (!cancelled) setHistory(data);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setHistoryError(e instanceof Error ? e.message : "Error al cargar historial");
          setHistory(null);
        }
      })
      .finally(() => {
        if (!cancelled) setHistoryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const mercadoOptions = useMemo(() => {
    const set = new Set<string>();
    for (const h of history ?? []) {
      const m = h.mercado?.trim();
      if (m) set.add(m);
    }
    return [...set].sort((a, b) => a.localeCompare(b, "es", { sensitivity: "base" }));
  }, [history]);

  const tipoOptions = useMemo(() => {
    const set = new Set<string>();
    for (const h of history ?? []) {
      const label = h.tipo_alerta_label?.trim();
      const key = h.tipo_alerta?.trim();
      if (label) set.add(label);
      else if (key) set.add(key);
    }
    return [...set].sort((a, b) => a.localeCompare(b, "es", { sensitivity: "base" }));
  }, [history]);

  const filteredHistory = useMemo(() => {
    const rows = history ?? [];
    const qTick = filterTicker.trim().toLowerCase();
    return rows.filter((h) => {
      if (filterMercado && (h.mercado ?? "").trim() !== filterMercado) {
        return false;
      }
      if (qTick) {
        const t = (h.ticker ?? "").toLowerCase();
        if (!t.includes(qTick)) return false;
      }
      if (filterTipo) {
        const label = (h.tipo_alerta_label ?? "").trim();
        const key = (h.tipo_alerta ?? "").trim();
        if (label !== filterTipo && key !== filterTipo) {
          return false;
        }
      }
      return true;
    });
  }, [history, filterMercado, filterTicker, filterTipo]);

  const resumenActualesUsa = useMemo(() => {
    if (loading) return null;
    if (error || alerts === null) return null;
    return alerts.filter((a) => mercadoBucket(a.mercado) === "usa").length;
  }, [loading, error, alerts]);

  const resumenActualesArg = useMemo(() => {
    if (loading) return null;
    if (error || alerts === null) return null;
    return alerts.filter((a) => mercadoBucket(a.mercado) === "argentina").length;
  }, [loading, error, alerts]);

  const resumenHistorialCount = useMemo(() => {
    if (historyLoading) return null;
    if (historyError || history === null) return null;
    return history.length;
  }, [historyLoading, historyError, history]);

  const resumenUltimoScanAt = useMemo(() => {
    if (historyLoading) return null;
    if (historyError || history === null || history.length === 0) return null;
    let bestMs = Number.NEGATIVE_INFINITY;
    let bestIso: string | null = null;
    for (const h of history) {
      const ms = Date.parse(h.scan_at);
      if (!Number.isNaN(ms) && ms >= bestMs) {
        bestMs = ms;
        bestIso = h.scan_at;
      }
    }
    return bestIso ? formatScanAt(bestIso) : null;
  }, [historyLoading, historyError, history]);

  const fmtResumen = (v: number | null) => (v === null ? "—" : String(v));

  return (
    <>
      <h1 className="page-title">Alertas</h1>
      <p className="page-desc">
        Consultá las alertas del último export y el historial por scan (
        <code>/latest-alerts</code> y <code>/alert-history</code> vía <code>/api</code>).
      </p>

      <div className="dashboard-stats-grid" style={{ marginBottom: "1.25rem" }}>
        <div className="stat dashboard-stat">
          <div className="stat__label">Alertas actuales USA</div>
          <div className="stat__value">{fmtResumen(resumenActualesUsa)}</div>
          <div className="msg-muted dashboard-stat__hint">
            Filas con mercado USA en la última carga
          </div>
        </div>
        <div className="stat dashboard-stat">
          <div className="stat__label">Alertas actuales Argentina</div>
          <div className="stat__value">{fmtResumen(resumenActualesArg)}</div>
          <div className="msg-muted dashboard-stat__hint">
            Filas con mercado Argentina en la última carga
          </div>
        </div>
        <div className="stat dashboard-stat">
          <div className="stat__label">Eventos en historial</div>
          <div className="stat__value">{fmtResumen(resumenHistorialCount)}</div>
          <div className="msg-muted dashboard-stat__hint">
            Registros devueltos por /alert-history (hasta {HISTORY_FETCH_LIMIT})
          </div>
        </div>
        <div className="stat dashboard-stat">
          <div className="stat__label">Último evento (scan)</div>
          <div className="stat__value" style={{ fontSize: "1.15rem" }}>
            {resumenUltimoScanAt ?? "—"}
          </div>
          <div className="msg-muted dashboard-stat__hint">
            Fecha/hora más reciente según <code>scan_at</code> en el historial cargado
          </div>
        </div>
      </div>

      <div
        className="alertas-tablist"
        role="tablist"
        aria-label="Secciones de alertas"
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.5rem",
          marginBottom: "1rem",
        }}
      >
        <button
          type="button"
          role="tab"
          aria-selected={tab === "actuales"}
          className={`radar-chip${tab === "actuales" ? " radar-chip--active" : ""}`}
          onClick={() => setTab("actuales")}
        >
          Alertas actuales
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "historial"}
          className={`radar-chip${tab === "historial" ? " radar-chip--active" : ""}`}
          onClick={() => setTab("historial")}
        >
          Historial
        </button>
      </div>

      {tab === "actuales" && (
        <div className="card">
          <h2 style={{ marginTop: 0, fontSize: "1rem", fontWeight: 600 }}>
            Alertas actuales
          </h2>
          <p className="msg-muted" style={{ marginTop: 0 }}>
            Filas de la última exportación (misma lógica de cooldown que el pipeline).
          </p>
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
                      <td className="table-cell--nowrap">{a.ticker ?? "—"}</td>
                      <td>
                        <span className={classForTipoAlerta(a.tipo_alerta, a.tipo_alerta)}>
                          {a.tipo_alerta ?? "—"}
                        </span>
                      </td>
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
      )}

      {tab === "historial" && (
        <div className="card">
          <h2 style={{ marginTop: 0, fontSize: "1rem", fontWeight: 600 }}>
            Historial de alertas
          </h2>
          <p className="msg-muted" style={{ marginTop: 0 }}>
            Todas las alertas detectadas por scan (sin cooldown). Agrupá por{" "}
            <code>scan_id</code>.
          </p>

          <div
            className="radar-toolbar"
            style={{ marginBottom: "0.75rem", alignItems: "flex-end" }}
            aria-label="Filtros del historial"
          >
            <label className="radar-toolbar__field">
              <span className="radar-toolbar__label">Mercado</span>
              <select
                className="radar-toolbar__select"
                value={filterMercado}
                onChange={(e) => setFilterMercado(e.target.value)}
              >
                <option value="">Todos</option>
                {mercadoOptions.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </label>
            <label className="radar-toolbar__field">
              <span className="radar-toolbar__label">Ticker</span>
              <input
                type="search"
                className="radar-toolbar__input"
                placeholder="Contiene…"
                value={filterTicker}
                onChange={(e) => setFilterTicker(e.target.value)}
                autoComplete="off"
              />
            </label>
            <label className="radar-toolbar__field">
              <span className="radar-toolbar__label">Tipo</span>
              <select
                className="radar-toolbar__select"
                value={filterTipo}
                onChange={(e) => setFilterTipo(e.target.value)}
              >
                <option value="">Todos</option>
                {tipoOptions.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <p className="radar-toolbar__hint msg-muted" style={{ marginLeft: "auto" }}>
              {filteredHistory.length} de {history?.length ?? 0} eventos
            </p>
          </div>

          {historyLoading && <p className="msg-muted">Cargando historial…</p>}
          {historyError && <p className="msg-error">{historyError}</p>}
          {!historyLoading && !historyError && history && history.length === 0 && (
            <p className="msg-muted">
              Todavía no hay eventos registrados (ejecutá un scan para poblar el historial).
            </p>
          )}
          {!historyLoading &&
            !historyError &&
            history &&
            history.length > 0 &&
            filteredHistory.length === 0 && (
              <p className="msg-muted">No hay eventos con los filtros actuales.</p>
            )}
          {!historyLoading && !historyError && history && history.length > 0 && filteredHistory.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>scan_id</th>
                    <th>Ticker</th>
                    <th>Mercado</th>
                    <th>Segmento</th>
                    <th>Tipo</th>
                    <th>Conv.</th>
                    <th>Prio</th>
                    <th>Total</th>
                    <th>RSI</th>
                    <th>Precio</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredHistory.map((h, i) => {
                    const tipoDisplay = h.tipo_alerta_label?.trim() || h.tipo_alerta || "—";
                    return (
                      <tr key={`${h.scan_id ?? h.scan_at}-${h.ticker ?? "x"}-${i}`}>
                        <td className="table-cell--nowrap" title={h.scan_at}>
                          {formatScanAt(h.scan_at)}
                        </td>
                        <td
                          className="table-cell--nowrap"
                          style={{ fontSize: "0.8rem" }}
                          title={h.scan_id ?? ""}
                        >
                          {shortenScanId(h.scan_id)}
                        </td>
                        <td className="table-cell--nowrap">{h.ticker ?? "—"}</td>
                        <td>{h.mercado ?? "—"}</td>
                        <td>{segmentLabel(h)}</td>
                        <td>
                          <span
                            className={classForTipoAlerta(h.tipo_alerta, h.tipo_alerta_label)}
                            title={h.tipo_alerta ?? ""}
                          >
                            {tipoDisplay}
                          </span>
                        </td>
                        <td>
                          {h.conviccion != null && String(h.conviccion).trim() !== "" ? (
                            <span className={classForConviccion(h.conviccion)}>
                              {String(h.conviccion)}
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td>
                          {h.prioridad != null && h.prioridad !== undefined ? (
                            <span className={classForPrioridadNum(h.prioridad)} title="Prioridad (alerta)">
                              {h.prioridad}
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td>{String(h.total_score ?? "—")}</td>
                        <td>{String(h.rsi ?? "—")}</td>
                        <td>{String(h.precio ?? "—")}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </>
  );
}
