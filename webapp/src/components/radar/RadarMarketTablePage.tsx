import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";

import { type LatestRadarResponse, type RadarRow } from "@/services/api";

import { renderCellInner, type RenderCellKeys } from "./radarTableCells";
import {
  cellForColumn,
  compareRowsByCriteria,
  getRaw,
  initialColWidths,
  parseNumberLoose,
  type CellFormatOptions,
} from "./radarTableCore";
import type { ColumnDef, QuickFilterId, SortCriterion } from "./radarTableModel";

export type RadarMarketTablePageProps = {
  pageTitle: string;
  columns: ColumnDef[];
  fetchRadar: () => Promise<LatestRadarResponse | null>;
  formatEbitda: CellFormatOptions["formatEbitda"];
  /** Si se define, columna Precio usa solo este formateo visual (orden sigue con el número crudo). */
  formatPrecio?: CellFormatOptions["formatPrecio"];
  emptySheetMessage: string;
  /** Valor inicial del campo Buscar (p. ej. desde <code>?ticker=</code> en la ruta). */
  initialSearch?: string;
  /** Si true (p. ej. <code>?exact=1</code>), el texto de búsqueda filtra solo por ticker exacto. */
  tickerSearchExact?: boolean;
  /** Columna extra con acciones (p. ej. compra/venta desde cartera). */
  renderRowActions?: (row: RadarRow) => ReactNode;
  universe?: {
    label: string;
    allLabel: string;
    keys: string[];
    options: string[];
  };
};

function colKeys(columns: ColumnDef[], id: string): string[] {
  const c = columns.find((x) => x.id === id);
  if (!c) {
    throw new Error(`Column id not found: ${id}`);
  }
  return c.keys;
}

