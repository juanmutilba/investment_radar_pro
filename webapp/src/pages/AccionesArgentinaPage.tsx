import { useSearchParams } from "react-router-dom";
import { RadarMarketTablePage } from "@/components/radar/RadarMarketTablePage";
import { formatEbitdaArs, formatPrecioDolarAr } from "@/components/radar/radarTableCore";
import { COLUMNS_ARGENTINA } from "@/components/radar/radarTableModel";
import { fetchLatestRadarArgentina } from "@/services/api";

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
    />
  );
}
