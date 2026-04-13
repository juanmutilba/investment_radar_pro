import { RadarMarketTablePage } from "@/components/radar/RadarMarketTablePage";
import { formatEbitdaUsd } from "@/components/radar/radarTableCore";
import { COLUMNS_USA } from "@/components/radar/radarTableModel";
import { fetchLatestRadar } from "@/services/api";

export function AccionesUsaPage() {
  return (
    <RadarMarketTablePage
      pageTitle="ACCIONES USA"
      columns={COLUMNS_USA}
      fetchRadar={fetchLatestRadar}
      formatEbitda={formatEbitdaUsd}
      emptySheetMessage="El último export no contiene filas en Radar_Completo."
    />
  );
}
