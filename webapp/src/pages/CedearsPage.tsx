import { useCallback, useEffect, useMemo, useState } from "react";

import { TickerRadarLink } from "@/components/navigation/radarLinks";
import { fetchCedears, type CedearRatioEstado, type CedearRow } from "@/services/api";

const EMPTY = "-";

type SortMode = "gap_desc" | "gap_asc" | "score_desc" | "score_asc";

/** Miles y decimales estilo ARS (sin símbolo de moneda; se antepone `$ `). */
const fmtEsArsLike = new Intl.NumberFormat("es-AR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** USD / valores en dólares: miles locales, 2 decimales, sin prefijo $. */
const fmtEsUsd2 = new Intl.NumberFormat("es-AR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** Precio CEDEAR en línea USD: hasta 4 decimales si hace falta. */
const fmtEsUsd2to4 = new Intl.NumberFormat("es-AR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

function fmtArsConSigno(v: number | null): string {
  if (v === null || Number.isNaN(v)) return EMPTY;
  return `$ ${fmtEsArsLike.format(v)}`;
}

/** Valores en USD: prefijo literal, miles/decimales es-AR, sin $. */
function fmtUsdPrefijo2(v: number | null): string {
  if (v === null || Number.isNaN(v)) return EMPTY;
  return `USD ${fmtEsUsd2.format(v)}`;
}

function fmtUsdPrefijo2to4(v: number | null): string {
  if (v === null || Number.isNaN(v)) return EMPTY;
  return `USD ${fmtEsUsd2to4.format(v)}`;
}

function fmtFixed(v: number | null, digits: number): string {
  if (v === null || Number.isNaN(v)) return EMPTY;
  return v.toFixed(digits);
}

function fmtPct(v: number | null): string {
  if (v === null || Number.isNaN(v)) return EMPTY;
  return `${v.toFixed(2)}%`;
}

function fmtFuente(text: string | null | undefined): { display: string; full: string | undefined } {
  const t = text?.trim() ?? "";
  if (!t) {
    return { display: EMPTY, full: undefined };
  }
  if (t.length > 44) {
    return { display: `${t.slice(0, 42)}…`, full: t };
  }
  return { display: t, full: t };
}

const GAP_TOOLTIP =
  "Gap % = (Acción implícita USD / Acción USA - 1) * 100\n" +
  ">0.5% verde · <-0.5% rojo · ±0.5% gris";

/** Umbrales en puntos porcentuales (mismo rango que gap_pct del backend). */
function gapPctCellClass(gap: number | null): string {
  if (gap === null || Number.isNaN(gap)) {
    return "table-cell--empty";
  }
  if (gap > 0.5) {
    return "radar-cell--score-high";
  }
  if (gap < -0.5) {
    return "cedear-cell--gap-neg";
  }
  return "radar-cell--score-very-low";
}

function estadoRatioBadge(estado: CedearRatioEstado, dias: number | null): { cls: string; label: string; title: string } {
  if (estado === "ok") {
    return {
      cls: "radar-badge radar-badge--conv-alta",
      label: "OK",
      title: dias !== null ? `Validado hace ${dias} días (ventana ≤180)` : "Ratio al día según fecha del maestro",
    };
  }
  if (estado === "pendiente_validar") {
    return {
      cls: "radar-badge radar-badge--conv-media",
      label: "Pendiente",
      title: "Sin fecha de validación en el maestro o fecha no interpretable",
    };
  }
  return {
    cls: "radar-badge radar-badge--conv-baja",
    label: "Revisar",
    title:
      dias !== null
        ? `Última validación hace ${dias} días (>180); conviene actualizar fuente y fecha`
        : "Fecha futura o antigüedad fuera de regla; revisar el maestro",
  };
}

function compareNullableNum(a: number | null, b: number | null, dir: 1 | -1): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  if (a === b) return 0;
  return a < b ? -dir : dir;
}

function sortRows(rows: CedearRow[], mode: SortMode): CedearRow[] {
  const copy = [...rows];
  const dir: 1 | -1 = mode === "gap_desc" || mode === "score_desc" ? -1 : 1;
  copy.sort((ra, rb) => {
    if (mode === "gap_desc" || mode === "gap_asc") {
      const c = compareNullableNum(ra.gap_pct, rb.gap_pct, dir);
      if (c !== 0) return c;
    } else {
      const c = compareNullableNum(ra.TotalScore, rb.TotalScore, dir);
      if (c !== 0) return c;
    }
    return ra.ticker_usa.localeCompare(rb.ticker_usa, "en", { sensitivity: "base" });
  });
  return copy;
}

export function CedearsPage() {
  const [rows, setRows] = useState<CedearRow[] | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [minScore, setMinScore] = useState("");
  const [sortMode, setSortMode] = useState<SortMode>("gap_desc");
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const applyCedearsResult = useCallback((r: Awaited<ReturnType<typeof fetchCedears>>) => {
    if (r.kind === "no_export") {
      setRows(null);
      return;
    }
    setRows(r.rows);
  }, []);

  const load = useCallback(() => {
    setError(null);
    setRows(undefined);
    fetchCedears()
      .then(applyCedearsResult)
      .catch((e: unknown) => {
        setRows(undefined);
        setError(e instanceof Error ? e.message : "Error al cargar CEDEARs");
      });
  }, [applyCedearsResult]);

  useEffect(() => {
    load();
  }, [load]);

  const onRefresh = useCallback(() => {
    setRefreshError(null);
    setRefreshing(true);
    fetchCedears()
      .then((r) => {
        applyCedearsResult(r);
        setError(null);
      })
      .catch((e: unknown) => {
        setRefreshError(e instanceof Error ? e.message : "Error al actualizar");
      })
      .finally(() => {
        setRefreshing(false);
      });
  }, [applyCedearsResult]);

  const noExport = rows === null && !error;
  const emptySheet = rows !== undefined && rows !== null && rows.length === 0 && !error;

  const filtered = useMemo(() => {
    const list = rows ?? [];
    let out = list;
    const q = search.trim().toLowerCase();
    if (q) {
      out = out.filter((r) => {
        const hay = [
          r.ticker_usa,
          r.ticker_cedear_ars,
          r.ticker_cedear_usd,
          r.fuente_ratio ?? "",
        ]
          .join(" ")
          .toLowerCase();
        return hay.includes(q);
      });
    }
    const minRaw = minScore.trim();
    if (minRaw !== "" && Number.isFinite(Number(minRaw))) {
      const m = Number(minRaw);
      out = out.filter((r) => r.TotalScore !== null && r.TotalScore >= m);
    }
    return out;
  }, [rows, search, minScore]);

  const displayRows = useMemo(() => sortRows(filtered, sortMode), [filtered, sortMode]);

  const loading = rows === undefined && error === null;

  return (
    <>
      <h1 className="page-title">CEDEARs</h1>
      <p className="msg-muted" style={{ marginTop: 0, marginBottom: "1rem", maxWidth: "48rem" }}>
        Equivalencias locales sobre el último radar USA: CCL implícito (precio en pesos / precio en
        dólares del CEDEAR), precio implícito en USD y gap frente al precio USA del export. Scores y
        señal provienen del radar sin recalcular. Si el subyacente no está en ese export, el precio USA
        es spot (Yahoo) y la columna <span className="table-cell--nowrap">modulo usa</span> marca NO. Cotizaciones
        locales CEDEAR (ARS y cable): Yahoo.
      </p>

      {rows !== undefined && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.75rem",
            flexWrap: "wrap",
            marginBottom: "1rem",
          }}
        >
          <button type="button" className="radar-refresh-btn" onClick={onRefresh} disabled={refreshing}>
            {refreshing ? "Cargando…" : "Actualizar"}
          </button>
          {refreshError ? (
            <span className="msg-error" style={{ fontSize: "0.875rem" }}>
              {refreshError}
            </span>
          ) : null}
        </div>
      )}

      {loading && <p className="msg-muted">Cargando…</p>}
      {error && <p className="msg-error">{error}</p>}

      {noExport && (
        <p className="msg-muted">
          No hay archivo de radar exportado en el servidor. Ejecutá un scan desde el Dashboard para
          generar datos y exportar resultados.
        </p>
      )}

      {emptySheet && (
        <p className="msg-muted">
          El último export no devolvió filas CEDEAR (ningún ticker del mapeo coincidió con el radar USA o
          no hay mapeos configurados).
        </p>
      )}

      {!loading && !error && rows !== null && rows !== undefined && rows.length > 0 && (
        <div className="card" style={{ marginBottom: "1rem" }}>
          <div className="radar-toolbar" aria-label="Filtros CEDEAR">
            <label className="radar-toolbar__field">
              <span className="radar-toolbar__label">Buscar ticker</span>
              <input
                type="search"
                className="radar-toolbar__input"
                placeholder="Ticker o fuente…"
                value={search}
                onChange={(ev) => setSearch(ev.target.value)}
                autoComplete="off"
              />
            </label>
            <label className="radar-toolbar__field">
              <span className="radar-toolbar__label">TotalScore mín.</span>
              <input
                type="number"
                className="radar-toolbar__input radar-toolbar__input--narrow"
                placeholder="Ej. 5"
                value={minScore}
                onChange={(ev) => setMinScore(ev.target.value)}
                step="any"
              />
            </label>
            <label className="radar-toolbar__field">
              <span className="radar-toolbar__label">Orden</span>
              <select
                className="radar-toolbar__select"
                value={sortMode}
                onChange={(ev) => setSortMode(ev.target.value as SortMode)}
              >
                <option value="gap_desc">Gap % (mayor primero)</option>
                <option value="gap_asc">Gap % (menor primero)</option>
                <option value="score_desc">TotalScore (mayor primero)</option>
                <option value="score_asc">TotalScore (menor primero)</option>
              </select>
            </label>
            <p className="radar-toolbar__hint msg-muted">
              {displayRows.length} de {rows.length} filas
            </p>
          </div>

          <div className="radar-table-wrap">
            <table className="radar-table">
              <thead>
                <tr>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head">
                    <span className="radar-table__sort-label radar-table__sort-label--static">USA</span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <span className="radar-table__sort-label radar-table__sort-label--static" title="Precio del CEDEAR en pesos">
                      CEDEAR $
                    </span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <span className="radar-table__sort-label radar-table__sort-label--static" title="Precio del CEDEAR en USD (cable)">
                      CEDEAR USD
                    </span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <span className="radar-table__sort-label radar-table__sort-label--static" title="Tipo de cambio implícito (ARS / USD del par CEDEAR)">
                      CCL implícito
                    </span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <span className="radar-table__sort-label radar-table__sort-label--static" title="Precio de la acción USA en el radar">
                      Acción USA
                    </span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <span
                      className="radar-table__sort-label radar-table__sort-label--static"
                      title="Precio implícito de 1 acción USA vía CEDEAR (USD)"
                    >
                      Acción implícita USD
                    </span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <span className="radar-table__sort-label radar-table__sort-label--static" title={GAP_TOOLTIP}>
                      Gap %
                    </span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <span className="radar-table__sort-label radar-table__sort-label--static">TotalScore</span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head">
                    <span className="radar-table__sort-label radar-table__sort-label--static">SignalState</span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "center" }}>
                    <span
                      className="radar-table__sort-label radar-table__sort-label--static"
                      title="SI: precio (y score/señal) desde el radar USA. NO: precio spot Yahoo; sin score/señal del radar."
                    >
                      modulo usa
                    </span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <span className="radar-table__sort-label radar-table__sort-label--static">Ratio</span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head">
                    <span className="radar-table__sort-label radar-table__sort-label--static">Fuente ratio</span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head">
                    <span className="radar-table__sort-label radar-table__sort-label--static">Validado</span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head">
                    <span className="radar-table__sort-label radar-table__sort-label--static">Estado ratio</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {displayRows.map((r) => {
                  const fuente = fmtFuente(r.fuente_ratio);
                  const est = estadoRatioBadge(r.estado_ratio, r.dias_desde_validacion);
                  return (
                  <tr key={r.ticker_usa}>
                    <td className="radar-table__sticky-col table-cell--nowrap">
                      <TickerRadarLink ticker={r.ticker_usa} mercado="USA" />
                    </td>
                    <td style={{ textAlign: "right" }} className={r.precio_cedear_ars === null ? "table-cell--empty" : ""}>
                      {fmtArsConSigno(r.precio_cedear_ars)}
                    </td>
                    <td style={{ textAlign: "right" }} className={r.precio_cedear_usd === null ? "table-cell--empty" : ""}>
                      {fmtUsdPrefijo2to4(r.precio_cedear_usd)}
                    </td>
                    <td style={{ textAlign: "right" }} className={r.ccl_implicito === null ? "table-cell--empty" : ""}>
                      {fmtArsConSigno(r.ccl_implicito)}
                    </td>
                    <td style={{ textAlign: "right" }} className={r.precio_usa_real === null ? "table-cell--empty" : ""}>
                      {fmtUsdPrefijo2(r.precio_usa_real)}
                    </td>
                    <td style={{ textAlign: "right" }} className={r.precio_implicito_usd === null ? "table-cell--empty" : ""}>
                      {fmtUsdPrefijo2(r.precio_implicito_usd)}
                    </td>
                    <td style={{ textAlign: "right" }} className={`table-cell--nowrap ${gapPctCellClass(r.gap_pct)}`}>
                      {fmtPct(r.gap_pct)}
                    </td>
                    <td style={{ textAlign: "right" }} className={r.TotalScore === null ? "table-cell--empty" : ""}>
                      {fmtFixed(r.TotalScore, 1)}
                    </td>
                    <td className="table-cell--nowrap">
                      {r.SignalState?.trim() ? r.SignalState : EMPTY}
                    </td>
                    <td style={{ textAlign: "center" }} className="table-cell--nowrap" title={r.mod_usa === "SI" ? "Radar USA" : "Precio spot (no en radar)"}>
                      {r.mod_usa}
                    </td>
                    <td style={{ textAlign: "right" }} className="table-cell--nowrap">
                      {fmtFixed(r.ratio, 2)}
                    </td>
                    <td
                      className="table-cell--nowrap cedear-table__fuente"
                      title={fuente.full}
                      style={{ maxWidth: "14rem" }}
                    >
                      {fuente.display}
                    </td>
                    <td className="table-cell--nowrap">
                      {r.fecha_validacion_ratio?.trim() ? r.fecha_validacion_ratio.trim() : EMPTY}
                    </td>
                    <td className="table-cell--nowrap">
                      <span className={est.cls} title={est.title}>
                        {est.label}
                      </span>
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
