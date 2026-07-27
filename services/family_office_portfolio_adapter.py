"""
Integraci├│n Family Office Ôåö Cartera (solo lectura).

No modifica l├│gica de Cartera. Consume servicios/repos p├║blicos existentes.

Caja (efectivo / saldo disponible en Cartera):
  UI Cartera ÔåÆ GET /portfolio/balance ÔåÆ compute_portfolio_balance
  ÔåÆ sum_cash_by_currency ÔåÆ SUM(amount) FROM portfolio_cash_movements.

Si la tabla de movimientos no est├í en la DB (bases antiguas sin repair),
no se lanza excepci├│n: cash=0 y warning "cash movements unavailable".
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from persistence.sqlite import family_office_flow_repo as flow
from persistence.sqlite.positions_repo import (
    list_trades_filtered,
    portfolio_instrument_metrics,
    row_as_mapping,
)
from services.portfolio_strategy_accounting import (
    compute_strategy_cashflow_pnl,
    compute_strategy_cashflow_total,
    compute_strategy_is_closed,
    management_events_from_row,
    option_strategy_use_cashflow_pnl,
)

_CASH_UNAVAILABLE_WARNING = "cash movements unavailable"


def _load_portfolio_balance():
    try:
        from services import portfolio_balance as pb
    except ImportError:
        return None
    return pb


def _load_list_cash_movements():
    try:
        from persistence.sqlite.cash_movements_repo import list_cash_movements
    except ImportError:
        return None
    return list_cash_movements


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _currency_from_asset_type(asset_type: str | None) -> str:
    at = (asset_type or "").strip()
    if at == "Argentina":
        return "ARS"
    return "USD"


def _is_cash_movements_unavailable(exc: BaseException) -> bool:
    """True si falla por ausencia / inaccesibilidad de portfolio_cash_movements."""
    msg = str(exc).lower()
    if "portfolio_cash_movements" in msg:
        return True
    if isinstance(exc, sqlite3.OperationalError) and "no such table" in msg:
        return True
    return False


def _balance_without_cash_ledger(*, portfolio_type: str) -> dict[str, Any]:
    """
    Misma forma que compute_portfolio_balance, pero cash=0.
    Reusa las funciones de posiciones de Cartera (sin tocar su l├│gica interna).
    """
    pb = _load_portfolio_balance()
    if pb is None:
        return {
            "portfolio_type": portfolio_type,
            "cash_ars": 0.0,
            "cash_usd": 0.0,
            "invested_market_value_ars": 0.0,
            "invested_market_value_usd": 0.0,
            "committed_capital_option_strategy_open_ars": 0.0,
            "committed_capital_option_strategy_open_usd": 0.0,
            "realized_pnl_closed_approx_ars": 0.0,
            "realized_pnl_closed_approx_usd": 0.0,
            "balance_estimated_ars": 0.0,
            "balance_estimated_usd": 0.0,
            "notes": [_CASH_UNAVAILABLE_WARNING],
            "cash_source": "unavailable",
        }
    pt = portfolio_type
    committed_ars, committed_usd = pb.sum_open_committed_option_strategy_split(portfolio_type=pt)
    realized_ars, realized_usd = pb.sum_closed_realized_pnl_by_asset_currency(portfolio_type=pt)
    mv = pb.estimate_open_invested_market_value(portfolio_type=pt)
    inv_ars = float(mv.get("invested_market_value_ars") or 0)
    inv_usd = float(mv.get("invested_market_value_usd") or 0)
    notes = list(mv.get("estimation_notes") or [])
    notes.append(_CASH_UNAVAILABLE_WARNING)
    notes.append(
        "Caja no le├¡da: portfolio_cash_movements ausente o inaccesible. "
        "Cartera usa esa tabla v├¡a sum_cash_by_currency; se reporta cash=0."
    )
    return {
        "portfolio_type": pt,
        "cash_ars": 0.0,
        "cash_usd": 0.0,
        "invested_market_value_ars": mv.get("invested_market_value_ars"),
        "invested_market_value_usd": mv.get("invested_market_value_usd"),
        "committed_capital_option_strategy_open_ars": committed_ars,
        "committed_capital_option_strategy_open_usd": committed_usd,
        "realized_pnl_closed_approx_ars": realized_ars,
        "realized_pnl_closed_approx_usd": realized_usd,
        "balance_estimated_ars": round(0.0 + inv_ars, 4),
        "balance_estimated_usd": round(0.0 + inv_usd, 4),
        "notes": notes,
        "cash_source": "unavailable",
    }


def _safe_compute_portfolio_balance(*, portfolio_type: str) -> tuple[dict[str, Any], list[str]]:
    """
    Fuente oficial de caja: compute_portfolio_balance (Cartera).
    Si el ledger de caja no existe, degrada sin excepci├│n.
    """
    extra_warnings: list[str] = []
    pb = _load_portfolio_balance()
    if pb is None:
        extra_warnings.append(_CASH_UNAVAILABLE_WARNING)
        return _balance_without_cash_ledger(portfolio_type=portfolio_type), extra_warnings
    try:
        balance = pb.compute_portfolio_balance(portfolio_type=portfolio_type)
        balance = {**balance, "cash_source": "portfolio_cash_movements"}
        return balance, extra_warnings
    except Exception as exc:
        if _is_cash_movements_unavailable(exc):
            extra_warnings.append(_CASH_UNAVAILABLE_WARNING)
            try:
                return _balance_without_cash_ledger(portfolio_type=portfolio_type), extra_warnings
            except Exception as inner:
                extra_warnings.append(f"positions fallback degraded: {inner}")
                return {
                    "portfolio_type": portfolio_type,
                    "cash_ars": 0.0,
                    "cash_usd": 0.0,
                    "invested_market_value_ars": 0.0,
                    "invested_market_value_usd": 0.0,
                    "committed_capital_option_strategy_open_ars": 0.0,
                    "committed_capital_option_strategy_open_usd": 0.0,
                    "realized_pnl_closed_approx_ars": 0.0,
                    "realized_pnl_closed_approx_usd": 0.0,
                    "balance_estimated_ars": 0.0,
                    "balance_estimated_usd": 0.0,
                    "notes": [_CASH_UNAVAILABLE_WARNING],
                    "cash_source": "unavailable",
                }, extra_warnings
        # Cualquier otro error: responder con ceros + warning (endpoint siempre responde).
        extra_warnings.append(_CASH_UNAVAILABLE_WARNING)
        extra_warnings.append(f"portfolio balance error: {exc}")
        return {
            "portfolio_type": portfolio_type,
            "cash_ars": 0.0,
            "cash_usd": 0.0,
            "invested_market_value_ars": 0.0,
            "invested_market_value_usd": 0.0,
            "committed_capital_option_strategy_open_ars": 0.0,
            "committed_capital_option_strategy_open_usd": 0.0,
            "realized_pnl_closed_approx_ars": 0.0,
            "realized_pnl_closed_approx_usd": 0.0,
            "balance_estimated_ars": 0.0,
            "balance_estimated_usd": 0.0,
            "notes": [_CASH_UNAVAILABLE_WARNING, str(exc)],
            "cash_source": "unavailable",
        }, extra_warnings


def _safe_list_cash_movements(*, portfolio_type: str, limit: int = 500) -> tuple[list[dict[str, Any]], list[str]]:
    list_cash_movements = _load_list_cash_movements()
    if list_cash_movements is None:
        return [], [_CASH_UNAVAILABLE_WARNING]
    try:
        return list_cash_movements(portfolio_type=portfolio_type, currency="all", limit=limit), []
    except Exception as exc:
        # Ledger ausente u otro fallo de lectura: no bloquear preview/import.
        warn = [_CASH_UNAVAILABLE_WARNING]
        if not _is_cash_movements_unavailable(exc):
            warn.append(f"cash movements read error: {exc}")
        return [], warn


def build_portfolio_summary(*, portfolio_type: str = "real") -> dict[str, Any]:
    """Resumen Cartera por moneda para Family Office (solo lectura)."""
    pt = (portfolio_type or "real").strip().lower()
    if pt not in ("real", "radar"):
        pt = "real"

    balance, cash_warnings = _safe_compute_portfolio_balance(portfolio_type=pt)

    metrics: dict[str, Any] = {}
    open_trades: list[dict[str, Any]] = []
    closed_trades: list[dict[str, Any]] = []
    try:
        metrics = portfolio_instrument_metrics(portfolio_type=pt)
        open_trades = [
            row_as_mapping(r)
            for r in list_trades_filtered(
                status="open", instrument_type="option_strategy", portfolio_type=pt
            )
        ]
        closed_trades = [
            row_as_mapping(r)
            for r in list_trades_filtered(
                status="closed", instrument_type="option_strategy", portfolio_type=pt
            )
        ]
    except Exception as exc:
        cash_warnings.append(f"positions metrics unavailable: {exc}")

    premiums_by_cur = {"ARS": 0.0, "USD": 0.0}
    for row in open_trades + closed_trades:
        cur = _currency_from_asset_type(str(row.get("asset_type") or ""))
        total = compute_strategy_cashflow_total(row)
        if total > 0:
            premiums_by_cur[cur] = premiums_by_cur.get(cur, 0.0) + float(total)
        elif row.get("initial_debit_credit") is not None:
            try:
                idc = float(row["initial_debit_credit"])
                if idc > 0:
                    premiums_by_cur[cur] = premiums_by_cur.get(cur, 0.0) + idc
            except (TypeError, ValueError):
                pass

    warnings: list[str] = list(cash_warnings)
    for note in balance.get("notes") or []:
        s = str(note)
        if s not in warnings:
            warnings.append(s)
    warnings.append(
        "Market value de opciones abiertas no es mark-to-market; usa committed_capital o costo."
    )
    warnings.append(
        "Primas cobradas Ôëá caja familiar retirada. Solo cuentan retiros/aplicaciones expl├¡citas en FO."
    )
    warnings.append("PnL no realizado no se incluye como flujo de caja.")

    open_by = {"ARS": 0, "USD": 0}
    closed_by = {"ARS": 0, "USD": 0}
    for row in open_trades:
        open_by[_currency_from_asset_type(str(row.get("asset_type") or ""))] += 1
    for row in closed_trades:
        closed_by[_currency_from_asset_type(str(row.get("asset_type") or ""))] += 1

    missing_spot: list[str] = []
    for note in balance.get("notes") or []:
        s = str(note)
        if "spot" in s.lower() or "precio" in s.lower() or "mark" in s.lower():
            missing_spot.append(s)

    cash_source = str(balance.get("cash_source") or "portfolio_cash_movements")
    by_currency = {
        "ARS": {
            "asset_value": float(balance.get("invested_market_value_ars") or 0),
            "cash": float(balance.get("cash_ars") or 0),
            "committed_capital": float(
                balance.get("committed_capital_option_strategy_open_ars") or 0
            ),
            "realized_pnl": float(balance.get("realized_pnl_closed_approx_ars") or 0),
            "premiums_collected": float(premiums_by_cur.get("ARS") or 0),
            "premiums_collected_approx": float(premiums_by_cur.get("ARS") or 0),
            "open_strategies": open_by["ARS"],
            "closed_strategies": closed_by["ARS"],
            "updated_at": _now_iso(),
            "missing_spot_warnings": list(missing_spot),
            "data_source": "portfolio.read_only",
            "cash_source": cash_source,
        },
        "USD": {
            "asset_value": float(balance.get("invested_market_value_usd") or 0),
            "cash": float(balance.get("cash_usd") or 0),
            "committed_capital": float(
                balance.get("committed_capital_option_strategy_open_usd") or 0
            ),
            "realized_pnl": float(balance.get("realized_pnl_closed_approx_usd") or 0),
            "premiums_collected": float(premiums_by_cur.get("USD") or 0),
            "premiums_collected_approx": float(premiums_by_cur.get("USD") or 0),
            "open_strategies": open_by["USD"],
            "closed_strategies": closed_by["USD"],
            "updated_at": _now_iso(),
            "missing_spot_warnings": list(missing_spot),
            "data_source": "portfolio.read_only",
            "cash_source": cash_source,
        },
    }

    return {
        "portfolio_type": pt,
        "by_currency": by_currency,
        "open_strategies": int(metrics.get("open_option_strategies_count") or len(open_trades)),
        "closed_strategies": int(
            metrics.get("closed_option_strategies_count") or len(closed_trades)
        ),
        "updated_at": _now_iso(),
        "warnings": warnings,
        "source": {
            "module": "portfolio",
            "functions": [
                "services.portfolio_balance.compute_portfolio_balance",
                "persistence.sqlite.cash_movements_repo.sum_cash_by_currency",
                "persistence.sqlite.positions_repo.portfolio_instrument_metrics",
                "persistence.sqlite.positions_repo.list_trades_filtered",
            ],
            "cash_ledger": "portfolio_cash_movements",
            "cash_status": cash_source,
            "note": "Solo lectura. No modifica Cartera.",
        },
        "notes": [
            "Totales ARS y USD separados; no sumar.",
            "covered call proyectada (p.ej. 55%) no es resultado realizado.",
        ],
    }


def preview_portfolio_import(
    *,
    portfolio_type: str = "real",
    include_source_ids: list[str] | None = None,
    exclude_source_ids: list[str] | None = None,
) -> dict[str, Any]:
    """
    Vista previa de importaci├│n a investment_cashflow_records.
    No escribe. Excluye PnL no realizado.
    """
    pt = (portfolio_type or "real").strip().lower()
    if pt not in ("real", "radar"):
        pt = "real"
    include = set(include_source_ids or [])
    exclude = set(exclude_source_ids or [])

    candidates: list[dict[str, Any]] = []
    warnings = [
        "PnL no realizado excluido.",
        "Primas en estado generated no son caja familiar disponible.",
        "Revis├í y exclu├¡ registros antes de confirmar.",
        "No se importan proyecciones (covered call 55%, etc.).",
    ]

    # Cash movements: dividend / interest only (realized cash ledger)
    movements, mov_warnings = _safe_list_cash_movements(portfolio_type=pt, limit=500)
    for w in mov_warnings:
        if w not in warnings:
            warnings.append(w)

    for mov in movements:
        mt = str(mov.get("movement_type") or "")
        if mt not in ("dividend", "interest"):
            continue
        amount = float(mov.get("amount") or 0)
        if amount <= 0:
            continue
        source_id = f"portfolio:cash_movement:{mov['id']}"
        source_type = "portfolio_cash_movement"
        if exclude and source_id in exclude:
            continue
        if include and source_id not in include:
            continue
        already = flow.get_investment_cashflow_by_source(source_type, source_id) is not None
        date_s = str(mov.get("date") or "")[:10]
        month = date_s[:7] if len(date_s) >= 7 else _now_iso()[:7]
        candidates.append(
            {
                "source_type": source_type,
                "source_id": source_id,
                "already_imported": already,
                "strategy_type": mt,
                "account_name": f"cartera:{pt}",
                "currency": str(mov.get("currency") or "USD").upper(),
                "month": month,
                "gross_income": amount,
                "commissions": 0.0,
                "taxes": 0.0,
                "financing_cost": 0.0,
                "net_cashflow": amount,
                "cash_status": "settled",
                "generated_date": date_s or None,
                "settlement_date": date_s or None,
                "description": mov.get("description"),
                "notes": f"Import preview from cash movement #{mov['id']} ({mt}).",
                "include_default": not already,
            }
        )

    # Closed strategies: realized cashflow PnL only (not unrealized)
    try:
        closed_rows = [
            row_as_mapping(r)
            for r in list_trades_filtered(
                status="closed", instrument_type="option_strategy", portfolio_type=pt
            )
        ]
    except Exception as exc:
        closed_rows = []
        warnings.append(f"closed positions unavailable: {exc}")

    for row in closed_rows:
        pnl = compute_strategy_cashflow_pnl(row)
        if pnl is None:
            continue
        accounting = "cashflow" if option_strategy_use_cashflow_pnl(row) else "legacy"
        stype = str(row.get("strategy_type") or "other")
        if stype == "covered_call" and pnl >= 0:
            fo_type = "covered_call"
        elif pnl >= 0:
            fo_type = "realized_gain"
        else:
            fo_type = "realized_loss"
        source_id = f"portfolio:position:{row['id']}:realized"
        source_type = "portfolio_position"
        if exclude and source_id in exclude:
            continue
        if include and source_id not in include:
            continue
        already = flow.get_investment_cashflow_by_source(source_type, source_id) is not None
        sell_date = str(row.get("sell_date") or row.get("closed_at") or "")[:10]
        month = sell_date[:7] if len(sell_date) >= 7 else _now_iso()[:7]
        cur = _currency_from_asset_type(str(row.get("asset_type") or ""))
        gross = abs(float(pnl))
        candidates.append(
            {
                "source_type": source_type,
                "source_id": source_id,
                "already_imported": already,
                "strategy_type": fo_type,
                "account_name": f"cartera:{pt}:{row.get('ticker') or row.get('underlying_symbol') or row['id']}",
                "currency": cur,
                "month": month,
                "gross_income": gross if pnl >= 0 else 0.0,
                "commissions": 0.0,
                "taxes": 0.0,
                "financing_cost": 0.0,
                "net_cashflow": float(pnl),
                "cash_status": "generated",
                "generated_date": sell_date or None,
                "settlement_date": None,
                "description": f"Closed {stype} ({accounting} accounting)",
                "notes": (
                    f"Import preview position #{row['id']}. "
                    "Estado generated: NO es caja familiar retirada. "
                    "Proyecciones (p.ej. 55%) no se importan."
                ),
                "include_default": not already,
                "strategy_pnl_accounting": accounting,
                "is_closed": compute_strategy_is_closed(row),
            }
        )

        events = management_events_from_row(row)
        for ev in events:
            if str(ev.get("event_type") or "") != "open":
                continue
            dc = ev.get("debit_credit")
            if dc is None:
                continue
            try:
                dc_f = float(dc)
            except (TypeError, ValueError):
                continue
            if dc_f <= 0:
                continue
            eid = str(ev.get("id") or "open")
            sid = f"portfolio:position:{row['id']}:event:{eid}"
            if exclude and sid in exclude:
                continue
            if include and sid not in include:
                continue
            already_ev = flow.get_investment_cashflow_by_source("portfolio_event", sid) is not None
            edate = str(ev.get("date") or "")[:10]
            candidates.append(
                {
                    "source_type": "portfolio_event",
                    "source_id": sid,
                    "already_imported": already_ev,
                    "strategy_type": "covered_call" if stype == "covered_call" else "other",
                    "account_name": f"cartera:{pt}:{row.get('ticker') or row['id']}",
                    "currency": cur,
                    "month": edate[:7] if len(edate) >= 7 else month,
                    "gross_income": dc_f,
                    "commissions": 0.0,
                    "taxes": 0.0,
                    "financing_cost": 0.0,
                    "net_cashflow": dc_f,
                    "cash_status": "generated",
                    "generated_date": edate or None,
                    "settlement_date": None,
                    "description": "Opening premium credit (generated, not withdrawn)",
                    "notes": (
                        "Prima generada/cobrada en cuenta de inversi├│n. "
                        "No cuenta como caja familiar hasta withdrawn/applied."
                    ),
                    "include_default": False,
                }
            )

    importable = [c for c in candidates if not c["already_imported"]]
    return {
        "portfolio_type": pt,
        "candidates": candidates,
        "counts": {
            "total": len(candidates),
            "already_imported": sum(1 for c in candidates if c["already_imported"]),
            "importable": len(importable),
        },
        "warnings": warnings,
        "preview_only": True,
    }


def confirm_portfolio_import(
    *,
    portfolio_type: str = "real",
    include_source_ids: list[str],
    exclude_source_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Importa registros seleccionados con idempotencia source_type+source_id."""
    preview = preview_portfolio_import(
        portfolio_type=portfolio_type,
        include_source_ids=include_source_ids,
        exclude_source_ids=exclude_source_ids,
    )
    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    ts = _now_iso()
    wanted = set(include_source_ids)
    for c in preview["candidates"]:
        sid = c["source_id"]
        if sid not in wanted:
            continue
        if c["already_imported"]:
            skipped.append({"source_id": sid, "reason": "already_imported"})
            continue
        rid = flow.insert_investment_cashflow(
            month=c["month"],
            account_name=c["account_name"],
            strategy_type=c["strategy_type"],
            currency=c["currency"],
            gross_income=c["gross_income"],
            commissions=c["commissions"],
            taxes=c["taxes"],
            financing_cost=c["financing_cost"],
            net_cashflow=c["net_cashflow"],
            cash_status=c.get("cash_status") or "generated",
            generated_date=c.get("generated_date"),
            settlement_date=c.get("settlement_date"),
            source_type=c["source_type"],
            source_id=sid,
            imported_at=ts,
            notes=c.get("notes"),
        )
        row = flow.get_investment_cashflow(rid)
        imported.append(row or {"id": rid, "source_id": sid})
    return {
        "imported_count": len(imported),
        "skipped_count": len(skipped),
        "imported": imported,
        "skipped": skipped,
        "warnings": preview["warnings"],
    }
