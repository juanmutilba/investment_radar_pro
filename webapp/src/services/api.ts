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
  last_scan?: ScanMetrics;
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

export type ScanMetrics = {
  scan_finished_at: string;
  usa_scan_seconds: number;
  arg_scan_seconds: number;
  cedear_scan_seconds: number;
  alerts_seconds: number;
  summary_seconds: number | null;
  total_scan_seconds: number;
  usa_total_activos: number;
  arg_total_activos: number;
  cedear_total_activos: number;
  usa_alertas: number;
  arg_alertas: number;
  cedear_alertas: number;
};

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
  /** Origen de los precios locales CEDEAR ($ y USD). */
  fuente_cedear: "Yahoo";
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
    o.fuente_cedear === "Yahoo"
  );
}

/** Resultado GET /cedears: filas o sin export. */
export type CedearsFetchResult = { kind: "rows"; rows: CedearRow[] } | { kind: "no_export" };

/** Una sola petición HTTP en vuelo: evita GET duplicados (p. ej. React StrictMode en dev). */
let cedearsFetchInflight: Promise<CedearsFetchResult> | null = null;

type CedearsCache = { data: CedearsFetchResult; cached_at_ms: number; source_scan_finished_at?: string | null };
let cedearsCache: CedearsCache | null = null;
const CEDEARS_CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutos
const CEDEARS_CACHE_STORAGE_KEY = "investment_radar_pro:cedears_cache:v1";

export type CedearsBuildMeta = {
  scan_finished_at: string | null;
  row_count: number | null;
  cedear_alertas: number | null;
  source_export_file?: string | null;
};

function isCedearsBuildMeta(data: unknown): data is CedearsBuildMeta {
  if (data === null || typeof data !== "object") {
    return false;
  }
  const o = data as Record<string, unknown>;
  const sf = o.scan_finished_at;
  const rc = o.row_count;
  const ca = o.cedear_alertas;
  const sef = o.source_export_file;
  if (!(sf === null || typeof sf === "string")) {
    return false;
  }
  if (!(rc === null || typeof rc === "number")) {
    return false;
  }
  if (!(ca === null || typeof ca === "number")) {
    return false;
  }
  if ("source_export_file" in o && !(sef === null || sef === undefined || typeof sef === "string")) {
    return false;
  }
  return true;
}

