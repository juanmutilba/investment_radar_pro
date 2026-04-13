import { useCallback, useEffect, useState } from "react";
import {
  fetchLatestSummary,
  runScan,
  type LatestSummary,
} from "@/services/api";

type ScanPhase = "idle" | "loading" | "success" | "error";

export function DashboardPage() {
  const [summary, setSummary] = useState<LatestSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [scanPhase, setScanPhase] = useState<ScanPhase>("idle");
  const [scanMessage, setScanMessage] = useState<string | null>(null);

  const loadSummary = useCallback(() => {
    return fetchLatestSummary()
      .then((s) => {
        setSummary(s);
        setSummaryError(null);
      })
      .catch((e: unknown) => {
        setSummaryError(
          e instanceof Error ? e.message : "Error al cargar el resumen",
        );
      });
  }, []);

  useEffect(() => {
    void loadSummary();
  }, [loadSummary]);

  const handleRunScan = useCallback(async () => {
    setScanMessage(null);
    setScanPhase("loading");
    try {
      const { summary: next } = await runScan();
      setSummary(next);
      setSummaryError(null);
      setScanPhase("success");
      setScanMessage("Scan completado. Datos actualizados.");
    } catch (e: unknown) {
      setScanPhase("error");
      setScanMessage(
        e instanceof Error ? e.message : "Error al ejecutar el scan",
      );
    }
  }, []);

  const totalAlerts =
    summary !== null
      ? summary.usa_alerts_count + summary.arg_alerts_count
      : null;

  return (
    <>
      <h1 className="page-title">Dashboard</h1>
      <p className="page-desc">
        Vista general del radar. Ejecutá el scan aquí; en Acciones USA /
        Argentina solo se visualizan y refrescan los datos ya generados.
      </p>

      <div className="dashboard__scan-row">
        <button
          type="button"
          className="radar-refresh-btn"
          disabled={scanPhase === "loading"}
          onClick={() => void handleRunScan()}
        >
          {scanPhase === "loading" ? "Ejecutando…" : "Ejecutar scan"}
        </button>
        {scanPhase === "success" && scanMessage !== null ? (
          <span className="msg-success">{scanMessage}</span>
        ) : null}
        {scanPhase === "error" && scanMessage !== null ? (
          <span className="msg-error">{scanMessage}</span>
        ) : null}
      </div>

      {summaryError !== null ? (
        <p className="msg-error" style={{ marginTop: 0 }}>
          {summaryError}
        </p>
      ) : null}

      <div className="grid-3">
        <div className="stat">
          <div className="stat__label">Radar USA</div>
          <div className="stat__value">
            {summary !== null ? summary.usa_tickers_count : "—"}
          </div>
          <div className="msg-muted" style={{ marginTop: "0.35rem" }}>
            tickers en último export
          </div>
        </div>
        <div className="stat">
          <div className="stat__label">Radar Argentina</div>
          <div className="stat__value">
            {summary !== null ? summary.arg_tickers_count : "—"}
          </div>
          <div className="msg-muted" style={{ marginTop: "0.35rem" }}>
            tickers en último export
          </div>
        </div>
        <div className="stat">
          <div className="stat__label">Alertas (último export)</div>
          <div className="stat__value">
            {totalAlerts !== null ? totalAlerts : "—"}
          </div>
          <div className="msg-muted" style={{ marginTop: "0.35rem" }}>
            USA + Argentina · Ver módulo Alertas
          </div>
        </div>
      </div>
      <div className="card">
        <h2>Datos</h2>
        <p className="msg-muted" style={{ margin: 0 }}>
          Las tarjetas usan <code>GET /latest-summary</code>. Tras un scan
          exitoso, el resumen se actualiza automáticamente.
        </p>
      </div>
    </>
  );
}
