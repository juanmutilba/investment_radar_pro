/** Unidades soportadas por el backend (ccxt/Binance): 15m, 1h, 4h, 1d, 1w, etc. */

export type TimeframeUnit = "m" | "h" | "d" | "w";

export type TimeframeParts = {
  value: number;
  unit: TimeframeUnit;
};

export const TIMEFRAME_UNIT_OPTIONS: { unit: TimeframeUnit; label: string }[] = [
  { unit: "m", label: "Minutos" },
  { unit: "h", label: "Horas" },
  { unit: "d", label: "Días" },
  { unit: "w", label: "Semanas" },
];

export const TIMEFRAME_PRESETS = ["15m", "1h", "4h", "1d"] as const;

const DEFAULT_PARTS: TimeframeParts = { value: 1, unit: "h" };

export function parseTimeframe(raw: string | null | undefined): TimeframeParts {
  const s = (raw ?? "").trim().toLowerCase();
  const m = /^(\d+)\s*([mhdw])$/i.exec(s);
  if (!m) {
    return { ...DEFAULT_PARTS };
  }
  const value = Number.parseInt(m[1], 10);
  const unit = m[2].toLowerCase() as TimeframeUnit;
  if (!Number.isFinite(value) || value <= 0) {
    return { ...DEFAULT_PARTS };
  }
  if (unit !== "m" && unit !== "h" && unit !== "d" && unit !== "w") {
    return { ...DEFAULT_PARTS };
  }
  return { value, unit };
}

export function formatTimeframe(parts: TimeframeParts): string {
  const value = Math.max(1, Math.floor(Number(parts.value)) || 1);
  const unit = parts.unit ?? "h";
  return `${value}${unit}`;
}

export function normalizeTimeframeString(raw: string | null | undefined): string {
  return formatTimeframe(parseTimeframe(raw));
}
