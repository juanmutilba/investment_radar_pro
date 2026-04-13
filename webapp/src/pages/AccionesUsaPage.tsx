import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";

import {
  type LatestRadarResponse,
  type RadarRow,
  fetchLatestRadar,
} from "@/services/api";

type SortDir = "asc" | "desc";

type SortCriterion = { columnId: string; dir: SortDir };

type ColumnDef = {
  id: string;
  header: string;
  keys: string[];
  minWidth: number;
  align?: "left" | "right" | "center";
  headerTitle?: string;
  nowrap?: boolean;
  /** Cómo ordenar por esta columna; `null` = no ordenable desde UI. */
  sortKind?: "string" | "number" | "trend" | "flag" | null;
};

const SCORE_HELP = {
  tech: "Síntesis del análisis técnico del radar: tendencia, momentum e indicadores (RSI, MACD, medias).",
  fund: "Síntesis de fundamentales del radar: rentabilidad, márgenes, deuda y valoración relativa.",
  risk: "Puntuación de riesgo del modelo (volatilidad y perfil del activo); interpretar según la escala del radar.",
} as const;

const COLUMNS: ColumnDef[] = [
  { id: "ticker", header: "Ticker", keys: ["Ticker", "ticker"], minWidth: 92, nowrap: true, sortKind: "string" },
  { id: "empresa", header: "Empresa", keys: ["Empresa", "empresa"], minWidth: 160, sortKind: "string" },
  { id: "sector", header: "Sector", keys: ["Sector", "sector"], minWidth: 120, sortKind: "string" },
  { id: "precio", header: "Precio", keys: ["Precio", "precio"], minWidth: 72, align: "right", nowrap: true, sortKind: "number" },
  { id: "pe", header: "P/E", keys: ["PE", "Pe", "pe", "P/E", "P/E Ratio"], minWidth: 64, align: "right", nowrap: true, sortKind: "number" },
  { id: "ebitda", header: "EBITDA", keys: ["EBITDA", "ebitda"], minWidth: 100, align: "right", nowrap: true, sortKind: "number" },
  { id: "rsi", header: "RSI", keys: ["RSI", "rsi"], minWidth: 52, align: "right", nowrap: true, sortKind: "number" },
  { id: "trend", header: "Tendencia", keys: ["Trend", "trend"], minWidth: 108, nowrap: true, sortKind: "trend" },
  {
    id: "macd",
    header: "MACD Alcista",
    keys: ["MACD_Bull", "macd_bull"],
    minWidth: 108,
    align: "center",
    nowrap: true,
    sortKind: "flag",
  },
  {
    id: "tech",
    header: "TechScore",
    keys: ["TechScore", "tech_score"],
    minWidth: 92,
    align: "right",
    nowrap: true,
    headerTitle: SCORE_HELP.tech,
    sortKind: "number",
  },
  {
    id: "fund",
    header: "FundScore",
    keys: ["FundScore", "fund_score"],
    minWidth: 92,
    align: "right",
    nowrap: true,
    headerTitle: SCORE_HELP.fund,
    sortKind: "number",
  },
  {
    id: "risk",
    header: "RiskScore",
    keys: ["RiskScore", "risk_score"],
    minWidth: 92,
    align: "right",
    nowrap: true,
    headerTitle: SCORE_HELP.risk,
    sortKind: "number",
  },
  { id: "total", header: "TotalScore", keys: ["TotalScore", "total_score"], minWidth: 96, align: "right", nowrap: true, sortKind: "number" },
  {
    id: "signal",
    header: "SignalState",
    keys: ["SignalState", "signal_state", "signalState"],
    minWidth: 112,
    nowrap: true,
    sortKind: "string",
  },
  {
    id: "conv",
    header: "Conviccion",
    keys: ["Conviccion", "conviccion", "Conviction"],
    minWidth: 88,
    nowrap: true,
    sortKind: "string",
  },
];

const COLUMN_BY_ID = Object.fromEntries(COLUMNS.map((c) => [c.id, c])) as Record<string, ColumnDef>;

const TICKER_COL = COLUMNS[0];
const EMPRESA_KEYS = COLUMNS.find((c) => c.id === "empresa")!.keys;
const SECTOR_KEYS = COLUMNS.find((c) => c.id === "sector")!.keys;
const TOTAL_KEYS = COLUMNS.find((c) => c.id === "total")!.keys;

