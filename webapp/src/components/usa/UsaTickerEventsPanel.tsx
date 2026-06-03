import { useEffect, useState } from "react";

import { getUsaEventsForTicker, type UsaEventsForTickerPayload } from "@/services/api";

function fmtIsoDate(s: string | null | undefined): string {
  const t = (s ?? "").trim();
  if (!t) return "—";
  if (/^\d{4}-\d{2}-\d{2}$/.test(t)) {
    const [y, m, d] = t.split("-").map(Number);
    if (Number.isFinite(y) && Number.isFinite(m) && Number.isFinite(d)) {
      return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("es-AR", {
        timeZone: "UTC",
        year: "numeric",
        month: "short",
        day: "numeric",
      });
    }
  }
  return t;
}

function fmtUpdatedAt(s: string | null | undefined): string {
  const t = (s ?? "").trim();
  if (!t) return "—";
  const d = new Date(t);
  return Number.isNaN(d.getTime()) ? t : d.toLocaleString("es-AR");
}

function motivoLabel(code: string): string {
  if (code === "earnings_proximo_7d") return "Earnings en ≤7 días (fecha cache)";
  if (code === "earnings_fecha_cache_reciente_pasada") return "Fecha de earnings en cache recién pasada (1–3 días)";
  if (code === "dividendo_reciente_3d") return "Pago de dividendo en los últimos 3 días (fecha cache)";
  return code;
}

function fmtEarningsDelta(d: number | null | undefined): string {
  if (d === null || d === undefined) return "—";
  if (d === 0) return "Hoy";
  if (d > 0) return `${d}`;
  return `${d} (fecha en cache ya pasó)`;
}

