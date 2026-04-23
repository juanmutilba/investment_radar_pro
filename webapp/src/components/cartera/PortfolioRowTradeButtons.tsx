import { useCallback, useMemo, useState } from "react";
import type { PortfolioAssetType, PortfolioOpenRow } from "@/services/api";
import { usePortfolioOpenPositions } from "@/context/PortfolioOpenPositionsContext";
import { CarteraBuyModal, type CarteraBuyPreset } from "./CarteraBuyModal";
import { CarteraSellModal } from "./CarteraSellModal";
import { formatPriceInputArs, formatPriceInputUsd } from "./carteraFormUtils";

export type PortfolioRowTradeButtonsProps = {
  assetType: PortfolioAssetType;
  ticker: string;
  suggestedBuyPriceArs?: number | null;
  suggestedBuyPriceUsd?: number | null;
  suggestedSellPriceArs?: number | null;
  suggestedSellPriceUsd?: number | null;
  suggestedSellCedearUsd?: number | null;
};

export function PortfolioRowTradeButtons({
  assetType,
  ticker,
  suggestedBuyPriceArs,
  suggestedBuyPriceUsd,
  suggestedSellPriceArs,
  suggestedSellPriceUsd,
  suggestedSellCedearUsd,
}: PortfolioRowTradeButtonsProps) {
  const t = ticker.trim();
  const { loading: openLoading, error: openError, hasOpenPosition, findOpenPosition, refresh } =
    usePortfolioOpenPositions();
  const [buyOpen, setBuyOpen] = useState(false);
  const [buyPreset, setBuyPreset] = useState<CarteraBuyPreset | null>(null);
  const [sellOpen, setSellOpen] = useState(false);
  const [sellPosition, setSellPosition] = useState<PortfolioOpenRow | null>(null);
  const [sellHintArs, setSellHintArs] = useState("");
  const [sellHintUsd, setSellHintUsd] = useState("");
  const [sellHintCedear, setSellHintCedear] = useState("");
  const [tradeMsg, setTradeMsg] = useState<string | null>(null);

  const canSell = useMemo(() => {
    if (openLoading || !t) return false;
    return hasOpenPosition(t, assetType);
  }, [openLoading, t, assetType, hasOpenPosition]);

  const sellTitle = useMemo(() => {
    if (openLoading) return "Verificando cartera abierta…";
    if (openError) return "No se pudo verificar la cartera";
    if (!hasOpenPosition(t, assetType)) return "Sin posición abierta";
    return undefined;
  }, [openLoading, openError, hasOpenPosition, t, assetType]);

  const openBuy = useCallback(() => {
    setTradeMsg(null);
    setBuyPreset({
      ticker: t,
      assetType,
      suggestedPriceArs: suggestedBuyPriceArs,
      suggestedPriceUsd: suggestedBuyPriceUsd,
    });
    setBuyOpen(true);
  }, [t, assetType, suggestedBuyPriceArs, suggestedBuyPriceUsd]);

  const openSell = useCallback(() => {
    if (!canSell) return;
    const row = findOpenPosition(t, assetType);
    if (!row) return;
    setSellHintArs(formatPriceInputArs(suggestedSellPriceArs));
    setSellHintUsd(formatPriceInputUsd(suggestedSellPriceUsd));
    setSellHintCedear(formatPriceInputUsd(suggestedSellCedearUsd));
    setSellPosition(row);
    setSellOpen(true);
  }, [
    canSell,
    findOpenPosition,
    t,
    assetType,
    suggestedSellPriceArs,
    suggestedSellPriceUsd,
    suggestedSellCedearUsd,
  ]);

  const afterPortfolioMutation = useCallback(() => {
    void refresh({ silent: true });
  }, [refresh]);

  if (!t) {
    return null;
  }

  return (
    <>
      <div className="radar-row-trade-btns">
        <button type="button" className="cartera-btn cartera-btn--primary" onClick={openBuy}>
          Comprar
        </button>
        <span
          className={`radar-row-trade-btns__sell-wrap${!canSell ? " radar-row-trade-btns__sell-wrap--muted" : ""}`}
          title={sellTitle}
        >
          <button
            type="button"
            className="cartera-btn cartera-btn--sell"
            disabled={!canSell}
            onClick={openSell}
            aria-disabled={!canSell}
          >
            Vender
          </button>
        </span>
      </div>
      {tradeMsg ? (
        <div className="radar-row-trade-msg msg-muted" role="status">
          {tradeMsg}
        </div>
      ) : null}

      <CarteraBuyModal
        open={buyOpen}
        preset={buyPreset}
        lockAssetType
        onClose={() => {
          setBuyOpen(false);
          setBuyPreset(null);
        }}
        onSuccess={afterPortfolioMutation}
        onError={(m) => setTradeMsg(m)}
      />

      <CarteraSellModal
        open={sellOpen}
        position={sellPosition}
        hintSellArs={sellHintArs}
        hintSellUsd={sellHintUsd}
        hintSellCedearUsd={sellHintCedear}
        onClose={() => {
          setSellOpen(false);
          setSellPosition(null);
        }}
        onSuccess={afterPortfolioMutation}
        onError={(m) => setTradeMsg(m)}
      />
    </>
  );
}