const USD_FORMAT = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
  minimumFractionDigits: 0,
});

function getRaw(row: RadarRow, keys: string[]): unknown {
  for (const k of keys) {
    if (!(k in row)) {
      continue;
    }
    const v = row[k];
    if (v === null || v === undefined || v === "") {
      continue;
    }
    return v;
  }
  return undefined;
}

function parseNumberLoose(raw: unknown): number | null {
  if (raw === null || raw === undefined || raw === "") {
    return null;
  }
  if (typeof raw === "number") {
    return Number.isFinite(raw) ? raw : null;
  }
  const s = String(raw)
    .trim()
    .replace(/\s/g, "")
    .replace(/[$€£]/g, "")
    .replace(/,/g, "");
  const n = parseFloat(s);
  return Number.isFinite(n) ? n : null;
}

function formatTrend(raw: unknown): { text: string; missing: boolean } {
  if (raw === null || raw === undefined || raw === "") {
    return { text: "—", missing: true };
  }
  if (typeof raw === "boolean") {
    return { text: raw ? "Alcista" : "No alcista", missing: false };
  }
  if (typeof raw === "number") {
    if (!Number.isFinite(raw)) {
      return { text: "—", missing: true };
    }
    if (raw === 1) {
      return { text: "Alcista", missing: false };
    }
    if (raw === 0) {
      return { text: "No alcista", missing: false };
    }
    return { text: raw > 0 ? "Alcista" : "No alcista", missing: false };
  }

  const s = String(raw).trim();
  const lower = s.toLowerCase();

  const positive = new Set([
    "alcista",
    "sí",
    "si",
    "yes",
    "true",
    "bull",
    "bullish",
    "uptrend",
    "up",
    "positive",
  ]);
  const negative = new Set([
    "no alcista",
    "bajista",
    "no",
    "false",
    "bear",
    "bearish",
    "downtrend",
    "down",
    "negative",
  ]);

  if (positive.has(lower)) {
    return { text: "Alcista", missing: false };
  }
  if (negative.has(lower)) {
    return { text: "No alcista", missing: false };
  }
  if (lower.includes("uptrend") || lower.includes("bull")) {
    return { text: "Alcista", missing: false };
  }
  if (lower.includes("downtrend") || lower.includes("bear")) {
    return { text: "No alcista", missing: false };
  }

  return { text: s, missing: false };
}

function formatEbitdaUsd(raw: unknown): { text: string; missing: boolean } {
  const n = parseNumberLoose(raw);
  if (n === null) {
    return { text: "—", missing: true };
  }
  return { text: USD_FORMAT.format(n), missing: false };
}

/** MACD alcista: solo lectura / presentación; mismas claves que el backend. */
function formatMacdAlcista(raw: unknown): { text: string; missing: boolean } {
  if (raw === null || raw === undefined || raw === "") {
    return { text: "—", missing: true };
  }
  if (typeof raw === "boolean") {
    return { text: raw ? "Sí" : "No", missing: false };
  }
  if (typeof raw === "number") {
    if (!Number.isFinite(raw)) {
      return { text: "—", missing: true };
    }
    if (raw === 1) {
      return { text: "Sí", missing: false };
    }
    if (raw === 0) {
      return { text: "No", missing: false };
    }
    return { text: raw > 0 ? "Sí" : "No", missing: false };
  }
  const s = String(raw).trim();
  const lower = s.toLowerCase();
  const yes = new Set([
    "true",
    "1",
    "yes",
    "y",
    "si",
    "sí",
    "t",
    "bull",
    "bullish",
  ]);
  const no = new Set(["false", "0", "no", "n", "f", "bear", "bearish"]);
  if (yes.has(lower)) {
    return { text: "Sí", missing: false };
  }
  if (no.has(lower)) {
    return { text: "No", missing: false };
  }
  if (lower.includes("bull")) {
    return { text: "Sí", missing: false };
  }
  if (lower.includes("bear")) {
    return { text: "No", missing: false };
  }
  return { text: "—", missing: true };
}

function formatScalar(raw: unknown): { text: string; missing: boolean } {
  if (raw === null || raw === undefined || raw === "") {
    return { text: "—", missing: true };
  }
  if (typeof raw === "boolean") {
    return { text: raw ? "Sí" : "No", missing: false };
  }
  if (typeof raw === "number") {
    return Number.isFinite(raw)
      ? { text: String(raw), missing: false }
      : { text: "—", missing: true };
  }
  return { text: String(raw), missing: false };
}

