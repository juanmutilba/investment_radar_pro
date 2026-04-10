import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "@/components/layout/AppLayout";
import { AccionesPage } from "@/pages/AccionesPage";
import { AlertasPage } from "@/pages/AlertasPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { PlaceholderPage } from "@/pages/PlaceholderPage";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="acciones" element={<AccionesPage />} />
        <Route path="alertas" element={<AlertasPage />} />
        <Route
          path="cedears"
          element={
            <PlaceholderPage
              title="CEDEARs"
              description="Listados y análisis de CEDEARs. Pendiente de definir fuente de datos y API."
            />
          }
        />
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
