import { useEffect, useMemo, useRef, useState } from "react";

import { getRaw, parseNumberLoose } from "@/components/radar/radarTableCore";
import {
  fetchLatestRadar,
  getUsaEventsUpdateStatus,
  triggerUsaEventsUpdate,
  type LatestRadarResponse,
  type RadarRow,
  type UsaEventsUpdateStatus,
} from "@/services/api";

type UsaEventRow = {
  ticker: string;
  empresa: string | null;
  sector: string | null;
  precio: number | null;
  tieneCedear: boolean | null;
  totalScore: number | null;
  signalState: string | null;
  prioridadRadar: number | null;
  fechaProximoEarnings: string | null;
  diasHastaEarnings: number | null;
  earningsEn7d: boolean | null;
  earningsEn30d: boolean | null;
  fechaUltimoDividendo: string | null;
  ultimoDividendo: number | null;
  dividendYieldPagoPct: number | null;
  dividendYieldAnualEstimadoPct: number | null;
  frecuenciaDividendos: string | null;
  fechaProximoDividendoEstimado: string | null;
  diasHastaProximoDividendo: number | null;
  dividendosEstimados12m: number | null;
  flujoDividendos12mPorAccion: number | null;
  updatedAt: string | null;
};

const KEYS = {
  ticker: ["Ticker", "ticker"],
  cedear: ["CEDEAR", "cedear"],
  empresa: ["Empresa", "empresa", "LongName", "longName"],
  sector: ["Sector", "sector"],
  precio: ["Precio", "precio"],
  total: ["TotalScore", "total_score", "total"],
  signal: ["SignalState", "signal_state", "signalState"],
  prioridad: ["PrioridadRadar", "prioridad_radar", "prioridad"],

  fechaE: ["fecha_proximo_earnings", "FechaProximoEarnings", "fechaProximoEarnings"],
  diasE: ["dias_hasta_earnings", "DiasHastaEarnings", "diasHastaEarnings"],
  e7: ["earnings_en_7d", "EarningsEn7d", "earningsEn7d"],
  e30: ["earnings_en_30d", "EarningsEn30d", "earningsEn30d"],

  fechaUltDiv: ["fecha_ultimo_dividendo", "FechaUltimoDividendo", "fechaUltimoDividendo"],
  ultDiv: ["ultimo_dividendo", "UltimoDividendo", "ultimoDividendo"],
  yPago: [
    "dividend_yield_pago_pct",
    "DividendYieldPagoPct",
    "dividendYieldPagoPct",
  ],
  yAnual: [
    "dividend_yield_anual_estimado_pct",
    "DividendYieldAnualEstimadoPct",
    "dividendYieldAnualEstimadoPct",
  ],
  freq: ["frecuencia_dividendos", "FrecuenciaDividendos", "frecuenciaDividendos"],
  fechaNextDiv: [
    "fecha_proximo_dividendo_estimado",
    "FechaProximoDividendoEstimado",
    "fechaProximoDividendoEstimado",
  ],
  diasNextDiv: [
    "dias_hasta_proximo_dividendo",
    "DiasHastaProximoDividendo",
    "diasHastaProximoDividendo",
  ],
  nPagos12m: ["dividendos_estimados_12m", "DividendosEstimados12m", "dividendosEstimados12m"],
  flujo12m: ["flujo_dividendos_12m_por_accion", "FlujoDividendos12mPorAccion", "flujoDividendos12mPorAccion"],
  updatedAt: ["updated_at", "UpdatedAt", "updatedAt"],
} as const;

function parseIsoDate(v: unknown): Date | null {
  const s = v === null || v === undefined ? "" : String(v).trim();
  if (!s) return null;
  // Formato esperado: YYYY-MM-DD
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (!m) return null;
  const y = Number(m[1]);
  const mo = Number(m[2]) - 1;
  const d = Number(m[3]);
  const dt = new Date(Date.UTC(y, mo, d));
  return Number.isNaN(dt.getTime()) ? null : dt;
}

function parseIsoDateTimeUtc(v: unknown): Date | null {
  const s = v === null || v === undefined ? "" : String(v).trim();
  if (!s) return null;
  const dt = new Date(s);
  return Number.isNaN(dt.getTime()) ? null : dt;
}

function fmtDateIsoOrEmpty(s: string | null): string {
  const t = (s ?? "").trim();
  return t ? t : "Sin dato";
}

