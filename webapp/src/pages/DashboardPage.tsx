import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  fetchLatestSummary,
  runScan,
  type LatestSummary,
  type ScanMetrics,
} from "@/services/api";

type ScanPhase = "idle" | "loading" | "success" | "error";

function fileBasename(path: string): string {
  const normalized = path.replace(/\\/g, "/");
  const i = normalized.lastIndexOf("/");
  return i >= 0 ? normalized.slice(i + 1) : normalized;
}

export function DashboardPage() {
  const [summary, setSummary] = useState<LatestSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [scanPhase, setScanPhase] = useState<ScanPhase>("idle");
  const [scanMessage, setScanMessage] = useState<string | null>(null);
  const [lastScan, setLastScan] = useState<ScanMetrics | null>(null);

  const loadSummary = useCallback(() => {
    return fetchLatestSummary()
      .then((s) => {
        setSummary(s);
        setLastScan(s?.last_scan ?? null);
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
      const r = await runScan();
      const next = r.summary;
      setSummary(next);
      setLastScan(r.scan_metrics ?? next.last_scan ?? null);
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

  const scanStatusText =
    scanPhase === "loading"
      ? "Ejecutando"
      : scanPhase === "success"
        ? "Éxito"
        : scanPhase === "error"
          ? "Error"
          : "Listo";

  return (
    <>
      <h1 className="page-title">Dashboard</h1>
      <p className="page-desc">
        Centro operativo del radar: ejecutá el scan, revisá totales del último
        export y accedé a los módulos de mercado.
      </p>

      <div className="card dashboard-scan-card">
        <div className="dashboard-scan-card__head">
          <h2 className="dashboard-scan-card__title">Scan del radar</h2>
          <span
            className={`dashboard-scan__pill dashboard-scan__pill--${scanPhase}`}
            aria-live="polite"
          >
            {scanStatusText}
          </span>
        </div>
        <p className="dashboard-scan-card__lede msg-muted">
          Ejecutá el pipeline completo y generá el Excel. Las vistas de acciones
          solo leen el último export.
        </p>
        <div className="dashboard-scan-card__actions">
          <button
            type="button"
            className="radar-refresh-btn"
            disabled={scanPhase === "loading"}
            onClick={() => void handleRunScan()}
          >
            {scanPhase === "loading" ? "Ejecutando…" : "Ejecutar scan"}
          </button>
        </div>

        {scanPhase === "success" && scanMessage !== null ? (
          <div
            className="dashboard-scan__result dashboard-scan__result--success"
            role="status"
            aria-live="polite"
          >
            <strong>Resultado:</strong> {scanMessage}
          </div>
        ) : null}
        {scanPhase === "error" && scanMessage !== null ? (
          <div
            className="dashboard-scan__result dashboard-scan__result--error"
            role="alert"
          >
            <strong>No se completó el scan.</strong> {scanMessage}
          </div>
        ) : null}

        {summary?.file ? (
          <p className="dashboard-scan__export msg-muted">
            <span className="dashboard-scan__export-label">Último export</span>{" "}
            <code className="dashboard-scan__export-path">{fileBasename(summary.file)}</code>
          </p>
        ) : null}

        <h3 className="dashboard-section-title" style={{ marginTop: "1rem", marginBottom: "0.5rem" }}>
          Último scan
        </h3>
        <div className="dashboard-stats-grid">
          <div className="stat dashboard-stat">
            <div className="stat__label">Duración total</div>
            <div className="stat__value">{lastScan ? `${lastScan.total_scan_seconds.toFixed(1)}s` : "—"}</div>
            <div className="msg-muted dashboard-stat__hint">USA + ARG + CEDEAR + alertas</div>
          </div>
          <div className="stat dashboard-stat">
            <div className="stat__label">USA</div>
            <div className="stat__value">{lastScan ? `${lastScan.usa_scan_seconds.toFixed(1)}s` : "—"}</div>
            <div className="msg-muted dashboard-stat__hint">
              {lastScan ? `${lastScan.usa_total_activos} activos · ${lastScan.usa_alertas} alertas` : "—"}
            </div>
          </div>
          <div className="stat dashboard-stat">
            <div className="stat__label">Argentina</div>
            <div className="stat__value">{lastScan ? `${lastScan.arg_scan_seconds.toFixed(1)}s` : "—"}</div>
            <div className="msg-muted dashboard-stat__hint">
              {lastScan ? `${lastScan.arg_total_activos} activos · ${lastScan.arg_alertas} alertas` : "—"}
            </div>
          </div>
          <div className="stat dashboard-stat">
            <div className="stat__label">CEDEAR</div>
            <div className="stat__value">{lastScan ? `${lastScan.cedear_scan_seconds.toFixed(1)}s` : "—"}</div>
            <div className="msg-muted dashboard-stat__hint">
              {lastScan ? `${lastScan.cedear_total_activos} activos · ${lastScan.cedear_alertas} con señal` : "—"}
            </div>
          </div>
          <div className="stat dashboard-stat">
            <div className="stat__label">Alertas (pipeline)</div>
            <div className="stat__value">{lastScan ? `${lastScan.alerts_seconds.toFixed(1)}s` : "—"}</div>
            <div className="msg-muted dashboard-stat__hint">
              {lastScan && lastScan.summary_seconds !== null
                ? `Resumen Excel: ${lastScan.summary_seconds.toFixed(1)}s`
                : "—"}
            </div>
          </div>
        </div>
        {lastScan?.scan_finished_at ? (
          <p className="msg-muted" style={{ marginBottom: 0, marginTop: "0.75rem" }}>
            Finalizado: <code>{lastScan.scan_finished_at}</code>
          </p>
        ) : null}

        {summaryError !== null ? (
          <p className="msg-error" style={{ marginBottom: 0 }}>
            {summaryError}
          </p>
        ) : null}
      </div>

      <div className="card">
        <h2>Accesos rápidos</h2>
        <nav className="dashboard-quick" aria-label="Accesos rápidos">
          <Link to="/acciones-usa" className="dashboard-quick__link">
            Acciones USA
          </Link>
          <Link to="/acciones-argentina" className="dashboard-quick__link">
            Acciones Argentina
          </Link>
          <Link to="/alertas" className="dashboard-quick__link">
            Alertas
          </Link>
        </nav>
        <p className="msg-muted" style={{ margin: "0.85rem 0 0", fontSize: "0.82rem" }}>
          Métricas del último scan: <code>GET /latest-summary</code> (campo <code>last_scan</code>).
        </p>
      </div>
    </>
  );
}