export async function fetchCedearsBuildMeta(): Promise<CedearsBuildMeta | null> {
  const res = await fetch(`${BASE}/cedears/build-meta`);
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${await readHttpErrorMessage(res)}`);
  }
  const data: unknown = await res.json().catch(() => null);
  if (!isCedearsBuildMeta(data)) {
    throw new Error("Respuesta inesperada: cedears/build-meta");
  }
  return data;
}

function readCedearsCacheFromSessionStorage(nowMs: number): CedearsCache | null {
  try {
    if (typeof sessionStorage === "undefined") {
      return null;
    }
    const raw = sessionStorage.getItem(CEDEARS_CACHE_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed: unknown = JSON.parse(raw);
    if (parsed === null || typeof parsed !== "object") {
      return null;
    }
    const o = parsed as { cached_at_ms?: unknown; data?: unknown; source_scan_finished_at?: unknown };
    if (typeof o.cached_at_ms !== "number" || !Number.isFinite(o.cached_at_ms)) {
      return null;
    }
    if (nowMs - o.cached_at_ms > CEDEARS_CACHE_TTL_MS) {
      return null;
    }
    const src =
      o.source_scan_finished_at === null || o.source_scan_finished_at === undefined
        ? null
        : typeof o.source_scan_finished_at === "string"
          ? o.source_scan_finished_at
          : null;
    const d = o.data as { kind?: unknown; rows?: unknown } | undefined;
    if (d?.kind === "no_export") {
      return { cached_at_ms: o.cached_at_ms, data: { kind: "no_export" }, source_scan_finished_at: src };
    }
    if (d?.kind === "rows" && Array.isArray(d.rows)) {
      const out: CedearRow[] = [];
      for (const item of d.rows) {
        if (!isCedearRow(item)) {
          return null;
        }
        out.push(item);
      }
      return { cached_at_ms: o.cached_at_ms, data: { kind: "rows", rows: out }, source_scan_finished_at: src };
    }
  } catch {
    return null;
  }
  return null;
}

function writeCedearsCacheToSessionStorage(cache: CedearsCache): void {
  try {
    if (typeof sessionStorage === "undefined") {
      return;
    }
    sessionStorage.setItem(CEDEARS_CACHE_STORAGE_KEY, JSON.stringify(cache));
  } catch {
    // ignore
  }
}

export function peekCedearsCache(): CedearsFetchResult | null {
  const now = Date.now();
  if (cedearsCache !== null && now - cedearsCache.cached_at_ms <= CEDEARS_CACHE_TTL_MS) {
    return cedearsCache.data;
  }
  const fromStorage = readCedearsCacheFromSessionStorage(now);
  if (fromStorage !== null) {
    cedearsCache = fromStorage;
    return fromStorage.data;
  }
  return null;
}

/**
 * GET /cedears — vista CEDEAR sobre el último radar USA.
 * no_export: 404.
 */
export async function fetchCedears(opts?: { force?: boolean }): Promise<CedearsFetchResult> {
  const force = Boolean(opts?.force);
  const now = Date.now();

  const shouldInvalidateAgainstMeta = async (cur: CedearsCache | null): Promise<boolean> => {
    if (force) {
      return false;
    }
    try {
      const meta = await fetchCedearsBuildMeta();
      const m = meta?.scan_finished_at?.trim() ?? "";
      if (!m) {
        return false;
      }
      const s = cur?.source_scan_finished_at?.trim() ?? "";
      if (!s) {
        return true;
      }
      return m !== s;
    } catch {
      return false;
    }
  };

  if (!force && cedearsCache !== null && now - cedearsCache.cached_at_ms <= CEDEARS_CACHE_TTL_MS) {
    if (await shouldInvalidateAgainstMeta(cedearsCache)) {
      cedearsCache = null;
    } else {
      return cedearsCache.data;
    }
  }
  if (!force) {
    const fromStorage = readCedearsCacheFromSessionStorage(now);
    if (fromStorage !== null) {
      if (await shouldInvalidateAgainstMeta(fromStorage)) {
        cedearsCache = null;
      } else {
        cedearsCache = fromStorage;
        return fromStorage.data;
      }
    }
  }
  if (cedearsFetchInflight !== null) {
    return cedearsFetchInflight;
  }
  const p = (async (): Promise<CedearsFetchResult> => {
    try {
      let metaScanAt: string | null = null;
      try {
        const meta = await fetchCedearsBuildMeta();
        metaScanAt = meta?.scan_finished_at?.trim() ? meta.scan_finished_at : null;
      } catch {
        metaScanAt = null;
      }

      const q = force ? "?force=1" : "";
      const res = await fetch(`${BASE}/cedears${q}`);
      if (res.status === 404) {
        const out: CedearsFetchResult = { kind: "no_export" };
        cedearsCache = { data: out, cached_at_ms: Date.now(), source_scan_finished_at: metaScanAt };
        writeCedearsCacheToSessionStorage(cedearsCache);
        return out;
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
      const result: CedearsFetchResult = { kind: "rows", rows: out };
      cedearsCache = { data: result, cached_at_ms: Date.now(), source_scan_finished_at: metaScanAt };
      writeCedearsCacheToSessionStorage(cedearsCache);
      return result;
    } finally {
      cedearsFetchInflight = null;
    }
  })();
  cedearsFetchInflight = p;
  return p;
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
  scan_metrics?: ScanMetrics;
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

// --- Cartera (SQLite) ---

export type PortfolioAssetType = "USA" | "Argentina" | "CEDEAR";

export type PortfolioOpenRow = {
  id: number;
  ticker: string;
  asset_type: PortfolioAssetType;
  quantity: number;
  buy_date: string;
  buy_price_ars: number | null;
  buy_price_usd: number | null;
  tc_mep_compra?: number | null;
  notes: string | null;
  buy_price_cedear_usd?: number | null;
  buy_price_usa?: number | null;
  buy_gap?: number | null;
  score_at_buy: number | null;
  signalstate_at_buy: string | null;
  techscore_at_buy?: number | null;
  fundscore_at_buy?: number | null;
  riskscore_at_buy?: number | null;
  current_score: number | null;
  current_signalstate: string | null;
  current_price_ars: number | null;
  current_price_usd: number | null;
  /** CEDEAR: precio línea CCL (USD) auxiliar; el principal en cartera abierta es current_price_usd (USA). */
  current_price_cedear_usd?: number | null;
  return_pct: number | null;
  days_in_position: number | null;
  buy_alert_label?: string | null;
};

export type PortfolioHistoryRow = {
  id: number;
  ticker: string;
  asset_type: PortfolioAssetType;
  buy_date: string | null;
  sell_date: string | null;
  buy_price_ars: number | null;
  buy_price_usd: number | null;
  sell_price_ars: number | null;
  sell_price_usd: number | null;
  tc_mep_compra?: number | null;
  tc_mep_venta?: number | null;
  score_at_buy: number | null;
  score_at_sell: number | null;
  signalstate_at_buy: string | null;
  signalstate_at_sell: string | null;
  realized_return_pct: number | null;
  realized_return_usd_pct?: number | null;
  holding_days: number | null;
  sell_alert_label?: string | null;
};

export type PortfolioCreatePayload = {
  ticker: string;
  asset_type: PortfolioAssetType;
  quantity: number;
  buy_date: string;
  buy_price_ars?: number | null;
  buy_price_usd?: number | null;
  tc_mep_compra?: number | null;
  notes?: string | null;
};

export type PortfolioClosePayload = {
  sell_date: string;
  sell_price_ars?: number | null;
  sell_price_usd?: number | null;
  sell_notes?: string | null;
  tc_mep_venta?: number | null;
  sell_price_cedear_usd?: number | null;
  sell_price_usa?: number | null;
  sell_gap?: number | null;
};

export async function fetchPortfolioOpen(): Promise<PortfolioOpenRow[]> {
  const res = await fetch(`${BASE}/portfolio/positions/open`);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${await readHttpErrorMessage(res)}`);
  }
  const data: unknown = await res.json().catch(() => null);
  if (!Array.isArray(data)) {
    throw new Error("Respuesta inesperada: portfolio open");
  }
  return data as PortfolioOpenRow[];
}

