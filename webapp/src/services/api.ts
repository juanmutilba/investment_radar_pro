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