function cellForColumn(col: ColumnDef, row: RadarRow): { text: string; missing: boolean } {
  const raw = getRaw(row, col.keys);
  if (col.id === "trend") {
    return formatTrend(raw);
  }
  if (col.id === "ebitda") {
    return formatEbitdaUsd(raw);
  }
  if (col.id === "macd") {
    return formatMacdAlcista(raw);
  }
  return formatScalar(raw);
}

/** Valor para ordenar (null = ausente, va al final en asc). */
function sortableValue(row: RadarRow, col: ColumnDef): string | number | null {
  if (col.sortKind === null || col.sortKind === undefined) {
    return null;
  }
  const raw = getRaw(row, col.keys);
  if (col.sortKind === "trend") {
    const t = formatTrend(raw);
    if (t.missing) {
      return null;
    }
    return t.text === "Alcista" ? 1 : 0;
  }
  if (col.sortKind === "flag") {
    const f = formatMacdAlcista(raw);
    if (f.missing) {
      return null;
    }
    return f.text === "Sí" ? 1 : 0;
  }
  if (col.sortKind === "number") {
    return parseNumberLoose(raw);
  }
  if (raw === null || raw === undefined || raw === "") {
    return null;
  }
  return String(raw).trim().toLowerCase();
}

function compareNullable(
  a: string | number | null,
  b: string | number | null,
): number {
  const aMissing = a === null;
  const bMissing = b === null;
  if (aMissing && bMissing) {
    return 0;
  }
  if (aMissing) {
    return 1;
  }
  if (bMissing) {
    return -1;
  }
  if (typeof a === "number" && typeof b === "number") {
    return a - b;
  }
  return String(a).localeCompare(String(b), "es", { numeric: true });
}

function compareRowsByCriteria(a: RadarRow, b: RadarRow, criteria: SortCriterion[]): number {
  for (const { columnId, dir } of criteria) {
    const col = COLUMN_BY_ID[columnId];
    if (!col || col.sortKind === null || col.sortKind === undefined) {
      continue;
    }
    const va = sortableValue(a, col);
    const vb = sortableValue(b, col);
    const base = compareNullable(va, vb);
    if (base !== 0) {
      return dir === "asc" ? base : -base;
    }
  }
  const ta = String(sortableValue(a, TICKER_COL) ?? "");
  const tb = String(sortableValue(b, TICKER_COL) ?? "");
  return ta.localeCompare(tb, "es", { numeric: true });
}

function initialColWidths(): Record<string, number> {
  return Object.fromEntries(COLUMNS.map((c) => [c.id, c.minWidth]));
}

