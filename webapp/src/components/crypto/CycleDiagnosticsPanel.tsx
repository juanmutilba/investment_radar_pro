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
}: CycleDiagnosticsPanelProps) {
  const hasTiming = Boolean(startedAt || finishedAt);
  const hasSummary = Boolean(summary && (summary.evaluated_count > 0 || primaryReason));
  const chips = rejectionChips(summary?.reasons);

  if (!hasTiming && !hasSummary && !bestRejected && !entryCandidate) {
    return (
      <p className="msg-muted" style={{ margin: "0.75rem 0 0", fontSize: "0.85rem" }}>
        {emptyHint}
      </p>
    );
  }

  const healthOk =
    !primaryReason ||
    primaryReason === "opened" ||
    (summary && summary.evaluated_count > 0) ||
    Boolean(bestRejected);

  return (
    <div className="crypto-cycle-diagnostics" style={{ marginTop: "0.85rem" }}>
      <h4 className="msg-muted" style={{ margin: "0 0 0.5rem", fontSize: "0.88rem", fontWeight: 600 }}>
        Último ciclo
        {phases && phases.length > 0 ? (
          <span className="msg-muted" style={{ fontWeight: 400, marginLeft: "0.35rem", fontSize: "0.8rem" }}>
            ({phases.join(" + ")})
          </span>
        ) : null}
      </h4>
      {phases?.length === 1 && phases[0] === "exits" ? (
        <p className="msg-muted" style={{ margin: "0 0 0.5rem", fontSize: "0.8rem" }}>
          Este ciclo solo revisó salidas. Los datos de entrada abajo son del último ciclo que buscó entradas.
        </p>
      ) : null}

      <div
        className="crypto-testnet-mini-grid crypto-testnet-mini-grid--dense"
        style={{ marginBottom: "0.65rem" }}
      >
        <div className="crypto-testnet-kpi">
          <span className="crypto-testnet-kpi-label">Inicio</span>
          <span className="crypto-testnet-kpi-value" style={{ fontSize: "0.8rem", fontWeight: 500 }}>
            {startedAt ? fmtIsoLocalShort(startedAt) : "—"}
          </span>
        </div>
        <div className="crypto-testnet-kpi">
          <span className="crypto-testnet-kpi-label">Fin</span>
          <span className="crypto-testnet-kpi-value" style={{ fontSize: "0.8rem", fontWeight: 500 }}>
            {finishedAt ? fmtIsoLocalShort(finishedAt) : "—"}
          </span>
        </div>
        <div className="crypto-testnet-kpi">
          <span className="crypto-testnet-kpi-label">Duración</span>
          <span className="crypto-testnet-kpi-value">{fmtDurationMs(durationMs)}</span>
        </div>
        {summary ? (
          <>
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">Evaluados</span>
              <span className="crypto-testnet-kpi-value">{summary.evaluated_count}</span>
            </div>
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">Rechazados</span>
              <span className="crypto-testnet-kpi-value">{summary.rejected_count}</span>
            </div>
            <div className="crypto-testnet-kpi">
              <span className="crypto-testnet-kpi-label">Aceptados</span>
              <span className="crypto-testnet-kpi-value">{summary.accepted_count}</span>
            </div>
          </>
        ) : null}
      </div>

      <div
        className="crypto-testnet-note"
        style={{
          marginBottom: "0.65rem",
          fontSize: "0.82rem",
          borderColor: healthOk ? undefined : "var(--danger)",
        }}
      >
        <strong>Motivo principal:</strong> {primaryReasonLabel(primaryReason)}
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
            Rechazos
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
        <div className="crypto-testnet-note crypto-testnet-note--blue" style={{ marginBottom: "0.5rem", fontSize: "0.82rem" }}>
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
          <strong>Última entrada ejecutada / seleccionada:</strong> {entryCandidate.symbol}
          {entryCandidate.score != null ? ` · score ${entryCandidate.score}` : ""}
          {entryCandidate.signal ? ` · ${entryCandidate.signal}` : ""}
        </div>
      ) : null}
    </div>
  );
}