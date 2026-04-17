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

/** Límite por defecto alineado con la UI de historial (máx. eventos pedidos al backend). */
export const ALERT_HISTORY_DEFAULT_LIMIT = 100;

export async function fetchAlertHistory(limit = ALERT_HISTORY_DEFAULT_LIMIT): Promise<AlertHistoryEvent[]> {
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

export type AlertAnalysisRow = {
  ticker: string;
  score_actual: number;
  tipo_actual: string | null;
  cantidad_eventos: number;
  cantidad_scans: number;
  aceleracion: number;
  novedad: number;
  recencia_segundos: number;
  recencia_score: number;
  cambio_regimen: boolean;
  direccion_regimen: "mejora" | "deterioro" | "sin_cambio";
  racha_scans: number;
  score_promedio: number;
  ranking_score: number;
  tendencia: "subiendo" | "bajando" | "plano";
};

export async function fetchAlertsAnalysis(limit = 5000): Promise<AlertAnalysisRow[]> {
  const q = new URLSearchParams({ limit: String(limit) });
  const res = await fetch(`${BASE}/alerts-analysis?${q.toString()}`);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${await readHttpErrorMessage(res)}`);
  }
  const data: unknown = await res.json().catch(() => null);
  if (!Array.isArray(data)) {
    throw new Error("Respuesta inesperada: se esperaba un array");
  }
  return data as AlertAnalysisRow[];
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

export type CedearRatioEstado = "ok" | "pendiente_validar" | "revisar";

/**
 * Fila GET /cedears (alias JSON TotalScore / SignalState desde el backend).
 */
export type CedearRow = {
  ticker_usa: string;
  ticker_cedear_ars: string;
  ticker_cedear_usd: string;
  /** cedears_por_accion_usa del maestro JSON (no inferido). */
  ratio: number;
  fuente_ratio?: string | null;
  fecha_validacion_ratio?: string | null;
  estado_ratio: CedearRatioEstado;
  dias_desde_validacion: number | null;
  precio_cedear_ars: number | null;
  precio_cedear_usd: number | null;
  ccl_implicito: number | null;
  precio_usa_real: number | null;
  precio_implicito_usd: number | null;
  gap_pct: number | null;
  TotalScore: number | null;
  SignalState: string | null;
  /** SI: datos USA desde el radar; NO: precio USA spot (sin score/señal del radar). */
  mod_usa: "SI" | "NO";
  /** Origen de los precios locales CEDEAR ($ y USD): ambos Cocos, o hubo fallback Yahoo. */
  fuente_cedear: "Cocos" | "Yahoo";
};

function isNullableNumber(v: unknown): v is number | null {
  return v === null || (typeof v === "number" && !Number.isNaN(v));
}

function isNullableInt(v: unknown): v is number | null {
  if (v === null) {
    return true;
  }
  if (typeof v !== "number" || !Number.isFinite(v)) {
    return false;
  }
  return Number.isInteger(v);
}

function isCedearRatioEstado(v: unknown): v is CedearRatioEstado {
  return v === "ok" || v === "pendiente_validar" || v === "revisar";
}

function isCedearRow(x: unknown): x is CedearRow {
  if (x === null || typeof x !== "object") {
    return false;
  }
  const o = x as Record<string, unknown>;
  const fr = o.fuente_ratio;
  const fd = o.fecha_validacion_ratio;
  if (fr !== undefined && fr !== null && typeof fr !== "string") {
    return false;
  }
  if (fd !== undefined && fd !== null && typeof fd !== "string") {
    return false;
  }
  return (
    typeof o.ticker_usa === "string" &&
    typeof o.ticker_cedear_ars === "string" &&
    typeof o.ticker_cedear_usd === "string" &&
    typeof o.ratio === "number" &&
    isCedearRatioEstado(o.estado_ratio) &&
    isNullableInt(o.dias_desde_validacion) &&
    isNullableNumber(o.precio_cedear_ars) &&
    isNullableNumber(o.precio_cedear_usd) &&
    isNullableNumber(o.ccl_implicito) &&
    isNullableNumber(o.precio_usa_real) &&
    isNullableNumber(o.precio_implicito_usd) &&
    isNullableNumber(o.gap_pct) &&
    isNullableNumber(o.TotalScore) &&
    (o.SignalState === null || typeof o.SignalState === "string") &&
    (o.mod_usa === "SI" || o.mod_usa === "NO") &&
    (o.fuente_cedear === "Cocos" || o.fuente_cedear === "Yahoo")
  );
}

export type CedearsCocosGateCode = "cocos_token_required" | "cocos_auth_failed";

/** Resultado GET /cedears: filas, falta token Cocos, o sin export. */
export type CedearsFetchResult =
  | { kind: "rows"; rows: CedearRow[] }
  | { kind: "need_cocos_token"; code: CedearsCocosGateCode; message: string }
  | { kind: "no_export" };

function parseCedearsCocos403(raw: unknown): { code: CedearsCocosGateCode; message: string } {
  let code: CedearsCocosGateCode = "cocos_token_required";
  let message = "Se requiere token de Cocos para cotizar CEDEAR.";
  const detail = raw && typeof raw === "object" && "detail" in raw ? (raw as { detail: unknown }).detail : null;
  if (detail && typeof detail === "object") {
    const o = detail as { code?: unknown; message?: unknown };
    if (o.code === "cocos_auth_failed" || o.code === "cocos_token_required") {
      code = o.code;
    }
    if (typeof o.message === "string" && o.message.trim()) {
      message = o.message.trim();
    }
  }
  return { code, message };
}

/**
 * POST /cedears/cocos-token — guarda JWT Cocos en memoria del backend.
 */
export async function postCedearsCocosToken(token: string): Promise<void> {
  const res = await fetch(`${BASE}/cedears/cocos-token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: token.trim() }),
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${await readHttpErrorMessage(res)}`);
  }
}

/**
 * GET /cedears — vista CEDEAR sobre el último radar USA.
 * no_export: 404. need_cocos_token: 403 con código Cocos.
 */
export async function fetchCedears(): Promise<CedearsFetchResult> {
  const res = await fetch(`${BASE}/cedears`);
  if (res.status === 404) {
    return { kind: "no_export" };
  }
  if (res.status === 403) {
    const raw: unknown = await res.json().catch(() => null);
    const { code, message } = parseCedearsCocos403(raw);
    return { kind: "need_cocos_token", code, message };
  }
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${await readHttpErrorMessage(res)}`);
  }
  const data: unknown = await res.json().catch(() => null);
  if (!Array.isArray(data)) {
    throw new Error("Respuesta inesperada: se esperaba un array de CEDEAR");
  }
  const out: CedearRow[] = [];
  for (const item of data) {
    if (!isCedearRow(item)) {
      throw new Error("Respuesta inesperada: fila CEDEAR inválida");
    }
    out.push(item);
  }
  return { kind: "rows", rows: out };
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
