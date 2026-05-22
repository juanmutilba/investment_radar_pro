import { useNavigate, useSearchParams } from "react-router-dom";
import { PortfolioRowTradeButtons } from "@/components/cartera/PortfolioRowTradeButtons";
import { RadarMarketTablePage } from "@/components/radar/RadarMarketTablePage";
import { formatEbitdaUsd, getRaw, parseNumberLoose } from "@/components/radar/radarTableCore";
import { COLUMNS_USA } from "@/components/radar/radarTableModel";
import { fetchLatestRadar, type RadarRow } from "@/services/api";

const TICKER_KEYS = COLUMNS_USA.find((c) => c.id === "ticker")!.keys;
const PRECIO_KEYS = COLUMNS_USA.find((c) => c.id === "precio")!.keys;

export function AccionesUsaPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const initialSearch = params.get("ticker")?.trim() || undefined;
  const tickerSearchExact = params.get("exact") === "1";

  return (
    <RadarMarketTablePage
      pageTitle="ACCIONES USA"
      columns={COLUMNS_USA}
      fetchRadar={fetchLatestRadar}
      formatEbitda={formatEbitdaUsd}
      initialSearch={initialSearch}
      tickerSearchExact={tickerSearchExact}
      usaTickerScreenerDetail
      onTickerClick={(t) => {
        const q = new URLSearchParams();
        q.set("ticker", t);
        q.set("exact", "1");
        navigate(`/acciones-usa?${q.toString()}`, { replace: true });
      }}
      onTickerDetailClose={() => {
        navigate("/acciones-usa", { replace: true });
      }}
      universe={{
        label: "Universo",
        allLabel: "Todas",
        keys: ["Universo", "universo", "Indice", "Índice", "indice", "Index", "index"],
        options: ["Nasdaq", "S&P 500", "Dow Jones"],
      }}
      emptySheetMessage="El último export no contiene filas en Radar_Completo."
      renderRowActions={(row: RadarRow) => {
        const tick = String(getRaw(row, TICKER_KEYS) ?? "").trim();
        const px = parseNumberLoose(getRaw(row, PRECIO_KEYS));
        return (
          <PortfolioRowTradeButtons
            assetType="USA"
            ticker={tick}
            suggestedBuyPriceUsd={px}
            suggestedSellPriceUsd={px}
          />
        );
      }}
    />
  );
}
