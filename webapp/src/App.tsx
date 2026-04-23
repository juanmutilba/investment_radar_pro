import { BrowserRouter } from "react-router-dom";
import { PortfolioOpenPositionsProvider } from "@/context/PortfolioOpenPositionsContext";
import { AppRoutes } from "@/routes/AppRoutes";

export default function App() {
  return (
    <BrowserRouter>
      <PortfolioOpenPositionsProvider>
        <AppRoutes />
      </PortfolioOpenPositionsProvider>
    </BrowserRouter>
  );
}
