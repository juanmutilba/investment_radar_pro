import { useSearchParams } from "react-router-dom";
import { RadarMarketTablePage } from "@/components/radar/RadarMarketTablePage";
import { formatEbitdaUsd } from "@/components/radar/radarTableCore";
import { COLUMNS_USA } from "@/components/radar/radarTableModel";
import { fetchLatestRadar } from "@/services/api";

export function AccionesUsaPage() {
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
      universe={{
        label: "Universo",
        allLabel: "Todas",
        keys: ["Universo", "universo", "Indice", "Índice", "indice", "Index", "index"],
        options: ["Nasdaq", "S&P 500", "Dow Jones"],
      }}
      emptySheetMessage="El último export no contiene filas en Radar_Completo."
    />
  );
}
