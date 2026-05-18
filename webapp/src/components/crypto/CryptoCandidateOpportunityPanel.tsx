import type { CryptoCandidateOpportunity } from "@/services/api";

type EvaluatedDiagnosticRow = {
  symbol?: string | null;
  signal?: string | null;
  score?: number | null;
  status?: string;
  reason?: string;
  setup_type?: string | null;
  rsi?: number | null;
  rsi_context?: string | null;
  macd_context?: string | null;
  trend_context?: string | null;
  volume_context?: string | null;
  btc_context?: string | null;
  entry_eligible?: boolean;
  scan_acceptance_reason?: string | null;
  evaluation_status?: string | null;
  evaluation_reason?: string | null;
  evaluation_outcome?: string | null;
};

const SETUP_LABELS: Record<string, string> = {
  pullback: "Pullback",
  rebound: "Rebote",
  momentum_intraday: "Momentum intradía",
  reversal_controlled: "Reversal controlado",
};

function setupLabel(setup: string | null | undefined): string {
  if (!setup) return "—";
  return SETUP_LABELS[setup] ?? setup;
}

function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}

function entryEligibleLabel(v: boolean | undefined): string {
  if (v === true) return "Sí";
  if (v === false) return "No";
  return "—";
}

function evaluationStatusLabel(st: string | null | undefined): string {
  const s = (st || "").toLowerCase();
  if (s === "accepted" || s === "selected") return "Aceptado";
  if (s === "rejected") return "Rechazado";
  if (s === "skipped") return "Omitido";
  return st || "—";
}

type Props = {
  opportunities: CryptoCandidateOpportunity[];
  /** Si true, solo muestra el bloque cuando hay filas */
  hideWhenEmpty?: boolean;
  className?: string;
};

export function CryptoCandidateOpportunityPanel({
  opportunities,
  hideWhenEmpty = true,
  className,
}: Props) {
  if (hideWhenEmpty && opportunities.length === 0) return null;

  return (
    <div className={className} style={{ marginTop: "0.75rem" }}>
      <h4
        className="dashboard-section-title"
        style={{ margin: "0 0 0.5rem", fontSize: "0.95rem" }}
      >
        Por qué apareció esta oportunidad
      </h4>
      <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
        {opportunities.map((opp) => (
          <article
            key={opp.symbol}
            className="crypto-testnet-note crypto-testnet-note--blue"
            style={{ padding: "0.65rem 0.75rem", fontSize: "0.82rem" }}
          >
            <p style={{ margin: "0 0 0.45rem", fontWeight: 600 }}>
              {opp.symbol}
              {opp.setup_type ? (
                <span className="msg-muted" style={{ fontWeight: 400 }}>
                  {" "}
                  · {setupLabel(opp.setup_type)}
                </span>
              ) : null}
              {opp.score != null ? (
                <span style={{ marginLeft: "0.35rem" }}>· score {fmtNum(opp.score, 1)}</span>
              ) : null}
            </p>
            <dl
              style={{
                margin: 0,
                display: "grid",
                gridTemplateColumns: "minmax(7rem, auto) 1fr",
                gap: "0.2rem 0.65rem",
                fontSize: "0.8rem",
              }}
            >
              <dt className="msg-muted">Setup</dt>
              <dd style={{ margin: 0 }}>{setupLabel(opp.setup_type)}</dd>
              <dt className="msg-muted">RSI</dt>
              <dd style={{ margin: 0 }}>{fmtNum(opp.rsi ?? opp.rsi_14)}</dd>
              <dt className="msg-muted">RSI (contexto)</dt>
              <dd style={{ margin: 0 }}>{opp.rsi_context ?? "—"}</dd>
              <dt className="msg-muted">MACD</dt>
              <dd style={{ margin: 0 }}>{opp.macd_context ?? "—"}</dd>
              <dt className="msg-muted">Tendencia</dt>
              <dd style={{ margin: 0 }}>{opp.trend_context ?? "—"}</dd>
              <dt className="msg-muted">Volumen</dt>
              <dd style={{ margin: 0 }}>{opp.volume_context ?? "—"}</dd>
              <dt className="msg-muted">BTC</dt>
              <dd style={{ margin: 0 }}>{opp.btc_context ?? "—"}</dd>
              <dt className="msg-muted">entry_eligible</dt>
              <dd style={{ margin: 0 }}>{entryEligibleLabel(opp.entry_eligible)}</dd>
              <dt className="msg-muted">Por qué candidato</dt>
              <dd style={{ margin: 0 }}>{opp.scan_acceptance_reason ?? "—"}</dd>
              {opp.evaluation_status || opp.evaluation_outcome ? (
                <>
                  <dt className="msg-muted">Filtros de entrada</dt>
                  <dd style={{ margin: 0 }}>
                    {evaluationStatusLabel(opp.evaluation_status)}
                    {opp.evaluation_outcome ? ` — ${opp.evaluation_outcome}` : ""}
                    {!opp.evaluation_outcome && opp.evaluation_reason
                      ? ` — ${opp.evaluation_reason}`
                      : ""}
                  </dd>
                </>
              ) : null}
            </dl>
          </article>
        ))}
      </div>
    </div>
  );
}

/** Combina oportunidades del scan con el resultado de filtros post-scan (ejecutar / testnet). */
export function mergeCandidateOpportunitiesWithEvaluated(
  opportunities: CryptoCandidateOpportunity[] | undefined,
  candidates: CryptoCandidateOpportunity[] | undefined,
  evaluated: EvaluatedDiagnosticRow[] | undefined,
): CryptoCandidateOpportunity[] {
  const base =
    opportunities && opportunities.length > 0
      ? opportunities
      : candidates && candidates.length > 0
        ? candidates
        : [];
  if (base.length === 0 && evaluated?.length) {
    return evaluated
      .filter((e) => e.symbol)
      .map((e) => ({
        symbol: String(e.symbol),
        setup_type: e.setup_type ?? null,
        score: e.score ?? null,
        rsi: e.rsi ?? null,
        rsi_context: e.rsi_context ?? null,
        macd_context: e.macd_context ?? null,
        trend_context: e.trend_context ?? null,
        volume_context: e.volume_context ?? null,
        btc_context: e.btc_context ?? null,
        entry_eligible: e.entry_eligible,
        scan_acceptance_reason: e.scan_acceptance_reason ?? null,
        evaluation_status: e.evaluation_status ?? e.status ?? null,
        evaluation_reason: e.evaluation_reason ?? e.reason ?? null,
        evaluation_outcome: e.evaluation_outcome ?? null,
      }));
  }
  if (!evaluated?.length || base.length === 0) return base;

  const bySym = new Map(
    evaluated
      .filter((e) => e.symbol)
      .map((e) => [String(e.symbol).toUpperCase(), e]),
  );

  return base.map((opp) => {
    const ev = bySym.get(String(opp.symbol).toUpperCase());
    if (!ev) return opp;
    const status = ev.evaluation_status ?? ev.status;
    const reason = ev.evaluation_reason ?? ev.reason;
    const outcome =
      ev.evaluation_outcome ??
      (status && reason
        ? `${status}: ${reason}`
        : status
          ? String(status)
          : reason
            ? String(reason)
            : null);
    return {
      ...opp,
      evaluation_status: status ?? opp.evaluation_status,
      evaluation_reason: reason ?? opp.evaluation_reason,
      evaluation_outcome: outcome ?? opp.evaluation_outcome,
    };
  });
}
