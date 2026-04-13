/**
 * Llamadas HTTP al backend FastAPI.
 * En desarrollo, Vite reescribe /api → http://127.0.0.1:8000 (ver vite.config.ts).
 */
const BASE = "/api";

export type LatestAlert = {
  ticker: string | null;
  tipo_alerta: string | null;
  score: number | null;
  score_anterior: number | null;
  cambio_score: number | null;
  mercado: string | null;
};

export async function fetchLatestAlerts(): Promise<LatestAlert[]> {
  const res = await fetch(`${BASE}/latest-alerts`);
  if (res.status === 404) {
    return [];
  }
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  }
  const data: unknown = await res.json();
  if (!Array.isArray(data)) {
    throw new Error("Respuesta inesperada: se esperaba un array");
  }
  return data as LatestAlert[];
}

/** Fila tal como viene del Excel (claves pueden variar en casing); usar helpers al renderizar. */
export type RadarRow = Record<string, unknown>;

export type LatestRadarResponse = {
  file: string;
  sheet: string;
  rows: RadarRow[];
};

function isLatestRadarResponse(data: unknown): data is LatestRadarResponse {
  if (data === null || typeof data !== "object") {
    return false;
  }
  const o = data as Record<string, unknown>;
  return (
    typeof o.file === "string" &&
    typeof o.sheet === "string" &&
    Array.isArray(o.rows)
  );
}

/**
 * GET /latest-radar (vía proxy /api).
 * null si no hay export en el backend (404).
 */
export async function fetchLatestRadar(): Promise<LatestRadarResponse | null> {
  const res = await fetch(`${BASE}/latest-radar`);
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  }
  const data: unknown = await res.json();
  if (!isLatestRadarResponse(data)) {
    throw new Error("Respuesta inesperada: se esperaba { file, sheet, rows }");
  }
  return data;
}