export function RadarMarketTablePage({
  pageTitle,
  columns,
  fetchRadar,
  formatEbitda,
  formatPrecio,
  universe,
  initialSearch,
  tickerSearchExact = false,
  renderRowActions,
  emptySheetMessage,
}: RadarMarketTablePageProps) {
  const cellOpts = useMemo<CellFormatOptions>(
    () =>
      formatPrecio !== undefined
        ? { formatEbitda, formatPrecio }
        : { formatEbitda },
    [formatEbitda, formatPrecio],
  );

  const columnById = useMemo(
    () => Object.fromEntries(columns.map((c) => [c.id, c])) as Record<string, ColumnDef>,
    [columns],
  );

  const tickerCol = columns[0];
  const empresaKeys = useMemo(() => colKeys(columns, "empresa"), [columns]);
  const sectorKeys = useMemo(() => colKeys(columns, "sector"), [columns]);
  const totalKeys = useMemo(() => colKeys(columns, "total"), [columns]);
  const rsiKeys = useMemo(() => colKeys(columns, "rsi"), [columns]);
  const fundKeys = useMemo(() => colKeys(columns, "fund"), [columns]);
  const debtEbitdaKeys = useMemo(() => colKeys(columns, "debtToEbitda"), [columns]);
  const cedearKeys = useMemo(() => {
    const c = columns.find((x) => x.id === "tieneCedear");
    return c?.keys ?? ["TieneCedear", "tieneCedear"];
  }, [columns]);
  const cedearFlagKeys = useMemo(() => {
    const c = columns.find((x) => x.id === "cedear");
    return c?.keys ?? ["CEDEAR", "cedear"];
  }, [columns]);

  const renderKeys = useMemo<RenderCellKeys>(
    () => ({ totalKeys, rsiKeys }),
    [totalKeys, rsiKeys],
  );

  const [radar, setRadar] = useState<LatestRadarResponse | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [colWidths, setColWidths] = useState<Record<string, number>>(() =>
    initialColWidths(columns),
  );
  const colWidthsRef = useRef(colWidths);
  colWidthsRef.current = colWidths;

  const [search, setSearch] = useState(() => (initialSearch ?? "").trim());
  const [sector, setSector] = useState<string>("");
  const [minTotalScore, setMinTotalScore] = useState<string>("");
  const [quickFilter, setQuickFilter] = useState<QuickFilterId | null>(null);
  const [cedearFilter, setCedearFilter] = useState<"TODOS" | "SI" | "NO">("TODOS");
  const [sortCriteria, setSortCriteria] = useState<SortCriterion[]>([]);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [universeValue, setUniverseValue] = useState<string>("");

  const onRefreshRadar = useCallback(() => {
    setRefreshError(null);
    setIsRefreshing(true);
    fetchRadar()
      .then((data) => {
        setRadar(data);
        setError(null);
      })
      .catch((e: unknown) => {
        setRefreshError(e instanceof Error ? e.message : "Error al cargar el radar");
      })
      .finally(() => {
        setIsRefreshing(false);
      });
  }, [fetchRadar]);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setRadar(undefined);

    fetchRadar()
      .then((data) => {
        if (!cancelled) {
          setRadar(data);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setRadar(undefined);
          setError(e instanceof Error ? e.message : "Error al cargar el radar");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [fetchRadar]);

  useEffect(() => {
    if (radar?.file) {
      setColWidths(initialColWidths(columns));
      setSector("");
      setMinTotalScore("");
      setSearch((initialSearch ?? "").trim());
      setQuickFilter(null);
      setCedearFilter("TODOS");
      setSortCriteria([]);
      setUniverseValue("");
    }
  }, [radar?.file, columns, initialSearch]);

  useEffect(() => {
    setSearch((initialSearch ?? "").trim());
  }, [initialSearch]);

  /** Al llegar con <code>?ticker=</code> (p. ej. desde CEDEAR), no arrastrar filtros de una visita o ticker anterior. */
  useEffect(() => {
    const tin = (initialSearch ?? "").trim();
    if (!tin) return;
    setQuickFilter(null);
    setUniverseValue("");
    setSector("");
    setMinTotalScore("");
    setCedearFilter("TODOS");
    setSortCriteria([]);
  }, [initialSearch]);

  // Si hubo error de fetch/parseo, no queremos quedar "pegados" en loading.
  const loading = radar === undefined && error === null;
  const noExport = radar === null;
  const rows = radar?.rows ?? [];
  const emptySheet = radar !== null && radar !== undefined && rows.length === 0;

  const radarHasTieneCedear = useMemo(
    () =>
      rows.some(
        (r) =>
          typeof r === "object" &&
          r !== null &&
          Object.prototype.hasOwnProperty.call(r, "TieneCedear"),
      ),
    [rows],
  );

  const radarHasCedearFlag = useMemo(
    () =>
      rows.some(
        (r) =>
          typeof r === "object" &&
          r !== null &&
          (Object.prototype.hasOwnProperty.call(r, "CEDEAR") || Object.prototype.hasOwnProperty.call(r, "cedear")),
      ),
    [rows],
  );

  const sectorOptions = useMemo(() => {
    const set = new Set<string>();
    for (const row of rows) {
      const v = getRaw(row, sectorKeys);
      if (v !== undefined && v !== null && String(v).trim() !== "") {
        set.add(String(v).trim());
      }
    }
    return [...set].sort((a, b) => a.localeCompare(b, "es", { sensitivity: "base" }));
  }, [rows, sectorKeys]);

  const filteredRows = useMemo(() => {
    let out = rows;
    if (universe && universeValue) {
      out = out.filter((r) => String(getRaw(r, universe.keys) ?? "").trim() === universeValue);
    }
    const q = search.trim().toLowerCase();
    if (q) {
      out = out.filter((r) => {
        const t = String(getRaw(r, tickerCol.keys) ?? "")
          .toLowerCase()
          .trim();
        const e = String(getRaw(r, empresaKeys) ?? "")
          .toLowerCase()
          .trim();
        if (tickerSearchExact) {
          return t === q;
        }
        return t.includes(q) || e.includes(q);
      });
    }
    if (sector) {
      out = out.filter((r) => String(getRaw(r, sectorKeys) ?? "").trim() === sector);
    }
    const minRaw = minTotalScore.trim();
    if (minRaw !== "" && Number.isFinite(Number(minRaw))) {
      const m = Number(minRaw);
      out = out.filter((r) => {
        const v = parseNumberLoose(getRaw(r, totalKeys));
        return v !== null && v >= m;
      });
    }
    if (quickFilter === "oportunidades") {
      out = out.filter((r) => {
        const v = parseNumberLoose(getRaw(r, totalKeys));
        return v !== null && v >= 7;
      });
    }
    if (quickFilter === "oversold") {
      out = out.filter((r) => {
        const v = parseNumberLoose(getRaw(r, rsiKeys));
        return v !== null && v <= 35;
      });
    }
    if (quickFilter === "calidad") {
      out = out.filter((r) => {
        const fs = parseNumberLoose(getRaw(r, fundKeys));
        const de = parseNumberLoose(getRaw(r, debtEbitdaKeys));
        return fs !== null && fs >= 7 && de !== null && de <= 2;
      });
    }
    if (quickFilter === "solo_cedear" && radarHasTieneCedear) {
      out = out.filter((r) => {
        const v = getRaw(r, cedearKeys);
        if (typeof v === "boolean") {
          return v;
        }
        if (v === 1) {
          return true;
        }
        if (typeof v === "string") {
          const s = v.trim().toLowerCase();
          return s === "true" || s === "1" || s === "sí" || s === "si";
        }
        return false;
      });
    }
    if (cedearFilter !== "TODOS") {
      out = out.filter((r) => {
        const raw = radarHasCedearFlag ? getRaw(r, cedearFlagKeys) : null;
        const v = String(raw ?? "").trim().toUpperCase();
        if (radarHasCedearFlag) {
          return cedearFilter === "SI" ? v === "SI" : v === "NO";
        }
        // Fallback (exports viejos): usar TieneCedear si existe.
        if (!radarHasTieneCedear) {
          return true;
        }
        const tc = getRaw(r, cedearKeys);
        const has =
          tc === true ||
          tc === 1 ||
          (typeof tc === "string" && (() => {
            const s = tc.trim().toLowerCase();
            return s === "true" || s === "1" || s === "sí" || s === "si";
          })());
        return cedearFilter === "SI" ? has : !has;
      });
    }
    return out;
  }, [
    rows,
    universe,
    universeValue,
    search,
    sector,
    minTotalScore,
    quickFilter,
    tickerSearchExact,
    tickerCol.keys,
    empresaKeys,
    sectorKeys,
    totalKeys,
    rsiKeys,
    fundKeys,
    debtEbitdaKeys,
    cedearKeys,
    radarHasTieneCedear,
    cedearFlagKeys,
    radarHasCedearFlag,
    cedearFilter,
    universe?.keys,
  ]);

  const displayRows = useMemo(() => {
    if (sortCriteria.length === 0) {
      return filteredRows;
    }
    const copy = [...filteredRows];
    copy.sort((a, b) =>
      compareRowsByCriteria(a, b, sortCriteria, columnById, tickerCol),
    );
    return copy;
  }, [filteredRows, sortCriteria, columnById, tickerCol]);

  const onHeaderSortClick = useCallback(
    (columnId: string, e: ReactMouseEvent<HTMLButtonElement>) => {
      const col = columnById[columnId];
      if (!col || col.sortKind === null || col.sortKind === undefined) {
        return;
      }
      e.preventDefault();
      if (e.shiftKey) {
        setSortCriteria((prev) => {
          const idx = prev.findIndex((p) => p.columnId === columnId);
          if (idx >= 0) {
            const next = [...prev];
            const cur = next[idx];
            next[idx] = { columnId, dir: cur.dir === "asc" ? "desc" : "asc" };
            return next;
          }
          return [...prev, { columnId, dir: "asc" }];
        });
        return;
      }
      setSortCriteria((prev) => {
        if (prev.length === 1 && prev[0].columnId === columnId) {
          if (prev[0].dir === "asc") {
            return [{ columnId, dir: "desc" }];
          }
          return [];
        }
        return [{ columnId, dir: "asc" }];
      });
    },
    [columnById],
  );

  const onResizeMouseDown = useCallback(
    (columnId: string, e: ReactMouseEvent<HTMLSpanElement>) => {
      e.preventDefault();
      e.stopPropagation();
      const col = columnById[columnId];
      const minPx = Math.max(40, col?.minWidth ?? 48);
      const startX = e.clientX;
      const startW = colWidthsRef.current[columnId] ?? col?.minWidth ?? 80;

      const onMove = (ev: MouseEvent) => {
        const dx = ev.clientX - startX;
        const next = Math.max(minPx, Math.round(startW + dx));
        setColWidths((w) => ({ ...w, [columnId]: next }));
      };
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },
    [columnById],
  );

  const sortIndexForColumn = useCallback(
    (columnId: string) => sortCriteria.findIndex((s) => s.columnId === columnId),
    [sortCriteria],
  );

  return (
    <>
      <h1 className="page-title">{pageTitle}</h1>

      {radar !== undefined && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.75rem",
            flexWrap: "wrap",
            marginBottom: "1rem",
          }}
        >
          <button
            type="button"
            className="radar-refresh-btn"
            onClick={onRefreshRadar}
            disabled={isRefreshing}
          >
            {isRefreshing ? "Cargando…" : "Actualizar radar"}
          </button>
          {refreshError ? (
            <span className="msg-error" style={{ fontSize: "0.875rem" }}>
              {refreshError}
            </span>
          ) : null}
        </div>
      )}

      {loading && <p className="msg-muted">Cargando radar…</p>}

      {error && <p className="msg-error">{error}</p>}

      {!loading && noExport && (
        <p className="msg-muted">
          No hay archivo de radar exportado en el servidor. Ejecutá un scan desde el
          Dashboard para generar datos y exportar resultados.
        </p>
      )}

      {!loading && !noExport && emptySheet && (
        <p className="msg-muted">{emptySheetMessage}</p>
      )}

      {!loading && !noExport && !emptySheet && (
        <div className="card" style={{ marginBottom: "1rem" }}>
          <div className="radar-toolbar" aria-label="Filtros del listado">
            {universe ? (
              <div
                className="radar-toolbar__quick"
                role="group"
                aria-label={universe.label}
                style={{ flexBasis: "100%", marginTop: 0, paddingTop: 0, borderTop: "none" }}
              >
                <span className="radar-toolbar__label">{universe.label}</span>
                <button
                  type="button"
                  className={`radar-chip${universeValue === "" ? " radar-chip--active" : ""}`}
                  onClick={() => setUniverseValue("")}
                >
                  {universe.allLabel}
                </button>
                {universe.options.map((opt) => (
                  <button
                    key={opt}
                    type="button"
                    className={`radar-chip${universeValue === opt ? " radar-chip--active" : ""}`}
                    onClick={() => setUniverseValue(opt)}
                  >
                    {opt}
                  </button>
                ))}
              </div>
            ) : null}
            <label className="radar-toolbar__field">
              <span className="radar-toolbar__label">Buscar</span>
              <input
                type="search"
                className="radar-toolbar__input"
                placeholder="Ticker o empresa…"
                value={search}
                onChange={(ev) => setSearch(ev.target.value)}
                autoComplete="off"
              />
            </label>
            <label className="radar-toolbar__field">
              <span className="radar-toolbar__label">Sector</span>
              <select
                className="radar-toolbar__select"
                value={sector}
                onChange={(ev) => setSector(ev.target.value)}
              >
                <option value="">Todos</option>
                {sectorOptions.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
            <label className="radar-toolbar__field">
              <span className="radar-toolbar__label">TotalScore mín.</span>
              <input
                type="number"
                className="radar-toolbar__input radar-toolbar__input--narrow"
                placeholder="Ej. 50"
                value={minTotalScore}
                onChange={(ev) => setMinTotalScore(ev.target.value)}
                step="any"
              />
            </label>
            <div className="radar-toolbar__quick" role="group" aria-label="Filtros rápidos">
              <span className="radar-toolbar__label">Rápidos</span>
              <button
                type="button"
                className={`radar-chip${quickFilter === "oportunidades" ? " radar-chip--active" : ""}`}
                title="Muestra activos con TotalScore igual o mayor a 7"
                onClick={() => setQuickFilter((q) => (q === "oportunidades" ? null : "oportunidades"))}
              >
                Oportunidades
              </button>
              <button
                type="button"
                className={`radar-chip${quickFilter === "oversold" ? " radar-chip--active" : ""}`}
                title="Muestra activos con RSI igual o menor a 35"
                onClick={() => setQuickFilter((q) => (q === "oversold" ? null : "oversold"))}
              >
                Oversold
              </button>
              <button
                type="button"
                className={`radar-chip${quickFilter === "calidad" ? " radar-chip--active" : ""}`}
                title="Muestra activos con FundScore igual o mayor a 7 y Debt/EBITDA igual o menor a 2"
                onClick={() => setQuickFilter((q) => (q === "calidad" ? null : "calidad"))}
              >
                Calidad
              </button>
              {radarHasTieneCedear ? (
                <button
                  type="button"
                  className={`radar-chip${quickFilter === "solo_cedear" ? " radar-chip--active" : ""}`}
                  title="Solo tickers USA con equivalencia CEDEAR activa en la tabla maestra"
                  onClick={() => setQuickFilter((q) => (q === "solo_cedear" ? null : "solo_cedear"))}
                >
                  Solo CEDEAR
                </button>
              ) : null}
              <div style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
                <span className="radar-toolbar__label" style={{ marginLeft: "0.25rem" }}>
                  CEDEAR
                </span>
                <select
                  className="radar-toolbar__select"
                  value={cedearFilter}
                  onChange={(ev) => setCedearFilter(ev.target.value as "TODOS" | "SI" | "NO")}
                  style={{ paddingTop: "0.25rem", paddingBottom: "0.25rem" }}
                  aria-label="Filtro CEDEAR"
                >
                  <option value="TODOS">Todos</option>
                  <option value="SI">Con CEDEAR</option>
                  <option value="NO">Sin CEDEAR</option>
                </select>
              </div>
              <button
                type="button"
                className="radar-chip radar-chip--ghost"
                title="Quitar filtro rápido (no borra búsqueda ni sector)"
                onClick={() => {
                  setQuickFilter(null);
                  setCedearFilter("TODOS");
                }}
              >
                Limpiar
              </button>
            </div>
            <p className="radar-toolbar__hint msg-muted">
              {displayRows.length} de {rows.length} filas
              {sortCriteria.length > 1 ? ` · ${sortCriteria.length} niveles de orden` : ""}
              {quickFilter ? " · filtro rápido activo" : ""}
              {universe && universeValue ? ` · ${universe.label.toLowerCase()}: ${universeValue}` : ""}
            </p>
          </div>

          <div className="radar-table-wrap">
            <table className="radar-table">
              <thead>
                <tr>
                  {columns.map((c) => {
                    const w = colWidths[c.id] ?? c.minWidth;
                    const sortIdx = sortIndexForColumn(c.id);
                    const crit = sortIdx >= 0 ? sortCriteria[sortIdx] : null;
                    const sortable = Boolean(c.sortKind);

                    return (
                      <th
                        key={c.id}
                        scope="col"
                        style={{ width: w, minWidth: w, maxWidth: w, textAlign: c.align ?? "left" }}
                        className={
                          c.id === "ticker"
                            ? "radar-table__sticky-col radar-table__th radar-table__th--sticky-head"
                            : c.headerTitle
                              ? "radar-table__th radar-table__th--help radar-table__th--sticky-head"
                              : "radar-table__th radar-table__th--sticky-head"
                        }
                      >
                        <div
                          className="radar-table__th-inner"
                          style={{
                            justifyContent:
                              c.align === "center" ? "center" : c.align === "right" ? "flex-end" : "flex-start",
                          }}
                        >
                          {sortable ? (
                            <button
                              type="button"
                              className="radar-table__sort-btn"
                              onClick={(ev) => onHeaderSortClick(c.id, ev)}
                              title={
                                [
                                  c.headerTitle,
                                  sortCriteria.length > 0
                                    ? "Clic: orden principal. Shift+clic: añade o invierte criterio secundario."
                                    : "Clic para ordenar. Shift+clic: orden multi-columna.",
                                ]
                                  .filter(Boolean)
                                  .join(" ")
                              }
                            >
                              <span className="radar-table__sort-label">{c.header}</span>
                              {crit ? (
                                <span className="radar-table__sort-icons" aria-hidden>
                                  {sortCriteria.length > 1 ? (
                                    <span className="radar-table__sort-priority">{sortIdx + 1}</span>
                                  ) : null}
                                  <span className="radar-table__sort-dir">
                                    {crit.dir === "asc" ? "\u25B2" : "\u25BC"}
                                  </span>
                                </span>
                              ) : null}
                            </button>
                          ) : (
                            <span
                              className="radar-table__sort-label radar-table__sort-label--static"
                              title={c.headerTitle}
                            >
                              {c.header}
                            </span>
                          )}
                          <span
                            className="radar-table__resize-handle"
                            role="separator"
                            aria-hidden
                            onMouseDown={(ev) => onResizeMouseDown(c.id, ev)}
                          />
                        </div>
                      </th>
                    );
                  })}
                  {renderRowActions ? (
                    <th
                      scope="col"
                      style={{ width: 112, minWidth: 112, maxWidth: 112 }}
                      className="radar-table__th radar-table__th--sticky-head"
                    >
                      <span className="radar-table__sort-label radar-table__sort-label--static">Cartera</span>
                    </th>
                  ) : null}
                </tr>
              </thead>
              <tbody>
                {displayRows.map((row, i) => (
                  <tr key={`${cellForColumn(tickerCol, row, cellOpts).text}-${String(i)}`}>
                    {columns.map((c) => {
                      const { text, missing } = cellForColumn(c, row, cellOpts);
                      const w = colWidths[c.id] ?? c.minWidth;
                      return (
                        <td
                          key={c.id}
                          style={{
                            width: w,
                            minWidth: w,
                            maxWidth: w,
                            textAlign: c.align ?? "left",
                          }}
                          className={
                            c.id === "ticker"
                              ? `radar-table__sticky-col table-cell--nowrap${missing ? " table-cell--empty" : ""}`
                              : missing
                                ? "table-cell--empty"
                                : c.nowrap
                                  ? "table-cell--nowrap"
                                  : undefined
                          }
                        >
                          {renderCellInner(c, row, text, missing, renderKeys)}
                        </td>
                      );
                    })}
                    {renderRowActions ? (
                      <td
                        style={{ width: 112, minWidth: 112, maxWidth: 112, verticalAlign: "middle" }}
                        className="table-cell--nowrap radar-table__actions-cell"
                      >
                        {renderRowActions(row)}
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {radar?.file ? (
            <p
              className="msg-muted"
              style={{
                fontSize: "0.72rem",
                margin: "0.75rem 0 0",
                textAlign: "left",
              }}
            >
              Fuente:{" "}
              <code style={{ fontSize: "0.68rem", color: "inherit", opacity: 0.9 }}>
                {radar.file}
              </code>
              {radar.sheet ? (
                <>
                  {" "}
                  · hoja <code style={{ fontSize: "0.68rem", color: "inherit", opacity: 0.9 }}>{radar.sheet}</code>
                </>
              ) : null}
            </p>
          ) : null}
        </div>
      )}
    </>
  );
}