export async function fetchPortfolioHistory(): Promise<PortfolioHistoryRow[]> {
  const res = await fetch(`${BASE}/portfolio/positions/history`);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${await readHttpErrorMessage(res)}`);
  }
  const data: unknown = await res.json().catch(() => null);
  if (!Array.isArray(data)) {
    throw new Error("Respuesta inesperada: portfolio history");
  }
  return data as PortfolioHistoryRow[];
}

export async function createPortfolioPosition(payload: PortfolioCreatePayload): Promise<{ id: number }> {
  const res = await fetch(`${BASE}/portfolio/positions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(await readHttpErrorMessage(res));
  }
  const data: unknown = await res.json().catch(() => null);
  if (data === null || typeof data !== "object" || typeof (data as { id?: unknown }).id !== "number") {
    throw new Error("Respuesta inesperada: crear posición");
  }
  return { id: (data as { id: number }).id };
}

export async function closePortfolioPosition(positionId: number, payload: PortfolioClosePayload): Promise<void> {
  const res = await fetch(`${BASE}/portfolio/positions/${positionId}/close`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(await readHttpErrorMessage(res));
  }
}

// --- Autocomplete ticker (Cartera) ---

export type PortfolioTickersAutocompleteResponse = string[] | { items: string[] };

function coerceStringArray(v: unknown): string[] | null {
  if (!Array.isArray(v)) return null;
  const out: string[] = [];
  for (const it of v) {
    if (typeof it === "string" && it.trim()) out.push(it);
  }
  return out;
}

export async function fetchPortfolioTickersAutocomplete(
  assetType: PortfolioAssetType,
  q: string,
  opts?: { limit?: number; signal?: AbortSignal },
): Promise<string[]> {
  const query = q.trim();
  if (!query) return [];
  const limit = typeof opts?.limit === "number" && Number.isFinite(opts.limit) ? String(opts.limit) : "30";
  const qs = new URLSearchParams({ asset_type: assetType, q: query, limit });
  const res = await fetch(`${BASE}/portfolio/tickers/autocomplete?${qs.toString()}`, { signal: opts?.signal });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${await readHttpErrorMessage(res)}`);
  }
  const data: unknown = await res.json().catch(() => null);
  const direct = coerceStringArray(data);
  if (direct) return direct;
  if (data !== null && typeof data === "object" && "items" in data) {
    const items = coerceStringArray((data as { items?: unknown }).items);
    if (items) return items;
  }
  return [];
}
