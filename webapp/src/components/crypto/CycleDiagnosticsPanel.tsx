export type CycleSummaryShape = {
  evaluated_count: number;
  accepted_count: number;
  rejected_count: number;
  skipped_count?: number;
  reasons: Record<string, number>;
  watchlist_count?: number;
  scan_count?: number;
  scan_ok_count?: number;
  scan_error_count?: number;
  candidates_count?: number;
  scan_error?: string | null;
  scan_duration_ms?: number;
  first_symbols_sample?: string[];
  scan_diagnosis?: string | null;
  scan_scenario?: string;
  scan_scenario_label?: string;
  scan_scenario_detail?: string;
  total_scan_rows?: number;
  rows_with_signal?: number;
  rows_signal_compra_potencial?: number;
  rows_signal_other?: number;
  rows_missing_signal?: number;
  unique_signals_detected?: string[];
  signal_counts?: Record<string, number>;
  sample_rows?: Array<Record<string, unknown>>;
  entry_candidate_filter?: Record<string, unknown>;
  evaluated_count_note?: string;
  timeframe?: string;
  limit?: number;
  watchlist_sample?: string[];
  scan_type?: string;
};

export type ScanDebugShape = {
  timeframe?: string;
  limit?: number;
  watchlist_count?: number;
  watchlist_sample?: string[];
  scan_type?: string;
  scan_count?: number;
  scan_ok_count?: number;
  scan_error_count?: number;
  candidates_count?: number;
  scan_error?: string | null;
  scan_duration_ms?: number;
  first_symbols_sample?: string[];
  scan_diagnosis?: string | null;
  scan_scenario?: string;
  scan_scenario_label?: string;
  scan_scenario_detail?: string;
  total_scan_rows?: number;
  rows_with_signal?: number;
  rows_signal_compra_potencial?: number;
  rows_signal_other?: number;
  rows_missing_signal?: number;
  unique_signals_detected?: string[];
  signal_counts?: Record<string, number>;
  sample_rows?: Array<Record<string, unknown>>;
  entry_candidate_filter?: Record<string, unknown>;
  evaluated_count_note?: string;
  updated_at?: string;
};

export type CycleCandidateShape = {
  symbol: string;
  score?: number | null;
  reason?: string | null;
  signal?: string | null;
};

export type PaperCyclePhase = "exits_only" | "strategy" | "both";

export type PaperAutoRunSchedule = {
  cyclePhase: PaperCyclePhase | null;
  lastExitsReviewAt: string | null;
  lastStrategyRunAt: string | null;
  nextStrategyRunAt: string | null;
  nextExitsReviewAt: string | null;
  strategyIntervalSeconds: number;
  exitsIntervalSeconds: number;
};

const REASON_CHIP_ORDER = [
  "score_below_min",
  "btc_trend_filter",
  "cooldown_symbol",
  "already_open",
  "already_hold_base_testnet",
  "max_open_positions",
  "max_one_per_run",
  "not_whitelisted_testnet",
  "testnet_balances_unavailable",
] as const;

const REASON_CHIP_LABELS: Record<string, string> = {
  score_below_min: "Score bajo",
  btc_trend_filter: "Filtro BTC",
  cooldown_symbol: "Cooldown",
  already_open: "Ya abierto",
  already_hold_base_testnet: "Ya en cartera",
  max_open_positions: "Máx. posiciones",
  max_one_per_run: "1 por ciclo",
  not_whitelisted_testnet: "No whitelist",
  testnet_balances_unavailable: "Sin balances",
};

const PHASE_LABELS: Record<PaperCyclePhase, string> = {
  exits_only: "Solo revisión de salidas",
  strategy: "Solo búsqueda de entradas",
  both: "Salidas + entradas",
};