export function UsaTickerEventsPanel({
  ticker,
  variant = "standalone",
}: {
  ticker: string;
  variant?: "standalone" | "embedded";
}) {
  const embedded = variant === "embedded";
  const [data, setData] = useState<UsaEventsForTickerPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    setData(null);
    void getUsaEventsForTicker(ticker)
      .then((p) => {
        if (!cancelled) setData(p);
      })
      .catch((e: unknown) => {
        if (!cancelled) setErr(e instanceof Error ? e.message : "Error al cargar eventos");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  return (
    <section
      className="usa-ticker-events"
      style={{
        margin: embedded ? 0 : "0 0 1rem",
        padding: embedded ? "0.25rem 0 0" : "0.85rem 1rem",
        border: embedded ? "none" : "1px solid var(--border)",
        borderRadius: embedded ? 0 : "var(--radius)",
        background: embedded ? "transparent" : "var(--bg-panel, rgba(15, 23, 42, 0.2))",
      }}
      aria-label={`Eventos relevantes ${ticker}`}
    >
      {!embedded ? (
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}>
          <h3 className="dashboard-section-title" style={{ margin: 0, fontSize: "0.95rem" }}>
            Eventos relevantes
          </h3>
          <span className="msg-muted" style={{ fontSize: "0.78rem" }}>
            {ticker}
          </span>
          {data?.evento_sensible ? (
            <span className="radar-badge radar-badge--conv-media" title="Ventana sensible según fechas del cache local">
              Evento sensible
            </span>
          ) : null}
        </div>
      ) : (
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "0.5rem", marginBottom: "0.35rem" }}>
          <span className="msg-muted" style={{ fontSize: "0.74rem" }}>
            {ticker}
          </span>
          {data?.evento_sensible ? (
            <span className="radar-badge radar-badge--conv-media" title="Ventana sensible según fechas del cache local">
              Evento sensible
            </span>
          ) : null}
        </div>
      )}
      <p className="msg-muted" style={{ margin: "0 0 0.65rem", fontSize: embedded ? "0.72rem" : "0.78rem", lineHeight: 1.4 }}>
        {embedded ? (
          <>
            Cache local <code style={{ fontSize: "0.68rem" }}>events_cache_usa.json</code> (sin Yahoo en vivo).
          </>
        ) : (
          <>
            Datos desde <code style={{ fontSize: "0.72rem" }}>events_cache_usa.json</code> (sin Yahoo en vivo). El cache no
            guarda explícitamente la fecha de un earnings ya reportado; si la fecha de calendario quedó en el pasado, mostramos
            días transcurridos como referencia.
          </>
        )}
      </p>

      {loading ? <p className="msg-muted" style={{ margin: 0 }}>Cargando eventos del cache…</p> : null}
      {err ? (
        <p className="msg-error" style={{ margin: 0 }} role="alert">
          {err}
        </p>
      ) : null}

      {!loading && !err && data && !data.ok ? (
        <p className="msg-error" style={{ margin: 0 }}>
          Solicitud inválida ({data.error ?? "—"}).
        </p>
      ) : null}

      {!loading && !err && data && data.ok && !data.found ? (
        <p className="msg-muted" style={{ margin: 0 }}>
          Sin eventos registrados en cache.
        </p>
      ) : null}

      {!loading && !err && data && data.ok && data.found && data.skipped === true ? (
        <p className="msg-muted" style={{ margin: 0 }}>
          Ticker omitido en el generador de eventos
          {data.skip_reason ? `: ${data.skip_reason}` : "."}
        </p>
      ) : null}

      {!loading && !err && data && data.ok && data.found && data.cache_row_error ? (
        <p className="msg-error" style={{ margin: "0 0 0.5rem" }}>
          Error en fila de cache:{" "}
          {typeof data.cache_row_error.msg === "string"
            ? data.cache_row_error.msg
            : JSON.stringify(data.cache_row_error)}
        </p>
      ) : null}

      {!loading && !err && data && data.ok && data.found && !data.skipped && !data.cache_row_error ? (
        <>
          {!data.has_eventos_en_cache ? (
            <p className="msg-muted" style={{ margin: 0 }}>
              Sin eventos registrados en cache.
            </p>
          ) : (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(11.5rem, 1fr))",
                gap: "0.45rem 0.75rem",
                fontSize: "0.82rem",
              }}
            >
              <div>
                <div className="msg-muted" style={{ fontSize: "0.72rem" }}>
                  Último earnings
                </div>
                <div>{data.fecha_ultimo_earnings ? fmtIsoDate(data.fecha_ultimo_earnings) : "—"}</div>
              </div>
              <div>
                <div className="msg-muted" style={{ fontSize: "0.72rem" }}>
                  Próximo earnings
                </div>
                <div>{data.fecha_proximo_earnings ? fmtIsoDate(data.fecha_proximo_earnings) : "—"}</div>
              </div>
              <div>
                <div className="msg-muted" style={{ fontSize: "0.72rem" }}>
                  Días hasta próx. earnings
                </div>
                <div>{fmtEarningsDelta(data.dias_hasta_proximo_earnings)}</div>
              </div>
              <div>
                <div className="msg-muted" style={{ fontSize: "0.72rem" }}>
                  Días desde fecha earnings (cache)
                </div>
                <div>{data.dias_desde_ultimo_earnings ?? "—"}</div>
              </div>
              <div>
                <div className="msg-muted" style={{ fontSize: "0.72rem" }}>
                  Último dividendo (fecha)
                </div>
                <div>{data.fecha_ultimo_dividendo ? fmtIsoDate(data.fecha_ultimo_dividendo) : "—"}</div>
              </div>
              <div>
                <div className="msg-muted" style={{ fontSize: "0.72rem" }}>
                  Ex-dividend
                </div>
                <div>{data.fecha_ex_dividendo ? fmtIsoDate(data.fecha_ex_dividendo) : "—"}</div>
              </div>
              <div>
                <div className="msg-muted" style={{ fontSize: "0.72rem" }}>
                  Monto últ. dividendo
                </div>
                <div>{data.ultimo_dividendo != null ? String(data.ultimo_dividendo) : "—"}</div>
              </div>
              <div>
                <div className="msg-muted" style={{ fontSize: "0.72rem" }}>
                  Próximo dividendo (estim.)
                </div>
                <div>
                  {data.fecha_proximo_dividendo_estimado ? fmtIsoDate(data.fecha_proximo_dividendo_estimado) : "—"}
                </div>
              </div>
              <div>
                <div className="msg-muted" style={{ fontSize: "0.72rem" }}>
                  Días hasta próx. dividendo
                </div>
                <div>{data.dias_hasta_proximo_dividendo ?? "—"}</div>
              </div>
              <div>
                <div className="msg-muted" style={{ fontSize: "0.72rem" }}>
                  Actualización fila (cache)
                </div>
                <div>{fmtUpdatedAt(data.updated_at)}</div>
              </div>
            </div>
          )}
          {data.cache_stale_warning ? (
            <p className="msg-muted" style={{ margin: "0.65rem 0 0", fontSize: "0.78rem" }}>
              Cache de esta fila con más de 7 días de antigüedad
              {data.cache_row_age_days != null ? ` (~${data.cache_row_age_days} días).` : "."} Convén actualizar desde{" "}
              <strong>Eventos USA</strong>.
            </p>
          ) : data.updated_at ? (
            <p className="msg-muted" style={{ margin: "0.65rem 0 0", fontSize: "0.74rem" }}>
              Última actualización de esta fila en cache: {fmtUpdatedAt(data.updated_at)}
            </p>
          ) : null}
          {data.evento_sensible && data.evento_sensible_motivos.length > 0 ? (
            <ul className="msg-muted" style={{ margin: "0.5rem 0 0", paddingLeft: "1.1rem", fontSize: "0.76rem" }}>
              {data.evento_sensible_motivos.map((m) => (
                <li key={m}>{motivoLabel(m)}</li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
