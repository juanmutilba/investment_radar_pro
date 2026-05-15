import { useCallback, useEffect, useState } from "react";
import type { CSSProperties } from "react";
import {
  closeCryptoPaperPosition,
  getCryptoAnalysis,
  getCryptoOhlcv,
  executeCryptoPaperStrategy,
  getCryptoPaperCycle,
  reviewCryptoPaperExits,
  getCryptoPaperPortfolio,
  getCryptoScan,
  getCryptoStatus,
  getCryptoTicker,
  getCryptoWatchlist,
  openCryptoPaperPositionMarket,
  openCryptoPaperPositionMarketAmount,
  resetCryptoPaperPortfolio,
  type CryptoAnalysisPayload,
  type CryptoAnalysisSignalKind,
  type CryptoOhlcvCandle,
  type CryptoOhlcvResponse,
  type CryptoPaperCycleResponse,
  type CryptoPaperPortfolio,
  type CryptoPaperPosition,
  type CryptoScanRow,
  type CryptoStatusPayload,
  type CryptoTicker,
} from "@/services/api";

const SYM_BTC = "BTC/USDT";
const SYM_ETH = "ETH/USDT";
const ANALYSIS_TF = "1h";
const ANALYSIS_LIMIT = 200;
const STRATEGY_DEFAULT_AMOUNT = 100;
const STRATEGY_DEFAULT_STOP_LOSS = 2;
const STRATEGY_DEFAULT_TAKE_PROFIT = 4;
const STRATEGY_DEFAULT_TRAILING = 1.5;
const STRATEGY_DEFAULT_MAX_POSITIONS = 3;

const dtFmt = new Intl.DateTimeFormat("es-AR", {
  dateStyle: "short",
  timeStyle: "short",
});

const numFmt2 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const numFmt0 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 });

function fmtPrice(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return numFmt2.format(v);
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const s = `${v >= 0 ? "+" : ""}${numFmt2.format(v)}%`;
  return s;
}

function fmtVol(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return numFmt0.format(v);
}

function readTickerLast(t: CryptoTicker): number | null {
  const x = t.last;
  return typeof x === "number" && Number.isFinite(x) ? x : null;
}

function readTickerPct(t: CryptoTicker): number | null {
  const x = t.percentage;
  return typeof x === "number" && Number.isFinite(x) ? x : null;
}

function readTickerVol(t: CryptoTicker): number | null {
  const x = t.baseVolume;
  return typeof x === "number" && Number.isFinite(x) ? x : null;
}

function pctStyle(pct: number | null): CSSProperties {
  if (pct === null || !Number.isFinite(pct)) return { color: "var(--text-muted)" };
  if (pct > 0) return { color: "rgba(21, 128, 61, 0.96)", fontWeight: 700 };
  if (pct < 0) return { color: "rgba(185, 28, 28, 0.96)", fontWeight: 700 };
  return { color: "var(--text-muted)" };
}

function fmtMacd(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toFixed(6);
}

function signalBadgeClass(s: CryptoAnalysisSignalKind): string {
  if (s === "compra_potencial") return "radar-badge radar-badge--conv-alta";
  if (s === "cuidado") return "radar-badge radar-badge--conv-baja";
  return "radar-badge radar-badge--conv-media";
}

function signalLabelEs(s: CryptoAnalysisSignalKind): string {
  if (s === "compra_potencial") return "Compra potencial";
  if (s === "cuidado") return "Cuidado";
  return "Neutral";
}

function fmtUsdt(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `USDT ${numFmt2.format(v)}`;
}

function pnlStyle(v: number | null | undefined): CSSProperties {
  if (v === null || v === undefined || !Number.isFinite(v)) return { color: "var(--text-muted)" };
  if (v > 0) return { color: "rgba(21, 128, 61, 0.96)", fontWeight: 700 };
  if (v < 0) return { color: "rgba(185, 28, 28, 0.96)", fontWeight: 700 };
  return { color: "var(--text-muted)" };
}

function parseBreakEvenPct(triggerStr: string, plusStr: string): { trigger: number; plus: number } | { error: string } {
  const tRaw = triggerStr.trim();
  const trigger = tRaw === "" ? 0 : parseFloat(tRaw.replace(",", "."));
  const plus = plusStr.trim() === "" ? 0 : parseFloat(plusStr.replace(",", "."));
  if (tRaw !== "" && (!Number.isFinite(trigger) || trigger < 0)) {
    return { error: "Break even trigger % inválido" };
  }
  if (!Number.isFinite(plus) || plus < 0) {
    return { error: "Break even plus % inválido" };
  }
  return { trigger, plus };
}

function parseManualRiskPct(
  stopStr: string,
  takeProfitStr: string,
  trailingStr: string,
):
  | { stopLossPct: number; takeProfitPct: number; trailingStopPct: number }
  | { error: string } {
  const parsePct = (raw: string, label: string): number | { error: string } => {
    const t = raw.trim();
    if (t === "") return 0;
    const v = parseFloat(t.replace(",", "."));
    if (!Number.isFinite(v) || v < 0) return { error: `${label} inválido` };
    return v;
  };
  const sl = parsePct(stopStr, "Stop loss %");
  if (typeof sl !== "number") return sl;
  const tp = parsePct(takeProfitStr, "Take profit %");
  if (typeof tp !== "number") return tp;
  const trail = parsePct(trailingStr, "Trailing stop %");
  if (typeof trail !== "number") return trail;
  return { stopLossPct: sl, takeProfitPct: tp, trailingStopPct: trail };
}

function manualRiskApiFields(risk: {
  stopLossPct: number;
  takeProfitPct: number;
  trailingStopPct: number;
}): {
  stop_loss_pct?: number;
  take_profit_pct?: number;
  trailing_stop_pct?: number;
} {
  return {
    stop_loss_pct: risk.stopLossPct > 0 ? risk.stopLossPct : undefined,
    take_profit_pct: risk.takeProfitPct > 0 ? risk.takeProfitPct : undefined,
    trailing_stop_pct: risk.trailingStopPct > 0 ? risk.trailingStopPct : undefined,
  };
}

const TOOLTIP_BE_PENDING =
  "Break-even pendiente: el precio todavía no alcanzó el trigger configurado.";
const TOOLTIP_BE_ACTIVE =
  "Break-even activo: el stop ya fue elevado al piso protegido (entrada + plus %).";
const TOOLTIP_TRAIL_PCT =
  "Trail %: stop dinámico calculado desde el precio máximo alcanzado (máx. × (1 − trail%)).";
const TOOLTIP_TRAIL_ACTIVE = "Trailing activo: el máximo superó la entrada; el piso dinámico puede cerrar la posición.";

function paperTrailingStopPrice(pos: CryptoPaperPosition): number | null {
  const pct = pos.trailing_stop_pct;
  const high = pos.highest_price ?? pos.entry_price;
  if (pct === null || pct === undefined || !Number.isFinite(pct) || pct <= 0) return null;
  if (high === null || high === undefined || !Number.isFinite(high) || high <= 0) return null;
  return high * (1 - pct / 100);
}

function paperTrailingActive(pos: CryptoPaperPosition): boolean {
  const pct = pos.trailing_stop_pct;
  if (pct === null || pct === undefined || !Number.isFinite(pct) || pct <= 0) return false;
  const entry = pos.entry_price;
  const high = pos.highest_price;
  if (!Number.isFinite(entry) || entry <= 0) return false;
  if (high === null || high === undefined || !Number.isFinite(high)) return false;
  return high > entry;
}

function formatPaperExitPolicy(policy: string | null | undefined): string {
  if (!policy?.trim()) return "—";
  const labels: Record<string, string> = {
    stop_loss: "Stop loss",
    take_profit: "Take profit",
    trailing_stop: "Trailing",
    break_even: "Break-even",
  };
  return policy
    .split("+")
    .map((p) => labels[p.trim()] ?? p.trim())
    .join(" · ");
}

