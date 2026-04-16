import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "@/components/layout/AppLayout";
import { AccionesArgentinaPage } from "@/pages/AccionesArgentinaPage";
import { AccionesUsaPage } from "@/pages/AccionesUsaPage";
import { AlertasPage } from "@/pages/AlertasPage";
import { CedearsPage } from "@/pages/CedearsPage";
import { DashboardPage } from "@/pages/DashboardPage";
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
        <Route path="cedears" element={<CedearsPage />} />
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
          path="opciones"
          element={
            <PlaceholderPage
              title="Opciones"
              description="Cadena de opciones y griegas. Placeholder hasta integrar proveedor."
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
        <Route
          path="tenencia"
          element={
            <PlaceholderPage
              title="Tenencia"
              description="Cartera propia, P&amp;L y asignación. Conectará con backend dedicado."
            />
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
