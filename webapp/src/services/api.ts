/**
 * Llamadas HTTP al backend FastAPI.
 * En desarrollo, Vite reescribe /api → http://127.0.0.1:8000 (ver vite.config.ts).
 */
const BASE = "/api";

export type LatestAlert = {
  ticker: string | null;
  /** Etiqueta legible (hoja Alertas / TipoAlerta). */
  tipo_alerta: string | null;
  /** Clave interna del motor: compra_fuerte, compra_potencial, … (si el export la incluye). */
  tipo_alerta_key?: string | null;
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

export type AlertHistoryEvent = {
  /** Presente desde la versión con agrupación por corrida; eventos viejos pueden no tenerlo. */
  scan_id?: string;
  scan_at: string;
  ticker: string | null;
  mercado: string | null;
  universo?: unknown;
  panel?: unknown;
  tipo_alerta?: string | null;
  tipo_alerta_label?: string | null;
  prioridad?: number | null;
  prioridad_radar?: unknown;
  conviccion?: unknown;
  total_score?: unknown;
  rsi?: unknown;
  precio?: unknown;
  setup?: unknown;
  motivo?: unknown;
  fingerprint?: unknown;
  score?: unknown;
  score_anterior?: unknown;
  cambio_score?: unknown;
  senales_activas?: unknown;
  mensaje?: unknown;
};

export async function fetchAlertHistory(limit = 200): Promise<AlertHistoryEvent[]> {
  const q = new URLSearchParams({ limit: String(limit) });
  const res = await fetch(`${BASE}/alert-history?${q.toString()}`);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${await readHttpErrorMessage(res)}`);
  }
  const data: unknown = await res.json().catch(() => null);
  if (!Array.isArray(data)) {
    throw new Error("Respuesta inesperada: se esperaba un array");
  }
  return data as AlertHistoryEvent[];
}

/** Fila tal como viene del Excel (claves pueden variar en casing); usar helpers al renderizar. */
export type RadarRow = Record<string, unknown>;

export type LatestRadarResponse = {
  file: string;
  sheet?: string | null;
  rows: RadarRow[];
};

function isLatestRadarResponse(data: unknown): data is LatestRadarResponse {
  if (data === null || typeof data !== "object") {
    return false;
  }
  const o = data as Record<string, unknown>;
  return (
    typeof o.file === "string" &&
    (typeof o.sheet === "string" || o.sheet === null || o.sheet === undefined) &&
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
    throw new Error(`HTTP ${res.status}: ${await readHttpErrorMessage(res)}`);
  }
  const data: unknown = await res.json().catch(() => null);
  if (!isLatestRadarResponse(data)) {
    throw new Error("Respuesta inesperada: se esperaba { file, sheet?, rows }");
  }
  return data;
}

/**
 * GET /latest-radar-argentina — hoja Radar_Argentina_Completo del último export.
 */
export async function fetchLatestRadarArgentina(): Promise<LatestRadarResponse | null> {
  const res = await fetch(`${BASE}/latest-radar-argentina`);
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${await readHttpErrorMessage(res)}`);
  }
  const data: unknown = await res.json().catch(() => null);
  if (!isLatestRadarResponse(data)) {
    throw new Error("Respuesta inesperada: se esperaba { file, sheet?, rows }");
  }
  return data;
}

export type LatestSummary = {
  file: string;
  usa_tickers_count: number;
  arg_tickers_count: number;
  usa_alerts_count: number;
  arg_alerts_count: number;
};

function isLatestSummary(data: unknown): data is LatestSummary {
  if (data === null || typeof data !== "object") {
    return false;
  }
  const o = data as Record<string, unknown>;
  return (
    typeof o.file === "string" &&
    typeof o.usa_tickers_count === "number" &&
    typeof o.arg_tickers_count === "number" &&
    typeof o.usa_alerts_count === "number" &&
    typeof o.arg_alerts_count === "number"
  );
}

/** GET /latest-summary. null si no hay export (404). */
export async function fetchLatestSummary(): Promise<LatestSummary | null> {
  const res = await fetch(`${BASE}/latest-summary`);
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  }
  const data: unknown = await res.json();
  if (!isLatestSummary(data)) {
    throw new Error("Respuesta inesperada: latest-summary");
  }
  return data;
}

export type RunScanResponse = {
  status: "ok";
  summary: LatestSummary;
};

async function readHttpErrorMessage(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json();
    if (body !== null && typeof body === "object" && "detail" in body) {
      const d = (body as { detail: unknown }).detail;
      if (typeof d === "string") {
        return d;
      }
    }
  } catch {
    /* ignore */
  }
  return res.statusText || `HTTP ${res.status}`;
}

/** POST /run-scan: ejecuta pipeline + export en el backend. */
export async function runScan(): Promise<RunScanResponse> {
  const res = await fetch(`${BASE}/run-scan`, { method: "POST" });
  if (!res.ok) {
    throw new Error(await readHttpErrorMessage(res));
  }
  const data: unknown = await res.json();
  if (
    data === null ||
    typeof data !== "object" ||
    (data as { status?: unknown }).status !== "ok" ||
    !isLatestSummary((data as { summary?: unknown }).summary)
  ) {
    throw new Error("Respuesta inesperada: run-scan");
  }
  const o = data as { status: "ok"; summary: LatestSummary };
  return { status: o.status, summary: o.summary };
}
