export type SortDir = "asc" | "desc";

export type SortCriterion = { columnId: string; dir: SortDir };

export type ColumnDef = {
  id: string;
  header: string;
  keys: string[];
  minWidth: number;
  align?: "left" | "right" | "center";
  headerTitle?: string;
  nowrap?: boolean;
  sortKind?: "string" | "number" | "trend" | "flag" | null;
};

export const SCORE_HELP = {
  tech: "Síntesis del análisis técnico del radar: tendencia, momentum e indicadores (RSI, MACD, medias).",
  fund: "Síntesis de fundamentales del radar: rentabilidad, márgenes, deuda y valoración relativa.",
  risk: "Puntuación de riesgo del modelo (volatilidad y perfil del activo); interpretar según la escala del radar.",
} as const;

export const COLUMNS_USA: ColumnDef[] = [
  { id: "ticker", header: "Ticker", keys: ["Ticker", "ticker"], minWidth: 92, nowrap: true, sortKind: "string" },
  { id: "empresa", header: "Empresa", keys: ["Empresa", "empresa"], minWidth: 160, sortKind: "string" },
  { id: "sector", header: "Sector", keys: ["Sector", "sector"], minWidth: 120, sortKind: "string" },
  { id: "precio", header: "Precio", keys: ["Precio", "precio"], minWidth: 84, align: "right", nowrap: true, sortKind: "number" },
  {
    id: "pe",
    header: "P/E",
    keys: ["PE", "Pe", "pe", "P/E", "P/E Ratio"],
    minWidth: 76,
    align: "right",
    nowrap: true,
    sortKind: "number",
    headerTitle:
      "Price to Earnings (P/E): relación entre el precio de la acción y la ganancia por acción. Un valor bajo puede indicar una valuación más barata, aunque depende del sector y del crecimiento esperado.",
  },
  {
    id: "priceToBook",
    header: "Price to Book",
    keys: ["PriceToBook", "priceToBook", "PB", "pb"],
    minWidth: 96,
    align: "right",
    nowrap: true,
    sortKind: "number",
    headerTitle:
      "Price to Book (P/B): relación entre el precio de mercado de la acción y su valor contable. Un valor bajo puede indicar que está barata en relación a sus activos.",
  },
  { id: "ebitda", header: "EBITDA", keys: ["EBITDA", "ebitda"], minWidth: 100, align: "right", nowrap: true, sortKind: "number" },
  {
    id: "leverage",
    header: "Deuda/Patrimonio",
    keys: ["DebtToEquity", "debtToEquity"],
    minWidth: 108,
    align: "right",
    nowrap: true,
    sortKind: "number",
    headerTitle: "Relación entre deuda y patrimonio de la empresa",
  },
  {
    id: "debtToEbitda",
    header: "Debt/EBITDA",
    keys: ["DebtToEbitda", "debtToEbitda"],
    minWidth: 96,
    align: "right",
    nowrap: true,
    sortKind: "number",
    headerTitle:
      "Debt/EBITDA: relación entre la deuda financiera y el EBITDA. Mide cuántos años de generación operativa harían falta para cubrir la deuda. Un valor bajo suele indicar menor apalancamiento.",
  },
  { id: "trend", header: "Tendencia", keys: ["Trend", "trend"], minWidth: 108, nowrap: true, sortKind: "trend" },
  {
    id: "rsi",
    header: "RSI",
    keys: ["RSI", "rsi"],
    minWidth: 52,
    align: "right",
    nowrap: true,
    sortKind: "number",
    headerTitle:
      "RSI: indicador técnico de momentum que mide si una acción puede estar sobrevendida o sobrecomprada. Valores bajos pueden señalar sobreventa; valores altos, sobrecompra.",
  },
  {
    id: "macd",
    header: "MACD Alcista",
    keys: ["MACD_Bull", "macd_bull"],
    minWidth: 108,
    align: "center",
    nowrap: true,
    sortKind: "flag",
  },
  {
    id: "tech",
    header: "TechScore",
    keys: ["TechScore", "tech_score"],
    minWidth: 92,
    align: "right",
    nowrap: true,
    headerTitle: SCORE_HELP.tech,
    sortKind: "number",
  },
  {
    id: "fund",
    header: "FundScore",
    keys: ["FundScore", "fund_score"],
    minWidth: 92,
    align: "right",
    nowrap: true,
    headerTitle: SCORE_HELP.fund,
    sortKind: "number",
  },
  {
    id: "risk",
    header: "RiskScore",
    keys: ["RiskScore", "risk_score"],
    minWidth: 92,
    align: "right",
    nowrap: true,
    headerTitle: SCORE_HELP.risk,
    sortKind: "number",
  },
  { id: "total", header: "TotalScore", keys: ["TotalScore", "total_score"], minWidth: 96, align: "right", nowrap: true, sortKind: "number" },
  {
    id: "signal",
    header: "SignalState",
    keys: ["SignalState", "signal_state", "signalState"],
    minWidth: 112,
    nowrap: true,
    sortKind: "string",
  },
  {
    id: "conv",
    header: "Conviccion",
    keys: ["Conviccion", "conviccion", "Conviction"],
    minWidth: 88,
    nowrap: true,
    sortKind: "string",
  },
];

/**
 * Misma grilla visible que USA (sin columna Industria; el dato puede seguir en las filas del export).
 */
export const COLUMNS_ARGENTINA: ColumnDef[] = [...COLUMNS_USA];

export type QuickFilterId = "oportunidades" | "oversold" | "calidad" | "solo_cedear";
