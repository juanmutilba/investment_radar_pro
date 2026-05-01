import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  fetchLatestSummary,
  getScanStatus,
  triggerScanRun,
  type LatestSummary,
  type ScanMetrics,
  type ScanStatus,
} from "@/services/api";

type ScanPhase = "idle" | "loading" | "success" | "error";

function fileBasename(path: string): string {
  const normalized = path.replace(/\\/g, "/");
  const i = normalized.lastIndexOf("/");
  return i >= 0 ? normalized.slice(i + 1) : normalized;
}

function dashboardScanPhase(scanStatus: ScanStatus | null): ScanPhase {
  if (!scanStatus) return "idle";
  if (scanStatus.status === "running") return "loading";
  if (scanStatus.status === "success") return "success";
  if (scanStatus.status === "error") return "error";
  return "idle";
}

export function DashboardPage() {
  const [summary, setSummary] = useState<LatestSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null);
  const [scanMessage, setScanMessage] = useState<string | null>(null);
  const [lastScan, setLastScan] = useState<ScanMetrics | null>(null);
  const [isTriggering, setIsTriggering] = useState(false);

  const scanPhase = dashboardScanPhase(scanStatus);

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

  useEffect(() => {
    let cancelled = false;
    getScanStatus()
      .then((s) => {
        if (!cancelled) setScanStatus(s);
      })
      .catch(() => null);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (scanStatus?.status !== "running") return;
    const id = window.setInterval(() => {
      getScanStatus()
        .then((s) => {
          setScanStatus(s);
          if (s.status === "success") {
            setScanMessage("Scan ejecutado correctamente.");
            void loadSummary();
          } else if (s.status === "error") {
            setScanMessage(
              s.error ? `No se completó el scan: ${s.error}` : "No se completó el scan.",
            );
          }
        })
        .catch(() => null);
    }, 4000);
    return () => window.clearInterval(id);
  }, [scanStatus?.status, loadSummary]);

  const handleRunScan = useCallback(() => {
    setScanMessage(null);
    setIsTriggering(true);
    triggerScanRun()
      .then((s) => {
        setScanStatus(s);
        if (s.status === "running") {
          /* el polling actualiza mensaje y resumen */
        } else if (s.status === "success") {
          setScanMessage("Scan ejecutado correctamente.");
          void loadSummary();
        } else if (s.status === "error") {
          setScanMessage(
            s.error ? `No se completó el scan: ${s.error}` : "No se completó el scan.",
          );
        }
      })
      .catch((e: unknown) => {
        setScanMessage(e instanceof Error ? e.message : "Error al iniciar el scan");
      })
      .finally(() => setIsTriggering(false));
  }, [loadSummary]);

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
            disabled={scanStatus?.status === "running" || isTriggering}
            onClick={() => handleRunScan()}
          >
            {scanStatus?.status === "running" ? "Ejecutando…" : "Ejecutar scan"}
          </button>
        </div>

        {scanStatus?.status === "running" ? (
          <div style={{ marginTop: "0.85rem", padding: "0.75rem 0 0" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              <div
                style={{
                  flex: 1,
                  height: 8,
                  background: "var(--border)",
                  borderRadius: 4,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    width: `${Math.min(100, Math.max(0, Math.round(Number(scanStatus.progress_pct) || 0)))}%`,
                    height: "100%",
                    background: "var(--accent)",
                    transition: "width 0.35s ease",
                  }}
                />
              </div>
              <span className="msg-muted" style={{ fontSize: "0.85rem", minWidth: "2.75rem", textAlign: "right" }}>
                {Math.min(100, Math.max(0, Math.round(Number(scanStatus.progress_pct) || 0)))}%
              </span>
            </div>
            <p className="msg-muted" style={{ margin: "0.45rem 0 0", fontSize: "0.82rem" }}>
              {scanStatus.progress_message ?? "Ejecutando scan…"}
            </p>
          </div>
        ) : null}

        {scanPhase === "success" && scanMessage !== null ? (
          <div
            className="dashboard-scan__result dashboard-scan__result--success"
            role="status"
            aria-live="polite"
            style={{ marginTop: "0.85rem" }}
          >
            <strong>Resultado:</strong> {scanMessage}
          </div>
        ) : null}
        {scanPhase === "error" && scanMessage !== null ? (
          <div
            className="dashboard-scan__result dashboard-scan__result--error"
            role="alert"
            style={{ marginTop: "0.85rem" }}
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
