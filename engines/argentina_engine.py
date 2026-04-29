from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import time
import yfinance as yf

from core.config import PRICE_HISTORY_PERIOD, YFINANCE_INFO_TIMEOUT_S
from core.risk import calculate_risk_score, classify_risk_profile
from core.scoring import calculate_fund_score, calculate_tech_score
from core.signals import classify_conviction, classify_setup, classify_signal_state, suggested_capital
from core.technicals import compute_technical_metrics
from data.universe_arg import ARGENTINA_UNIVERSE
from services.engine_run_metrics import format_delta_line, load_previous_engine, save_engine_metrics
from services.fundamentals_cache import FundamentalsCache
from services.yfinance_helpers import fetch_info_with_timeout, precio_valido, try_apply_fast_info_price


ARG_MAX_WORKERS = 4


def format_number(value):
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _arg_log(level: str, yahoo_ticker: str, local_ticker: str, panel: str, msg: str) -> None:
    """
    Logger simple por stdout para el motor Argentina.
    Mantener formato estable para grep: [ARG][LEVEL][LOCAL][YAHOO][PANEL] mensaje
    """
    lvl = (level or "INFO").strip().upper()
    yt = (yahoo_ticker or "").strip()
    lt = (local_ticker or "").strip()
    pn = (panel or "").strip() or "?"
    print(f"[ARG][{lvl}][{lt}][{yt}][{pn}] {msg}")


