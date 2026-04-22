import { Link } from "react-router-dom";

/** Agrupa mercado de alertas/radar para rutas USA vs Argentina. */
export function mercadoBucket(
  m: string | null | undefined,
): "usa" | "argentina" | "otro" {
  const s = (m ?? "").trim().toUpperCase();
  if (!s) return "otro";
  if (s === "USA" || s === "US" || s === "UNITED STATES") return "usa";
  if (s === "ARGENTINA" || s === "AR" || s === "ARG") return "argentina";
  if (s.includes("ARGENTINA")) return "argentina";
  if (s.includes("USA")) return "usa";
  return "otro";
}

/** Ruta al radar con filtro inicial; null si mercado no es USA/Argentina o no hay ticker. */
export function radarHrefForTicker(
  ticker: string | null | undefined,
  mercado: string | null | undefined,
): string | null {
  const t = ticker?.trim();
  if (!t) return null;
  const b = mercadoBucket(mercado);
  /** exact=1: filtro por ticker exacto (evita coincidencias parciales t.includes(q)). */
  const q = new URLSearchParams({ ticker: t, exact: "1" }).toString();
  if (b === "usa") return `/acciones-usa?${q}`;
  if (b === "argentina") return `/acciones-argentina?${q}`;
  return null;
}

export function TickerRadarLink({
  ticker,
  mercado,
}: {
  ticker: string | null;
  mercado: string | null;
}) {
  const href = radarHrefForTicker(ticker, mercado);
  if (!ticker?.trim()) {
    return <>—</>;
  }
  if (!href) {
    return <span className="table-cell--nowrap">{ticker}</span>;
  }
  return (
    <Link
      replace
      to={href}
      className="table-cell--nowrap"
      title={`Abrir ${ticker} en el radar (${mercado ?? "mercado"})`}
    >
      {ticker}
    </Link>
  );
}
