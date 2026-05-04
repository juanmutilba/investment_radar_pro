import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "@/components/layout/AppLayout";
import { AccionesArgentinaPage } from "@/pages/AccionesArgentinaPage";
import { AccionesUsaPage } from "@/pages/AccionesUsaPage";
import { AlertasPage } from "@/pages/AlertasPage";
import { CarteraPage } from "@/pages/CarteraPage";
import { CedearsPage } from "@/pages/CedearsPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { EventosPage } from "@/pages/EventosPage";
import { OptionsPage } from "@/pages/OptionsPage";
import { PlaceholderPage } from "@/pages/PlaceholderPage";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="acciones" element={<Navigate to="/acciones-usa" replace />} />
        <Route path="acciones-usa" element={<AccionesUsaPage />} />
        <Route path="acciones-argentina" element={<AccionesArgentinaPage />} />
        <Route path="alertas" element={<AlertasPage />} />
        <Route path="eventos" element={<EventosPage />} />
        <Route path="cedears" element={<CedearsPage />} />
        <Route path="options" element={<OptionsPage />} />
        <Route path="opciones" element={<Navigate to="/options" replace />} />
        <Route
          path="bonos"
          element={
            <PlaceholderPage
              title="Bonos"
              description="Rentas fijas y curvas. Módulo reservado para una fase posterior."
            />
          }
        />
        <Route
          path="futuros"
          element={
            <PlaceholderPage
              title="Futuros"
              description="Contratos y vencimientos. Pendiente de alcance y datos."
            />
          }
        />
        <Route path="cartera" element={<CarteraPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
