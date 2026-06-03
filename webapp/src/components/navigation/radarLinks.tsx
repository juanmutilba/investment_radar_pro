import { Link } from "react-router-dom";
import {
  type AlertMarketHint,
  mercadoBucketFromAlert,
  mercadoLabelForRadarLink,
  type MercadoBucket,
} from "@/components/navigation/alertMarketUtils";

export type { AlertMarketHint, MercadoBucket };
export {
  collectAlertMarketTokens,
  isArgentinaAlert,
  isUsaAlert,
  mercadoBucket,
  mercadoBucketFromAlert,
  mercadoLabelForRadarLink,
} from "@/components/navigation/alertMarketUtils";

/** Ruta al radar con filtro inicial; null si mercado no es USA/Argentina o no hay ticker. */
export function radarHrefForTicker(
  ticker: string | null | undefined,
  mercado: string | null | undefined,
  extra?: Omit<AlertMarketHint, "ticker" | "mercado">,
): string | null {
  const hint: AlertMarketHint = { ticker, mercado, ...extra };
  const b = mercadoBucketFromAlert(hint);
  const t = ticker?.trim();
  if (!t) return null;
  const q = new URLSearchParams({ ticker: t, exact: "1" }).toString();
  if (b === "usa") return `/acciones-usa?${q}`;
  if (b === "argentina") return `/acciones-argentina?${q}`;
  return null;
}

export function TickerRadarLink({
  ticker,
  mercado,
  panel,
  universo,
  country,
  region,
  source,
  exchange,
  asset_type,
}: AlertMarketHint) {
  const hint: AlertMarketHint = {
    ticker,
    mercado,
    panel,
    universo,
    country,
    region,
    source,
    exchange,
    asset_type,
  };
  const label = (ticker ?? "").trim();
  if (!label) {
    return <>—</>;
  }
  const href = radarHrefForTicker(ticker, mercado, {
    panel,
    universo,
    country,
    region,
    source,
    exchange,
    asset_type,
  });
  if (!href) {
    return <span className="table-cell--nowrap">{label}</span>;
  }
  const mercadoUi = mercadoLabelForRadarLink(hint) ?? mercado ?? "";
  return (
    <Link
      replace
      to={href}
      className="table-cell--nowrap radar-ticker-link"
      title={`Ver detalle de ${label}${mercadoUi ? ` (${mercadoUi})` : ""}`}
    >
      {label}
    </Link>
  );
}
