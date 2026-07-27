import type {
  FoAssetCategory,
  FoHousePriority,
  FoHouseStatus,
  FoLiabilityType,
  FoLiquidity,
  FoOwnershipStatus,
  FoPolicyDestination,
} from "@/services/api";

export const ASSET_CATEGORY_LABELS: Record<FoAssetCategory, string> = {
  real_estate: "Inmueble",
  vehicle: "Vehículo",
  financial: "Financiero",
  business: "Negocio",
  cash: "Efectivo",
  other: "Otro",
};

export const OWNERSHIP_LABELS: Record<FoOwnershipStatus, string> = {
  owned: "Propio",
  mortgaged: "Hipotecado",
  purchase_agreement: "Boleto / compromiso",
  other: "Otro",
};

export const LIQUIDITY_LABELS: Record<FoLiquidity, string> = {
  high: "Alta",
  medium: "Media",
  low: "Baja",
};

export const LIABILITY_TYPE_LABELS: Record<FoLiabilityType, string> = {
  mortgage_uva: "Hipoteca UVA",
  family_debt: "Deuda familiar",
  overdraft: "Sobregiro",
  vehicle_loan: "Préstamo vehículo",
  personal_loan: "Préstamo personal",
  other: "Otro",
};

export const POLICY_DESTINATION_LABELS: Record<FoPolicyDestination, string> = {
  debt: "Deuda",
  investments: "Inversiones",
  salva: "Salva Foods",
  investment_radar: "Herramienta (legacy)",
  house: "Casa",
  emergency_fund: "Fondo de emergencia",
  other: "Otro",
};

export const HOUSE_PRIORITY_LABELS: Record<FoHousePriority, string> = {
  necessary: "Necesario",
  functional: "Funcional",
  aesthetic: "Estético",
};

export const HOUSE_STATUS_LABELS: Record<FoHouseStatus, string> = {
  planned: "Planificado",
  approved: "Aprobado",
  in_progress: "En curso",
  completed: "Completado",
  paused: "Pausado",
};

/** Unidades / fuentes económicas (no confundir con categoría). */
export const SOURCE_UNIT_LABELS: Record<string, string> = {
  employment: "Empleo",
  consulting: "Consultoría",
  salva: "Salva Foods",
  investments: "Inversiones",
  house: "Casa",
  family: "Familia",
  other: "Otro",
  investment_radar: "Otro (legacy)",
  debt: "Otro (legacy)",
};

export const SOURCE_UNITS_UI = [
  "employment",
  "consulting",
  "salva",
  "investments",
  "house",
  "family",
  "other",
] as const;

/** Categorías de ingreso. */
export const INCOME_CATEGORY_LABELS: Record<string, string> = {
  salary: "Sueldo",
  fees: "Honorarios",
  dividend: "Dividendos",
  interest: "Intereses",
  business_withdrawal: "Retiro de negocio",
  asset_sale: "Venta de activo",
  other: "Otros",
};

export const INCOME_CATEGORIES_UI = [
  "salary",
  "fees",
  "dividend",
  "interest",
  "business_withdrawal",
  "asset_sale",
  "other",
] as const;

/** Categorías de egreso (también plantillas de gasto fijo). */
export const EXPENSE_CATEGORY_LABELS: Record<string, string> = {
  housing: "Vivienda",
  utilities: "Servicios",
  education: "Educación",
  health: "Salud",
  transport: "Transporte",
  insurance: "Seguros",
  credit_cards: "Tarjetas",
  taxes: "Impuestos",
  food: "Alimentación",
  debt_payment: "Deuda",
  investment: "Inversión",
  other: "Otros",
  // legacy aliases
  debt: "Deuda",
};

export const EXPENSE_CATEGORIES_UI = [
  "housing",
  "utilities",
  "education",
  "health",
  "transport",
  "insurance",
  "credit_cards",
  "taxes",
  "food",
  "debt_payment",
  "investment",
  "other",
] as const;

export const CLOSURE_STATUS_LABELS: Record<string, string> = {
  draft: "Borrador",
  closed: "Cerrado",
  reopened: "Reabierto",
};

export const ALLOCATION_STATUS_LABELS: Record<string, string> = {
  proposed: "Propuesto",
  approved: "Aprobado",
  executed: "Ejecutado",
  cancelled: "Cancelado",
};

export const ALLOCATION_DESTINATION_LABELS: Record<string, string> = {
  debt: "Deuda",
  investments: "Inversiones",
  salva: "Salva Foods",
  investment_radar: "Herramienta (legacy)",
  house: "Casa",
  emergency_fund: "Fondo de emergencia",
  cash: "Caja",
  other: "Otro",
};

export function labelOrCode(map: Record<string, string>, code: string | null | undefined): string {
  if (!code) return "—";
  return map[code] ?? `${code} (legacy)`;
}

export function todayIsoDate(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function currentMonth(): string {
  return todayIsoDate().slice(0, 7);
}

export function parseNonNeg(s: string): number | null {
  const t = s.trim().replace(",", ".");
  if (!t) return null;
  const n = Number(t);
  if (!Number.isFinite(n) || n < 0) return null;
  return n;
}

export function fmtMoney(n: number | null | undefined, maxFrac = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString("es-AR", { maximumFractionDigits: maxFrac });
}