function toUsaEventRow(r: RadarRow): UsaEventRow | null {
  const ticker = String(getRaw(r, KEYS.ticker) ?? "").trim();
  if (!ticker) return null;

  const empresaRaw = getRaw(r, KEYS.empresa);
  const sectorRaw = getRaw(r, KEYS.sector);
  const signalRaw = getRaw(r, KEYS.signal);
  const cedearRaw = getRaw(r, KEYS.cedear);
  const cedearStr = cedearRaw === undefined || cedearRaw === null ? "" : String(cedearRaw).trim().toUpperCase();
  const tieneCedear =
    cedearStr === "SI" || cedearStr === "SÍ" || cedearStr === "YES" || cedearStr === "TRUE" ? true
      : cedearStr === "NO" || cedearStr === "FALSE" ? false
        : null;

  return {
    ticker,
    empresa: empresaRaw !== undefined ? String(empresaRaw) : null,
    sector: sectorRaw !== undefined ? String(sectorRaw) : null,
    precio: parseNumberLoose(getRaw(r, KEYS.precio)),
    tieneCedear,
    totalScore: parseNumberLoose(getRaw(r, KEYS.total)),
    signalState: signalRaw !== undefined ? String(signalRaw) : null,
    prioridadRadar: parseNumberLoose(getRaw(r, KEYS.prioridad)),

    fechaProximoEarnings: (() => {
      const v = getRaw(r, KEYS.fechaE);
      const s = v === undefined || v === null ? "" : String(v).trim();
      return s ? s : null;
    })(),
    diasHastaEarnings: parseNumberLoose(getRaw(r, KEYS.diasE)),
    earningsEn7d: (() => {
      const v = getRaw(r, KEYS.e7);
      if (typeof v === "boolean") return v;
      if (typeof v === "number") return v !== 0;
      const s = v === undefined || v === null ? "" : String(v).trim().toLowerCase();
      if (s === "true" || s === "1" || s === "si" || s === "sí") return true;
      if (s === "false" || s === "0" || s === "no") return false;
      return null;
    })(),
    earningsEn30d: (() => {
      const v = getRaw(r, KEYS.e30);
      if (typeof v === "boolean") return v;
      if (typeof v === "number") return v !== 0;
      const s = v === undefined || v === null ? "" : String(v).trim().toLowerCase();
      if (s === "true" || s === "1" || s === "si" || s === "sí") return true;
      if (s === "false" || s === "0" || s === "no") return false;
      return null;
    })(),

    fechaUltimoDividendo: (() => {
      const v = getRaw(r, KEYS.fechaUltDiv);
      const s = v === undefined || v === null ? "" : String(v).trim();
      return s ? s : null;
    })(),
    ultimoDividendo: parseNumberLoose(getRaw(r, KEYS.ultDiv)),
    dividendYieldPagoPct: parseNumberLoose(getRaw(r, KEYS.yPago)),
    dividendYieldAnualEstimadoPct: parseNumberLoose(getRaw(r, KEYS.yAnual)),
    frecuenciaDividendos: (() => {
      const v = getRaw(r, KEYS.freq);
      const s = v === undefined || v === null ? "" : String(v).trim();
      return s ? s : null;
    })(),
    fechaProximoDividendoEstimado: (() => {
      const v = getRaw(r, KEYS.fechaNextDiv);
      const s = v === undefined || v === null ? "" : String(v).trim();
      return s ? s : null;
    })(),
    diasHastaProximoDividendo: parseNumberLoose(getRaw(r, KEYS.diasNextDiv)),
    dividendosEstimados12m: parseNumberLoose(getRaw(r, KEYS.nPagos12m)),
    flujoDividendos12mPorAccion: parseNumberLoose(getRaw(r, KEYS.flujo12m)),
    updatedAt: (() => {
      const v = getRaw(r, KEYS.updatedAt);
      const s = v === undefined || v === null ? "" : String(v).trim();
      return s ? s : null;
    })(),
  };
}

function addMonthsUtc(d: Date, months: number): Date {
  const y = d.getUTCFullYear();
  const m = d.getUTCMonth();
  const day = d.getUTCDate();
  // Evitar “wrap” extraño: ir al primer día, sumar meses, volver a min(day, lastDay)
  const first = new Date(Date.UTC(y, m, 1));
  const target = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + months, 1));
  const nextMonth = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 1));
  const lastDay = Math.round((nextMonth.getTime() - target.getTime()) / (24 * 3600 * 1000));
  const safeDay = Math.min(day, lastDay);
  return new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth(), safeDay));
}