function paperProbableExit(pos: CryptoPaperPosition): { label: string; title: string } {
  const cp = pos.current_price;
  if (cp === null || cp === undefined || !Number.isFinite(cp)) {
    return { label: "—", title: "Sin precio de mercado para estimar salida." };
  }

  const sl = pos.stop_loss;
  const tp = pos.take_profit;
  const trailPx = paperTrailingStopPrice(pos);

  if (sl !== null && sl !== undefined && Number.isFinite(sl) && cp <= sl) {
    return {
      label: pos.break_even_active ? "Stop BE (tocado)" : "Stop loss (tocado)",
      title: "El precio actual está en o por debajo del stop loss.",
    };
  }
  if (tp !== null && tp !== undefined && Number.isFinite(tp) && cp >= tp) {
    return { label: "Take profit (tocado)", title: "El precio actual alcanzó o superó el take profit." };
  }
  if (trailPx !== null && Number.isFinite(trailPx) && cp <= trailPx) {
    return {
      label: "Trailing (tocado)",
      title: `Precio actual ≤ trailing (${fmtPrice(trailPx)} desde máx. ${fmtPrice(pos.highest_price)}).`,
    };
  }

  type Candidate = { label: string; distPct: number; title: string };
  const down: Candidate[] = [];
  if (sl !== null && sl !== undefined && Number.isFinite(sl) && sl < cp) {
    down.push({
      label: pos.break_even_active ? "Stop BE" : "Stop loss",
      distPct: ((cp - sl) / cp) * 100,
      title: `Stop en ${fmtPrice(sl)} (${numFmt2.format(((cp - sl) / cp) * 100)}% abajo).`,
    });
  }
  if (trailPx !== null && Number.isFinite(trailPx) && trailPx < cp) {
    down.push({
      label: "Trailing",
      distPct: ((cp - trailPx) / cp) * 100,
      title: `Trailing en ${fmtPrice(trailPx)} (${numFmt2.format(((cp - trailPx) / cp) * 100)}% abajo).`,
    });
  }
  if (tp !== null && tp !== undefined && Number.isFinite(tp) && tp > cp) {
    const distPct = ((tp - cp) / cp) * 100;
    return {
      label: `Take profit (${numFmt2.format(distPct)}%)`,
      title: `Objetivo en ${fmtPrice(tp)} (${numFmt2.format(distPct)}% arriba). Prioridad de revisión: SL → TP → trailing.`,
    };
  }

  if (down.length === 0) {
    return { label: "Sin reglas", title: "No hay stop, trailing ni take profit configurados." };
  }

  const nearest = down.reduce((a, b) => (a.distPct < b.distPct ? a : b));
  const urgency = nearest.distPct < 0.75 ? "muy cerca" : `${numFmt2.format(nearest.distPct)}% abajo`;
  return {
    label: `${nearest.label} (${urgency})`,
    title: `${nearest.title} La revisión automática evalúa stop loss antes que trailing.`,
  };
}

function strategyPrimaryReasonLabel(reason: string | null | undefined): string {
  if (!reason) return "—";
  const labels: Record<string, string> = {
    no_opportunity: "Sin oportunidades (compra_potencial)",
    score_below_min: "Score por debajo del mínimo",
    already_open: "Posición ya abierta en el símbolo",
    cooldown_symbol: "Cooldown activo para el símbolo",
    btc_trend_filter: "BTC sin tendencia alcista",
    opened: "Se abrió posición",
    max_one_per_run: "Máximo 1 entrada por ejecución",
    max_open_positions: "Máximo de posiciones abiertas",
    no_entry: "Sin entrada tras evaluar candidatos",
  };
  return labels[reason] ?? reason;
}

function strategyResultBannerStyle(
  cycle: CryptoPaperCycleResponse,
  lastMode: "search" | "execute",
): CSSProperties {
  const base: CSSProperties = {
    marginBottom: "0.85rem",
    padding: "0.65rem 0.85rem",
    borderRadius: "8px",
    border: "1px solid var(--border)",
    fontSize: "0.9rem",
  };
  if (lastMode === "search") {
    return {
      ...base,
      background: "rgba(100, 116, 139, 0.12)",
      borderColor: "rgba(100, 116, 139, 0.35)",
      color: "var(--text-muted)",
    };
  }
  const opened = cycle.opened_count ?? 0;
  if (cycle.status === "opened" || opened > 0) {
    return {
      ...base,
      background: "rgba(21, 128, 61, 0.1)",
      borderColor: "rgba(21, 128, 61, 0.45)",
      color: "rgba(21, 128, 61, 0.96)",
    };
  }
  if (cycle.status === "no_opportunity" || (cycle.status === "skipped" && opened === 0)) {
    return {
      ...base,
      background: "rgba(194, 65, 12, 0.1)",
      borderColor: "rgba(194, 65, 12, 0.45)",
      color: "rgba(194, 65, 12, 0.96)",
    };
  }
  if (cycle.status === "error") {
    return {
      ...base,
      background: "rgba(185, 28, 28, 0.1)",
      borderColor: "rgba(185, 28, 28, 0.45)",
      color: "rgba(185, 28, 28, 0.96)",
    };
  }
  return base;
}

function CryptoAnalysisCard({ title, payload }: { title: string; payload: CryptoAnalysisPayload | null }) {
  if (!payload) {
    return (
      <div className="card">
        <h3 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
          {title}
        </h3>
        <p className="msg-muted" style={{ margin: 0 }}>
          Sin datos de análisis.
        </p>
      </div>
    );
  }
  const a = payload.analysis;
  return (
    <div className="card">
      <h3 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
        {title}
      </h3>
      <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.65rem", fontSize: "0.82rem" }}>
        {payload.symbol} · {payload.timeframe} · {payload.limit} velas
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.45rem", alignItems: "center", marginBottom: "0.75rem" }}>
        <span className={signalBadgeClass(a.signal)} title="Señal heurística (sin órdenes)">
          {signalLabelEs(a.signal)}
        </span>
        <span className="radar-badge radar-badge--conv-media">Score {a.score}</span>
        <span className="radar-badge radar-badge--conv-media">Tendencia: {a.trend}</span>
        <span className="radar-badge radar-badge--conv-media">Momentum: {a.momentum}</span>
        <span className="radar-badge radar-badge--conv-media">Riesgo: {a.risk}</span>
      </div>
      <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
        <div className="stat__label">Precio (último cierre)</div>
        <div className="stat__value">{fmtPrice(a.price)}</div>
      </div>
      <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
        <div className="stat__label">RSI 14</div>
        <div className="stat__value">{Number.isFinite(a.rsi_14) ? a.rsi_14.toFixed(2) : "—"}</div>
      </div>
      <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
        <div className="stat__label">SMA 20</div>
        <div className="stat__value">{fmtPrice(a.sma_20)}</div>
      </div>
      <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
        <div className="stat__label">SMA 50</div>
        <div className="stat__value">{fmtPrice(a.sma_50)}</div>
      </div>
      <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
        <div className="stat__label">EMA 20</div>
        <div className="stat__value">{fmtPrice(a.ema_20)}</div>
      </div>
      <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
        <div className="stat__label">MACD hist</div>
        <div className="stat__value">{fmtMacd(a.macd_hist)}</div>
      </div>
      <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
        <div className="stat__label">MACD / señal</div>
        <div className="stat__value">
          {fmtMacd(a.macd)} / {fmtMacd(a.macd_signal)}
        </div>
      </div>
    </div>
  );
}

