import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  fetchAlertHistory,
  fetchLatestAlerts,
  type AlertHistoryEvent,
  type LatestAlert,
} from "@/services/api";

type AlertasTab = "actuales" | "historial";

/** Filtro global por mercado (normalizado con mercadoBucket). "" = todas. */
type MercadoFiltroVista = "" | "usa" | "argentina";

const HISTORY_FETCH_LIMIT = 800;

/** Tooltips por clave interna del motor (estable aunque cambien las etiquetas visibles). */
const ALERT_TYPE_TOOLTIPS: Record<string, string> = {
  compra_potencial:
    "Alerta táctica en ventana intermedia de score. Puede aparecer aunque el radar aún no clasifique al activo como «compra potencial» (SignalState).",
  compra_fuerte:
    "Alerta táctica de score alto con señales activas o confluencia. No equivale necesariamente al nombre del estado operativo en el radar (SignalState).",
  venta: "Señal de deterioro o debilidad según score y/o señales técnicas.",
  toma_ganancia:
    "Señal de posible toma de ganancia tras extensión o retroceso desde niveles altos.",
};

/** Resuelve la clave interna para estilo y tooltip (export viejos o solo etiqueta). */
function resolveAlertTypeKey(
  tipoKey: string | null | undefined,
  tipoLabel: string | null | undefined,
): string | null {
  const k = tipoKey?.trim().toLowerCase();
  if (k && ALERT_TYPE_TOOLTIPS[k]) {
    return k;
  }
  const lab = (tipoLabel ?? "").toLowerCase();
  if (lab.includes("ventana score 7")) {
    return "compra_potencial";
  }
  if (lab.includes("score alto") && lab.includes("confluencia")) {
    return "compra_fuerte";
  }
  if (lab.includes("compra fuerte")) {
    return "compra_fuerte";
  }
  if (lab.includes("compra potencial")) {
    return "compra_potencial";
  }
  if (lab.includes("venta") || lab.includes("deterioro")) {
    return "venta";
  }
  if (lab.includes("toma") && lab.includes("ganancia")) {
    return "toma_ganancia";
  }
  return k && ALERT_TYPE_TOOLTIPS[k] ? k : null;
}