export function AccionesUsaPage() {
  const [radar, setRadar] = useState<LatestRadarResponse | null | undefined>(
    undefined,
  );
  const [error, setError] = useState<string | null>(null);
  const [colWidths, setColWidths] = useState<Record<string, number>>(initialColWidths);
  const colWidthsRef = useRef(colWidths);
  colWidthsRef.current = colWidths;

  const [search, setSearch] = useState("");
  const [sector, setSector] = useState<string>("");
  const [minTotalScore, setMinTotalScore] = useState<string>("");
  const [sortCriteria, setSortCriteria] = useState<SortCriterion[]>([]);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setRadar(undefined);

    fetchLatestRadar()
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
  }, []);

  useEffect(() => {
    if (radar?.file) {
      setColWidths(initialColWidths());
      setSector("");
      setMinTotalScore("");
      setSearch("");
      setSortCriteria([]);
    }
  }, [radar?.file]);

  const loading = radar === undefined;
  const noExport = radar === null;
  const rows = radar?.rows ?? [];
  const emptySheet = radar !== null && radar !== undefined && rows.length === 0;

  const sectorOptions = useMemo(() => {
    const set = new Set<string>();
    for (const row of rows) {
      const v = getRaw(row, SECTOR_KEYS);
      if (v !== undefined && v !== null && String(v).trim() !== "") {
        set.add(String(v).trim());
      }
    }
    return [...set].sort((a, b) => a.localeCompare(b, "es", { sensitivity: "base" }));
  }, [rows]);

  const filteredRows = useMemo(() => {
    let out = rows;
    const q = search.trim().toLowerCase();
    if (q) {
      out = out.filter((r) => {
        const t = String(getRaw(r, TICKER_COL.keys) ?? "")
          .toLowerCase()
          .trim();
        const e = String(getRaw(r, EMPRESA_KEYS) ?? "")
          .toLowerCase()
          .trim();
        return t.includes(q) || e.includes(q);
      });
    }
    if (sector) {
      out = out.filter((r) => String(getRaw(r, SECTOR_KEYS) ?? "").trim() === sector);
    }
    const minRaw = minTotalScore.trim();
    if (minRaw !== "" && Number.isFinite(Number(minRaw))) {
      const m = Number(minRaw);
      out = out.filter((r) => {
        const v = parseNumberLoose(getRaw(r, TOTAL_KEYS));
        return v !== null && v >= m;
      });
    }
    return out;
  }, [rows, search, sector, minTotalScore]);

  const displayRows = useMemo(() => {
    if (sortCriteria.length === 0) {
      return filteredRows;
    }
    const copy = [...filteredRows];
    copy.sort((a, b) => compareRowsByCriteria(a, b, sortCriteria));
    return copy;
  }, [filteredRows, sortCriteria]);

  const onHeaderSortClick = useCallback((columnId: string, e: ReactMouseEvent<HTMLButtonElement>) => {
    const col = COLUMN_BY_ID[columnId];
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
  }, []);

  const onResizeMouseDown = useCallback((columnId: string, e: ReactMouseEvent<HTMLSpanElement>) => {
    e.preventDefault();
    e.stopPropagation();
    const col = COLUMN_BY_ID[columnId];
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
  }, []);

  const sortIndexForColumn = useCallback(
    (columnId: string) => sortCriteria.findIndex((s) => s.columnId === columnId),
    [sortCriteria],
  );

  return (
    <>
      <h1 className="page-title">Acciones USA</h1>
      <p className="page-desc">
        Radar USA (último export). Orden: clic en encabezado; orden secundario:
        Shift+clic. Ajustá anchos arrastrando el borde derecho del encabezado.
      </p>

      {loading && <p className="msg-muted">Cargando radar…</p>}

      {error && <p className="msg-error">{error}</p>}

      {!loading && noExport && (
        <p className="msg-muted">
          No hay archivo de radar exportado en el servidor. Ejecutá un scan y
          exportá resultados para ver la tabla.
        </p>
      )}

      {!loading && !noExport && emptySheet && (
        <p className="msg-muted">
          El último export no contiene filas en Radar_Completo.
        </p>
      )}

      {!loading && !noExport && !emptySheet && (
        <div className="card" style={{ marginBottom: "1rem" }}>
          <h2>Listado</h2>
          {radar?.file ? (
            <p className="msg-muted" style={{ margin: "0 0 0.75rem" }}>
              Fuente: <code style={{ fontSize: "0.8rem" }}>{radar.file}</code>
            </p>
          ) : null}

          <div className="radar-toolbar" aria-label="Filtros del listado">
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
            <p className="radar-toolbar__hint msg-muted">
              {displayRows.length} de {rows.length} filas
              {sortCriteria.length > 1 ? ` · ${sortCriteria.length} niveles de orden` : ""}
            </p>
          </div>

          <div className="radar-table-wrap">
            <table className="radar-table">
              <thead>
                <tr>
                  {COLUMNS.map((c) => {
                    const w = colWidths[c.id] ?? c.minWidth;
                    const sortIdx = sortIndexForColumn(c.id);
                    const crit = sortIdx >= 0 ? sortCriteria[sortIdx] : null;
                    const sortable = Boolean(c.sortKind);

                    return (
                      <th
                        key={c.id}
                        scope="col"
                        style={{ width: w, minWidth: w, maxWidth: w }}
                        className={
                          c.id === "ticker"
                            ? "radar-table__sticky-col radar-table__th radar-table__th--sticky-head"
                            : c.headerTitle
                              ? "radar-table__th radar-table__th--help radar-table__th--sticky-head"
                              : "radar-table__th radar-table__th--sticky-head"
                        }
                      >
                        <div className="radar-table__th-inner">
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
                </tr>
              </thead>
              <tbody>
                {displayRows.map((row, i) => (
                  <tr key={`${cellForColumn(TICKER_COL, row).text}-${String(i)}`}>
                    {COLUMNS.map((c) => {
                      const { text, missing } = cellForColumn(c, row);
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
                          {text}
                        </td>
                      );
                    })}
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