export function CryptoPage() {
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [fatalError, setFatalError] = useState<string | null>(null);
  const [status, setStatus] = useState<CryptoStatusPayload | null>(null);
  const [btc, setBtc] = useState<CryptoTicker | null>(null);
  const [eth, setEth] = useState<CryptoTicker | null>(null);
  const [ohlcv, setOhlcv] = useState<CryptoOhlcvResponse | null>(null);
  const [analysisBtc, setAnalysisBtc] = useState<CryptoAnalysisPayload | null>(null);
  const [analysisEth, setAnalysisEth] = useState<CryptoAnalysisPayload | null>(null);
  const [tickerError, setTickerError] = useState<string | null>(null);
  const [watchlistCount, setWatchlistCount] = useState<number | null>(null);
  const [scanRows, setScanRows] = useState<CryptoScanRow[] | null>(null);
  const [scanLoading, setScanLoading] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [paper, setPaper] = useState<CryptoPaperPortfolio | null>(null);
  const [paperLoading, setPaperLoading] = useState(false);
  const [paperError, setPaperError] = useState<string | null>(null);
  const [paperActionError, setPaperActionError] = useState<string | null>(null);
  const [paperSymbol, setPaperSymbol] = useState("BTC/USDT");
  const [paperAmountUsdt, setPaperAmountUsdt] = useState("");
  const [paperQty, setPaperQty] = useState("");
  const [paperReason, setPaperReason] = useState("");
  const [paperOpening, setPaperOpening] = useState(false);
  const [paperClosingId, setPaperClosingId] = useState<string | null>(null);
  const [strategyTf, setStrategyTf] = useState("1h");
  const [strategyAmountUsdt, setStrategyAmountUsdt] = useState(String(STRATEGY_DEFAULT_AMOUNT));
  const [strategyCycle, setStrategyCycle] = useState<CryptoPaperCycleResponse | null>(null);
  const [strategyLoading, setStrategyLoading] = useState(false);
  const [strategyExecuting, setStrategyExecuting] = useState(false);
  const [strategyError, setStrategyError] = useState<string | null>(null);
  const [strategyLastMode, setStrategyLastMode] = useState<"search" | "execute">("search");
  const [strategyStopLossPct, setStrategyStopLossPct] = useState(String(STRATEGY_DEFAULT_STOP_LOSS));
  const [strategyTakeProfitPct, setStrategyTakeProfitPct] = useState(String(STRATEGY_DEFAULT_TAKE_PROFIT));
  const [strategyTrailingPct, setStrategyTrailingPct] = useState(String(STRATEGY_DEFAULT_TRAILING));
  const [strategyMaxPositions, setStrategyMaxPositions] = useState(String(STRATEGY_DEFAULT_MAX_POSITIONS));
  const [strategyBreakEvenTriggerPct, setStrategyBreakEvenTriggerPct] = useState("");
  const [strategyBreakEvenPlusPct, setStrategyBreakEvenPlusPct] = useState("0");
  const [strategyCooldownMinutes, setStrategyCooldownMinutes] = useState("0");
  const [strategyRequireBtcTrendUp, setStrategyRequireBtcTrendUp] = useState(false);
  const [strategyMinEntryScore, setStrategyMinEntryScore] = useState("0");
  const [strategyReviewing, setStrategyReviewing] = useState(false);

  const loadPaper = useCallback(async () => {
    setPaperLoading(true);
    setPaperError(null);
    try {
      const p = await getCryptoPaperPortfolio();
      setPaper(p);
    } catch (e: unknown) {
      setPaperError(e instanceof Error ? e.message : "Error al cargar cartera paper");
    } finally {
      setPaperLoading(false);
    }
  }, []);

  const loadScanner = useCallback(async () => {
    setScanLoading(true);
    setScanError(null);
    try {
      const payload = await getCryptoScan(ANALYSIS_TF, ANALYSIS_LIMIT);
      setScanRows(payload.results);
    } catch (e: unknown) {
      setScanError(e instanceof Error ? e.message : "Error al ejecutar el scanner");
    } finally {
      setScanLoading(false);
    }
  }, []);

  const load = useCallback(async (isRefresh: boolean) => {
    if (isRefresh) setRefreshing(true);
    else {
      setLoading(true);
      setFatalError(null);
    }
    setTickerError(null);
    try {
      const results = await Promise.allSettled([
        getCryptoStatus(),
        getCryptoTicker(SYM_BTC),
        getCryptoTicker(SYM_ETH),
        getCryptoOhlcv("BTC/USDT", "1h", 100),
        getCryptoAnalysis(SYM_BTC, ANALYSIS_TF, ANALYSIS_LIMIT),
        getCryptoAnalysis(SYM_ETH, ANALYSIS_TF, ANALYSIS_LIMIT),
      ]);

      const st = results[0];
      if (st.status === "rejected") {
        const msg = st.reason instanceof Error ? st.reason.message : "Error en /crypto/status";
        if (!isRefresh) {
          setFatalError(msg);
          setStatus(null);
          setBtc(null);
          setEth(null);
          setOhlcv(null);
          setAnalysisBtc(null);
          setAnalysisEth(null);
        } else {
          setTickerError(msg);
        }
        return;
      }
      setStatus(st.value);
      setFatalError(null);

      const parts: string[] = [];

      const rBtc = results[1];
      if (rBtc.status === "fulfilled") setBtc(rBtc.value);
      else {
        setBtc(null);
        parts.push(`BTC: ${rBtc.reason instanceof Error ? rBtc.reason.message : "error"}`);
      }
      const rEth = results[2];
      if (rEth.status === "fulfilled") setEth(rEth.value);
      else {
        setEth(null);
        parts.push(`ETH: ${rEth.reason instanceof Error ? rEth.reason.message : "error"}`);
      }
      const rOh = results[3];
      if (rOh.status === "fulfilled") setOhlcv(rOh.value);
      else {
        setOhlcv(null);
        parts.push(`OHLCV: ${rOh.reason instanceof Error ? rOh.reason.message : "error"}`);
      }
      const rAb = results[4];
      if (rAb.status === "fulfilled") setAnalysisBtc(rAb.value);
      else {
        setAnalysisBtc(null);
        parts.push(`Análisis BTC: ${rAb.reason instanceof Error ? rAb.reason.message : "error"}`);
      }
      const rAe = results[5];
      if (rAe.status === "fulfilled") setAnalysisEth(rAe.value);
      else {
        setAnalysisEth(null);
        parts.push(`Análisis ETH: ${rAe.reason instanceof Error ? rAe.reason.message : "error"}`);
      }
      setTickerError(parts.length > 0 ? parts.join(" · ") : null);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Error al cargar datos cripto";
      if (isRefresh) {
        setTickerError(msg);
      } else {
        setFatalError(msg);
        setStatus(null);
        setBtc(null);
        setEth(null);
        setOhlcv(null);
        setAnalysisBtc(null);
        setAnalysisEth(null);
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load(false);
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    getCryptoWatchlist()
      .then((w) => {
        if (!cancelled) setWatchlistCount(w.count);
      })
      .catch(() => {
        if (!cancelled) setWatchlistCount(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    void loadPaper();
  }, [loadPaper]);

  const handleSearchOpportunities = useCallback(async () => {
    if (strategyLoading || strategyExecuting || strategyReviewing) return;
    setStrategyLoading(true);
    setStrategyError(null);
    try {
      const data = await getCryptoPaperCycle(strategyTf.trim() || "1h", ANALYSIS_LIMIT);
      setStrategyLastMode("search");
      setStrategyCycle(data);
    } catch (e: unknown) {
      setStrategyError(e instanceof Error ? e.message : "Error al buscar oportunidades");
    } finally {
      setStrategyLoading(false);
    }
  }, [strategyExecuting, strategyLoading, strategyReviewing, strategyTf]);

  const parseStrategyRiskParams = useCallback(():
    | { ok: false; message: string }
    | {
        ok: true;
        amountUsdt: number;
        stopLossPct: number;
        takeProfitPct: number;
        trailingStopPct: number;
        maxOpenPositions: number;
        breakEvenTriggerPct: number;
        breakEvenPlusPct: number;
        cooldownMinutes: number;
        requireBtcTrendUp: boolean;
        minEntryScore: number;
      } => {
    const amountUsdt = parseFloat(strategyAmountUsdt.replace(",", "."));
    const stopLossPct = parseFloat(strategyStopLossPct.replace(",", "."));
    const takeProfitPct = parseFloat(strategyTakeProfitPct.replace(",", "."));
    const trailingStopPct = parseFloat(strategyTrailingPct.replace(",", "."));
    const maxOpenPositions = parseInt(strategyMaxPositions, 10);
    const cooldownMinutes = parseInt(strategyCooldownMinutes.trim() || "0", 10);
    const minEntryScore = parseFloat(strategyMinEntryScore.replace(",", "."));
    const beParsed = parseBreakEvenPct(strategyBreakEvenTriggerPct, strategyBreakEvenPlusPct);
    if ("error" in beParsed) {
      return { ok: false, message: beParsed.error };
    }
    const breakEvenTriggerPct = beParsed.trigger;
    const breakEvenPlusPct = beParsed.plus;
    if (!Number.isFinite(amountUsdt) || amountUsdt <= 0) {
      return { ok: false, message: "Monto USDT inválido" };
    }
    if (!Number.isFinite(stopLossPct) || stopLossPct < 0) {
      return { ok: false, message: "Stop loss % inválido" };
    }
    if (!Number.isFinite(takeProfitPct) || takeProfitPct < 0) {
      return { ok: false, message: "Take profit % inválido" };
    }
    if (!Number.isFinite(trailingStopPct) || trailingStopPct < 0) {
      return { ok: false, message: "Trailing stop % inválido" };
    }
    if (!Number.isFinite(maxOpenPositions) || maxOpenPositions < 1) {
      return { ok: false, message: "Máx. posiciones inválido" };
    }
    if (!Number.isFinite(cooldownMinutes) || cooldownMinutes < 0) {
      return { ok: false, message: "Cooldown símbolo (min) inválido" };
    }
    if (!Number.isFinite(minEntryScore) || minEntryScore < 0 || minEntryScore > 100) {
      return { ok: false, message: "Score mínimo entrada inválido (0–100)" };
    }
    return {
      ok: true,
      amountUsdt,
      stopLossPct,
      takeProfitPct,
      trailingStopPct,
      maxOpenPositions,
      breakEvenTriggerPct,
      breakEvenPlusPct,
      cooldownMinutes,
      requireBtcTrendUp: strategyRequireBtcTrendUp,
      minEntryScore,
    };
  }, [
    strategyAmountUsdt,
    strategyBreakEvenPlusPct,
    strategyBreakEvenTriggerPct,
    strategyCooldownMinutes,
    strategyMaxPositions,
    strategyMinEntryScore,
    strategyRequireBtcTrendUp,
    strategyStopLossPct,
    strategyTakeProfitPct,
    strategyTrailingPct,
  ]);

  const handleReviewPaperExits = useCallback(async () => {
    if (strategyLoading || strategyExecuting || strategyReviewing) return;
    setStrategyReviewing(true);
    setStrategyError(null);
    try {
      const { actions } = await reviewCryptoPaperExits();
      setStrategyCycle((prev) => ({
        timeframe: strategyTf.trim() || "1h",
        candidates: prev?.candidates ?? [],
        positions_review: prev?.positions_review ?? [],
        actions,
        message:
          actions.length > 0
            ? `Revisión de salidas: ${actions.filter((a) => a.status === "executed").length} cierre(s).`
            : "Revisión de salidas: sin cierres por reglas.",
      }));
      await loadPaper();
    } catch (e: unknown) {
      setStrategyError(e instanceof Error ? e.message : "Error al revisar salidas paper");
    } finally {
      setStrategyReviewing(false);
    }
  }, [loadPaper, strategyExecuting, strategyLoading, strategyReviewing, strategyTf]);

  const handleExecutePaperStrategy = useCallback(async () => {
    if (strategyLoading || strategyExecuting || strategyReviewing) return;
    const risk = parseStrategyRiskParams();
    if (!risk.ok) {
      setStrategyError(risk.message);
      return;
    }
    setStrategyExecuting(true);
    setStrategyError(null);
    try {
      const data = await executeCryptoPaperStrategy({
        timeframe: strategyTf.trim() || "1h",
        limit: ANALYSIS_LIMIT,
        amountUsdt: risk.amountUsdt,
        stopLossPct: risk.stopLossPct,
        takeProfitPct: risk.takeProfitPct,
        trailingStopPct: risk.trailingStopPct,
        maxOpenPositions: risk.maxOpenPositions,
        breakEvenTriggerPct: risk.breakEvenTriggerPct,
        breakEvenPlusPct: risk.breakEvenPlusPct,
        cooldownMinutes: risk.cooldownMinutes,
        requireBtcTrendUp: risk.requireBtcTrendUp,
        minEntryScore: risk.minEntryScore,
      });
      setStrategyLastMode("execute");
      setStrategyCycle(data);
      await loadPaper();
    } catch (e: unknown) {
      setStrategyError(e instanceof Error ? e.message : "Error al ejecutar estrategia paper");
    } finally {
      setStrategyExecuting(false);
    }
  }, [
    loadPaper,
    parseStrategyRiskParams,
    strategyExecuting,
    strategyLoading,
    strategyReviewing,
    strategyTf,
  ]);

  const handleOpenPaperMarketAmount = useCallback(async () => {
    if (paperOpening) return;
    setPaperActionError(null);
    const amount_usdt = parseFloat(paperAmountUsdt.replace(",", "."));
    if (!Number.isFinite(amount_usdt) || amount_usdt <= 0) {
      setPaperActionError("Monto USDT inválido");
      return;
    }
    const riskParsed = parseManualRiskPct(strategyStopLossPct, strategyTakeProfitPct, strategyTrailingPct);
    if ("error" in riskParsed) {
      setPaperActionError(riskParsed.error);
      return;
    }
    const beParsed = parseBreakEvenPct(strategyBreakEvenTriggerPct, strategyBreakEvenPlusPct);
    if ("error" in beParsed) {
      setPaperActionError(beParsed.error);
      return;
    }
    setPaperOpening(true);
    try {
      await openCryptoPaperPositionMarketAmount({
        symbol: paperSymbol.trim(),
        side: "long",
        amount_usdt,
        reason: paperReason.trim() || "entrada paper por monto",
        ...manualRiskApiFields(riskParsed),
        break_even_trigger_pct: beParsed.trigger > 0 ? beParsed.trigger : undefined,
        break_even_plus_pct: beParsed.plus,
      });
      setPaperAmountUsdt("");
      setPaperReason("");
      await loadPaper();
    } catch (e: unknown) {
      setPaperActionError(e instanceof Error ? e.message : "Error al abrir posición paper");
    } finally {
      setPaperOpening(false);
    }
  }, [
    loadPaper,
    paperAmountUsdt,
    paperOpening,
    paperReason,
    paperSymbol,
    strategyBreakEvenPlusPct,
    strategyBreakEvenTriggerPct,
    strategyStopLossPct,
    strategyTakeProfitPct,
    strategyTrailingPct,
  ]);

  const handleOpenPaperMarketQty = useCallback(async () => {
    if (paperOpening) return;
    setPaperActionError(null);
    const quantity = parseFloat(paperQty.replace(",", "."));
    if (!Number.isFinite(quantity) || quantity <= 0) {
      setPaperActionError("Cantidad inválida");
      return;
    }
    const riskParsed = parseManualRiskPct(strategyStopLossPct, strategyTakeProfitPct, strategyTrailingPct);
    if ("error" in riskParsed) {
      setPaperActionError(riskParsed.error);
      return;
    }
    const beParsed = parseBreakEvenPct(strategyBreakEvenTriggerPct, strategyBreakEvenPlusPct);
    if ("error" in beParsed) {
      setPaperActionError(beParsed.error);
      return;
    }
    setPaperOpening(true);
    try {
      await openCryptoPaperPositionMarket({
        symbol: paperSymbol.trim(),
        side: "long",
        quantity,
        reason: paperReason.trim() || "entrada manual paper a mercado",
        ...manualRiskApiFields(riskParsed),
        break_even_trigger_pct: beParsed.trigger > 0 ? beParsed.trigger : undefined,
        break_even_plus_pct: beParsed.plus,
      });
      setPaperQty("");
      await loadPaper();
    } catch (e: unknown) {
      setPaperActionError(e instanceof Error ? e.message : "Error al abrir posición paper");
    } finally {
      setPaperOpening(false);
    }
  }, [
    loadPaper,
    paperOpening,
    paperQty,
    paperReason,
    paperSymbol,
    strategyBreakEvenPlusPct,
    strategyBreakEvenTriggerPct,
    strategyStopLossPct,
    strategyTakeProfitPct,
    strategyTrailingPct,
  ]);

  const handleClosePaper = useCallback(
    async (pos: CryptoPaperPosition) => {
      if (paperClosingId !== null) return;
      setPaperActionError(null);
      let price = pos.current_price ?? null;
      if (price === null || !Number.isFinite(price)) {
        const raw = window.prompt(
          `Precio de cierre USDT para ${pos.symbol}:`,
          String(pos.entry_price),
        );
        if (raw === null) return;
        price = parseFloat(raw.replace(",", "."));
        if (!Number.isFinite(price) || price <= 0) {
          setPaperActionError("Precio de cierre inválido");
          return;
        }
      }
      setPaperClosingId(pos.id);
      try {
        await closeCryptoPaperPosition({
          position_id: pos.id,
          price,
          reason: "cierre_manual_paper",
        });
        await loadPaper();
      } catch (e: unknown) {
        setPaperActionError(e instanceof Error ? e.message : "Error al cerrar posición paper");
      } finally {
        setPaperClosingId(null);
      }
    },
    [loadPaper, paperClosingId],
  );

  const handleResetPaper = useCallback(async () => {
    if (!window.confirm("¿Resetear la cartera paper? Se borran posiciones y trades simulados.")) {
      return;
    }
    setPaperActionError(null);
    try {
      const p = await resetCryptoPaperPortfolio(10000);
      setPaper(p);
    } catch (e: unknown) {
      setPaperActionError(e instanceof Error ? e.message : "Error al resetear cartera paper");
    }
  }, []);

  const statusHeadline = fatalError !== null ? "Error" : status !== null ? "Conectado" : "—";

  return (
    <>
      <h1 className="page-title">Cripto</h1>
      <p className="page-desc" style={{ maxWidth: "48rem" }}>
        Vista de solo lectura vía Binance (ccxt): estado, precios, señales, scanner y cartera paper simulada.
        Sin órdenes reales en Binance.
      </p>

      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap", marginBottom: "1rem" }}>
        <button type="button" className="radar-refresh-btn" onClick={() => void load(true)} disabled={loading || refreshing}>
          {refreshing ? "Actualizando…" : "Actualizar"}
        </button>
        {tickerError ? (
          <span className="msg-error" style={{ fontSize: "0.875rem" }}>
            {tickerError}
          </span>
        ) : null}
      </div>

      {loading && <p className="msg-muted">Cargando…</p>}
      {fatalError && !loading && <p className="msg-error">{fatalError}</p>}

      {!loading && fatalError === null && status && (
        <div className="card" style={{ marginBottom: "1rem" }}>
          <h2 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.65rem" }}>
            Estado Binance
          </h2>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", alignItems: "center", marginBottom: "0.75rem" }}>
            <span
              className={`radar-badge ${statusHeadline === "Error" ? "radar-badge--conv-baja" : "radar-badge--conv-alta"}`}
              title="Respuesta del backend /crypto/status"
            >
              {statusHeadline}
            </span>
            <span className="radar-badge radar-badge--conv-media" title="CRYPTO_TRADING_ENABLED en .env">
              Trading UI: {status.trading_enabled ? "habilitado" : "deshabilitado"}
            </span>
            <span className="radar-badge radar-badge--conv-media" title="BINANCE_TESTNET en .env">
              Testnet: {status.testnet ? "sí" : "no"}
            </span>
            <span
              className={`radar-badge ${status.can_read_balance ? "radar-badge--conv-alta" : "radar-badge--conv-baja"}`}
              title="Lectura de balance (credenciales)"
            >
              Balance: {status.can_read_balance ? "OK" : "no OK"}
            </span>
          </div>
          <p className="msg-muted" style={{ margin: 0, fontSize: "0.9rem" }}>
            {status.message}
          </p>
        </div>
      )}

      {!loading && fatalError === null && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
            gap: "1rem",
            marginBottom: "1rem",
          }}
        >
          <div className="card">
            <h3 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
              {SYM_BTC}
            </h3>
            <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
              <div className="stat__label">Último</div>
              <div className="stat__value">{fmtPrice(btc ? readTickerLast(btc) : null)}</div>
            </div>
            <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
              <div className="stat__label">Variación (24h ref.)</div>
              <div className="stat__value" style={pctStyle(btc ? readTickerPct(btc) : null)}>
                {fmtPct(btc ? readTickerPct(btc) : null)}
              </div>
            </div>
            <div className="stat dashboard-stat">
              <div className="stat__label">Volumen (base)</div>
              <div className="stat__value">{fmtVol(btc ? readTickerVol(btc) : null)}</div>
            </div>
          </div>
          <div className="card">
            <h3 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
              {SYM_ETH}
            </h3>
            <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
              <div className="stat__label">Último</div>
              <div className="stat__value">{fmtPrice(eth ? readTickerLast(eth) : null)}</div>
            </div>
            <div className="stat dashboard-stat" style={{ marginBottom: "0.35rem" }}>
              <div className="stat__label">Variación (24h ref.)</div>
              <div className="stat__value" style={pctStyle(eth ? readTickerPct(eth) : null)}>
                {fmtPct(eth ? readTickerPct(eth) : null)}
              </div>
            </div>
            <div className="stat dashboard-stat">
              <div className="stat__label">Volumen (base)</div>
              <div className="stat__value">{fmtVol(eth ? readTickerVol(eth) : null)}</div>
            </div>
          </div>
        </div>
      )}

      {!loading && fatalError === null && (
        <div style={{ marginBottom: "1rem" }}>
          <h2 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.65rem" }}>
            Señales técnicas
          </h2>
          <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.75rem", maxWidth: "48rem", fontSize: "0.9rem" }}>
            Indicadores calculados en backend (SMA, EMA, RSI, MACD) sobre OHLCV; clasificación orientativa, no
            recomendación de inversión.
          </p>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
              gap: "1rem",
            }}
          >
            <CryptoAnalysisCard title="BTC/USDT" payload={analysisBtc} />
            <CryptoAnalysisCard title="ETH/USDT" payload={analysisEth} />
          </div>
        </div>
      )}

      {!loading && fatalError === null && (
        <div className="card" style={{ marginBottom: "1rem" }}>
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              gap: "0.75rem",
              marginBottom: "0.75rem",
            }}
          >
            <h2 className="dashboard-section-title" style={{ margin: 0, flex: "1 1 auto" }}>
              Scanner cripto
            </h2>
            <button
              type="button"
              className="radar-refresh-btn"
              onClick={() => void loadScanner()}
              disabled={scanLoading}
            >
              {scanLoading ? "Escaneando…" : "Actualizar scanner"}
            </button>
          </div>
          <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.75rem", maxWidth: "48rem", fontSize: "0.9rem" }}>
            Ranking por score sobre la watchlist
            {watchlistCount !== null ? ` (${watchlistCount} pares)` : ""} · {ANALYSIS_TF} · {ANALYSIS_LIMIT} velas.
            Los errores por símbolo no detienen el resto.
          </p>
          {scanError ? (
            <p className="msg-error" style={{ fontSize: "0.875rem", marginBottom: "0.65rem" }}>
              {scanError}
            </p>
          ) : null}
          {scanLoading && scanRows === null ? <p className="msg-muted">Ejecutando scanner…</p> : null}
          {!scanLoading && scanRows === null && !scanError ? (
            <p className="msg-muted">Pulsá «Actualizar scanner» para analizar todos los pares de la watchlist.</p>
          ) : null}
          {scanRows && scanRows.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Símbolo</th>
                    <th style={{ textAlign: "right" }}>Precio</th>
                    <th style={{ textAlign: "right" }}>Score</th>
                    <th>Señal</th>
                    <th>Tendencia</th>
                    <th>Momentum</th>
                    <th>Riesgo</th>
                    <th style={{ textAlign: "right" }}>RSI</th>
                    <th style={{ textAlign: "right" }}>MACD Hist</th>
                    <th>Error</th>
                  </tr>
                </thead>
                <tbody>
                  {scanRows.map((row) => {
                    const hasErr = Boolean(row.error);
                    return (
                      <tr key={row.symbol} title={row.error ?? undefined}>
                        <td>
                          <strong>{row.symbol}</strong>
                        </td>
                        <td style={{ textAlign: "right" }}>{fmtPrice(row.price)}</td>
                        <td style={{ textAlign: "right" }}>{row.score !== null ? row.score : "—"}</td>
                        <td>
                          {row.signal ? (
                            <span className={signalBadgeClass(row.signal)}>{signalLabelEs(row.signal)}</span>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td>{row.trend ?? "—"}</td>
                        <td>{row.momentum ?? "—"}</td>
                        <td>{row.risk ?? "—"}</td>
                        <td style={{ textAlign: "right" }}>
                          {row.rsi_14 !== null ? row.rsi_14.toFixed(2) : "—"}
                        </td>
                        <td style={{ textAlign: "right" }}>{fmtMacd(row.macd_hist)}</td>
                        <td className={hasErr ? "msg-error" : "msg-muted"} style={{ fontSize: "0.82rem", maxWidth: "14rem" }}>
                          {row.error ?? "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      )}

      <div className="card" style={{ marginBottom: "1rem" }}>
        <h2 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.65rem" }}>
          Estrategia paper
        </h2>
        <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.75rem", maxWidth: "48rem", fontSize: "0.9rem" }}>
          Escanea señales compra_potencial en la watchlist. Buscar no abre posiciones; ejecutar abre paper
          simulado por monto USDT (sin órdenes reales en Binance).
        </p>
        <div className="radar-toolbar" style={{ marginBottom: "0.75rem" }}>
          <label className="radar-toolbar__field">
            <span className="radar-toolbar__label">Timeframe</span>
            <input
              className="radar-toolbar__input"
              value={strategyTf}
              onChange={(ev) => setStrategyTf(ev.target.value)}
              placeholder="1h"
            />
          </label>
          <label className="radar-toolbar__field">
            <span className="radar-toolbar__label">Monto USDT</span>
            <input
              className="radar-toolbar__input"
              type="text"
              inputMode="decimal"
              value={strategyAmountUsdt}
              onChange={(ev) => setStrategyAmountUsdt(ev.target.value)}
              placeholder="100"
            />
          </label>
          <label className="radar-toolbar__field">
            <span className="radar-toolbar__label">Stop loss %</span>
            <input
              className="radar-toolbar__input"
              type="text"
              inputMode="decimal"
              value={strategyStopLossPct}
              onChange={(ev) => setStrategyStopLossPct(ev.target.value)}
              placeholder="2"
            />
          </label>
          <label className="radar-toolbar__field">
            <span className="radar-toolbar__label">Take profit %</span>
            <input
              className="radar-toolbar__input"
              type="text"
              inputMode="decimal"
              value={strategyTakeProfitPct}
              onChange={(ev) => setStrategyTakeProfitPct(ev.target.value)}
              placeholder="4"
            />
          </label>
          <label className="radar-toolbar__field">
            <span className="radar-toolbar__label">Trailing stop %</span>
            <input
              className="radar-toolbar__input"
              type="text"
              inputMode="decimal"
              value={strategyTrailingPct}
              onChange={(ev) => setStrategyTrailingPct(ev.target.value)}
              placeholder="1.5"
            />
          </label>
          <label className="radar-toolbar__field">
            <span className="radar-toolbar__label">Máx. posiciones</span>
            <input
              className="radar-toolbar__input"
              type="text"
              inputMode="numeric"
              value={strategyMaxPositions}
              onChange={(ev) => setStrategyMaxPositions(ev.target.value)}
              placeholder="3"
            />
          </label>
          <label className="radar-toolbar__field">
            <span className="radar-toolbar__label">Break even trigger %</span>
            <input
              className="radar-toolbar__input"
              type="text"
              inputMode="decimal"
              value={strategyBreakEvenTriggerPct}
              onChange={(ev) => setStrategyBreakEvenTriggerPct(ev.target.value)}
              placeholder="opcional"
            />
          </label>
          <label className="radar-toolbar__field">
            <span className="radar-toolbar__label">Break even plus %</span>
            <input
              className="radar-toolbar__input"
              type="text"
              inputMode="decimal"
              value={strategyBreakEvenPlusPct}
              onChange={(ev) => setStrategyBreakEvenPlusPct(ev.target.value)}
              placeholder="0"
            />
          </label>
          <label className="radar-toolbar__field">
            <span className="radar-toolbar__label">Cooldown símbolo (min)</span>
            <input
              className="radar-toolbar__input"
              type="text"
              inputMode="numeric"
              value={strategyCooldownMinutes}
              onChange={(ev) => setStrategyCooldownMinutes(ev.target.value)}
              placeholder="0 = off"
            />
          </label>
          <label className="radar-toolbar__field">
            <span className="radar-toolbar__label">Score mínimo entrada</span>
            <input
              className="radar-toolbar__input"
              type="text"
              inputMode="decimal"
              value={strategyMinEntryScore}
              onChange={(ev) => setStrategyMinEntryScore(ev.target.value)}
              placeholder="0 = off"
            />
          </label>
          <label
            className="radar-toolbar__field"
            style={{ display: "flex", alignItems: "flex-end", gap: "0.4rem", minWidth: "14rem" }}
          >
            <input
              type="checkbox"
              checked={strategyRequireBtcTrendUp}
              onChange={(ev) => setStrategyRequireBtcTrendUp(ev.target.checked)}
            />
            <span className="radar-toolbar__label" style={{ margin: 0 }}>
              BTC tendencia alcista para altcoins
            </span>
          </label>
          <button
            type="button"
            className="radar-refresh-btn"
            onClick={() => void handleSearchOpportunities()}
            disabled={strategyLoading || strategyExecuting || strategyReviewing}
          >
            {strategyLoading ? "Buscando…" : "Buscar oportunidades"}
          </button>
          <button
            type="button"
            className="radar-refresh-btn"
            onClick={() => void handleReviewPaperExits()}
            disabled={strategyLoading || strategyExecuting || strategyReviewing}
          >
            {strategyReviewing ? "Revisando…" : "Revisar salidas paper"}
          </button>
          <button
            type="button"
            className="radar-refresh-btn"
            onClick={() => void handleExecutePaperStrategy()}
            disabled={strategyLoading || strategyExecuting || strategyReviewing}
          >
            {strategyExecuting ? "Ejecutando…" : "Ejecutar estrategia paper"}
          </button>
        </div>
        {strategyError ? (
          <p className="msg-error" style={{ fontSize: "0.875rem", marginBottom: "0.65rem" }}>
            {strategyError}
          </p>
        ) : null}
        {strategyCycle && !strategyLoading && !strategyExecuting && !strategyReviewing ? (
          <div style={strategyResultBannerStyle(strategyCycle, strategyLastMode)}>
            <p style={{ margin: 0, fontWeight: 600 }}>{strategyCycle.message ?? "—"}</p>
            <p style={{ margin: "0.4rem 0 0", fontSize: "0.85rem", opacity: 0.95 }}>
              Activos escaneados: {strategyCycle.scanned_count ?? "—"} · Candidatos:{" "}
              {strategyCycle.candidates_count ?? strategyCycle.candidates.length} · Abiertas en ciclo:{" "}
              {strategyCycle.opened_count ?? 0}
            </p>
            {strategyLastMode === "execute" ? (
              <p style={{ margin: "0.35rem 0 0", fontSize: "0.85rem", opacity: 0.95 }}>
                {(strategyCycle.opened_count ?? 0) > 0 ? (
                  <>
                    Acción: entrada ejecutada en{" "}
                    <strong>
                      {strategyCycle.evaluated?.find((e) => e.status === "accepted")?.symbol ??
                        strategyCycle.actions.find((a) => a.action === "entry" && a.status === "executed")
                          ?.symbol ??
                        "—"}
                    </strong>
                  </>
                ) : (
                  <>
                    Sin nueva entrada · motivo principal:{" "}
                    <strong>{strategyPrimaryReasonLabel(strategyCycle.primary_reason)}</strong>
                  </>
                )}
              </p>
            ) : null}
          </div>
        ) : null}
        {strategyCycle && strategyCycle.candidates.length > 0 ? (
          <>
            <h3 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
              Candidatos ({strategyCycle.candidates.length})
            </h3>
            <div className="table-wrap" style={{ marginBottom: "1rem" }}>
              <table>
                <thead>
                  <tr>
                    <th>Símbolo</th>
                    <th style={{ textAlign: "right" }}>Score</th>
                    <th>Señal</th>
                    <th>Tendencia</th>
                    <th>Riesgo</th>
                    <th style={{ textAlign: "right" }}>RSI</th>
                  </tr>
                </thead>
                <tbody>
                  {strategyCycle.candidates.map((c) => (
                    <tr key={c.symbol}>
                      <td>
                        <strong>{c.symbol}</strong>
                      </td>
                      <td style={{ textAlign: "right" }}>
                        {c.score !== null && c.score !== undefined ? c.score : "—"}
                      </td>
                      <td>
                        {c.signal ? (
                          <span className={signalBadgeClass(c.signal as CryptoAnalysisSignalKind)}>
                            {signalLabelEs(c.signal as CryptoAnalysisSignalKind)}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>{c.trend ?? "—"}</td>
                      <td>{c.risk ?? "—"}</td>
                      <td style={{ textAlign: "right" }}>
                        {c.rsi_14 !== null && c.rsi_14 !== undefined ? c.rsi_14.toFixed(2) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
        {strategyCycle && strategyCycle.actions.length > 0 ? (
          <>
            <h3 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
              Acciones ({strategyCycle.actions.length})
            </h3>
            <div className="table-wrap" style={{ marginBottom: "0.5rem" }}>
              <table>
                <thead>
                  <tr>
                    <th>Acción</th>
                    <th>Símbolo</th>
                    <th>Estado</th>
                    <th>Motivo / detalle</th>
                  </tr>
                </thead>
                <tbody>
                  {strategyCycle.actions.map((a, i) => (
                    <tr key={`${a.action ?? "x"}-${a.symbol}-${i}`}>
                      <td>{a.action === "exit" ? "Salida" : a.action === "entry" ? "Entrada" : "—"}</td>
                      <td>{a.symbol}</td>
                      <td>{a.status === "executed" ? "Ejecutada" : "Omitida"}</td>
                      <td className={a.status === "skipped" ? "msg-error" : "msg-muted"} style={{ fontSize: "0.82rem" }}>
                        {a.reason ?? "—"}
                        {a.amount_usdt !== undefined ? ` · ${fmtUsdt(a.amount_usdt)}` : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </div>

      <div className="card" style={{ marginBottom: "1rem" }}>
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: "0.75rem",
            marginBottom: "0.75rem",
          }}
        >
          <h2 className="dashboard-section-title" style={{ margin: 0, flex: "1 1 auto" }}>
            Cartera paper cripto
          </h2>
          <button type="button" className="radar-refresh-btn" onClick={() => void loadPaper()} disabled={paperLoading}>
            {paperLoading ? "Cargando…" : "Actualizar cartera"}
          </button>
          <button type="button" className="radar-refresh-btn" onClick={() => void handleResetPaper()}>
            Reset paper
          </button>
        </div>
        <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.75rem", maxWidth: "48rem", fontSize: "0.9rem" }}>
          Simulación local en USDT; no se envían órdenes a Binance. Precios de mercado vía ticker público.
        </p>
        {paperError ? <p className="msg-error">{paperError}</p> : null}
        {paperActionError ? (
          <p className="msg-error" style={{ fontSize: "0.875rem" }}>
            {paperActionError}
          </p>
        ) : null}
        {paperLoading && !paper ? <p className="msg-muted">Cargando cartera paper…</p> : null}
        {paper ? (
          <>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
                gap: "0.75rem",
                marginBottom: "1rem",
              }}
            >
              <div className="stat dashboard-stat">
                <div className="stat__label">Cash USDT</div>
                <div className="stat__value">{fmtUsdt(paper.cash_usdt)}</div>
              </div>
              <div className="stat dashboard-stat">
                <div className="stat__label">Equity estimada</div>
                <div className="stat__value">{fmtUsdt(paper.equity_usdt)}</div>
              </div>
              <div className="stat dashboard-stat">
                <div className="stat__label">PnL no realizado</div>
                <div className="stat__value" style={pnlStyle(paper.unrealized_pnl_usdt)}>
                  {fmtUsdt(paper.unrealized_pnl_usdt)}
                </div>
              </div>
            </div>

            <h3 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
              Abrir posición paper
            </h3>
            <p className="msg-muted" style={{ marginTop: 0, marginBottom: "0.65rem", fontSize: "0.875rem" }}>
              Usa precio actual de Binance, no ejecuta orden real.
            </p>
            <div className="radar-toolbar" style={{ marginBottom: "1rem" }}>
              <label className="radar-toolbar__field">
                <span className="radar-toolbar__label">Símbolo</span>
                <input
                  className="radar-toolbar__input"
                  value={paperSymbol}
                  onChange={(ev) => setPaperSymbol(ev.target.value)}
                  placeholder="BTC/USDT"
                />
              </label>
              <label className="radar-toolbar__field">
                <span className="radar-toolbar__label">Monto USDT</span>
                <input
                  className="radar-toolbar__input"
                  type="text"
                  inputMode="decimal"
                  value={paperAmountUsdt}
                  onChange={(ev) => setPaperAmountUsdt(ev.target.value)}
                  placeholder="100"
                />
              </label>
              <label className="radar-toolbar__field" style={{ minWidth: "12rem" }}>
                <span className="radar-toolbar__label">Motivo</span>
                <input
                  className="radar-toolbar__input"
                  value={paperReason}
                  onChange={(ev) => setPaperReason(ev.target.value)}
                  placeholder="entrada paper por monto"
                />
              </label>
              <label className="radar-toolbar__field">
                <span className="radar-toolbar__label">Stop loss %</span>
                <input
                  className="radar-toolbar__input"
                  type="text"
                  inputMode="decimal"
                  value={strategyStopLossPct}
                  onChange={(ev) => setStrategyStopLossPct(ev.target.value)}
                  placeholder="opcional (0 = off)"
                />
              </label>
              <label className="radar-toolbar__field">
                <span className="radar-toolbar__label">Take profit %</span>
                <input
                  className="radar-toolbar__input"
                  type="text"
                  inputMode="decimal"
                  value={strategyTakeProfitPct}
                  onChange={(ev) => setStrategyTakeProfitPct(ev.target.value)}
                  placeholder="opcional (0 = off)"
                />
              </label>
              <label className="radar-toolbar__field">
                <span className="radar-toolbar__label">Trailing stop %</span>
                <input
                  className="radar-toolbar__input"
                  type="text"
                  inputMode="decimal"
                  value={strategyTrailingPct}
                  onChange={(ev) => setStrategyTrailingPct(ev.target.value)}
                  placeholder="opcional (0 = off)"
                />
              </label>
              <label className="radar-toolbar__field">
                <span className="radar-toolbar__label">Break even trigger %</span>
                <input
                  className="radar-toolbar__input"
                  type="text"
                  inputMode="decimal"
                  value={strategyBreakEvenTriggerPct}
                  onChange={(ev) => setStrategyBreakEvenTriggerPct(ev.target.value)}
                  placeholder="opcional (compartido con estrategia)"
                />
              </label>
              <label className="radar-toolbar__field">
                <span className="radar-toolbar__label">Break even plus %</span>
                <input
                  className="radar-toolbar__input"
                  type="text"
                  inputMode="decimal"
                  value={strategyBreakEvenPlusPct}
                  onChange={(ev) => setStrategyBreakEvenPlusPct(ev.target.value)}
                  placeholder="0"
                />
              </label>
              <button
                type="button"
                className="radar-refresh-btn"
                onClick={() => void handleOpenPaperMarketAmount()}
                disabled={paperOpening}
              >
                {paperOpening ? "Abriendo…" : "Abrir paper por USDT"}
              </button>
            </div>
            <details style={{ marginBottom: "1rem" }}>
              <summary className="msg-muted" style={{ cursor: "pointer", fontSize: "0.875rem", marginBottom: "0.5rem" }}>
                Abrir por cantidad cripto (avanzado)
              </summary>
              <div className="radar-toolbar">
                <label className="radar-toolbar__field">
                  <span className="radar-toolbar__label">Cantidad</span>
                  <input
                    className="radar-toolbar__input"
                    type="text"
                    inputMode="decimal"
                    value={paperQty}
                    onChange={(ev) => setPaperQty(ev.target.value)}
                    placeholder="0.01"
                  />
                </label>
                <button
                  type="button"
                  className="radar-refresh-btn"
                  onClick={() => void handleOpenPaperMarketQty()}
                  disabled={paperOpening}
                >
                  {paperOpening ? "Abriendo…" : "Abrir paper a mercado (qty)"}
                </button>
              </div>
            </details>

            <h3 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
              Posiciones abiertas ({paper.positions.length})
            </h3>
            {paper.positions.length === 0 ? (
              <p className="msg-muted" style={{ marginBottom: "1rem" }}>
                Sin posiciones abiertas.
              </p>
            ) : (
              <>
                <p className="msg-muted" style={{ marginBottom: "0.5rem", fontSize: "0.78rem", lineHeight: 1.45 }}>
                  <strong>Break-even pendiente:</strong> aún no alcanzó el trigger.{" "}
                  <strong>Activo:</strong> el stop subió al piso protegido.{" "}
                  <strong>Trail %:</strong> stop dinámico desde el máximo alcanzado.
                </p>
                <div className="table-wrap" style={{ marginBottom: "1rem" }}>
                  <table>
                    <thead>
                      <tr>
                        <th>Símbolo</th>
                        <th style={{ textAlign: "right" }}>Monto</th>
                        <th style={{ textAlign: "right" }} title="Precio de entrada de la posición">
                          Entrada
                        </th>
                        <th style={{ textAlign: "right" }} title="Último precio de mercado (ticker)">
                          Actual
                        </th>
                        <th style={{ textAlign: "right" }} title="Ganancia/pérdida no realizada">
                          PnL %
                        </th>
                        <th style={{ textAlign: "right" }} title="Stop loss vigente (puede subir con break-even)">
                          SL actual
                        </th>
                        <th style={{ textAlign: "right" }} title="Precio objetivo de take profit">
                          TP
                        </th>
                        <th style={{ textAlign: "right" }} title={TOOLTIP_TRAIL_PCT}>
                          Trail %
                        </th>
                        <th style={{ textAlign: "right" }} title="Precio máximo registrado desde la apertura">
                          Máx. precio
                        </th>
                        <th title="Estado del break-even configurado al abrir">Break-even</th>
                        <th title="Reglas de salida configuradas en la posición">Política salida</th>
                        <th title="Salida más próxima según precio actual (heurística visual)">Salida probable</th>
                        <th />
                      </tr>
                    </thead>
                  <tbody>
                    {paper.positions.map((pos) => {
                      const exitHint = paperProbableExit(pos);
                      const trailPx = paperTrailingStopPrice(pos);
                      const trailActive = paperTrailingActive(pos);
                      const rowTitle = [pos.price_error, exitHint.title].filter(Boolean).join(" · ");
                      return (
                        <tr key={pos.id} title={rowTitle || undefined}>
                          <td>
                            <strong>{pos.symbol}</strong>
                            <div className="msg-muted" style={{ fontSize: "0.72rem" }}>
                              {pos.quantity} · {fmtUsdt(pos.unrealized_pnl_usdt)}
                            </div>
                          </td>
                          <td style={{ textAlign: "right" }}>{fmtUsdt(pos.amount_usdt)}</td>
                          <td style={{ textAlign: "right" }}>{fmtPrice(pos.entry_price)}</td>
                          <td style={{ textAlign: "right" }}>
                            {pos.current_price !== null && pos.current_price !== undefined
                              ? fmtPrice(pos.current_price)
                              : "—"}
                          </td>
                          <td style={{ textAlign: "right" }}>
                            <span style={pnlStyle(pos.unrealized_pnl_pct)}>{fmtPct(pos.unrealized_pnl_pct)}</span>
                          </td>
                          <td style={{ textAlign: "right" }} title={fmtPrice(pos.stop_loss)}>
                            {fmtPrice(pos.stop_loss)}
                          </td>
                          <td style={{ textAlign: "right" }}>{fmtPrice(pos.take_profit)}</td>
                          <td style={{ textAlign: "right" }}>
                            {pos.trailing_stop_pct !== null && pos.trailing_stop_pct !== undefined ? (
                              <span
                                title={
                                  trailActive
                                    ? `${TOOLTIP_TRAIL_PCT} ${TOOLTIP_TRAIL_ACTIVE} Nivel ≈ ${fmtPrice(trailPx)}.`
                                    : TOOLTIP_TRAIL_PCT
                                }
                              >
                                {numFmt2.format(pos.trailing_stop_pct)}%
                                {trailActive ? (
                                  <span
                                    className="radar-badge radar-badge--conv-media"
                                    style={{ marginLeft: "0.25rem", fontSize: "0.65rem", verticalAlign: "middle" }}
                                  >
                                    activo
                                  </span>
                                ) : null}
                              </span>
                            ) : (
                              "—"
                            )}
                          </td>
                          <td style={{ textAlign: "right" }}>{fmtPrice(pos.highest_price)}</td>
                          <td>
                            {pos.break_even_active ? (
                              <span className="radar-badge radar-badge--conv-alta" title={TOOLTIP_BE_ACTIVE}>
                                Activo
                              </span>
                            ) : pos.break_even_trigger_pct !== null &&
                                pos.break_even_trigger_pct !== undefined &&
                                pos.break_even_trigger_pct > 0 ? (
                              <span
                                className="msg-muted"
                                style={{ fontSize: "0.78rem", cursor: "help", textDecoration: "underline dotted" }}
                                title={TOOLTIP_BE_PENDING}
                              >
                                Pendiente
                                <div style={{ fontSize: "0.68rem" }}>
                                  trig. {numFmt2.format(pos.break_even_trigger_pct)}%
                                </div>
                              </span>
                            ) : (
                              "—"
                            )}
                          </td>
                          <td
                            className="msg-muted"
                            style={{ fontSize: "0.78rem", maxWidth: "7.5rem" }}
                            title={pos.exit_policy ?? undefined}
                          >
                            {formatPaperExitPolicy(pos.exit_policy)}
                          </td>
                          <td style={{ fontSize: "0.78rem", maxWidth: "9rem" }} title={exitHint.title}>
                            {exitHint.label}
                          </td>
                          <td>
                            <button
                              type="button"
                              className="radar-refresh-btn"
                              style={{ padding: "0.25rem 0.55rem", fontSize: "0.78rem" }}
                              onClick={() => void handleClosePaper(pos)}
                              disabled={paperClosingId !== null}
                            >
                              {paperClosingId === pos.id ? "Cerrando…" : "Cerrar"}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                </div>
              </>
            )}

            <h3 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
              Trades cerrados recientes
              {paper.trades_total > paper.trades.length
                ? ` (mostrando ${paper.trades.length} de ${paper.trades_total})`
                : ""}
            </h3>
            {paper.trades.length === 0 ? (
              <p className="msg-muted">Sin trades cerrados todavía.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Símbolo</th>
                      <th style={{ textAlign: "right" }}>Cantidad</th>
                      <th style={{ textAlign: "right" }}>Entrada</th>
                      <th style={{ textAlign: "right" }}>Salida</th>
                      <th style={{ textAlign: "right" }}>PnL USDT</th>
                      <th style={{ textAlign: "right" }}>PnL %</th>
                      <th>Motivo salida</th>
                    </tr>
                  </thead>
                  <tbody>
                    {paper.trades.map((t) => (
                      <tr key={t.id}>
                        <td>{t.symbol}</td>
                        <td style={{ textAlign: "right" }}>{t.quantity}</td>
                        <td style={{ textAlign: "right" }}>{fmtPrice(t.entry_price)}</td>
                        <td style={{ textAlign: "right" }}>{fmtPrice(t.exit_price)}</td>
                        <td style={{ textAlign: "right" }}>
                          <span style={pnlStyle(t.pnl_usdt)}>{fmtUsdt(t.pnl_usdt)}</span>
                        </td>
                        <td style={{ textAlign: "right" }}>
                          <span style={pnlStyle(t.pnl_pct)}>{fmtPct(t.pnl_pct)}</span>
                        </td>
                        <td className="msg-muted" style={{ fontSize: "0.82rem" }}>
                          {t.exit_reason || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        ) : null}
      </div>

      {!loading && fatalError === null && ohlcv && ohlcv.candles.length > 0 && (
        <div className="card">
          <h2 className="dashboard-section-title" style={{ marginTop: 0, marginBottom: "0.65rem" }}>
            Velas {ohlcv.symbol} · {ohlcv.timeframe} · últimas {ohlcv.candles.length}
          </h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th style={{ textAlign: "right" }}>Open</th>
                  <th style={{ textAlign: "right" }}>High</th>
                  <th style={{ textAlign: "right" }}>Low</th>
                  <th style={{ textAlign: "right" }}>Close</th>
                  <th style={{ textAlign: "right" }}>Volume</th>
                </tr>
              </thead>
              <tbody>
                {ohlcv.candles.map((row: CryptoOhlcvCandle, i: number) => {
                  const [ts, open, high, low, close, vol] = row;
                  const d = new Date(ts);
                  return (
                    <tr key={`${ts}-${i}`}>
                      <td className="table-cell--nowrap">{Number.isFinite(d.getTime()) ? dtFmt.format(d) : "—"}</td>
                      <td style={{ textAlign: "right" }}>{fmtPrice(open)}</td>
                      <td style={{ textAlign: "right" }}>{fmtPrice(high)}</td>
                      <td style={{ textAlign: "right" }}>{fmtPrice(low)}</td>
                      <td style={{ textAlign: "right" }}>{fmtPrice(close)}</td>
                      <td style={{ textAlign: "right" }}>{fmtVol(vol)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!loading && fatalError === null && ohlcv && ohlcv.candles.length === 0 && (
        <p className="msg-muted">No hay velas en la respuesta de /crypto/ohlcv.</p>
      )}
    </>
  );
}