const SCAN_DIAGNOSIS_HINTS: Record<string, string> = {
  watchlist_empty: "La watchlist configurada está vacía; no hay símbolos para escanear.",
  scanner_empty: "El scanner no devolvió filas (respuesta vacía).",
  scanner_error: "Error al escanear la watchlist (revisá conexión Binance o logs del servidor).",
  no_opportunity:
    "El scanner corrió, pero ningún activo tuvo señal compra_potencial en este timeframe.",
  candidates_present: "Hay candidatos con señal; revisá filtros de entrada (score, BTC, cooldown, etc.).",
  strategy_exception:
    "La estrategia falló antes o durante el escaneo (revisá last_error del auto-run y logs [CRYPTO_BOT_SCAN_DEBUG]).",
  strategy_precheck_failed: "Parámetros inválidos (p. ej. amount_usdt); el escaneo no se ejecutó.",
};

const SCAN_SCENARIO_HINTS: Record<string, string> = {
  A: "El scanner corrió (hay filas OK) pero ninguna fila tiene signal=compra_potencial exacto.",
  B: "El scanner no produjo filas útiles (error global, watchlist vacía o todas las filas con error).",
  C: "Hay indicios de señal en otro campo/casing o desajuste entre filas y candidates_count.",
  OK: "Hay candidatos compra_potencial; evaluated_count>0 solo si pasan filtros de entrada.",
};

function scanFieldsFrom(
  summary: CycleSummaryShape | null | undefined,
  lastScanDebug: ScanDebugShape | null | undefined,
): Partial<CycleSummaryShape> {
  const d: ScanDebugShape = lastScanDebug ?? {};
  const s: Partial<CycleSummaryShape> = summary ?? {};
  return {
    timeframe: d.timeframe ?? s.timeframe,
    limit: d.limit ?? s.limit,
    watchlist_count: d.watchlist_count ?? s.watchlist_count,
    watchlist_sample: d.watchlist_sample ?? s.watchlist_sample,
    scan_type: d.scan_type ?? s.scan_type,
    scan_count: d.scan_count ?? s.scan_count,
    scan_ok_count: d.scan_ok_count ?? s.scan_ok_count,
    scan_error_count: d.scan_error_count ?? s.scan_error_count,
    candidates_count: d.candidates_count ?? s.candidates_count,
    scan_error: d.scan_error ?? s.scan_error,
    scan_duration_ms: d.scan_duration_ms ?? s.scan_duration_ms,
    first_symbols_sample: d.first_symbols_sample ?? s.first_symbols_sample,
    scan_diagnosis: d.scan_diagnosis ?? s.scan_diagnosis,
    scan_scenario: d.scan_scenario ?? s.scan_scenario,
    scan_scenario_label: d.scan_scenario_label ?? s.scan_scenario_label,
    scan_scenario_detail: d.scan_scenario_detail ?? s.scan_scenario_detail,
    total_scan_rows: d.total_scan_rows ?? s.total_scan_rows,
    rows_with_signal: d.rows_with_signal ?? s.rows_with_signal,
    rows_signal_compra_potencial: d.rows_signal_compra_potencial ?? s.rows_signal_compra_potencial,
    rows_signal_other: d.rows_signal_other ?? s.rows_signal_other,
    rows_missing_signal: d.rows_missing_signal ?? s.rows_missing_signal,
    unique_signals_detected: d.unique_signals_detected ?? s.unique_signals_detected,
    signal_counts: d.signal_counts ?? s.signal_counts,
    sample_rows: d.sample_rows ?? s.sample_rows,
    entry_candidate_filter: d.entry_candidate_filter ?? s.entry_candidate_filter,
    evaluated_count_note: d.evaluated_count_note ?? s.evaluated_count_note,
  };
}

function fmtIsoLocalShort(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("es-AR", { dateStyle: "short", timeStyle: "medium" });
}

function fmtDurationMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

function fmtIntervalMinutes(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "—";
  const m = seconds / 60;
  return m >= 10 || m === Math.floor(m) ? `${Math.round(m)} min` : `${m.toFixed(1)} min`;
}

