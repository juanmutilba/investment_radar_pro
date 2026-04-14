import { RadarMarketTablePage } from "@/components/radar/RadarMarketTablePage";
import { formatEbitdaArs, formatPrecioDolarAr } from "@/components/radar/radarTableCore";
import { COLUMNS_ARGENTINA } from "@/components/radar/radarTableModel";
import { fetchLatestRadarArgentina } from "@/services/api";

export function AccionesArgentinaPage() {
  return (
    <RadarMarketTablePage
      pageTitle="ACCIONES ARGENTINA"
      columns={COLUMNS_ARGENTINA}
      fetchRadar={fetchLatestRadarArgentina}
      formatEbitda={formatEbitdaArs}
      formatPrecio={formatPrecioDolarAr}
      universe={{
        label: "Universo",
        allLabel: "Todas",
        keys: ["Panel", "panel", "Universo", "universo", "Indice", "Índice", "indice"],
        options: ["Merval", "Panel General"],
      }}
      emptySheetMessage="El último export no contiene filas en Radar_Argentina_Completo."
    />
  );
}
