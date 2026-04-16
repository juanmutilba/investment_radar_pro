import { useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { mercadoBucket, TickerRadarLink } from "@/components/navigation/radarLinks";
import {
  ALERT_HISTORY_DEFAULT_LIMIT,
  fetchAlertHistory,
  fetchAlertsAnalysis,
  fetchLatestAlerts,
  type AlertAnalysisRow,
  type AlertHistoryEvent,
  type LatestAlert,
} from "@/services/api";

type AlertasTab = "actuales" | "historial";

/** Filtro global por mercado (normalizado con mercadoBucket). "" = todas. */
type MercadoFiltroVista = "" | "usa" | "argentina";

const HISTORY_FETCH_LIMIT = ALERT_HISTORY_DEFAULT_LIMIT;
const ANALYSIS_FETCH_LIMIT = 5000;
const HISTORY_TABLE_PREVIEW = 15;
const RANKING_TABLE_PREVIEW = 20;

const RANKING_FORMATION_TOOLTIP =
  "Se construye agrupando eventos históricos por ticker y calculando un puntaje combinado con score actual, aceleración, cantidad de scans, novedad y recencia.";

const RANKING_COLUMN_TOOLTIP =
  "Puntaje combinado construido con score actual, aceleración, cantidad de scans, novedad y recencia. Sirve para priorizar tickers dentro del historial analizado.";

const RANKING_CELL_TOOLTIP = "Ranking calculado sobre el historial analizado para este ticker.";

/** Cards de resumen en fila: contenido centrado y altura mínima uniforme. */
const parallelStatCardStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "center",
  textAlign: "center",
  minHeight: "7.25rem",
};

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

function classForTendencia(t: string | null | undefined): string {
  const s = (t ?? "").trim().toLowerCase();
  if (s === "subiendo") return "radar-badge radar-badge--conv-alta";
  if (s === "bajando") return "radar-badge radar-badge--conv-baja";
  if (s === "plano") return "radar-badge radar-badge--conv-media";
  return "radar-badge";
}

function tendenciaLabel(t: string | null | undefined): string {
  const s = (t ?? "").trim().toLowerCase();
  if (s === "subiendo") return "acelerando";
  if (s === "bajando") return "perdiendo fuerza";
  if (s === "plano") return "estable";
  return (t ?? "").toString();
}

function classForTendenciaConRegimen(
  tendencia: string | null | undefined,
  opts: { cambioRegimen: boolean | null | undefined; direccionRegimen: string | null | undefined },
): string {
  if (opts.cambioRegimen) {
    const dir = (opts.direccionRegimen ?? "").trim().toLowerCase();
    if (dir === "deterioro") return "radar-badge radar-badge--conv-baja";
    if (dir === "mejora") return "radar-badge radar-badge--conv-alta";
    return "radar-badge radar-badge--conv-media";
  }
  return classForTendencia(tendencia);
}

function regimenLabel(dir: string | null | undefined): string | null {
  const s = (dir ?? "").trim().toLowerCase();
  if (s === "mejora") return "Mejora de régimen";
  if (s === "deterioro") return "Deterioro de régimen";
  return null;
}

function classForRegimen(dir: string | null | undefined): string {
  const s = (dir ?? "").trim().toLowerCase();
  if (s === "mejora") return "radar-badge radar-badge--conv-alta";
  if (s === "deterioro") return "radar-badge radar-badge--conv-baja";
  return "radar-badge";
}

function tooltipRegimenRanking(r: { cambio_regimen: boolean; direccion_regimen: string }): string {
  if (r.cambio_regimen && r.direccion_regimen === "mejora") {
    return "Cambio de régimen favorable respecto a eventos recientes";
  }
  if (r.cambio_regimen && r.direccion_regimen === "deterioro") {
    return "Cambio de régimen desfavorable respecto a eventos recientes";
  }
  return "Sin cambio de régimen relevante";
}