function rejectionChips(reasons: Record<string, number> | undefined): { key: string; label: string; count: number }[] {
  const r = reasons ?? {};
  const used = new Set<string>();
  const chips: { key: string; label: string; count: number }[] = [];

  for (const key of REASON_CHIP_ORDER) {
    const n = r[key];
    if (n && n > 0) {
      chips.push({ key, label: REASON_CHIP_LABELS[key] ?? key, count: n });
      used.add(key);
    }
  }

  let other = 0;
  for (const [k, n] of Object.entries(r)) {
    if (!used.has(k) && n > 0) other += n;
  }
  if (other > 0) {
    chips.push({ key: "_other", label: "Otros", count: other });
  }
  return chips;
}

type CycleDiagnosticsPanelProps = {
  startedAt: string | null | undefined;
  finishedAt: string | null | undefined;
  durationMs: number | null | undefined;
  primaryReason: string | null | undefined;
  summary: CycleSummaryShape | null | undefined;
  bestRejected: CycleCandidateShape | null | undefined;
  entryCandidate: CycleCandidateShape | null | undefined;
  phases?: string[] | null;
  primaryReasonLabel: (code: string | null | undefined) => string;
  emptyHint?: string;
  paperSchedule?: PaperAutoRunSchedule | null;
  lastScanDebug?: ScanDebugShape | null;
};

