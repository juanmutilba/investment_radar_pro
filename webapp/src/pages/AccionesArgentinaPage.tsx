import { useSearchParams } from "react-router-dom";
import { PortfolioRowTradeButtons } from "@/components/cartera/PortfolioRowTradeButtons";
import { RadarMarketTablePage } from "@/components/radar/RadarMarketTablePage";
import { formatEbitdaArs, formatPrecioDolarAr, getRaw, parseNumberLoose } from "@/components/radar/radarTableCore";
import { COLUMNS_ARGENTINA } from "@/components/radar/radarTableModel";
import { fetchLatestRadarArgentina, type RadarRow } from "@/services/api";

const TICKER_KEYS = COLUMNS_ARGENTINA.find((c) => c.id === "ticker")!.keys;
const PRECIO_KEYS = COLUMNS_ARGENTINA.find((c) => c.id === "precio")!.keys;

export function AccionesArgentinaPage() {
  const [params] = useSearchParams();
  const initialSearch = params.get("ticker")?.trim() || undefined;
  const tickerSearchExact = params.get("exact") === "1";

  return (
    <RadarMarketTablePage
      pageTitle="ACCIONES ARGENTINA"
      columns={COLUMNS_ARGENTINA}
      fetchRadar={fetchLatestRadarArgentina}
      formatEbitda={formatEbitdaArs}
      formatPrecio={formatPrecioDolarAr}
      initialSearch={initialSearch}
      tickerSearchExact={tickerSearchExact}
      universe={{
        label: "Mercado",
        allLabel: "Todos",
        keys: ["Mercado", "mercado", "Panel", "panel", "Universo", "universo", "Indice", "Índice", "indice"],
        options: ["Merval", "General"],
      }}
      emptySheetMessage="El último export no contiene filas en Radar_Argentina_Completo."
      renderRowActions={(row: RadarRow) => {
        const tick = String(getRaw(row, TICKER_KEYS) ?? "").trim();
        const px = parseNumberLoose(getRaw(row, PRECIO_KEYS));
        return (
          <PortfolioRowTradeButtons
            assetType="Argentina"
            ticker={tick}
            suggestedBuyPriceArs={px}
            suggestedSellPriceArs={px}
          />
        );
      }}
    />
  );
}