function tooltipTendenciaRanking(tendencia: string | null | undefined): string {
  const s = (tendencia ?? "").trim().toLowerCase();
  if (s === "subiendo") return "Los últimos eventos muestran impulso creciente";
  if (s === "plano") return "Sin cambios marcados en los últimos eventos";
  if (s === "bajando") return "Los últimos eventos muestran menor impulso";
  return "";
}

function fmt1(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toFixed(1);
}

function fmtMaybe(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return String(v);
}

function csvEscapeCell(v: unknown): string {
  const s = String(v ?? "");
  if (/[",\n\r]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

function fmtHaceSegundos(sec: number | null | undefined): string {
  if (sec === null || sec === undefined || Number.isNaN(sec)) return "—";
  const s = Math.max(0, Math.floor(sec));
  if (s < 10) return "hace instantes";
  if (s < 60) return `hace ${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `hace ${m} min`;
  const h = Math.floor(m / 60);
  if (h < 24) return `hace ${h} h`;
  const d = Math.floor(h / 24);
  return `hace ${d} d`;
}

function segmentLabel(h: AlertHistoryEvent): string {
  if (h.mercado === "Argentina") {
    return String(h.panel ?? "—");
  }
  return String(h.universo ?? "—");
}

export function AlertasPage() {
  const [tab, setTab] = useState<AlertasTab>("actuales");
  const [alerts, setAlerts] = useState<LatestAlert[] | null>(null);
  const [history, setHistory] = useState<AlertHistoryEvent[] | null>(null);
  const [analysis, setAnalysis] = useState<AlertAnalysisRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [analysisLoading, setAnalysisLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);

  const [mercadoFiltro, setMercadoFiltro] = useState<MercadoFiltroVista>("");
  const [filterMercado, setFilterMercado] = useState("");
  const [filterTicker, setFilterTicker] = useState("");
  const [filterTipo, setFilterTipo] = useState("");
  const [rankingEstadoFilter, setRankingEstadoFilter] = useState<"todos" | "activo" | "historial">("todos");
  const [showDestacadosUltimoScan, setShowDestacadosUltimoScan] = useState(false);
  const [showAllHistoryRows, setShowAllHistoryRows] = useState(false);
  const [showAllAnalysisRows, setShowAllAnalysisRows] = useState(false);

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

  useEffect(() => {
    let cancelled = false;
    setAnalysisLoading(true);
    setAnalysisError(null);
    fetchAlertsAnalysis(ANALYSIS_FETCH_LIMIT)
      .then((data) => {
        if (!cancelled) setAnalysis(data);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setAnalysisError(e instanceof Error ? e.message : "Error al cargar análisis");
          setAnalysis(null);
        }
      })
      .finally(() => {
        if (!cancelled) setAnalysisLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const historyForView = useMemo(() => {
    if (!history) return null;
    if (!mercadoFiltro) return history;
    return history.filter((h) => mercadoBucket(h.mercado) === mercadoFiltro);
  }, [history, mercadoFiltro]);

  const activeTickers = useMemo(() => {
    const set = new Set<string>();
    for (const a of alerts ?? []) {
      const t = (a.ticker ?? "").trim().toUpperCase();
      if (t) set.add(t);
    }
    return set;
  }, [alerts]);

  const tickerMercadoByTicker = useMemo(() => {
    const m = new Map<string, string>();
    for (const a of alerts ?? []) {
      const t = (a.ticker ?? "").trim().toUpperCase();
      const mk = (a.mercado ?? "").trim();
      if (t && mk && !m.has(t)) {
        m.set(t, mk);
      }
    }
    for (const h of history ?? []) {
      const t = (h.ticker ?? "").trim().toUpperCase();
      const mk = (h.mercado ?? "").trim();
      if (t && mk && !m.has(t)) {
        m.set(t, mk);
      }
    }
    return m;
  }, [alerts, history]);

  const analysisJoinedAll = useMemo(() => {
    const rows = analysis ?? [];
    return rows.map((r) => {
      const tickerUp = (r.ticker ?? "").trim().toUpperCase();
      const mercado = tickerUp ? (tickerMercadoByTicker.get(tickerUp) ?? null) : null;
      return {
        ...r,
        ticker: tickerUp || r.ticker,
        activoAhora: tickerUp ? activeTickers.has(tickerUp) : false,
        mercado,
      };
    });
  }, [analysis, activeTickers, tickerMercadoByTicker]);

  const analysisJoined = useMemo(() => {
    if (!mercadoFiltro) return analysisJoinedAll;
    return analysisJoinedAll.filter((r) => mercadoBucket(r.mercado) === mercadoFiltro);
  }, [analysisJoinedAll, mercadoFiltro]);

  const analysisRankingRows = useMemo(() => {
    if (rankingEstadoFilter === "activo") {
      return analysisJoined.filter((r) => r.activoAhora);
    }
    if (rankingEstadoFilter === "historial") {
      return analysisJoined.filter((r) => !r.activoAhora);
    }
    return analysisJoined;
  }, [analysisJoined, rankingEstadoFilter]);

  const displayedAnalysisRows = useMemo(() => {
    if (showAllAnalysisRows || analysisRankingRows.length <= RANKING_TABLE_PREVIEW) {
      return analysisRankingRows;
    }
    return analysisRankingRows.slice(0, RANKING_TABLE_PREVIEW);
  }, [analysisRankingRows, showAllAnalysisRows]);

  useEffect(() => {
    setShowAllAnalysisRows(false);
  }, [rankingEstadoFilter, mercadoFiltro]);

  const radarDelMomentoTop5 = useMemo(() => {
    return analysisJoined.slice(0, 5);
  }, [analysisJoined]);

  const mercadoOptions = useMemo(() => {
    const set = new Set<string>();
    for (const h of historyForView ?? []) {
      const m = h.mercado?.trim();
      if (m) set.add(m);
    }
    return [...set].sort((a, b) => a.localeCompare(b, "es", { sensitivity: "base" }));
  }, [historyForView]);

  const tipoOptions = useMemo(() => {
    const set = new Set<string>();
    for (const h of historyForView ?? []) {
      const label = h.tipo_alerta_label?.trim();
      const key = h.tipo_alerta?.trim();
      if (label) set.add(label);
      else if (key) set.add(key);
    }
    return [...set].sort((a, b) => a.localeCompare(b, "es", { sensitivity: "base" }));
  }, [historyForView]);

  const alertsFiltradasMercado = useMemo(() => {
    if (!alerts) return null;
    if (!mercadoFiltro) return alerts;
    return alerts.filter((a) => mercadoBucket(a.mercado) === mercadoFiltro);
  }, [alerts, mercadoFiltro]);

  const filteredHistory = useMemo(() => {
    const rows = historyForView ?? [];
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
  }, [historyForView, filterMercado, filterTicker, filterTipo]);

  const displayedHistoryRows = useMemo(() => {
    if (showAllHistoryRows || filteredHistory.length <= HISTORY_TABLE_PREVIEW) {
      return filteredHistory;
    }
    return filteredHistory.slice(0, HISTORY_TABLE_PREVIEW);
  }, [filteredHistory, showAllHistoryRows]);

  const downloadHistorialCsv = useCallback(() => {
    // Todas las filas que cumplen filtros del historial (mercado/ticker/tipo), hasta el límite del fetch.
    // No usar displayedHistoryRows: la tabla puede truncar a 15; el CSV exporta el subconjunto completo en memoria.
    const rows = filteredHistory;
    const header = [
      "Fecha",
      "Ticker",
      "Mercado",
      "Segmento",
      "Tipo",
      "Conviccion",
      "Prioridad",
      "TotalScore",
      "RSI",
      "Precio",
    ];
    const lines = [header.map(csvEscapeCell).join(",")];
    for (const h of rows) {
      const tipo = h.tipo_alerta_label?.trim() || h.tipo_alerta?.trim() || "";
      lines.push(
        [
          csvEscapeCell(formatScanAt(h.scan_at)),
          csvEscapeCell(h.ticker ?? ""),
          csvEscapeCell(h.mercado ?? ""),
          csvEscapeCell(segmentLabel(h)),
          csvEscapeCell(tipo),
          csvEscapeCell(
            h.conviccion != null && String(h.conviccion).trim() !== "" ? String(h.conviccion) : "",
          ),
          csvEscapeCell(h.prioridad ?? ""),
          csvEscapeCell(h.total_score ?? ""),
          csvEscapeCell(h.rsi ?? ""),
          csvEscapeCell(h.precio ?? ""),
        ].join(","),
      );
    }
    const csv = `\uFEFF${lines.join("\n")}`;
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "historial_alertas.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }, [filteredHistory]);

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
    if (historyError || historyForView === null) return null;
    const rows = historyForView;

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
  }, [historyLoading, historyError, historyForView]);

  const mercadoTopTickerFrecuente = useMemo(() => {
    const tt = analiticaHistorial?.topTicker?.ticker?.trim().toUpperCase();
    if (!tt || !historyForView) return null;
    for (const h of historyForView) {
      if ((h.ticker ?? "").trim().toUpperCase() !== tt) continue;
      const m = (h.mercado ?? "").trim();
      if (m) return m;
    }
    return null;
  }, [analiticaHistorial?.topTicker?.ticker, historyForView]);

  /** Tickers del último scan_id (por scan_at más reciente) con ranking vs historial completo cargado. */
  const ultimoScanTickersRanking = useMemo(() => {
    if (historyLoading || historyError || historyForView === null || historyForView.length === 0) {
      return null;
    }
    const rows = historyForView;

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
  }, [historyLoading, historyError, historyForView]);

  return (
    <>
      <h1 className="page-title">Alertas</h1>
      <p className="page-desc">
        Consultá las alertas del último export y el historial.
      </p>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.6rem",
          alignItems: "stretch",
          justifyContent: "flex-start",
          marginTop: "-0.35rem",
          marginBottom: "1.25rem",
          maxWidth: "60rem",
        }}
      >
        <div
          className="msg-muted"
          style={{ maxWidth: "40rem", flex: "0 1 520px" }}
          title="En el radar, SignalState resume el estado según score y reglas fijas. El tipo de alerta es un evento por corrida (cambio de score, huella de señales, etc.)."
        >
          <ul style={{ margin: 0, paddingLeft: "1.15rem" }}>
            <li>
              <strong>SignalState</strong>: es el estado del radar, en función al <strong>Total Score</strong>.
            </li>
            <li>
              <strong>Tipo de alerta</strong>: es el evento detectado en esa corrida según reglas del motor.
            </li>
          </ul>
        </div>
        <div
          className="stat dashboard-stat"
          style={{ ...parallelStatCardStyle, flex: "0 0 240px", minWidth: "220px" }}
        >
          <div className="stat__label">Último evento</div>
          <div className="stat__value" style={{ fontSize: "1.15rem" }}>
            {resumenUltimoScanAt ?? "—"}
          </div>
        </div>
      </div>

      <div className="dashboard-stats-grid" style={{ marginBottom: "1.25rem" }}>
        <div className="stat dashboard-stat" style={parallelStatCardStyle}>
          <div className="stat__label">Alertas actuales USA</div>
          <div className="stat__value">{fmtResumen(resumenActualesUsa)}</div>
        </div>
        <div className="stat dashboard-stat" style={parallelStatCardStyle}>
          <div className="stat__label">Alertas actuales Argentina</div>
          <div className="stat__value">{fmtResumen(resumenActualesArg)}</div>
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
          <h2 style={{ marginTop: 0, fontSize: "1.05rem", fontWeight: 700 }}>
            Historial de alertas
          </h2>
          <p className="msg-muted" style={{ marginTop: 0 }}>
            Evolución reciente de alertas detectadas por el radar.
          </p>

          <div className="dashboard-stats-grid" style={{ marginBottom: "1rem" }}>
            <div className="stat dashboard-stat" style={parallelStatCardStyle}>
              <div className="stat__label">Eventos cargados</div>
              <div className="stat__value">{analiticaHistorial ? String(analiticaHistorial.total) : "—"}</div>
            </div>
            <div className="stat dashboard-stat" style={parallelStatCardStyle}>
              <div className="stat__label">Por mercado</div>
              <div className="stat__value">
                {analiticaHistorial ? `USA ${analiticaHistorial.usa} · AR ${analiticaHistorial.argentina}` : "—"}
              </div>
            </div>
            <div className="stat dashboard-stat" style={parallelStatCardStyle}>
              <div className="stat__label">Por tipo</div>
              <div
                className="stat__value"
                style={{ fontSize: "1.05rem" }}
                title="CP=Compra potencial · CF=Compra fuerte · V=Venta · TG=Toma ganancia"
              >
                {analiticaHistorial
                  ? `CP ${analiticaHistorial.porTipo.compra_potencial} · CF ${analiticaHistorial.porTipo.compra_fuerte} · V ${analiticaHistorial.porTipo.venta} · TG ${analiticaHistorial.porTipo.toma_ganancia}`
                  : "—"}
              </div>
            </div>
            <div className="stat dashboard-stat" style={parallelStatCardStyle}>
              <div className="stat__label">Ticker más frecuente</div>
              <div className="stat__value">
                {analiticaHistorial?.topTicker ? (
                  <TickerRadarLink
                    ticker={analiticaHistorial.topTicker.ticker}
                    mercado={mercadoTopTickerFrecuente ?? "USA"}
                  />
                ) : (
                  "—"
                )}
              </div>
              <div className="msg-muted dashboard-stat__hint" style={{ textAlign: "center" }}>
                {analiticaHistorial?.topTicker ? `${analiticaHistorial.topTicker.count} eventos` : "—"}
              </div>
            </div>
          </div>

          <div style={{ marginBottom: "1.1rem" }}>
            <h3 style={{ margin: "0 0 0.35rem", fontSize: "0.95rem", fontWeight: 600 }}>
              Radar del momento
            </h3>

            {analysisLoading && <p className="msg-muted">Cargando análisis…</p>}
            {!analysisLoading && analysisError && <p className="msg-error">{analysisError}</p>}
            {!analysisLoading && !analysisError && analysisJoined.length === 0 && (
              <p className="msg-muted">No hay datos de análisis (historial vacío).</p>
            )}

            {!analysisLoading && !analysisError && radarDelMomentoTop5.length > 0 && (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                  gap: "0.65rem",
                }}
              >
                {radarDelMomentoTop5.map((r) => (
                  <div key={r.ticker} className="stat dashboard-stat" style={{ padding: "0.75rem" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem" }}>
                      <div className="stat__label">Ticker</div>
                      {r.activoAhora ? (
                        <span className="radar-badge radar-badge--conv-alta" title="Presente en /latest-alerts">
                          Activo ahora
                        </span>
                      ) : (
                        <span className="radar-badge" title="No aparece en /latest-alerts">
                          Solo historial
                        </span>
                      )}
                    </div>
                    <div className="stat__value" style={{ fontSize: "1.25rem" }}>
                      <TickerRadarLink ticker={r.ticker} mercado={r.mercado ?? "USA"} />
                    </div>
                    <div className="msg-muted dashboard-stat__hint" style={{ display: "flex", flexWrap: "wrap", gap: "0.35rem" }}>
                      <span className={classForTipoAlerta(r.tipo_actual, r.tipo_actual)} title={tooltipForAlertType(r.tipo_actual, r.tipo_actual)}>
                        {r.tipo_actual ?? "—"}
                      </span>
                      <span className="radar-badge" title="Score actual">
                        score {fmtMaybe(r.score_actual)}
                      </span>
                      <span className="radar-badge" title="Aceleración (suma Δ score últimos 3 eventos)">
                        acel {fmtMaybe(r.aceleracion)}
                      </span>
                      <span className="radar-badge" title="Scans distintos">
                        scans {fmtMaybe(r.cantidad_scans)}
                      </span>
                      <span className="radar-badge" title="Scans consecutivos recientes en los que apareció el ticker">
                        Consecutivo {fmtMaybe(r.racha_scans)}
                      </span>
                      {r.cambio_regimen && regimenLabel(r.direccion_regimen) && (
                        <span className={classForRegimen(r.direccion_regimen)} title="Cambio relevante compra_* ↔ venta/toma_ganancia en eventos recientes">
                          {regimenLabel(r.direccion_regimen)}
                        </span>
                      )}
                      <span
                        className={classForTendenciaConRegimen(r.tendencia, {
                          cambioRegimen: r.cambio_regimen,
                          direccionRegimen: r.direccion_regimen,
                        })}
                        title="Tendencia por aceleración (cambio de score reciente)"
                      >
                        {tendenciaLabel(r.tendencia)}
                      </span>
                      <span className="radar-badge" title="Ranking score">
                        rank {fmt1(r.ranking_score)}
                      </span>
                      <span className="msg-muted" title="Recencia">
                        {fmtHaceSegundos(r.recencia_segundos)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div style={{ marginBottom: "1.1rem" }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "0.4rem",
                flexWrap: "wrap",
                marginBottom: "0.35rem",
              }}
            >
              <h3
                style={{ margin: 0, fontSize: "0.95rem", fontWeight: 600 }}
                title={RANKING_FORMATION_TOOLTIP}
              >
                Ranking inteligente
              </h3>
              <span
                className="radar-chip"
                style={{ cursor: "help", fontSize: "0.72rem", padding: "0.15rem 0.4rem", lineHeight: 1.2 }}
                title={RANKING_FORMATION_TOOLTIP}
                aria-label={RANKING_FORMATION_TOOLTIP}
              >
                i
              </span>
            </div>
            <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.5rem", fontSize: "0.88rem" }}>
              Resumen de alertas por Activo.
            </p>
            <div
              role="group"
              aria-label="Filtrar ranking por estado"
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: "0.4rem",
                alignItems: "center",
                marginBottom: "0.6rem",
              }}
            >
              <button
                type="button"
                className={`radar-chip${rankingEstadoFilter === "todos" ? " radar-chip--active" : ""}`}
                onClick={() => setRankingEstadoFilter("todos")}
              >
                Todos
              </button>
              <button
                type="button"
                className={`radar-chip${rankingEstadoFilter === "activo" ? " radar-chip--active" : ""}`}
                onClick={() => setRankingEstadoFilter("activo")}
              >
                Activo ahora
              </button>
              <button
                type="button"
                className={`radar-chip${rankingEstadoFilter === "historial" ? " radar-chip--active" : ""}`}
                onClick={() => setRankingEstadoFilter("historial")}
              >
                Solo historial
              </button>
              <span
                className="msg-muted"
                style={{ marginLeft: "auto", fontSize: "0.85rem", cursor: "help" }}
                title="Resumen de alertas por Activo. Tickers únicos a partir del historial reciente cargado para análisis (máx. visible en esta pantalla). No equivale a alertas actuales ni al historial completo del sistema."
              >
                {analysisRankingRows.length} tickers únicos
              </span>
            </div>

            {!analysisLoading && !analysisError && displayedAnalysisRows.length > 0 && (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Ticker</th>
                      <th>Estado</th>
                      <th>Tipo actual</th>
                      <th>Score</th>
                      <th>Aceleración</th>
                      <th>Scans</th>
                      <th>Consecutivo</th>
                      <th>Novedad</th>
                      <th>Régimen</th>
                      <th>Tendencia</th>
                      <th title={RANKING_COLUMN_TOOLTIP}>Ranking</th>
                      <th>Recencia</th>
                    </tr>
                  </thead>
                  <tbody>
                    {displayedAnalysisRows.map((r) => (
                      <tr key={r.ticker}>
                        <td>
                          <TickerRadarLink ticker={r.ticker} mercado={r.mercado} />
                        </td>
                        <td>
                          {r.activoAhora ? (
                            <span className="radar-badge radar-badge--conv-alta" title="Presente en /latest-alerts">
                              Activo ahora
                            </span>
                          ) : (
                            <span className="radar-badge" title="No aparece en /latest-alerts">
                              Solo historial
                            </span>
                          )}
                        </td>
                        <td>
                          <span
                            className={classForTipoAlerta(r.tipo_actual, r.tipo_actual)}
                            title={tooltipForAlertType(r.tipo_actual, r.tipo_actual)}
                          >
                            {r.tipo_actual ?? "—"}
                          </span>
                        </td>
                        <td>{fmtMaybe(r.score_actual)}</td>
                        <td>{fmtMaybe(r.aceleracion)}</td>
                        <td>{fmtMaybe(r.cantidad_scans)}</td>
                        <td>{fmtMaybe(r.racha_scans)}</td>
                        <td>{fmtMaybe(r.novedad)}</td>
                        <td title={tooltipRegimenRanking(r)}>
                          {r.cambio_regimen && r.direccion_regimen === "mejora" ? (
                            <span className="radar-badge radar-badge--conv-alta">Mejora</span>
                          ) : r.cambio_regimen && r.direccion_regimen === "deterioro" ? (
                            <span className="radar-badge radar-badge--conv-baja">Deterioro</span>
                          ) : (
                            <span className="msg-muted">-</span>
                          )}
                        </td>
                        <td>
                          <span className={classForTendencia(r.tendencia)} title={tooltipTendenciaRanking(r.tendencia)}>
                            {tendenciaLabel(r.tendencia)}
                          </span>
                        </td>
                        <td title={RANKING_CELL_TOOLTIP}>{fmt1(r.ranking_score)}</td>
                        <td>{fmtHaceSegundos(r.recencia_segundos)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {!analysisLoading && !analysisError && analysisRankingRows.length > RANKING_TABLE_PREVIEW && (
              <div style={{ marginTop: "0.65rem", textAlign: "center" }}>
                <button type="button" className="radar-chip" onClick={() => setShowAllAnalysisRows((v) => !v)}>
                  {showAllAnalysisRows ? "Ocultar resto" : "Mostrar todos"}
                </button>
              </div>
            )}
          </div>

          <div style={{ marginBottom: "1.1rem" }}>
            <button
              type="button"
              className="radar-chip"
              aria-expanded={showDestacadosUltimoScan}
              onClick={() => setShowDestacadosUltimoScan((v) => !v)}
              style={{
                width: "100%",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "0.55rem 0.7rem",
                fontWeight: 600,
              }}
              title="Ver detalle del scan más reciente"
            >
              <span>Destacados del ultimo scan</span>
              <span aria-hidden style={{ opacity: 0.75, fontSize: "0.9rem" }}>
                {showDestacadosUltimoScan ? "▾" : "▸"}
              </span>
            </button>
            {showDestacadosUltimoScan && (
              <div style={{ marginTop: "0.6rem" }}>
              <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.6rem", fontSize: "0.88rem" }}>
                Muestra los tickers que aparecieron en el scan mas reciente y cuantas veces figuran en el historial
                cargado. El orden prioriza mayor presencia historica, y luego mayor presencia en el ultimo scan.
              </p>
              {!historyLoading &&
                !historyError &&
                historyForView &&
                historyForView.length > 0 &&
                ultimoScanTickersRanking?.kind === "no_scan_id" && (
                  <p className="msg-muted" style={{ margin: 0 }}>
                    No hay <code>scan_id</code> en los eventos cargados; no se puede armar este ranking.
                  </p>
                )}
              {!historyLoading &&
                !historyError &&
                historyForView &&
                historyForView.length > 0 &&
                ultimoScanTickersRanking?.kind === "empty_last" && (
                  <p className="msg-muted" style={{ margin: 0 }}>
                    Hay <code>scan_id</code> pero ningun evento coincide con el ultimo scan (
                    <code>{shortenScanId(ultimoScanTickersRanking.ultimoScanId)}</code>).
                  </p>
                )}
              {!historyLoading &&
                !historyError &&
                historyForView &&
                historyForView.length > 0 &&
                ultimoScanTickersRanking?.kind === "ok" && (
                  <>
                    <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.5rem", fontSize: "0.85rem" }}>
                      Scan:{" "}
                      <code title={ultimoScanTickersRanking.ultimoScanId}>
                        {shortenScanId(ultimoScanTickersRanking.ultimoScanId)}
                      </code>{" "}
                      · {ultimoScanTickersRanking.totalEnUltimoScan} tickers · top {ultimoScanTickersRanking.rows.length}
                    </p>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Ticker</th>
                            <th>Ultimo scan</th>
                            <th>Historial</th>
                            <th>Mercado</th>
                            <th>Tipo frec.</th>
                            <th title="3+ eventos en historial cargado y presente en el ultimo scan">Recurrente</th>
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
                                  <span className="radar-badge radar-badge--conv-alta" title="3+ eventos en el historial cargado">
                                    si
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
            )}
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "0.75rem",
              flexWrap: "wrap",
              marginBottom: "0.65rem",
            }}
          >
            <h3
              style={{
                margin: 0,
                fontSize: "0.95rem",
                fontWeight: 700,
                letterSpacing: "0.02em",
              }}
            >
              HISTORIAL DE ALERTAS (maximo visible {ALERT_HISTORY_DEFAULT_LIMIT})
            </h3>
            <button
              type="button"
              className="radar-chip"
              onClick={downloadHistorialCsv}
              disabled={historyLoading || filteredHistory.length === 0}
              title={
                filteredHistory.length === 0
                  ? "No hay filas para exportar con los filtros actuales"
                  : "Exportar todas las filas del historial filtrado cargadas en esta vista (hasta el límite del fetch), no solo las visibles en la tabla."
              }
            >
              Descargar CSV
            </button>
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
              {filteredHistory.length} de {historyForView?.length ?? 0} eventos
            </p>
          </div>

          {historyLoading && <p className="msg-muted">Cargando historial…</p>}
          {historyError && <p className="msg-error">{historyError}</p>}
          {!historyLoading && !historyError && historyForView && historyForView.length === 0 && (
            <p className="msg-muted">
              Todavía no hay eventos registrados (ejecutá un scan para poblar el historial).
            </p>
          )}
          {!historyLoading &&
            !historyError &&
            historyForView &&
            historyForView.length > 0 &&
            filteredHistory.length === 0 && (
              <p className="msg-muted">No hay eventos con los filtros actuales.</p>
            )}
          {!historyLoading && !historyError && historyForView && historyForView.length > 0 && filteredHistory.length > 0 && (
            <>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Fecha</th>
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
                    {displayedHistoryRows.map((h, i) => {
                    const tipoDisplay = h.tipo_alerta_label?.trim() || h.tipo_alerta || "—";
                    return (
                      <tr key={`${h.scan_id ?? h.scan_at}-${h.ticker ?? "x"}-${i}`}>
                        <td className="table-cell--nowrap" title={h.scan_at}>
                          {formatScanAt(h.scan_at)}
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
              {filteredHistory.length > HISTORY_TABLE_PREVIEW && (
                <div style={{ marginTop: "0.65rem", textAlign: "center" }}>
                  <button
                    type="button"
                    className="radar-chip"
                    onClick={() => setShowAllHistoryRows((v) => !v)}
                  >
                    {showAllHistoryRows ? "Ocultar resto" : "Mostrar todos"}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </>
  );
}