export function CycleDiagnosticsPanel({
  startedAt,
  finishedAt,
  durationMs,
  primaryReason,
  summary,
  bestRejected,
  entryCandidate,
  phases,
  primaryReasonLabel,
  emptyHint = "Sin datos de ciclo todavía. Iniciá el auto-run o el monitor y esperá la primera revisión.",
  paperSchedule,
  lastScanDebug,
}: CycleDiagnosticsPanelProps) {
  const cyclePhase = paperSchedule?.cyclePhase ?? null;
  const exitsOnly = cyclePhase === "exits_only";
  const strategyRanThisCycle = cyclePhase === "strategy" || cyclePhase === "both";

  const hasTiming = Boolean(startedAt || finishedAt);
  const hasPaperActivity = Boolean(
    paperSchedule?.lastExitsReviewAt || paperSchedule?.lastStrategyRunAt,
  );
  const hasSummary = Boolean(summary && (summary.evaluated_count > 0 || primaryReason));
  const chips = rejectionChips(summary?.reasons);

  const scan = scanFieldsFrom(summary, lastScanDebug);
  const evaluatedCount = summary?.evaluated_count ?? 0;

  const knownZeroEvalReasons = new Set([
    "no_opportunity",
    "watchlist_empty",
    "scanner_empty",
    "scanner_error",
    "strategy_exception",
    "strategy_precheck_failed",
  ]);
  const showScanProbe =
    strategyRanThisCycle &&
    evaluatedCount === 0 &&
    (scan.scan_count !== undefined ||
      scan.watchlist_count !== undefined ||
      lastScanDebug != null);

  const scanAnomaly =
    (scan.watchlist_count ?? 0) > 0 && scan.scan_count === 0;

  const strategyEmptyEvaluated =
    strategyRanThisCycle &&
    summary != null &&
    summary.evaluated_count === 0 &&
    primaryReason != null &&
    !knownZeroEvalReasons.has(primaryReason);

  if (!hasTiming && !hasSummary && !bestRejected && !entryCandidate && !hasPaperActivity) {
    return (
      <p className="msg-muted" style={{ margin: "0.75rem 0 0", fontSize: "0.85rem" }}>
        {emptyHint}
      </p>
    );
  }

  const healthOk =
    exitsOnly ||
    !primaryReason ||
    primaryReason === "opened" ||
    primaryReason === "no_opportunity" ||
    (summary && summary.evaluated_count > 0) ||
    Boolean(bestRejected);

  const showEntryStats = strategyRanThisCycle && summary;
  const showStrategyDiagnostics = !exitsOnly;

  return (
    <div className="crypto-cycle-diagnostics" style={{ marginTop: "0.85rem" }}>
      <h4 className="msg-muted" style={{ margin: "0 0 0.5rem", fontSize: "0.88rem", fontWeight: 600 }}>
        Último ciclo
        {cyclePhase ? (
          <span
            className="radar-badge radar-badge--conv-media"
            style={{
              marginLeft: "0.45rem",
              fontSize: "0.72rem",
              verticalAlign: "middle",
              background: exitsOnly ? "rgba(59, 130, 246, 0.18)" : "rgba(34, 197, 94, 0.15)",
            }}
          >
            {PHASE_LABELS[cyclePhase]}
          </span>
        ) : phases && phases.length > 0 ? (
          <span className="msg-muted" style={{ fontWeight: 400, marginLeft: "0.35rem", fontSize: "0.8rem" }}>
            ({phases.join(" + ")})
          </span>
        ) : null}
      </h4>

      {exitsOnly ? (
        <div
          className="crypto-testnet-note crypto-testnet-note--blue"
          style={{ marginBottom: "0.65rem", fontSize: "0.85rem" }}
        >
          <strong>Último ciclo:</strong> revisión de salidas; <strong>no se evaluaron entradas</strong> en esta pasada.
          El auto-run sigue activo. Los datos de estrategia abajo corresponden a la última búsqueda de entradas.
        </div>
      ) : null}

      {paperSchedule ? (
        <div
          className="crypto-testnet-mini-grid crypto-testnet-mini-grid--dense"
          style={{ marginBottom: "0.75rem" }}
        >
          <div className="crypto-testnet-kpi">
            <span className="crypto-testnet-kpi-label">Última revisión salidas</span>
            <span className="crypto-testnet-kpi-value" style={{ fontSize: "0.78rem", fontWeight: 500 }}>
              {paperSchedule.lastExitsReviewAt ? fmtIsoLocalShort(paperSchedule.lastExitsReviewAt) : "—"}
            </span>
          </div>
          <div className="crypto-testnet-kpi">
            <span className="crypto-testnet-kpi-label">Próxima revisión salidas</span>
            <span className="crypto-testnet-kpi-value" style={{ fontSize: "0.78rem", fontWeight: 500 }}>
              {paperSchedule.nextExitsReviewAt ? fmtIsoLocalShort(paperSchedule.nextExitsReviewAt) : "—"}
            </span>
          </div>
          <div className="crypto-testnet-kpi">
            <span className="crypto-testnet-kpi-label">Intervalo salidas</span>
            <span className="crypto-testnet-kpi-value">{fmtIntervalMinutes(paperSchedule.exitsIntervalSeconds)}</span>
          </div>
          <div className="crypto-testnet-kpi">
            <span className="crypto-testnet-kpi-label">Última evaluación entradas</span>
            <span className="crypto-testnet-kpi-value" style={{ fontSize: "0.78rem", fontWeight: 500 }}>
              {paperSchedule.lastStrategyRunAt ? fmtIsoLocalShort(paperSchedule.lastStrategyRunAt) : "—"}
            </span>
          </div>
          <div className="crypto-testnet-kpi">
            <span className="crypto-testnet-kpi-label">Próxima evaluación entradas</span>
            <span className="crypto-testnet-kpi-value" style={{ fontSize: "0.78rem", fontWeight: 500 }}>
              {paperSchedule.nextStrategyRunAt ? fmtIsoLocalShort(paperSchedule.nextStrategyRunAt) : "—"}
            </span>
          </div>
          <div className="crypto-testnet-kpi">
            <span className="crypto-testnet-kpi-label">Intervalo entradas</span>
            <span className="crypto-testnet-kpi-value">{fmtIntervalMinutes(paperSchedule.strategyIntervalSeconds)}</span>
          </div>
        </div>
      ) : null}

      <div
        className="crypto-testnet-mini-grid crypto-testnet-mini-grid--dense"
        style={{ marginBottom: "0.65rem" }}
      >
        <div className="crypto-testnet-kpi">
          <span className="crypto-testnet-kpi-label">Inicio ciclo</span>
          <span className="crypto-testnet-kpi-value" style={{ fontSize: "0.8rem", fontWeight: 500 }}>
            {startedAt ? fmtIsoLocalShort(startedAt) : "—"}
          </span>
        </div>
        <div className="crypto-testnet-kpi">
          <span className="crypto-testnet-kpi-label">Fin ciclo</span>
          <span className="crypto-testnet-kpi-value" style={{ fontSize: "0.8rem", fontWeight: 500 }}>
            {finishedAt ? fmtIsoLocalShort(finishedAt) : "—"}
          </span>
        </div>
        <div className="crypto-testnet-kpi">
          <span className="crypto-testnet-kpi-label">Duración</span>
          <span className="crypto-testnet-kpi-value">{fmtDurationMs(durationMs)}</span>
        </div>
        {showEntryStats ? (
          <>
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">Evaluados</span>
              <span className="crypto-testnet-kpi-value">{summary!.evaluated_count}</span>
            </div>
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">Rechazados</span>
              <span className="crypto-testnet-kpi-value">{summary!.rejected_count}</span>
            </div>
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">Aceptados</span>
              <span className="crypto-testnet-kpi-value">{summary!.accepted_count}</span>
            </div>
          </>
        ) : null}
      </div>

      {showScanProbe ? (
        <div
          className="crypto-testnet-note crypto-testnet-note--blue"
          style={{ marginBottom: "0.65rem", fontSize: "0.82rem" }}
        >
          <strong>Diagnóstico de escaneo</strong> (evaluados de filtros = 0 en este ciclo)
          {scan.evaluated_count_note || lastScanDebug?.evaluated_count_note ? (
            <p className="msg-muted" style={{ margin: "0.35rem 0 0", fontSize: "0.78rem" }}>
              {scan.evaluated_count_note ?? lastScanDebug?.evaluated_count_note}
            </p>
          ) : null}
          {scan.scan_scenario ? (
            <p style={{ margin: "0.45rem 0 0", fontSize: "0.82rem" }}>
              <strong>Escenario {scan.scan_scenario}</strong>
              {scan.scan_scenario_label ? ` — ${scan.scan_scenario_label}` : null}
              {scan.scan_scenario_detail ? (
                <span className="msg-muted" style={{ display: "block", marginTop: "0.2rem", fontSize: "0.78rem" }}>
                  {scan.scan_scenario_detail}
                  {SCAN_SCENARIO_HINTS[scan.scan_scenario] ? ` ${SCAN_SCENARIO_HINTS[scan.scan_scenario]}` : ""}
                </span>
              ) : null}
            </p>
          ) : null}
          {scanAnomaly ? (
            <p className="msg-error" style={{ margin: "0.45rem 0 0", fontSize: "0.82rem" }}>
              Watchlist con {scan.watchlist_count} símbolos pero escaneados = 0.
              {scan.scan_error
                ? ` ${scan.scan_error}`
                : " El scanner no produjo filas; revisá logs [CRYPTO_BOT_SCAN_DEBUG] en el servidor."}
            </p>
          ) : null}
          <div
            className="crypto-testnet-mini-grid crypto-testnet-mini-grid--dense"
            style={{ marginTop: "0.5rem" }}
          >
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">Timeframe</span>
              <span className="crypto-testnet-kpi-value">{scan.timeframe ?? "—"}</span>
            </div>
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">Tipo scan</span>
              <span className="crypto-testnet-kpi-value" style={{ fontSize: "0.75rem", fontWeight: 500 }}>
                {scan.scan_type ?? "—"}
              </span>
            </div>
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">Watchlist</span>
              <span className="crypto-testnet-kpi-value">{scan.watchlist_count ?? "—"} símbolos</span>
            </div>
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">Escaneados</span>
              <span className="crypto-testnet-kpi-value">{scan.scan_count ?? "—"}</span>
            </div>
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">OK / error scan</span>
              <span className="crypto-testnet-kpi-value">
                {scan.scan_ok_count ?? "—"} / {scan.scan_error_count ?? "—"}
              </span>
            </div>
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">Candidatos señal</span>
              <span className="crypto-testnet-kpi-value">{scan.candidates_count ?? "—"}</span>
            </div>
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">Duración scan</span>
              <span className="crypto-testnet-kpi-value">{fmtDurationMs(scan.scan_duration_ms)}</span>
            </div>
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">compra_potencial</span>
              <span className="crypto-testnet-kpi-value">{scan.rows_signal_compra_potencial ?? "—"}</span>
            </div>
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">Otras señales</span>
              <span className="crypto-testnet-kpi-value">{scan.rows_signal_other ?? "—"}</span>
            </div>
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">Sin signal</span>
              <span className="crypto-testnet-kpi-value">{scan.rows_missing_signal ?? "—"}</span>
            </div>
          </div>
          {(scan.unique_signals_detected?.length ?? 0) > 0 ? (
            <p className="msg-muted" style={{ margin: "0.45rem 0 0", fontSize: "0.78rem" }}>
              <strong>Señales en filas OK:</strong> {scan.unique_signals_detected!.join(", ")}
              {scan.signal_counts && Object.keys(scan.signal_counts).length > 0 ? (
                <span style={{ display: "block", marginTop: "0.2rem" }}>
                  Conteo:{" "}
                  {Object.entries(scan.signal_counts)
                    .map(([k, n]) => `${k}=${n}`)
                    .join(", ")}
                </span>
              ) : null}
            </p>
          ) : null}
          {(scan.sample_rows?.length ?? 0) > 0 ? (
            <div style={{ marginTop: "0.45rem", overflowX: "auto" }}>
              <p className="msg-muted" style={{ margin: "0 0 0.35rem", fontSize: "0.78rem" }}>
                <strong>sample_rows</strong> (entrada: campo{" "}
                {String(
                  (scan.entry_candidate_filter as { field?: string } | undefined)?.field ?? "signal",
                )}{" "}
                ={" "}
                {String(
                  (scan.entry_candidate_filter as { expected_exact?: string } | undefined)
                    ?.expected_exact ?? "compra_potencial",
                )}
                )
              </p>
              <table className="crypto-testnet-table" style={{ fontSize: "0.72rem", width: "100%" }}>
                <thead>
                  <tr>
                    <th>Símbolo</th>
                    <th>signal</th>
                    <th>action</th>
                    <th>score</th>
                    <th>trend</th>
                    <th>price</th>
                  </tr>
                </thead>
                <tbody>
                  {scan.sample_rows!.map((row, i) => (
                    <tr key={`${String(row.symbol)}-${i}`}>
                      <td>{String(row.symbol ?? "—")}</td>
                      <td>{String(row.signal ?? "—")}</td>
                      <td>{String(row.action ?? "—")}</td>
                      <td>{row.score != null ? String(row.score) : "—"}</td>
                      <td>{String(row.trend ?? "—")}</td>
                      <td>{row.price != null ? String(row.price) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <p className="msg-muted" style={{ margin: "0.45rem 0 0" }}>
            <strong>Muestra watchlist:</strong>{" "}
            {(scan.watchlist_sample?.length ?? 0) > 0
              ? scan.watchlist_sample!.join(", ")
              : (scan.first_symbols_sample?.length ?? 0) > 0
                ? scan.first_symbols_sample!.join(", ")
                : "—"}
          </p>
          {scan.scan_error && !scanAnomaly ? (
            <p className="msg-error" style={{ margin: "0.35rem 0 0", fontSize: "0.8rem" }}>
              Error scan: {scan.scan_error}
            </p>
          ) : null}
          <p className="msg-muted" style={{ margin: "0.35rem 0 0" }}>
            {SCAN_DIAGNOSIS_HINTS[scan.scan_diagnosis ?? primaryReason ?? ""] ??
              SCAN_DIAGNOSIS_HINTS[primaryReason ?? ""] ??
              primaryReasonLabel(primaryReason)}
          </p>
          {lastScanDebug ? (
            <details style={{ marginTop: "0.45rem" }}>
              <summary className="msg-muted" style={{ cursor: "pointer", fontSize: "0.78rem" }}>
                last_scan_debug (API)
              </summary>
              <pre
                className="msg-muted"
                style={{
                  margin: "0.35rem 0 0",
                  fontSize: "0.72rem",
                  overflow: "auto",
                  maxHeight: "12rem",
                }}
              >
                {JSON.stringify(lastScanDebug, null, 2)}
              </pre>
            </details>
          ) : null}
        </div>
      ) : null}

      {strategyEmptyEvaluated ? (
        <p className="msg-error" style={{ fontSize: "0.85rem", marginBottom: "0.65rem" }}>
          La estrategia corrió en este ciclo pero no devolvió candidatos evaluados en la lista de filtros (revisá
          logs del servidor).
        </p>
      ) : null}

      {showStrategyDiagnostics ? (
        <>
          <div
            className="crypto-testnet-note"
            style={{
              marginBottom: "0.65rem",
              fontSize: "0.82rem",
              borderColor: healthOk ? undefined : "var(--danger)",
            }}
          >
            <strong>Motivo principal (última estrategia):</strong> {primaryReasonLabel(primaryReason)}
            {summary && summary.evaluated_count === 0 && primaryReason === "no_opportunity" ? (
              <span className="msg-muted" style={{ display: "block", marginTop: "0.25rem" }}>
                El escaneo corrió; no hubo señales compra_potencial en la watchlist.
              </span>
            ) : null}
            {summary && summary.evaluated_count > 0 && summary.accepted_count === 0 && primaryReason !== "opened" ? (
              <span className="msg-muted" style={{ display: "block", marginTop: "0.25rem" }}>
                El bot está activo y filtró candidatos; ninguno pasó todas las reglas.
              </span>
            ) : null}
          </div>

          {chips.length > 0 ? (
            <div style={{ marginBottom: "0.65rem" }}>
              <div className="msg-muted" style={{ fontSize: "0.78rem", marginBottom: "0.35rem", fontWeight: 600 }}>
                Rechazos (última estrategia)
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.35rem" }}>
                {chips.map((c) => (
                  <span
                    key={c.key}
                    className="radar-badge radar-badge--conv-media"
                    style={{ fontSize: "0.75rem", padding: "0.2rem 0.5rem" }}
                  >
                    {c.label}: {c.count}
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          {bestRejected ? (
            <div
              className="crypto-testnet-note crypto-testnet-note--blue"
              style={{ marginBottom: "0.5rem", fontSize: "0.82rem" }}
            >
              <strong>Mejor candidato rechazado:</strong> {bestRejected.symbol}
              {bestRejected.score != null ? ` · score ${bestRejected.score}` : ""}
              {bestRejected.signal ? ` · ${bestRejected.signal}` : ""}
              <span className="msg-muted" style={{ display: "block", marginTop: "0.2rem" }}>
                {primaryReasonLabel(bestRejected.reason)}
              </span>
            </div>
          ) : null}

          {entryCandidate ? (
            <div className="crypto-testnet-note" style={{ fontSize: "0.82rem" }}>
              <strong>Última entrada ejecutada:</strong> {entryCandidate.symbol}
              {entryCandidate.score != null ? ` · score ${entryCandidate.score}` : ""}
              {entryCandidate.signal ? ` · ${entryCandidate.signal}` : ""}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
