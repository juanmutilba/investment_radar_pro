import { useCallback, useEffect, useMemo, useState } from "react";

import { TickerRadarLink } from "@/components/navigation/radarLinks";
import { fetchCedears, type CedearRow } from "@/services/api";

const EMPTY = "-";

type SortMode = "gap_desc" | "gap_asc" | "score_desc" | "score_asc";

function fmtFixed(v: number | null, digits: number): string {
  if (v === null || Number.isNaN(v)) return EMPTY;
  return v.toFixed(digits);
}

function fmtPct(v: number | null): string {
  if (v === null || Number.isNaN(v)) return EMPTY;
  return `${v.toFixed(2)}%`;
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

  const load = useCallback(() => {
    setError(null);
    setRows(undefined);
    fetchCedears()
      .then((data) => {
        setRows(data === null ? null : data);
      })
      .catch((e: unknown) => {
        setRows(undefined);
        setError(e instanceof Error ? e.message : "Error al cargar CEDEARs");
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const onRefresh = useCallback(() => {
    setRefreshError(null);
    setRefreshing(true);
    fetchCedears()
      .then((data) => {
        setRows(data === null ? null : data);
        setError(null);
      })
      .catch((e: unknown) => {
        setRefreshError(e instanceof Error ? e.message : "Error al actualizar");
      })
      .finally(() => {
        setRefreshing(false);
      });
  }, []);

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
        señal provienen del radar sin recalcular.
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
                placeholder="USA, ARS o USD…"
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
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head">
                    <span className="radar-table__sort-label radar-table__sort-label--static">CEDEAR $</span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head">
                    <span className="radar-table__sort-label radar-table__sort-label--static">CEDEAR USD</span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <span className="radar-table__sort-label radar-table__sort-label--static">Ratio</span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <span className="radar-table__sort-label radar-table__sort-label--static">Precio $</span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <span className="radar-table__sort-label radar-table__sort-label--static">Precio USD</span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <span className="radar-table__sort-label radar-table__sort-label--static">CCL implícito</span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <span className="radar-table__sort-label radar-table__sort-label--static">Precio USA</span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <span className="radar-table__sort-label radar-table__sort-label--static">Implícito USD</span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <span className="radar-table__sort-label radar-table__sort-label--static">Gap %</span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head" style={{ textAlign: "right" }}>
                    <span className="radar-table__sort-label radar-table__sort-label--static">TotalScore</span>
                  </th>
                  <th scope="col" className="radar-table__th radar-table__th--sticky-head">
                    <span className="radar-table__sort-label radar-table__sort-label--static">SignalState</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {displayRows.map((r) => (
                  <tr key={r.ticker_usa}>
                    <td className="radar-table__sticky-col table-cell--nowrap">
                      <TickerRadarLink ticker={r.ticker_usa} mercado="USA" />
                    </td>
                    <td className="table-cell--nowrap">{r.ticker_cedear_ars || EMPTY}</td>
                    <td className="table-cell--nowrap">{r.ticker_cedear_usd || EMPTY}</td>
                    <td style={{ textAlign: "right" }} className="table-cell--nowrap">
                      {fmtFixed(r.ratio, 2)}
                    </td>
                    <td style={{ textAlign: "right" }} className={r.precio_cedear_ars === null ? "table-cell--empty" : ""}>
                      {fmtFixed(r.precio_cedear_ars, 2)}
                    </td>
                    <td style={{ textAlign: "right" }} className={r.precio_cedear_usd === null ? "table-cell--empty" : ""}>
                      {fmtFixed(r.precio_cedear_usd, 4)}
                    </td>
                    <td style={{ textAlign: "right" }} className={r.ccl_implicito === null ? "table-cell--empty" : ""}>
                      {fmtFixed(r.ccl_implicito, 2)}
                    </td>
                    <td style={{ textAlign: "right" }} className={r.precio_usa_real === null ? "table-cell--empty" : ""}>
                      {fmtFixed(r.precio_usa_real, 2)}
                    </td>
                    <td style={{ textAlign: "right" }} className={r.precio_implicito_usd === null ? "table-cell--empty" : ""}>
                      {fmtFixed(r.precio_implicito_usd, 4)}
                    </td>
                    <td style={{ textAlign: "right" }} className={r.gap_pct === null ? "table-cell--empty" : ""}>
                      {fmtPct(r.gap_pct)}
                    </td>
                    <td style={{ textAlign: "right" }} className={r.TotalScore === null ? "table-cell--empty" : ""}>
                      {fmtFixed(r.TotalScore, 1)}
                    </td>
                    <td className="table-cell--nowrap">
                      {r.SignalState?.trim() ? r.SignalState : EMPTY}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