def run_argentina_engine() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    t0 = time.perf_counter()
    prev_run = load_previous_engine("arg")
    if prev_run:
        print(
            f"[ARG] Referencia corrida anterior: t={prev_run.get('elapsed_s')}s | "
            f"OK={prev_run.get('n_ok')} cache_hits={prev_run.get('cache_hits')} "
            f"info_fetches={prev_run.get('info_fetches')} SIN_HISTORY={prev_run.get('sin_history_total')}"
        )
    results = []
    universe_rows = []
    cache = FundamentalsCache()
    cache.load()
    n_ok = 0
    n_fail = 0
    n_hist_empty = 0
    n_hist_short = 0
    n_fast_price_used = 0
    n_sin_precio = 0
    fail_history_exc = 0
    fail_tech_exc = 0
    fail_info_exc = 0
    fail_other = 0
    # Diagnóstico: tickers sospechosos de símbolo Yahoo incorrecto / no soportado
    suspected_bad_yahoo: list[tuple[str, str, str]] = []

    tickers_total = len(ARGENTINA_UNIVERSE)
    # Accumulados (suma por ticker). En secuencial coinciden con wall-clock aproximado,
    # pero mantener nombres consistentes con USA para comparar.
    acc_yahoo_history_ms = 0.0
    acc_yahoo_info_ms = 0.0
    acc_scoring_ms = 0.0
    history_phase_wall_ms = 0.0
    processing_phase_wall_ms = 0.0

    items = list(ARGENTINA_UNIVERSE)

    ordered_history: list[tuple[pd.DataFrame | None, float, str | None, str | None] | None] = [None] * len(items)

    def _fetch_history_only(yahoo_ticker: str) -> tuple[pd.DataFrame | None, float, str | None, str | None]:
        t_hist0 = time.perf_counter()
        try:
            asset0 = yf.Ticker(yahoo_ticker)
            # repair=True puede requerir scipy en algunas instalaciones de yfinance; evitarlo para robustez.
            data0 = asset0.history(period=PRICE_HISTORY_PERIOD, auto_adjust=False, actions=False, repair=False)
            return data0, (time.perf_counter() - t_hist0) * 1000.0, None, None
        except Exception as e:
            return None, (time.perf_counter() - t_hist0) * 1000.0, type(e).__name__, str(e)

    t_hist_phase0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=ARG_MAX_WORKERS) as executor:
        future_to_idx = {
            executor.submit(_fetch_history_only, str(item.get("ticker") or "")): idx for idx, item in enumerate(items)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            yahoo_ticker = str(items[idx].get("ticker") or "")
            try:
                ordered_history[idx] = future.result()
            except Exception as e:
                print(f"[ARG_HISTORY_THREAD_ERROR] ticker={yahoo_ticker} error={type(e).__name__}: {e}")
                ordered_history[idx] = (None, 0.0, type(e).__name__, str(e))
    history_phase_wall_ms = (time.perf_counter() - t_hist_phase0) * 1000.0

    # Pre-validación + INFO secuencial (FundamentalsCache); construir tareas de processing.
    t_proc_phase0 = time.perf_counter()
    process_tasks: list[tuple[int, dict, pd.Series, dict]] = []
    t_started_by_idx: list[float | None] = [None] * len(items)
    t_finished_by_idx: list[float | None] = [None] * len(items)
    status_by_idx: list[str | None] = [None] * len(items)  # ok | fail | skipped
    stage_by_idx: list[str | None] = [None] * len(items)
    ctx_by_idx: list[dict | None] = [None] * len(items)

    for idx, item in enumerate(items):
        yahoo_ticker = item["ticker"]
        local_ticker = item["local_ticker"]
        panel = item.get("panel") or "Merval"
        mercado = item.get("mercado") or (
            "General" if str(panel).strip().lower() in ("general", "panel general") else "Merval"
        )
        _arg_log("INFO", yahoo_ticker, local_ticker, panel, "start")
        t_started_by_idx[idx] = time.perf_counter()
        stage = "init"
        try:
            pack = ordered_history[idx]
            stage = "history"
            stage_by_idx[idx] = stage
            if pack is None:
                print(f"[ARG_HISTORY_THREAD_ERROR] ticker={yahoo_ticker} error=MissingHistoryResult")
                raise RuntimeError("MissingHistoryResult")
            data, hist_ms, err_type, err_msg = pack
            acc_yahoo_history_ms += float(hist_ms or 0.0)
            if err_type is not None:
                print(f"[ARG_HISTORY_THREAD_ERROR] ticker={yahoo_ticker} error={err_type}: {err_msg}")
                raise RuntimeError(f"history_thread_error:{err_type}")
            if data is None or getattr(data, "empty", False):
                n_hist_empty += 1
                _arg_log("WARN", yahoo_ticker, local_ticker, panel, "omitido: history vacío (sin velas)")
                suspected_bad_yahoo.append((local_ticker, yahoo_ticker, "history_empty"))
                status_by_idx[idx] = "skipped"
                stage_by_idx[idx] = "history"
                t_finished_by_idx[idx] = time.perf_counter()
                continue

            required_cols = {"Close"}
            missing_cols = sorted([c for c in required_cols if c not in data.columns])
            if missing_cols:
                n_hist_empty += 1
                _arg_log(
                    "WARN",
                    yahoo_ticker,
                    local_ticker,
                    panel,
                    f"omitido: history sin columnas requeridas missing={missing_cols} cols={list(data.columns)}",
                )
                suspected_bad_yahoo.append((local_ticker, yahoo_ticker, f"missing_cols:{','.join(missing_cols)}"))
                status_by_idx[idx] = "skipped"
                stage_by_idx[idx] = "history"
                t_finished_by_idx[idx] = time.perf_counter()
                continue

            close = pd.to_numeric(data["Close"], errors="coerce").dropna()
            if close.empty:
                n_hist_empty += 1
                _arg_log("WARN", yahoo_ticker, local_ticker, panel, "omitido: Close vacío/NaN tras coerción")
                suspected_bad_yahoo.append((local_ticker, yahoo_ticker, "close_all_nan"))
                status_by_idx[idx] = "skipped"
                stage_by_idx[idx] = "history"
                t_finished_by_idx[idx] = time.perf_counter()
                continue
            if len(close) < 200:
                n_hist_short += 1
                _arg_log(
                    "WARN",
                    yahoo_ticker,
                    local_ticker,
                    panel,
                    f"omitido: history insuficiente ({len(close)} velas válidas < 200)",
                )
                status_by_idx[idx] = "skipped"
                stage_by_idx[idx] = "history"
                t_finished_by_idx[idx] = time.perf_counter()
                continue

            stage = "info"
            stage_by_idx[idx] = stage
            asset_info = yf.Ticker(yahoo_ticker)
            t_info0 = time.perf_counter()
            info = cache.get_or_fetch_info(
                ticker=yahoo_ticker,
                fetcher=lambda: fetch_info_with_timeout(asset_info, timeout_s=YFINANCE_INFO_TIMEOUT_S),
            )
            acc_yahoo_info_ms += (time.perf_counter() - t_info0) * 1000.0
            if not isinstance(info, dict) or not info:
                _arg_log("WARN", yahoo_ticker, local_ticker, panel, "info vacío/no dict (se sigue con defaults)")
                info = info if isinstance(info, dict) else {}

            item_ctx = {
                "yahoo_ticker": yahoo_ticker,
                "local_ticker": local_ticker,
                "panel": panel,
                "mercado": mercado,
            }
            ctx_by_idx[idx] = item_ctx
            process_tasks.append((idx, item_ctx, close, info))
        except Exception as e:
            n_fail += 1
            if stage == "history":
                fail_history_exc += 1
                suspected_bad_yahoo.append((local_ticker, yahoo_ticker, f"history_exc:{type(e).__name__}"))
            elif stage == "info":
                fail_info_exc += 1
            else:
                fail_other += 1
            status_by_idx[idx] = "fail"
            stage_by_idx[idx] = stage
            t_finished_by_idx[idx] = time.perf_counter()
            started = t_started_by_idx[idx] or t_finished_by_idx[idx] or time.perf_counter()
            elapsed_ms = (float(t_finished_by_idx[idx] or time.perf_counter()) - float(started)) * 1000.0
            _arg_log(
                "ERROR",
                yahoo_ticker,
                local_ticker,
                panel,
                f"FAIL stage={stage} err={type(e).__name__}: {e} elapsed_ms={elapsed_ms:.0f}",
            )

    ordered_results: list[list | None] = [None] * len(items)
    ordered_universe: list[list | None] = [None] * len(items)

    def _process_arg_ticker_from_history(
        idx: int,
        item_ctx: dict,
        close: pd.Series,
        info: dict,
    ) -> tuple[int, list | None, list | None, int, int, float, str | None, str | None]:
        """
        Devuelve: (idx, row, universe_row, fast_price_used_inc, sin_precio_inc, scoring_ms, err_type, err_msg)
        """
        t_sc0 = time.perf_counter()
        try:
            yahoo_ticker = str(item_ctx.get("yahoo_ticker") or "")
            local_ticker = str(item_ctx.get("local_ticker") or "")
            panel = str(item_ctx.get("panel") or "Merval")
            mercado = str(item_ctx.get("mercado") or "")

            company = info.get("longName") or info.get("shortName") or local_ticker
            sector = info.get("sector")
            industry = info.get("industry")
            market_cap = format_number(info.get("marketCap"))
            beta = format_number(info.get("beta"))
            roe = format_number(info.get("returnOnEquity"))
            risk_profile = classify_risk_profile(beta)
            risk_score = calculate_risk_score(beta)

            technicals = compute_technical_metrics(close)
            missing_tech_keys = [
                k
                for k in ("Precio", "RSI", "MA50", "MA200", "MACD_Bull", "Pullback", "Trend")
                if k not in technicals
            ]
            if missing_tech_keys:
                _arg_log("WARN", yahoo_ticker, local_ticker, panel, f"technicals incompleto missing_keys={missing_tech_keys}")

            asset = yf.Ticker(yahoo_ticker)
            fast_used = 1 if try_apply_fast_info_price(asset, technicals, format_number) else 0

            pe = format_number(info.get("trailingPE"))
            price_to_book = format_number(info.get("priceToBook"))
            ebitda = format_number(info.get("ebitda"))
            net_income = format_number(info.get("netIncomeToCommon"))
            total_debt = format_number(info.get("totalDebt"))
            debt_to_equity = format_number(info.get("debtToEquity"))
            target_price = format_number(info.get("targetMeanPrice"))

            debt_to_ebitda = None
            if total_debt is not None and ebitda is not None and ebitda > 0:
                debt_to_ebitda = round(total_debt / ebitda, 2)

            upside = None
            if target_price is not None and technicals["Precio"]:
                upside = (target_price - technicals["Precio"]) / technicals["Precio"]

            if not precio_valido(technicals.get("Precio")):
                _arg_log(
                    "WARN",
                    yahoo_ticker,
                    local_ticker,
                    panel,
                    f"precio no válido para scoring: Precio={technicals.get('Precio')!r}",
                )
            if technicals.get("RSI") is None:
                _arg_log("WARN", yahoo_ticker, local_ticker, panel, "RSI=None (puede afectar score técnico)")

            tech_score = calculate_tech_score(
                rsi=technicals["RSI"],
                pullback=technicals["Pullback"],
                trend_positive=technicals["Trend"],
                macd_bullish=technicals["MACD_Bull"],
            )
            fund_score = calculate_fund_score(net_income, ebitda, debt_to_equity, pe, upside)
            total_score = tech_score + fund_score + risk_score

            setup = classify_setup(
                rsi=technicals["RSI"],
                pullback=technicals["Pullback"],
                trend_positive=technicals["Trend"],
                macd_bullish=technicals["MACD_Bull"],
            )
            signal_state = classify_signal_state(
                total_score=total_score,
                upside=upside,
                price=technicals["Precio"],
                target_price=target_price,
                rsi=technicals["RSI"],
                macd_bullish=technicals["MACD_Bull"],
                trend_positive=technicals["Trend"],
            )
            conviction = classify_conviction(total_score)
            capital = suggested_capital(total_score)

            row = [
                local_ticker,
                company,
                sector,
                industry,
                "ARGENTINA",
                panel,
                mercado,
                market_cap,
                beta,
                roe,
                risk_profile,
                risk_score,
                technicals["Precio"],
                technicals["RSI"],
                technicals["MA50"],
                technicals["MA200"],
                technicals["MACD_Bull"],
                technicals["Pullback"],
                technicals["Trend"],
                round(pe, 2) if pe is not None else None,
                round(price_to_book, 2) if price_to_book is not None else None,
                ebitda,
                net_income,
                round(debt_to_equity, 2) if debt_to_equity is not None else None,
                debt_to_ebitda,
                round(target_price, 2) if target_price is not None else None,
                round(upside * 100, 2) if upside is not None else None,
                tech_score,
                fund_score,
                total_score,
                setup,
                signal_state,
                conviction,
                capital,
            ]
            universe_row = [
                local_ticker,
                company,
                sector,
                industry,
                "ARGENTINA",
                panel,
                mercado,
                market_cap,
                beta,
                roe,
                risk_profile,
            ]
            sin_precio_inc = 0 if precio_valido(technicals.get("Precio")) else 1
            scoring_ms = (time.perf_counter() - t_sc0) * 1000.0
            return idx, row, universe_row, fast_used, sin_precio_inc, scoring_ms, None, None
        except Exception as e:
            scoring_ms = (time.perf_counter() - t_sc0) * 1000.0
            return idx, None, None, 0, 0, scoring_ms, type(e).__name__, str(e)

    with ThreadPoolExecutor(max_workers=ARG_MAX_WORKERS) as executor:
        future_to_meta = {
            executor.submit(_process_arg_ticker_from_history, idx, item_ctx, close, info): (
                idx,
                str(item_ctx.get("yahoo_ticker") or ""),
            )
            for (idx, item_ctx, close, info) in process_tasks
        }
        for future in as_completed(future_to_meta):
            idx, yahoo_ticker = future_to_meta[future]
            try:
                out_idx, row, univ_row, fast_inc, sin_precio_inc, scoring_ms, err_type, err_msg = future.result()
            except Exception as e:
                print(f"[ARG_PROCESS_THREAD_ERROR] ticker={yahoo_ticker} error={type(e).__name__}: {e}")
                n_fail += 1
                fail_tech_exc += 1
                status_by_idx[idx] = "fail"
                stage_by_idx[idx] = "technicals"
                t_finished_by_idx[idx] = time.perf_counter()
                continue

            acc_scoring_ms += float(scoring_ms or 0.0)
            if err_type is not None:
                print(f"[ARG_PROCESS_THREAD_ERROR] ticker={yahoo_ticker} error={err_type}: {err_msg}")
                n_fail += 1
                fail_tech_exc += 1
                status_by_idx[out_idx] = "fail"
                stage_by_idx[out_idx] = "technicals"
                t_finished_by_idx[out_idx] = time.perf_counter()
                continue

            ordered_results[out_idx] = row
            ordered_universe[out_idx] = univ_row
            n_fast_price_used += int(fast_inc or 0)
            if int(sin_precio_inc or 0) > 0:
                n_sin_precio += int(sin_precio_inc or 0)
                # Mantener WARN original en el hilo principal (mismo prefijo [ARG]).
                try:
                    local_ticker = str(items[out_idx].get("local_ticker") or "")
                    panel = str(items[out_idx].get("panel") or "Merval")
                except Exception:
                    local_ticker = ""
                    panel = "?"
                _arg_log(
                    "WARN",
                    yahoo_ticker,
                    local_ticker,
                    panel,
                    f"precio inválido tras history/fast_info: {row[12] if row else None!r}",
                )
            n_ok += 1
            status_by_idx[out_idx] = "ok"
            stage_by_idx[out_idx] = "technicals"
            t_finished_by_idx[out_idx] = time.perf_counter()

    for i, item in enumerate(items):
        # Emitir logs finales en orden para mantener salida estable.
        try:
            yt = str(item.get("ticker") or "")
            lt = str(item.get("local_ticker") or "")
            pn = str(item.get("panel") or "Merval")
        except Exception:
            yt, lt, pn = "", "", "?"
        started = t_started_by_idx[i] or time.perf_counter()
        finished = t_finished_by_idx[i] or time.perf_counter()
        elapsed_ms = (float(finished) - float(started)) * 1000.0

        if status_by_idx[i] == "fail" and stage_by_idx[i] == "technicals":
            _arg_log("ERROR", yt, lt, pn, f"FAIL stage=technicals elapsed_ms={elapsed_ms:.0f}")

        if ordered_results[i] is not None:
            results.append(ordered_results[i])
            universe_rows.append(ordered_universe[i])  # type: ignore[arg-type]
            _arg_log("INFO", yt, lt, pn, f"ok elapsed_ms={elapsed_ms:.0f}")

    processing_phase_wall_ms = (time.perf_counter() - t_proc_phase0) * 1000.0

    if suspected_bad_yahoo:
        # Log simple para ayudar a detectar símbolos Yahoo incorrectos sin rehacer mapping ahora.
        uniq: dict[tuple[str, str], set[str]] = {}
        for lt, yt, reason in suspected_bad_yahoo:
            uniq.setdefault((lt, yt), set()).add(reason)
        top = sorted(uniq.items(), key=lambda kv: (kv[0][0], kv[0][1]))
        print("[ARG][WARN] Tickers con sospecha de símbolo Yahoo incorrecto/no soportado:")
        for (lt, yt), reasons in top[:30]:
            print(f"[ARG][WARN] - {lt} -> {yt} reasons={sorted(reasons)}")

    df = pd.DataFrame(results, columns=[
        'Ticker', 'Empresa', 'Sector', 'Industria', 'TipoUniverso', 'Panel', 'Mercado',
        'MarketCap', 'Beta', 'ROE', 'RiskProfile', 'RiskScore',
        'Precio', 'RSI', 'MA50', 'MA200', 'MACD_Bull', 'Pullback', 'Trend',
        'PE', 'PriceToBook', 'EBITDA', 'NetIncome', 'DebtToEquity', 'DebtToEbitda', 'TargetPrice', 'Upside_%',
        'TechScore', 'FundScore', 'TotalScore', 'Setup', 'SignalState',
        'Conviccion', 'CapitalSugerido_%',
    ])

    df_universo = pd.DataFrame(universe_rows, columns=[
        'Ticker', 'Empresa', 'Sector', 'Industria', 'TipoUniverso', 'Panel', 'Mercado',
        'MarketCap', 'Beta', 'ROE', 'RiskProfile',
    ]).drop_duplicates(subset=['Ticker'])

    sector_summary = (
        df.groupby('Sector', dropna=False)
        .agg(SectorScorePromedio=('TotalScore', 'mean'), CantidadActivos=('Ticker', 'count'))
        .reset_index()
    )
    if not sector_summary.empty:
        sector_summary['SectorScorePromedio'] = sector_summary['SectorScorePromedio'].round(2)
        sector_summary = sector_summary.sort_values('SectorScorePromedio', ascending=False).reset_index(drop=True)
        sector_summary['RankingSector'] = sector_summary.index + 1
        df = df.merge(sector_summary[['Sector', 'SectorScorePromedio', 'RankingSector']], on='Sector', how='left')
    else:
        df['SectorScorePromedio'] = None
        df['RankingSector'] = None

    cache.save()

    elapsed = time.perf_counter() - t0
    sin_hist_total = n_hist_empty + n_hist_short
    cmp = format_delta_line("[ARG]", prev_run, elapsed)
    if cmp:
        print(cmp)
    print(
        f"[ARG] OK={n_ok} FAIL={n_fail} | "
        f"SIN_HISTORY={sin_hist_total} (vacío={n_hist_empty} insuf_velas={n_hist_short}) | "
        f"SIN_PRECIO_OK={n_sin_precio} | "
        f"cache_hits={cache.stats.hits} cache_misses={cache.stats.misses} "
        f"info_fetches={cache.stats.stores} | "
        f"fast_price_used={n_fast_price_used} | "
        f"fail_breakdown=(history_exc={fail_history_exc} info_exc={fail_info_exc} tech_exc={fail_tech_exc} other={fail_other}) | "
        f"t={elapsed:.1f}s"
    )
    print(
        "[ARG_TIMING] total_ms=%.1f tickers=%s ok=%s fail=%s skipped_no_history=%s\n"
        "  history_phase_wall_ms=%.1f\n"
        "  processing_phase_wall_ms=%.1f\n"
        "  yahoo_history_accum_ms=%.1f\n"
        "  yahoo_info_ms=%.1f\n"
        "  scoring_accum_ms=%.1f\n"
        "  failures=%s"
        % (
            elapsed * 1000.0,
            tickers_total,
            n_ok,
            n_fail,
            sin_hist_total,
            history_phase_wall_ms,
            processing_phase_wall_ms,
            acc_yahoo_history_ms,
            acc_yahoo_info_ms,
            acc_scoring_ms,
            n_fail,
        )
    )

    save_engine_metrics(
        "arg",
        {
            "elapsed_s": round(elapsed, 3),
            "n_ok": n_ok,
            "n_fail": n_fail,
            "sin_history_empty": n_hist_empty,
            "sin_history_short": n_hist_short,
            "sin_history_total": sin_hist_total,
            "n_sin_precio_en_ok": n_sin_precio,
            "cache_hits": cache.stats.hits,
            "cache_misses": cache.stats.misses,
            "info_fetches": cache.stats.stores,
            "fast_price_used": n_fast_price_used,
            "cache_errors": cache.stats.errors,
        },
    )

    return df, df_universo, sector_summary