function tooltipForAlertType(
  tipoKey: string | null | undefined,
  tipoLabel: string | null | undefined,
): string {
  const resolved = resolveAlertTypeKey(tipoKey, tipoLabel);
  if (resolved && ALERT_TYPE_TOOLTIPS[resolved]) {
    return ALERT_TYPE_TOOLTIPS[resolved];
  }
  return "Evento detectado en la corrida. El tipo de alerta usa reglas distintas al SignalState del radar.";
}

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
  const resolved = resolveAlertTypeKey(tipoKey, tipoLabel);
  if (resolved === "compra_fuerte" || resolved === "compra_potencial") {
    return "radar-badge radar-badge--conv-alta";
  }
  if (resolved === "venta") {
    return "radar-badge radar-badge--conv-baja";
  }
  if (resolved === "toma_ganancia") {
    return "radar-badge radar-badge--conv-media";
  }
  const raw = `${tipoKey ?? ""} ${tipoLabel ?? ""}`.toLowerCase();
  if (raw.includes("venta") || raw.includes("deterioro")) {
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

/** Ruta al radar con filtro inicial; null si mercado no es USA/Argentina o no hay ticker. */
function radarHrefForTicker(
  ticker: string | null | undefined,
  mercado: string | null | undefined,
): string | null {
  const t = ticker?.trim();
  if (!t) return null;
  const b = mercadoBucket(mercado);
  const q = new URLSearchParams({ ticker: t }).toString();
  if (b === "usa") return `/acciones-usa?${q}`;
  if (b === "argentina") return `/acciones-argentina?${q}`;
  return null;
}

function TickerRadarLink({
  ticker,
  mercado,
}: {
  ticker: string | null;
  mercado: string | null;
}) {
  const href = radarHrefForTicker(ticker, mercado);
  if (!ticker?.trim()) {
    return <>—</>;
  }
  if (!href) {
    return <span className="table-cell--nowrap">{ticker}</span>;
  }
  return (
    <Link
      to={href}
      className="table-cell--nowrap"
      title={`Abrir ${ticker} en el radar (${mercado ?? "mercado"})`}
    >
      {ticker}
    </Link>
  );
}

export function AlertasPage() {
  const [tab, setTab] = useState<AlertasTab>("actuales");
  const [alerts, setAlerts] = useState<LatestAlert[] | null>(null);
  const [history, setHistory] = useState<AlertHistoryEvent[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const [mercadoFiltro, setMercadoFiltro] = useState<MercadoFiltroVista>("");
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

  const alertsFiltradasMercado = useMemo(() => {
    if (!alerts) return null;
    if (!mercadoFiltro) return alerts;
    return alerts.filter((a) => mercadoBucket(a.mercado) === mercadoFiltro);
  }, [alerts, mercadoFiltro]);

  const filteredHistory = useMemo(() => {
    const rows = history ?? [];
    const qTick = filterTicker.trim().toLowerCase();
    return rows.filter((h) => {
      if (mercadoFiltro && mercadoBucket(h.mercado) !== mercadoFiltro) {
        return false;
      }
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
  }, [history, mercadoFiltro, filterMercado, filterTicker, filterTipo]);

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

  const analiticaHistorial = useMemo(() => {
    if (historyLoading) return null;
    if (historyError || history === null) return null;
    const rows = history;

    const out = {
      total: rows.length,
      usa: 0,
      argentina: 0,
      porTipo: {
        compra_potencial: 0,
        compra_fuerte: 0,
        venta: 0,
        toma_ganancia: 0,
      } as Record<"compra_potencial" | "compra_fuerte" | "venta" | "toma_ganancia", number>,
      topTicker: null as { ticker: string; count: number } | null,
      ultimoScan: null as { scan_id: string; count: number; scan_at: string } | null,
    };

    const tickerCount = new Map<string, number>();
    const scanCount = new Map<string, { count: number; bestAtMs: number; bestAtIso: string }>();

    for (const h of rows) {
      const b = mercadoBucket(h.mercado);
      if (b === "usa") out.usa += 1;
      else if (b === "argentina") out.argentina += 1;

      const key = resolveAlertTypeKey(h.tipo_alerta, h.tipo_alerta_label);
      if (key && key in out.porTipo) {
        out.porTipo[key as keyof typeof out.porTipo] += 1;
      }

      const t = (h.ticker ?? "").trim().toUpperCase();
      if (t) {
        tickerCount.set(t, (tickerCount.get(t) ?? 0) + 1);
      }

      const sid = (h.scan_id ?? "").trim();
      if (sid) {
        const ms = Date.parse(h.scan_at);
        const safeMs = Number.isNaN(ms) ? Number.NEGATIVE_INFINITY : ms;
        const prev = scanCount.get(sid);
        if (!prev) {
          scanCount.set(sid, { count: 1, bestAtMs: safeMs, bestAtIso: h.scan_at });
        } else {
          prev.count += 1;
          if (safeMs >= prev.bestAtMs) {
            prev.bestAtMs = safeMs;
            prev.bestAtIso = h.scan_at;
          }
        }
      }
    }

    // Top ticker por eventos
    let bestT: string | null = null;
    let bestN = 0;
    for (const [t, n] of tickerCount.entries()) {
      if (n > bestN) {
        bestT = t;
        bestN = n;
      }
    }
    if (bestT) {
      out.topTicker = { ticker: bestT, count: bestN };
    }

    // Último scan_id (por scan_at más reciente)
    let bestScan: string | null = null;
    let bestScanAtMs = Number.NEGATIVE_INFINITY;
    for (const [sid, v] of scanCount.entries()) {
      if (v.bestAtMs >= bestScanAtMs) {
        bestScanAtMs = v.bestAtMs;
        bestScan = sid;
      }
    }
    if (bestScan) {
      const v = scanCount.get(bestScan);
      if (v) {
        out.ultimoScan = { scan_id: bestScan, count: v.count, scan_at: v.bestAtIso };
      }
    }

    return out;
  }, [historyLoading, historyError, history]);

  /** Tickers del último scan_id (por scan_at más reciente) con ranking vs historial completo cargado. */
  const ultimoScanTickersRanking = useMemo(() => {
    if (historyLoading || historyError || history === null || history.length === 0) {
      return null;
    }
    const rows = history;

    const scanBestAt = new Map<string, number>();
    for (const h of rows) {
      const sid = (h.scan_id ?? "").trim();
      if (!sid) continue;
      const ms = Date.parse(h.scan_at);
      const safeMs = Number.isNaN(ms) ? Number.NEGATIVE_INFINITY : ms;
      const prev = scanBestAt.get(sid);
      if (prev === undefined || safeMs >= prev) {
        scanBestAt.set(sid, safeMs);
      }
    }
    if (scanBestAt.size === 0) {
      return { kind: "no_scan_id" as const };
    }
    let ultimoScanId: string | null = null;
    let bestMs = Number.NEGATIVE_INFINITY;
    for (const [sid, at] of scanBestAt.entries()) {
      if (at >= bestMs) {
        bestMs = at;
        ultimoScanId = sid;
      }
    }
    if (!ultimoScanId) {
      return { kind: "no_scan_id" as const };
    }

    const histTotal = new Map<string, number>();
    const tipoByTicker = new Map<string, Map<string, number>>();
    const mercadoCualquiera = new Map<string, string>();

    for (const h of rows) {
      const t = (h.ticker ?? "").trim().toUpperCase();
      if (!t) continue;
      histTotal.set(t, (histTotal.get(t) ?? 0) + 1);
      const rk = resolveAlertTypeKey(h.tipo_alerta, h.tipo_alerta_label);
      if (rk) {
        let m = tipoByTicker.get(t);
        if (!m) {
          m = new Map();
          tipoByTicker.set(t, m);
        }
        m.set(rk, (m.get(rk) ?? 0) + 1);
      }
      const m0 = h.mercado?.trim();
      if (m0 && !mercadoCualquiera.has(t)) {
        mercadoCualquiera.set(t, m0);
      }
    }

    const enUltimoScan = new Map<string, number>();
    const mercadoUltimo = new Map<string, string>();
    for (const h of rows) {
      if ((h.scan_id ?? "").trim() !== ultimoScanId) continue;
      const t = (h.ticker ?? "").trim().toUpperCase();
      if (!t) continue;
      enUltimoScan.set(t, (enUltimoScan.get(t) ?? 0) + 1);
      const m0 = h.mercado?.trim();
      if (m0 && !mercadoUltimo.has(t)) {
        mercadoUltimo.set(t, m0);
      }
    }

    if (enUltimoScan.size === 0) {
      return { kind: "empty_last" as const, ultimoScanId };
    }

    const TIPO_CORTO: Record<string, string> = {
      compra_potencial: "CP",
      compra_fuerte: "CF",
      venta: "V",
      toma_ganancia: "TG",
    };

    type RankRow = {
      ticker: string;
      enUltimo: number;
      enHistorial: number;
      mercado: string | null;
      tipoFrecuente: string | null;
      caliente: boolean;
    };

    const outRows: RankRow[] = [];
    for (const [ticker, enUltimo] of enUltimoScan.entries()) {
      const enHistorial = histTotal.get(ticker) ?? enUltimo;
      let tipoFrecuente: string | null = null;
      let bestN = 0;
      const tm = tipoByTicker.get(ticker);
      if (tm) {
        for (const [k, n] of tm.entries()) {
          if (n > bestN) {
            bestN = n;
            tipoFrecuente = TIPO_CORTO[k] ?? k;
          }
        }
      }
      const mercado = mercadoUltimo.get(ticker) ?? mercadoCualquiera.get(ticker) ?? null;
      const caliente = enHistorial >= 3;
      outRows.push({ ticker, enUltimo, enHistorial, mercado, tipoFrecuente, caliente });
    }

    outRows.sort((a, b) => {
      if (b.enHistorial !== a.enHistorial) return b.enHistorial - a.enHistorial;
      if (b.enUltimo !== a.enUltimo) return b.enUltimo - a.enUltimo;
      return a.ticker.localeCompare(b.ticker, "es", { sensitivity: "base" });
    });

    return {
      kind: "ok" as const,
      ultimoScanId,
      rows: outRows.slice(0, 25),
      totalEnUltimoScan: enUltimoScan.size,
    };
  }, [historyLoading, historyError, history]);

  return (
    <>
      <h1 className="page-title">Alertas</h1>
      <p className="page-desc">
        Consultá las alertas del último export y el historial por scan (
        <code>/latest-alerts</code> y <code>/alert-history</code> vía <code>/api</code>).
      </p>
      <p className="msg-muted" style={{ marginTop: "-0.35rem", marginBottom: "1.25rem", maxWidth: "52rem" }}>
        <span title="En el radar, SignalState resume el estado según score y reglas fijas. El tipo de alerta es un evento por corrida (cambio de score, huella de señales, etc.).">
          <strong>SignalState</strong> es el estado del radar; <strong>tipo de alerta</strong> es el
          evento detectado en esa corrida (reglas distintas). Pasá el cursor sobre el badge de tipo
          para una explicación breve.
        </span>
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
        role="group"
        aria-label="Filtrar listados por mercado"
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: "0.5rem",
          marginBottom: "1rem",
        }}
      >
        <span className="radar-toolbar__label" style={{ marginRight: "0.15rem" }}>
          Mercado
        </span>
        <button
          type="button"
          className={`radar-chip${mercadoFiltro === "" ? " radar-chip--active" : ""}`}
          onClick={() => setMercadoFiltro("")}
        >
          Todas
        </button>
        <button
          type="button"
          className={`radar-chip${mercadoFiltro === "usa" ? " radar-chip--active" : ""}`}
          onClick={() => setMercadoFiltro("usa")}
        >
          USA
        </button>
        <button
          type="button"
          className={`radar-chip${mercadoFiltro === "argentina" ? " radar-chip--active" : ""}`}
          onClick={() => setMercadoFiltro("argentina")}
        >
          Argentina
        </button>
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
          {!loading &&
            !error &&
            alerts &&
            alerts.length > 0 &&
            alertsFiltradasMercado &&
            alertsFiltradasMercado.length === 0 && (
              <p className="msg-muted">No hay alertas para el mercado seleccionado.</p>
            )}
          {!loading && !error && alertsFiltradasMercado && alertsFiltradasMercado.length > 0 && (
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
                  {alertsFiltradasMercado.map((a, i) => (
                    <tr key={`${a.ticker ?? "x"}-${i}`}>
                      <td>
                        <TickerRadarLink ticker={a.ticker} mercado={a.mercado} />
                      </td>
                      <td>
                        <span
                          className={classForTipoAlerta(a.tipo_alerta_key, a.tipo_alerta)}
                          title={tooltipForAlertType(a.tipo_alerta_key, a.tipo_alerta)}
                        >
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

          <div className="dashboard-stats-grid" style={{ marginBottom: "1rem" }}>
            <div className="stat dashboard-stat">
              <div className="stat__label">Eventos cargados</div>
              <div className="stat__value">{analiticaHistorial ? String(analiticaHistorial.total) : "—"}</div>
              <div className="msg-muted dashboard-stat__hint">
                Total de filas recibidas desde <code>/alert-history</code> (hasta {HISTORY_FETCH_LIMIT})
              </div>
            </div>
            <div className="stat dashboard-stat">
              <div className="stat__label">Por mercado</div>
              <div className="stat__value">
                {analiticaHistorial ? `USA ${analiticaHistorial.usa} · AR ${analiticaHistorial.argentina}` : "—"}
              </div>
              <div className="msg-muted dashboard-stat__hint">Conteo por mercado en el historial cargado</div>
            </div>
            <div className="stat dashboard-stat">
              <div className="stat__label">Por tipo (4)</div>
              <div className="stat__value" style={{ fontSize: "1.05rem" }}>
                {analiticaHistorial
                  ? `CP ${analiticaHistorial.porTipo.compra_potencial} · CF ${analiticaHistorial.porTipo.compra_fuerte} · V ${analiticaHistorial.porTipo.venta} · TG ${analiticaHistorial.porTipo.toma_ganancia}`
                  : "—"}
              </div>
              <div className="msg-muted dashboard-stat__hint">
                Claves internas: compra_potencial/compra_fuerte/venta/toma_ganancia
              </div>
            </div>
            <div className="stat dashboard-stat">
              <div className="stat__label">Ticker más frecuente</div>
              <div className="stat__value">
                {analiticaHistorial?.topTicker ? analiticaHistorial.topTicker.ticker : "—"}
              </div>
              <div className="msg-muted dashboard-stat__hint">
                {analiticaHistorial?.topTicker ? `${analiticaHistorial.topTicker.count} eventos` : "—"}
              </div>
            </div>
            <div className="stat dashboard-stat">
              <div className="stat__label">Último scan_id</div>
              <div className="stat__value" style={{ fontSize: "1.05rem" }}>
                {analiticaHistorial?.ultimoScan ? shortenScanId(analiticaHistorial.ultimoScan.scan_id) : "—"}
              </div>
              <div className="msg-muted dashboard-stat__hint">
                {analiticaHistorial?.ultimoScan
                  ? `${analiticaHistorial.ultimoScan.count} eventos · ${formatScanAt(analiticaHistorial.ultimoScan.scan_at)}`
                  : "—"}
              </div>
            </div>
          </div>

          <div style={{ marginBottom: "1.1rem" }}>
            <h3 style={{ margin: "0 0 0.35rem", fontSize: "0.95rem", fontWeight: 600 }}>
              Ultimo scan: tickers y recurrencia
            </h3>
            <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.6rem", fontSize: "0.88rem" }}>
              Ultimo <code>scan_id</code>: el mas reciente por <code>scan_at</code> en el historial cargado. El ranking
              lista solo tickers con al menos un evento en ese scan. <strong>Caliente</strong>: en el ultimo scan y 3+
              eventos en todo el historial cargado.
            </p>
            {!historyLoading && !historyError && history && history.length > 0 && ultimoScanTickersRanking?.kind === "no_scan_id" && (
              <p className="msg-muted" style={{ margin: 0 }}>
                No hay <code>scan_id</code> en los eventos cargados; no se puede armar este ranking.
              </p>
            )}
            {!historyLoading &&
              !historyError &&
              history &&
              history.length > 0 &&
              ultimoScanTickersRanking?.kind === "empty_last" && (
                <p className="msg-muted" style={{ margin: 0 }}>
                  Hay <code>scan_id</code> pero ningún evento coincide con el último scan (
                  <code>{shortenScanId(ultimoScanTickersRanking.ultimoScanId)}</code>).
                </p>
              )}
            {!historyLoading &&
              !historyError &&
              history &&
              history.length > 0 &&
              ultimoScanTickersRanking?.kind === "ok" && (
                <>
                  <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.5rem", fontSize: "0.85rem" }}>
                    Scan: <code title={ultimoScanTickersRanking.ultimoScanId}>{shortenScanId(ultimoScanTickersRanking.ultimoScanId)}</code>{" "}
                    · {ultimoScanTickersRanking.totalEnUltimoScan} ticker(s) · mostrando top {ultimoScanTickersRanking.rows.length}
                  </p>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Ticker</th>
                          <th>Último scan</th>
                          <th>Historial</th>
                          <th>Mercado</th>
                          <th>Tipo frec.</th>
                          <th title="3+ eventos en historial cargado y presente en último scan">Caliente</th>
                        </tr>
                      </thead>
                      <tbody>
                        {ultimoScanTickersRanking.rows.map((r) => (
                          <tr key={r.ticker}>
                            <td>
                              <TickerRadarLink ticker={r.ticker} mercado={r.mercado} />
                            </td>
                            <td>{r.enUltimo}</td>
                            <td>{r.enHistorial}</td>
                            <td>{r.mercado ?? "—"}</td>
                            <td>{r.tipoFrecuente ?? "—"}</td>
                            <td>
                              {r.caliente ? (
                                <span
                                  className="radar-badge radar-badge--conv-alta"
                                  title="3+ eventos en el historial cargado"
                                >
                                  sí
                                </span>
                              ) : (
                                <span className="msg-muted">—</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
          </div>

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
                        <td>
                          <TickerRadarLink ticker={h.ticker} mercado={h.mercado} />
                        </td>
                        <td>{h.mercado ?? "—"}</td>
                        <td>{segmentLabel(h)}</td>
                        <td>
                          <span
                            className={classForTipoAlerta(h.tipo_alerta, h.tipo_alerta_label)}
                            title={tooltipForAlertType(h.tipo_alerta, h.tipo_alerta_label)}
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
