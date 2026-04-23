import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { PortfolioAssetType, PortfolioOpenRow } from "@/services/api";
import { fetchPortfolioOpen } from "@/services/api";

function positionKey(ticker: string, assetType: PortfolioAssetType): string {
  return `${ticker.trim().toUpperCase()}\u0000${assetType}`;
}

export type PortfolioOpenPositionsContextValue = {
  /** Primera carga; mientras es true no se asume si hay venta disponible. */
  loading: boolean;
  error: string | null;
  rows: PortfolioOpenRow[];
  /** silent: no deshabilita toda la UI ni borra filas si falla (solo log de error en error). */
  refresh: (opts?: { silent?: boolean }) => Promise<void>;
  hasOpenPosition: (ticker: string, assetType: PortfolioAssetType) => boolean;
  findOpenPosition: (ticker: string, assetType: PortfolioAssetType) => PortfolioOpenRow | undefined;
};

const PortfolioOpenPositionsContext = createContext<PortfolioOpenPositionsContextValue | null>(null);

export function PortfolioOpenPositionsProvider({ children }: { children: ReactNode }) {
  const [rows, setRows] = useState<PortfolioOpenRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (opts?: { silent?: boolean }) => {
    const silent = opts?.silent ?? false;
    if (!silent) {
      setLoading(true);
      setError(null);
    }
    try {
      const data = await fetchPortfolioOpen();
      setRows(data);
      if (!silent) {
        setError(null);
      }
    } catch (e) {
      if (!silent) {
        const msg = e instanceof Error ? e.message : "Error al cargar cartera";
        setError(msg);
        setRows([]);
      }
      // Refresco silencioso: mantener último snapshot si falla la red.
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void refresh({ silent: false });
  }, [refresh]);

  const keySet = useMemo(() => {
    const s = new Set<string>();
    for (const r of rows) {
      s.add(positionKey(r.ticker, r.asset_type));
    }
    return s;
  }, [rows]);

  const hasOpenPosition = useCallback(
    (ticker: string, assetType: PortfolioAssetType) => keySet.has(positionKey(ticker, assetType)),
    [keySet],
  );

  const findOpenPosition = useCallback(
    (ticker: string, assetType: PortfolioAssetType) =>
      rows.find(
        (r) => r.ticker.trim().toUpperCase() === ticker.trim().toUpperCase() && r.asset_type === assetType,
      ),
    [rows],
  );

  const value = useMemo<PortfolioOpenPositionsContextValue>(
    () => ({
      loading,
      error,
      rows,
      refresh,
      hasOpenPosition,
      findOpenPosition,
    }),
    [loading, error, rows, refresh, hasOpenPosition, findOpenPosition],
  );

  return (
    <PortfolioOpenPositionsContext.Provider value={value}>{children}</PortfolioOpenPositionsContext.Provider>
  );
}

export function usePortfolioOpenPositions(): PortfolioOpenPositionsContextValue {
  const v = useContext(PortfolioOpenPositionsContext);
  if (!v) {
    throw new Error("usePortfolioOpenPositions debe usarse dentro de PortfolioOpenPositionsProvider");
  }
  return v;
}
