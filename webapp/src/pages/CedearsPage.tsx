import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { PortfolioRowTradeButtons } from "@/components/cartera/PortfolioRowTradeButtons";
import { TickerRadarLink } from "@/components/navigation/radarLinks";
import { fetchCedears, peekCedearsCache, type CedearRatioEstado, type CedearRow } from "@/services/api";

const EMPTY = "-";

type SortDir = "asc" | "desc";

type CclFilter = "todos" | "con_ccl" | "sin_ccl";

type SortKey =
  | "ticker_usa"
  | "gap_pct"
  | "precio_cedear_ars"
  | "precio_cedear_usd"
  | "ccl_implicito"
  | "precio_usa_real"
  | "precio_implicito_usd"
  | "ratio";

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
  "<-1% verde · >1% rojo · ±1% gris";

/** Umbrales en puntos porcentuales (mismo rango que gap_pct del backend). */
function gapPctCellClass(gap: number | null): string {
  if (gap === null || Number.isNaN(gap)) {
    return "table-cell--empty";
  }
  // CEDEAR: gap < 0 => subvaluado vs USA (verde). gap > 0 => sobrevaluado (rojo).
  // Banda neutra para evitar ruido visual en gaps chicos.
  if (gap < -1) {
    return "radar-cell--score-high";
  }
  if (gap > 1) {
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

function compareNullableStr(a: string | null | undefined, b: string | null | undefined, dir: 1 | -1): number {
  const sa = (a ?? "").trim();
  const sb = (b ?? "").trim();
  const aEmpty = sa === "";
  const bEmpty = sb === "";
  if (aEmpty && bEmpty) return 0;
  if (aEmpty) return 1;
  if (bEmpty) return -1;
  const c = sa.localeCompare(sb, "en", { sensitivity: "base" });
  return c === 0 ? 0 : c * dir;
}

function sortRows(rows: CedearRow[], key: SortKey, dir: SortDir): CedearRow[] {
  const copy = [...rows];
  const sdir: 1 | -1 = dir === "asc" ? 1 : -1;
  copy.sort((ra, rb) => {
    let c = 0;
    switch (key) {
      case "ticker_usa":
        c = compareNullableStr(ra.ticker_usa, rb.ticker_usa, sdir);
        break;
      case "gap_pct":
        c = compareNullableNum(ra.gap_pct, rb.gap_pct, sdir);
        break;
      case "precio_cedear_ars":
        c = compareNullableNum(ra.precio_cedear_ars, rb.precio_cedear_ars, sdir);
        break;
      case "precio_cedear_usd":
        c = compareNullableNum(ra.precio_cedear_usd, rb.precio_cedear_usd, sdir);
        break;
      case "ccl_implicito":
        c = compareNullableNum(ra.ccl_implicito, rb.ccl_implicito, sdir);
        break;
      case "precio_usa_real":
        c = compareNullableNum(ra.precio_usa_real, rb.precio_usa_real, sdir);
        break;
      case "precio_implicito_usd":
        c = compareNullableNum(ra.precio_implicito_usd, rb.precio_implicito_usd, sdir);
        break;
      case "ratio":
        c = compareNullableNum(ra.ratio, rb.ratio, sdir);
        break;
      default:
        c = 0;
    }
    if (c !== 0) return c;
    // Tie-breaker estable: ticker asc
    return ra.ticker_usa.localeCompare(rb.ticker_usa, "en", { sensitivity: "base" });
  });
  return copy;
}

export function CedearsPage() {
  const [rows, setRows] = useState<CedearRow[] | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [cclFilter, setCclFilter] = useState<CclFilter>("todos");
  const [sortKey, setSortKey] = useState<SortKey>("gap_pct");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [searchParams] = useSearchParams();
  const tickerFilter = searchParams.get("ticker_usa")?.trim().toUpperCase() || "";

  const applyCedearsResult = useCallback((r: Awaited<ReturnType<typeof fetchCedears>>) => {
    if (r.kind === "no_export") {
      setRows(null);
      return;
    }
    setRows(r.rows);
  }, []);

  const load = useCallback(() => {
    setError(null);
    const cached = peekCedearsCache();
    if (cached !== null) {
      applyCedearsResult(cached);
      return;
    }
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
    fetchCedears({ force: true })
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
    if (tickerFilter) {
      out = out.filter((r) => String(r.ticker_usa ?? "").trim().toUpperCase() === tickerFilter);
    }
    if (cclFilter === "con_ccl") {
      out = out.filter((r) => r.precio_cedear_usd !== null);
    } else if (cclFilter === "sin_ccl") {
      out = out.filter((r) => r.precio_cedear_usd === null);
    }
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
    return out;
  }, [rows, search, tickerFilter, cclFilter]);

  const displayRows = useMemo(() => sortRows(filtered, sortKey, sortDir), [filtered, sortKey, sortDir]);

  const loading = rows === undefined && error === null;
  const filtersActive = search.trim() !== "" || cclFilter !== "todos";

  const headerBtnStyle: React.CSSProperties = {
    background: "none",
    border: "none",
    padding: 0,
    margin: 0,
    cursor: "pointer",
    color: "inherit",
    font: "inherit",
    textAlign: "inherit",
  };

  const toggleSort = useCallback((key: SortKey, defaultDir: SortDir) => {
    setSortKey((prevKey) => {
      if (prevKey !== key) {
        setSortDir(defaultDir);
        return key;
      }
      setSortDir((prevDir) => (prevDir === "asc" ? "desc" : "asc"));
      return prevKey;
    });
  }, []);

  const sortIndicator = useCallback(
    (key: SortKey) => (sortKey === key ? (sortDir === "asc" ? " ▲" : " ▼") : ""),
    [sortDir, sortKey],
  );

  return (
    <>
      <h1 className="page-title">CEDEARs</h1>
      {tickerFilter ? (
        <div className="msg-muted" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
          Mostrando CEDEAR de <strong>{tickerFilter}</strong>
        </div>
      ) : null}
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
              <span className="radar-toolbar__label">CCL</span>
              <select
                className="radar-toolbar__select"
                value={cclFilter}
                onChange={(ev) => setCclFilter(ev.target.value as CclFilter)}
                aria-label="Filtrar por precio CCL disponible"
              >
                <option value="todos">Todos</option>
                <option value="con_ccl">Con CCL</option>
                <option value="sin_ccl">Sin CCL</option>
              </select>
            </label>
            <p className="radar-toolbar__hint msg-muted">
              CEDEAR totales: {rows.length}
              {filtersActive ? (
                <>
                  <br />
                  Mostrando {displayRows.length} de {rows.length}
                </>
              ) : null}
            </p>
          </div>

          <div className="radar-table-wrap">
            <table className="radar-table">
              <thead>
                <tr>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head">
                    <button
                      type="button"
                      style={headerBtnStyle}
                      className="radar-table__sort-label radar-table__sort-label--static"
                      onClick={() => toggleSort("ticker_usa", "asc")}
                      title="Ordenar por ticker"
                    >
                      USA{sortIndicator("ticker_usa")}
                    </button>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <button
                      type="button"
                      style={{ ...headerBtnStyle, width: "100%" }}
                      className="radar-table__sort-label radar-table__sort-label--static"
                      onClick={() => toggleSort("precio_cedear_ars", "desc")}
                      title="Ordenar por precio CEDEAR $"
                    >
                      CEDEAR ${sortIndicator("precio_cedear_ars")}
                    </button>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <button
                      type="button"
                      style={{ ...headerBtnStyle, width: "100%" }}
                      className="radar-table__sort-label radar-table__sort-label--static"
                      onClick={() => toggleSort("precio_cedear_usd", "desc")}
                      title="Ordenar por precio CEDEAR USD (cable)"
                    >
                      CEDEAR USD{sortIndicator("precio_cedear_usd")}
                    </button>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <button
                      type="button"
                      style={{ ...headerBtnStyle, width: "100%" }}
                      className="radar-table__sort-label radar-table__sort-label--static"
                      onClick={() => toggleSort("ccl_implicito", "desc")}
                      title="Ordenar por CCL implícito (ARS/USD)"
                    >
                      CCL implícito{sortIndicator("ccl_implicito")}
                    </button>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <button
                      type="button"
                      style={{ ...headerBtnStyle, width: "100%" }}
                      className="radar-table__sort-label radar-table__sort-label--static"
                      onClick={() => toggleSort("precio_usa_real", "desc")}
                      title="Ordenar por precio Acción USA"
                    >
                      Acción USA{sortIndicator("precio_usa_real")}
                    </button>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <button
                      type="button"
                      style={{ ...headerBtnStyle, width: "100%" }}
                      className="radar-table__sort-label radar-table__sort-label--static"
                      onClick={() => toggleSort("precio_implicito_usd", "desc")}
                      title="Ordenar por Acción implícita USD"
                    >
                      Acción implícita USD{sortIndicator("precio_implicito_usd")}
                    </button>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <button
                      type="button"
                      style={{ ...headerBtnStyle, width: "100%" }}
                      className="radar-table__sort-label radar-table__sort-label--static"
                      onClick={() => toggleSort("gap_pct", "desc")}
                      title={GAP_TOOLTIP}
                    >
                      Gap %{sortIndicator("gap_pct")}
                    </button>
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
                    <button
                      type="button"
                      style={{ ...headerBtnStyle, width: "100%" }}
                      className="radar-table__sort-label radar-table__sort-label--static"
                      onClick={() => toggleSort("ratio", "desc")}
                      title="Ordenar por Ratio"
                    >
                      Ratio{sortIndicator("ratio")}
                    </button>
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
                  <th
                    scope="col"
                    className="radar-table__th radar-table__th--sticky-head"
                    style={{ width: 112, minWidth: 112 }}
                  >
                    <span className="radar-table__sort-label radar-table__sort-label--static">Cartera</span>
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
                    <td style={{ textAlign: "right" }} className="table-cell--nowrap">
                      {r.precio_cedear_usd === null ? (
                        <span style={{ color: "var(--text-muted)" }}>Sin datos CCL</span>
                      ) : (
                        fmtUsdPrefijo2to4(r.precio_cedear_usd)
                      )}
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
                    <td className="table-cell--nowrap radar-table__actions-cell" style={{ verticalAlign: "middle" }}>
                      <PortfolioRowTradeButtons
                        assetType="CEDEAR"
                        ticker={r.ticker_usa?.trim() ?? ""}
                        suggestedBuyPriceUsd={r.precio_usa_real}
                        suggestedSellCedearUsd={r.precio_usa_real}
                      />
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
