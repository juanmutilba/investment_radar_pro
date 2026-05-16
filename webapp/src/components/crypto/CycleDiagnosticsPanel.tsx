export type CycleSummaryShape = {
  evaluated_count: number;
  accepted_count: number;
  rejected_count: number;
  skipped_count?: number;
  reasons: Record<string, number>;
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

  const strategyEmptyEvaluated =
    strategyRanThisCycle &&
    summary !== null &&
    summary !== undefined &&
    summary.evaluated_count === 0 &&
    primaryReason !== "no_opportunity";

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

      {strategyEmptyEvaluated ? (
        <p className="msg-error" style={{ fontSize: "0.85rem", marginBottom: "0.65rem" }}>
          La estrategia corrió en este ciclo pero no devolvió candidatos evaluados (revisá logs del servidor o el
          escaneo de watchlist).
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