function monthKeyUtc(d: Date): string {
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

const fmtUsd2 = new Intl.NumberFormat("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtPct2 = new Intl.NumberFormat("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtEsArDateTime = new Intl.DateTimeFormat("es-AR", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export function EventosPage() {
  const [radar, setRadar] = useState<LatestRadarResponse | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [selectedMonth, setSelectedMonth] = useState<string | null>(null);
  const [detailSortBy, setDetailSortBy] = useState<"date" | "amount">("date");
  const [detailSortDir, setDetailSortDir] = useState<"asc" | "desc">("asc");
  const [flowOnlyCedear, setFlowOnlyCedear] = useState<boolean>(false);
  const detailRef = useRef<HTMLDivElement | null>(null);

  const [divRankCedear, setDivRankCedear] = useState<"all" | "cedear">("all");
  const [divRankNextPay, setDivRankNextPay] = useState<boolean>(false);
  const [divRankFreq, setDivRankFreq] = useState<
    "all" | "monthly" | "quarterly" | "semiannual" | "annual" | "irregular"
  >("all");
  const [divRankSort, setDivRankSort] = useState<
    "yield_anual" | "flujo_12m" | "pagos_12m" | "proximo_pago" | "score"
  >("yield_anual");

  const [updateStatus, setUpdateStatus] = useState<UsaEventsUpdateStatus | null>(null);
  const [updateMsg, setUpdateMsg] = useState<string | null>(null);
  const [isTriggering, setIsTriggering] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setRadar(undefined);
    fetchLatestRadar()
      .then((d) => {
        if (!cancelled) setRadar(d);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Error al cargar el radar");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    getUsaEventsUpdateStatus()
      .then((s) => {
        if (!cancelled) setUpdateStatus(s);
      })
      .catch(() => null);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (updateStatus?.status !== "running") return;
    const id = window.setInterval(() => {
      getUsaEventsUpdateStatus()
        .then((s) => {
          setUpdateStatus(s);
          if (s.status === "success") {
            setUpdateMsg("Eventos actualizados correctamente.");
            const lu = s.last_updated_at;
            fetchLatestRadar()
              .then((d) => setRadar(d))
              .catch(() => null)
              .finally(() => {
                if (!lu) return;
                setUpdateStatus((prev) => (prev ? { ...prev, last_updated_at: lu } : prev));
              });
          } else if (s.status === "error") {
            setUpdateMsg("No se pudieron actualizar los eventos. Podés reintentar.");
          }
        })
        .catch(() => null);
    }, 4000);
    return () => window.clearInterval(id);
  }, [updateStatus?.status]);

  const rows = radar?.rows ?? [];
  const events = useMemo(() => rows.map(toUsaEventRow).filter(Boolean) as UsaEventRow[], [rows]);

  const latestUpdatedAt = useMemo(() => {
    let max: Date | null = null;
    for (const r of events) {
      const dt = parseIsoDateTimeUtc(r.updatedAt);
      if (!dt) continue;
      if (max === null || dt.getTime() > max.getTime()) {
        max = dt;
      }
    }
    return max;
  }, [events]);

  const displayUpdatedAt = useMemo(() => {
    const raw = updateStatus?.last_updated_at;
    if (typeof raw === "string" && raw.trim()) {
      const dt = parseIsoDateTimeUtc(raw);
      if (dt) return dt;
    }
    return latestUpdatedAt;
  }, [updateStatus?.last_updated_at, latestUpdatedAt]);

  const upcoming = useMemo(() => {
    const items = events
      .map((r) => {
        const e = parseIsoDate(r.fechaProximoEarnings);
        const d = parseIsoDate(r.fechaProximoDividendoEstimado);
        const next = e && d ? (e.getTime() <= d.getTime() ? e : d) : e ?? d;
        return { row: r, next, e, d };
      })
      .filter((x) => x.next !== null);

    items.sort((a, b) => (a.next!.getTime() - b.next!.getTime()));
    return items.slice(0, 50);
  }, [events]);

  const flowEvents = useMemo(() => {
    if (!flowOnlyCedear) return events;
    return events.filter((r) => r.tieneCedear === true);
  }, [events, flowOnlyCedear]);

  const dividendRankRows = useMemo(() => {
    let out = events;
    if (divRankCedear === "cedear") {
      out = out.filter((r) => r.tieneCedear === true);
    }
    if (divRankNextPay) {
      out = out.filter((r) => (r.fechaProximoDividendoEstimado ?? "").trim() !== "");
    }
    if (divRankFreq !== "all") {
      out = out.filter((r) => (r.frecuenciaDividendos ?? "").trim().toLowerCase() === divRankFreq);
    }

    const numOrNegInf = (v: number | null) => (v === null ? Number.NEGATIVE_INFINITY : v);
    const daysOrInf = (v: number | null) => (v === null ? Number.POSITIVE_INFINITY : v);

    const sorted = [...out];
    sorted.sort((a, b) => {
      if (divRankSort === "yield_anual") {
        const va = numOrNegInf(a.dividendYieldAnualEstimadoPct);
        const vb = numOrNegInf(b.dividendYieldAnualEstimadoPct);
        if (va !== vb) return vb - va;
      } else if (divRankSort === "flujo_12m") {
        const va = numOrNegInf(a.flujoDividendos12mPorAccion);
        const vb = numOrNegInf(b.flujoDividendos12mPorAccion);
        if (va !== vb) return vb - va;
      } else if (divRankSort === "pagos_12m") {
        const va = numOrNegInf(a.dividendosEstimados12m);
        const vb = numOrNegInf(b.dividendosEstimados12m);
        if (va !== vb) return vb - va;
      } else if (divRankSort === "proximo_pago") {
        const va = daysOrInf(a.diasHastaProximoDividendo);
        const vb = daysOrInf(b.diasHastaProximoDividendo);
        if (va !== vb) return va - vb;
      } else if (divRankSort === "score") {
        const va = numOrNegInf(a.totalScore);
        const vb = numOrNegInf(b.totalScore);
        if (va !== vb) return vb - va;
      }
      return a.ticker.localeCompare(b.ticker);
    });

    return sorted.slice(0, 30);
  }, [divRankCedear, divRankFreq, divRankNextPay, divRankSort, events]);

  const dividendMonthly = useMemo(() => {
    const agg = new Map<string, { amount: number; count: number }>();
    const today = new Date();
    const start = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()));
    const end = addMonthsUtc(start, 12);

    for (const r of flowEvents) {
      const freq = (r.frecuenciaDividendos ?? "").toLowerCase();
      const stepMonths =
        freq === "monthly" ? 1 : freq === "quarterly" ? 3 : freq === "semiannual" ? 6 : freq === "annual" ? 12 : null;
      if (!stepMonths) continue;
      const first = parseIsoDate(r.fechaProximoDividendoEstimado);
      const perPay = r.ultimoDividendo;
      if (!first || perPay === null || !Number.isFinite(perPay) || perPay <= 0) continue;

      let pay = first;
      // Asegurar que esté dentro de ventana
      while (pay.getTime() < start.getTime()) {
        pay = addMonthsUtc(pay, stepMonths);
      }
      while (pay.getTime() < end.getTime()) {
        const k = monthKeyUtc(pay);
        const cur = agg.get(k) ?? { amount: 0, count: 0 };
        cur.amount += perPay;
        cur.count += 1;
        agg.set(k, cur);
        pay = addMonthsUtc(pay, stepMonths);
      }
    }

    const months = Array.from(agg.entries())
      .map(([k, v]) => ({ month: k, amount: v.amount, count: v.count }))
      .sort((a, b) => a.month.localeCompare(b.month));

    // Asegurar 12 meses en pantalla aunque estén vacíos
    const out: { month: string; amount: number; count: number }[] = [];
    let cur = start;
    for (let i = 0; i < 12; i++) {
      const k = monthKeyUtc(cur);
      const v = agg.get(k) ?? { amount: 0, count: 0 };
      out.push({ month: k, amount: v.amount, count: v.count });
      cur = addMonthsUtc(cur, 1);
    }
    return out;
  }, [flowEvents]);

  type ProjectedPay = {
    month: string;
    date: string;
    ticker: string;
    empresa: string | null;
    precio: number | null;
    amount: number;
  };

  const projectedPays = useMemo(() => {
    const out: ProjectedPay[] = [];
    const today = new Date();
    const start = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()));
    const end = addMonthsUtc(start, 12);

    for (const r of flowEvents) {
      const freq = (r.frecuenciaDividendos ?? "").toLowerCase();
      const stepMonths =
        freq === "monthly"
          ? 1
          : freq === "quarterly"
            ? 3
            : freq === "semiannual"
              ? 6
              : freq === "annual"
                ? 12
                : null;
      if (!stepMonths) continue;
      const first = parseIsoDate(r.fechaProximoDividendoEstimado);
      const perPay = r.ultimoDividendo;
      if (!first || perPay === null || !Number.isFinite(perPay) || perPay <= 0) continue;

      let pay = first;
      while (pay.getTime() < start.getTime()) {
        pay = addMonthsUtc(pay, stepMonths);
      }
      while (pay.getTime() < end.getTime()) {
        out.push({
          month: monthKeyUtc(pay),
          date: pay.toISOString().slice(0, 10),
          ticker: r.ticker,
          empresa: r.empresa,
          precio: r.precio,
          amount: perPay,
        });
        pay = addMonthsUtc(pay, stepMonths);
      }
    }

    out.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : a.ticker.localeCompare(b.ticker)));
    return out;
  }, [flowEvents]);

  const capitalNeededByMonth = useMemo(() => {
    const m = new Map<string, number>();
    const seenByMonth = new Map<string, Set<string>>();
    for (const p of projectedPays) {
      const px = p.precio;
      if (px === null || !Number.isFinite(px) || px <= 0) continue;
      const set = seenByMonth.get(p.month) ?? new Set<string>();
      if (set.has(p.ticker)) continue;
      set.add(p.ticker);
      seenByMonth.set(p.month, set);
      m.set(p.month, (m.get(p.month) ?? 0) + px);
    }
    return m;
  }, [projectedPays]);

  const selectedPays = useMemo(() => {
    if (!selectedMonth) return [];
    return projectedPays.filter((p) => p.month === selectedMonth);
  }, [projectedPays, selectedMonth]);

  const selectedPaysSorted = useMemo(() => {
    const dir = detailSortDir === "asc" ? 1 : -1;
    const arr = [...selectedPays];
    arr.sort((a, b) => {
      if (detailSortBy === "amount") {
        if (a.amount !== b.amount) return (a.amount - b.amount) * dir;
        if (a.date !== b.date) return (a.date < b.date ? -1 : 1) * dir;
        return a.ticker.localeCompare(b.ticker);
      }
      // date
      if (a.date !== b.date) return (a.date < b.date ? -1 : 1) * dir;
      if (a.amount !== b.amount) return (a.amount - b.amount) * dir;
      return a.ticker.localeCompare(b.ticker);
    });
    return arr;
  }, [detailSortBy, detailSortDir, selectedPays]);

  const selectedTotal = useMemo(() => {
    if (!selectedMonth) return null;
    return selectedPays.reduce((acc, p) => acc + p.amount, 0);
  }, [selectedMonth, selectedPays]);

  useEffect(() => {
    if (!selectedMonth) return;
    // UX: llevar el foco visual al detalle (evita “no pasó nada”).
    detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [selectedMonth]);

  const loading = radar === undefined && error === null;
  const noExport = radar === null;
  const emptySheet = radar !== null && radar !== undefined && rows.length === 0;

  return (
    <>
      <h1 className="page-title">Eventos</h1>
      <p className="page-desc">
        Próximos eventos del universo USA (earnings y dividendos estimados) y un flujo mensual proyectado de dividendos.
      </p>
      <div className="card" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "1rem" }}>
        <div className="msg-muted" style={{ margin: 0 }}>
          {displayUpdatedAt
            ? `Eventos actualizados: ${fmtEsArDateTime.format(displayUpdatedAt)}`
            : "Eventos sin actualizar"}
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "0.25rem" }}>
          <button
            type="button"
            className="radar-refresh-btn"
            disabled={isTriggering || updateStatus?.status === "running"}
            onClick={() => {
              setUpdateMsg(null);
              setIsTriggering(true);
              triggerUsaEventsUpdate()
                .then((s) => {
                  setUpdateStatus(s);
                  if (s.status === "running") {
                    setUpdateMsg("Actualizando eventos… puede tardar varios minutos.");
                  } else if (s.status === "success") {
                    setUpdateMsg("Eventos actualizados correctamente.");
                    const lu = s.last_updated_at;
                    fetchLatestRadar()
                      .then((d) => setRadar(d))
                      .catch(() => null)
                      .finally(() => {
                        if (!lu) return;
                        setUpdateStatus((prev) => (prev ? { ...prev, last_updated_at: lu } : prev));
                      });
                  } else if (s.status === "error") {
                    setUpdateMsg("No se pudieron actualizar los eventos. Podés reintentar.");
                  }
                })
                .catch((e: unknown) => {
                  setUpdateMsg(e instanceof Error ? e.message : "No se pudo iniciar la actualización.");
                })
                .finally(() => setIsTriggering(false));
            }}
            title="Actualiza events_cache_usa.json en background"
          >
            {updateStatus?.status === "running" ? "Actualizando…" : "Actualizar eventos"}
          </button>
          <span className="msg-muted" style={{ fontSize: "0.82rem" }}>
            {updateStatus?.status === "running"
              ? "Actualizando eventos… puede tardar varios minutos."
              : updateStatus?.status === "error"
                ? "Último intento falló."
                : "Actualización manual de eventos USA."}
          </span>
        </div>
      </div>
      {updateStatus?.status === "running" ? (
        <div className="card" style={{ padding: "0.75rem 1rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
            <div
              style={{
                flex: 1,
                height: 8,
                background: "var(--border)",
                borderRadius: 4,
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${Math.min(100, Math.max(0, Math.round(Number(updateStatus.progress_pct) || 0)))}%`,
                  height: "100%",
                  background: "var(--accent)",
                  transition: "width 0.35s ease",
                }}
              />
            </div>
            <span className="msg-muted" style={{ fontSize: "0.85rem", minWidth: "2.75rem", textAlign: "right" }}>
              {Math.min(100, Math.max(0, Math.round(Number(updateStatus.progress_pct) || 0)))}%
            </span>
          </div>
          <p className="msg-muted" style={{ margin: "0.45rem 0 0", fontSize: "0.82rem" }}>
            {updateStatus.progress_message ?? "Actualizando eventos…"}
          </p>
        </div>
      ) : null}
      {updateMsg ? (
        <div className="card">
          <p className="msg-muted" style={{ margin: 0 }}>
            {updateMsg}
            {updateStatus?.status === "error" && updateStatus.error ? ` (${updateStatus.error})` : ""}
          </p>
        </div>
      ) : null}

      {loading ? (
        <div className="card">
          <p className="msg-muted" style={{ margin: 0 }}>
            Cargando…
          </p>
        </div>
      ) : null}
      {error !== null ? (
        <div className="card">
          <p className="msg-error" style={{ margin: 0 }}>
            {error}
          </p>
        </div>
      ) : null}
      {noExport ? (
        <div className="card">
          <p className="msg-muted" style={{ margin: 0 }}>
            No hay export disponible todavía. Ejecutá el scan desde Dashboard.
          </p>
        </div>
      ) : null}
      {emptySheet ? (
        <div className="card">
          <p className="msg-muted" style={{ margin: 0 }}>
            El último export no contiene filas en Radar_Completo.
          </p>
        </div>
      ) : null}

      <div className="card">
        <h2>Próximos eventos</h2>
        <div
          style={{
            display: "flex",
            gap: "0.75rem",
            overflowX: "auto",
            paddingBottom: "0.25rem",
          }}
        >
          {upcoming.length === 0 ? (
            <p className="msg-muted" style={{ margin: 0 }}>
              Sin eventos próximos (no hay fechas de earnings/dividendos estimados en el radar).
            </p>
          ) : (
            upcoming.map(({ row, next, e, d }) => {
              const nextType =
                e && d
                  ? Math.abs(e.getTime() - d.getTime()) <= 7 * 24 * 3600 * 1000
                    ? "Ambos"
                    : e.getTime() <= d.getTime()
                      ? "Earnings"
                      : "Dividendo"
                  : e
                    ? "Earnings"
                    : "Dividendo";
              const highlightE = row.earningsEn7d === true;
              const highlightD = row.diasHastaProximoDividendo !== null && row.diasHastaProximoDividendo <= 30 && row.diasHastaProximoDividendo >= 0;

              const badgeBg =
                nextType === "Earnings" ? "rgba(61,139,253,0.15)" : nextType === "Dividendo" ? "rgba(46,204,113,0.12)" : "rgba(255,193,7,0.12)";
              const badgeBorder =
                nextType === "Earnings" ? "rgba(61,139,253,0.45)" : nextType === "Dividendo" ? "rgba(46,204,113,0.35)" : "rgba(255,193,7,0.35)";

              return (
                <div
                  key={row.ticker}
                  style={{
                    minWidth: 320,
                    maxWidth: 360,
                    background: "var(--bg-panel)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius)",
                    padding: "0.9rem",
                    flex: "0 0 auto",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem" }}>
                    <div>
                      <div style={{ fontWeight: 600, lineHeight: 1.2 }}>{row.ticker}</div>
                      <div className="msg-muted" style={{ fontSize: "0.85rem" }}>
                        {(row.empresa ?? "Sin dato").trim() || "Sin dato"}
                      </div>
                    </div>
                    <span
                      style={{
                        alignSelf: "flex-start",
                        padding: "0.2rem 0.5rem",
                        borderRadius: 999,
                        background: badgeBg,
                        border: `1px solid ${badgeBorder}`,
                        fontSize: "0.75rem",
                        whiteSpace: "nowrap",
                      }}
                      title="Tipo de evento más próximo"
                    >
                      {nextType}
                    </span>
                  </div>

                  <div style={{ marginTop: "0.75rem", display: "grid", gap: "0.35rem" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem" }}>
                      <span className="msg-muted">Próximo earnings</span>
                      <span style={{ fontWeight: 500, color: highlightE ? "var(--accent)" : "var(--text)" }}>
                        {fmtDateIsoOrEmpty(row.fechaProximoEarnings)}
                      </span>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem" }}>
                      <span className="msg-muted">Próximo dividendo (est.)</span>
                      <span style={{ fontWeight: 500, color: highlightD ? "#7ee2a8" : "var(--text)" }}>
                        {fmtDateIsoOrEmpty(row.fechaProximoDividendoEstimado)}
                      </span>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem" }}>
                      <span className="msg-muted">SignalState</span>
                      <span style={{ fontWeight: 500 }}>{(row.signalState ?? "Sin dato").trim() || "Sin dato"}</span>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem" }}>
                      <span className="msg-muted">TotalScore</span>
                      <span style={{ fontWeight: 500 }}>
                        {row.totalScore === null ? "Sin dato" : row.totalScore.toFixed(2)}
                      </span>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem" }}>
                      <span className="msg-muted">PrioridadRadar</span>
                      <span style={{ fontWeight: 500 }}>
                        {row.prioridadRadar === null ? "Sin dato" : String(row.prioridadRadar)}
                      </span>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "0.75rem" }}>
                      <span className="msg-muted">Yield anual est.</span>
                      <span style={{ fontWeight: 500 }}>
                        {row.dividendYieldAnualEstimadoPct === null
                          ? "Sin dato"
                          : `${row.dividendYieldAnualEstimadoPct.toFixed(2)}%`}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>
        <p className="msg-muted" style={{ margin: "0.75rem 0 0", fontSize: "0.82rem" }}>
          Resaltado: earnings en 7 días y/o dividendo estimado en ≤30 días.
        </p>
      </div>

      <div className="card">
        <h2>Flujo mensual proyectado de dividendos (próximos 12 meses)</h2>
        <p className="msg-muted" style={{ marginTop: 0 }}>
          Flujo estimado sobre base de 1 acción por empresa. No representa cartera real.
        </p>
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", marginBottom: "0.75rem" }}>
          <button
            type="button"
            className="radar-refresh-btn"
            style={{
              padding: "0.25rem 0.55rem",
              fontSize: "0.8rem",
              opacity: flowOnlyCedear ? 1 : 0.7,
              borderColor: flowOnlyCedear ? "var(--accent)" : undefined,
            }}
            onClick={() => setFlowOnlyCedear((v) => !v)}
            title="Alternar filtro CEDEAR"
          >
            CEDEAR
          </button>
        </div>
        <div className="table-wrap">
          <table className="radar-table" style={{ minWidth: 520 }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left" }}>Mes</th>
                <th style={{ textAlign: "center" }}>Flujo proyectado USD</th>
                <th style={{ textAlign: "center" }}>Pagos</th>
                <th style={{ textAlign: "center" }}>Capital necesario</th>
                <th style={{ textAlign: "center" }}>Yield</th>
              </tr>
            </thead>
            <tbody>
              {dividendMonthly.map((m) => (
                <tr
                  key={m.month}
                  onClick={() => setSelectedMonth(m.month)}
                  style={{
                    cursor: "pointer",
                    background: selectedMonth === m.month ? "var(--bg-hover)" : undefined,
                  }}
                  title="Ver detalle por empresa"
                >
                  <td style={{ fontWeight: selectedMonth === m.month ? 600 : undefined }}>{m.month}</td>
                  <td style={{ textAlign: "center" }}>{fmtUsd2.format(m.amount)}</td>
                  <td style={{ textAlign: "center" }}>{m.count}</td>
                  <td style={{ textAlign: "center" }}>
                    {(() => {
                      const cap = capitalNeededByMonth.get(m.month);
                      return cap === undefined ? "Sin dato" : `USD ${fmtUsd2.format(cap)}`;
                    })()}
                  </td>
                  <td style={{ textAlign: "center" }}>
                    {(() => {
                      const cap = capitalNeededByMonth.get(m.month);
                      if (cap === undefined || cap <= 0) return "Sin dato";
                      const y = (m.amount / cap) * 100.0;
                      return Number.isFinite(y) ? `${fmtPct2.format(y)}%` : "Sin dato";
                    })()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div ref={detailRef} style={{ marginTop: "1rem" }}>
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: "0.75rem" }}>
            <h3 style={{ margin: "0 0 0.5rem", fontSize: "0.95rem" }}>
              Detalle por empresa{selectedMonth ? ` — ${selectedMonth}` : ""}
            </h3>
            {selectedMonth ? (
              <button
                type="button"
                className="radar-refresh-btn"
                style={{ padding: "0.25rem 0.55rem", fontSize: "0.8rem" }}
                onClick={() => setSelectedMonth(null)}
                title="Limpiar selección"
              >
                Limpiar
              </button>
            ) : null}
          </div>
          {selectedMonth ? (
            <>
              <p className="msg-muted" style={{ marginTop: 0 }}>
                Total del mes:{" "}
                <strong>{selectedTotal === null ? "—" : `USD ${fmtUsd2.format(selectedTotal)}`}</strong>
              </p>
              {selectedPays.length === 0 ? (
                <p className="msg-muted" style={{ margin: 0 }}>
                  Sin pagos estimados.
                </p>
              ) : (
                <div className="table-wrap">
                  <table className="radar-table" style={{ minWidth: 620 }}>
                    <thead>
                      <tr>
                        <th style={{ textAlign: "left" }}>Ticker</th>
                        <th style={{ textAlign: "left" }}>Empresa</th>
                        <th
                          style={{ textAlign: "left", cursor: "pointer", userSelect: "none" }}
                          onClick={() => {
                            setDetailSortBy("date");
                            setDetailSortDir((d) =>
                              detailSortBy === "date" ? (d === "asc" ? "desc" : "asc") : "asc",
                            );
                          }}
                          title="Ordenar por fecha"
                        >
                          Fecha pago estimada{" "}
                          {detailSortBy === "date" ? (detailSortDir === "asc" ? "↑" : "↓") : ""}
                        </th>
                        <th
                          style={{ textAlign: "right", cursor: "pointer", userSelect: "none" }}
                          onClick={() => {
                            setDetailSortBy("amount");
                            setDetailSortDir((d) =>
                              detailSortBy === "amount" ? (d === "asc" ? "desc" : "asc") : "desc",
                            );
                          }}
                          title="Ordenar por monto"
                        >
                          Dividendo por acción (USD){" "}
                          {detailSortBy === "amount" ? (detailSortDir === "asc" ? "↑" : "↓") : ""}
                        </th>
                        <th style={{ textAlign: "right" }}>Valor acción</th>
                        <th style={{ textAlign: "right" }}>Yield</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedPaysSorted.map((p) => (
                        <tr key={`${p.month}-${p.ticker}-${p.date}`}>
                          <td>{p.ticker}</td>
                          <td className="msg-muted">{(p.empresa ?? "Sin dato").trim() || "Sin dato"}</td>
                          <td>{p.date}</td>
                          <td style={{ textAlign: "right" }}>{fmtUsd2.format(p.amount)}</td>
                          <td style={{ textAlign: "right" }}>
                            {p.precio === null ? "Sin dato" : `USD ${fmtUsd2.format(p.precio)}`}
                          </td>
                          <td style={{ textAlign: "right" }}>
                            {p.precio !== null && p.precio > 0
                              ? `${fmtPct2.format((p.amount / p.precio) * 100.0)}%`
                              : "Sin dato"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          ) : (
            <p className="msg-muted" style={{ margin: 0 }}>
              Hacé click en un mes para ver el detalle por empresa.
            </p>
          )}
        </div>

        <p className="msg-muted" style={{ marginBottom: 0, marginTop: "0.75rem", fontSize: "0.82rem" }}>
          Nota: por ahora se muestra solo el flujo proyectado; la estructura queda lista para sumar histórico real desde
          la cache de eventos en una fase posterior.
        </p>
      </div>

      <div className="card">
        <h2>Ranking de dividendos</h2>

        <div className="radar-toolbar" style={{ marginBottom: "0.75rem" }}>
          <div className="radar-toolbar__field">
            <label className="radar-toolbar__label">Universo</label>
            <select
              className="radar-toolbar__select"
              value={divRankCedear}
              onChange={(e) => setDivRankCedear(e.target.value === "cedear" ? "cedear" : "all")}
            >
              <option value="all">Todos</option>
              <option value="cedear">Solo CEDEAR</option>
            </select>
          </div>

          <div className="radar-toolbar__field">
            <label className="radar-toolbar__label">Próximo pago</label>
            <button
              type="button"
              className="radar-refresh-btn"
              style={{ padding: "0.35rem 0.6rem", opacity: divRankNextPay ? 1 : 0.7 }}
              onClick={() => setDivRankNextPay((v) => !v)}
              title="Filtrar solo empresas con próximo pago estimado"
            >
              Con próximo pago estimado
            </button>
          </div>

          <div className="radar-toolbar__field">
            <label className="radar-toolbar__label">Frecuencia</label>
            <select
              className="radar-toolbar__select"
              value={divRankFreq}
              onChange={(e) => setDivRankFreq(e.target.value as typeof divRankFreq)}
            >
              <option value="all">Todas</option>
              <option value="monthly">mensual</option>
              <option value="quarterly">trimestral</option>
              <option value="semiannual">semestral</option>
              <option value="annual">anual</option>
              <option value="irregular">irregular</option>
            </select>
          </div>

          <div className="radar-toolbar__field">
            <label className="radar-toolbar__label">Orden</label>
            <select
              className="radar-toolbar__select"
              value={divRankSort}
              onChange={(e) => setDivRankSort(e.target.value as typeof divRankSort)}
            >
              <option value="yield_anual">Mejor yield anual estimado</option>
              <option value="flujo_12m">Mayor flujo 12m por acción</option>
              <option value="pagos_12m">Más pagos estimados</option>
              <option value="proximo_pago">Próximo pago más cercano</option>
              <option value="score">Mejor score radar</option>
            </select>
          </div>
        </div>

        <div className="table-wrap">
          <table className="radar-table" style={{ minWidth: 980 }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left" }}>Ticker</th>
                <th style={{ textAlign: "left" }}>Empresa</th>
                <th style={{ textAlign: "center" }}>CEDEAR</th>
                <th style={{ textAlign: "center" }}>Frecuencia</th>
                <th style={{ textAlign: "center" }}>Próximo pago</th>
                <th style={{ textAlign: "center" }}>Días</th>
                <th style={{ textAlign: "right" }}>Último dividendo</th>
                <th style={{ textAlign: "right" }}>Yield anual %</th>
                <th style={{ textAlign: "right" }}>Flujo 12m por acción</th>
                <th style={{ textAlign: "center" }}>Pagos 12m</th>
                <th style={{ textAlign: "center" }}>SignalState</th>
                <th style={{ textAlign: "right" }}>TotalScore</th>
              </tr>
            </thead>
            <tbody>
              {dividendRankRows.length === 0 ? (
                <tr>
                  <td colSpan={12} className="msg-muted">
                    Sin filas para los filtros seleccionados.
                  </td>
                </tr>
              ) : (
                dividendRankRows.map((r) => (
                  <tr key={r.ticker}>
                    <td>{r.ticker}</td>
                    <td className="msg-muted">{(r.empresa ?? "Sin dato").trim() || "Sin dato"}</td>
                    <td style={{ textAlign: "center" }}>
                      {r.tieneCedear === null ? "—" : r.tieneCedear ? "SI" : "NO"}
                    </td>
                    <td style={{ textAlign: "center" }}>{(r.frecuenciaDividendos ?? "Sin dato").trim() || "Sin dato"}</td>
                    <td style={{ textAlign: "center" }}>{fmtDateIsoOrEmpty(r.fechaProximoDividendoEstimado)}</td>
                    <td style={{ textAlign: "center" }}>
                      {r.diasHastaProximoDividendo === null ? "Sin dato" : String(r.diasHastaProximoDividendo)}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {r.ultimoDividendo === null ? "Sin dato" : `USD ${fmtUsd2.format(r.ultimoDividendo)}`}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {r.dividendYieldAnualEstimadoPct === null
                        ? "Sin dato"
                        : `${fmtPct2.format(r.dividendYieldAnualEstimadoPct)}%`}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {r.flujoDividendos12mPorAccion === null ? "Sin dato" : `USD ${fmtUsd2.format(r.flujoDividendos12mPorAccion)}`}
                    </td>
                    <td style={{ textAlign: "center" }}>
                      {r.dividendosEstimados12m === null ? "Sin dato" : String(r.dividendosEstimados12m)}
                    </td>
                    <td style={{ textAlign: "center" }}>{(r.signalState ?? "Sin dato").trim() || "Sin dato"}</td>
                    <td style={{ textAlign: "right" }}>
                      {r.totalScore === null ? "Sin dato" : r.totalScore.toFixed(2)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <p className="msg-muted" style={{ marginBottom: 0, marginTop: "0.75rem", fontSize: "0.82rem" }}>
          Se muestra top 30 para mantener la página liviana.
        </p>
      </div>
    </>
  );
}

