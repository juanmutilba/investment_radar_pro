from __future__ import annotations

import pytest

from persistence.sqlite import family_office_business_repo as biz
from persistence.sqlite import family_office_flow_repo as flow
from persistence.sqlite import family_office_repo as repo

try:
    from persistence.sqlite.cash_movements_repo import insert_cash_movement
except ImportError:  # foundation worktree: no PCM repo
    insert_cash_movement = None
from services.family_office import build_fixed_expense_coverage
from services.family_office_portfolio_adapter import (
    build_portfolio_summary,
    confirm_portfolio_import,
    preview_portfolio_import,
)
from services.family_office_stage3 import (
    build_business_unit_summary,
    build_debt_analysis,
    compare_allocation_scenarios,
    simulate_debt_scenario,
)


@pytest.mark.skipif(insert_cash_movement is None, reason="foundation: no portfolio cash movements repo")
def test_portfolio_summary_separates_currencies(fo_db):
    insert_cash_movement(
        portfolio_type="real",
        asset_type="general",
        currency="ARS",
        date="2026-07-01",
        movement_type="deposit",
        amount=1000,
        description="test",
    )
    insert_cash_movement(
        portfolio_type="real",
        asset_type="general",
        currency="USD",
        date="2026-07-01",
        movement_type="deposit",
        amount=50,
        description="test",
    )
    summary = build_portfolio_summary(portfolio_type="real")
    assert summary["by_currency"]["ARS"]["cash"] == 1000
    assert summary["by_currency"]["USD"]["cash"] == 50
    assert "source" in summary


def test_portfolio_summary_without_cash_movements_ledger(fo_db):
    """Foundation: sin ledger PCM el adapter degrada a cash=0 con warning."""
    summary = build_portfolio_summary(portfolio_type="real")
    assert summary["by_currency"]["ARS"]["cash"] == 0
    assert summary["by_currency"]["USD"]["cash"] == 0
    assert "cash movements unavailable" in summary["warnings"]

    from unittest.mock import patch

    with patch(
        "services.family_office_portfolio_adapter._load_portfolio_balance",
        return_value=None,
    ):
        degraded = build_portfolio_summary(portfolio_type="real")
    assert degraded["by_currency"]["ARS"]["cash"] == 0
    assert "cash movements unavailable" in degraded["warnings"]

    with patch(
        "services.family_office_portfolio_adapter._load_list_cash_movements",
        return_value=None,
    ):
        preview = preview_portfolio_import(portfolio_type="real")
    assert preview["preview_only"] is True
    assert "cash movements unavailable" in preview["warnings"]
    assert all(c["source_type"] != "portfolio_cash_movement" for c in preview["candidates"])


@pytest.mark.skipif(insert_cash_movement is None, reason="foundation: no portfolio cash movements repo")
def test_import_idempotent_and_excludes_unrealized(fo_db):
    mid = insert_cash_movement(
        portfolio_type="real",
        asset_type="general",
        currency="ARS",
        date="2026-07-10",
        movement_type="dividend",
        amount=2500,
        description="div",
    )
    preview = preview_portfolio_import(portfolio_type="real")
    divs = [c for c in preview["candidates"] if c["strategy_type"] == "dividend"]
    assert len(divs) >= 1
    sid = divs[0]["source_id"]
    assert f"cash_movement:{mid}" in sid
    # No unrealized markers in candidates
    assert all("unrealized" not in str(c).lower() for c in preview["candidates"])

    r1 = confirm_portfolio_import(portfolio_type="real", include_source_ids=[sid])
    assert r1["imported_count"] == 1
    r2 = confirm_portfolio_import(portfolio_type="real", include_source_ids=[sid])
    assert r2["imported_count"] == 0
    assert r2["skipped_count"] == 1


def test_cash_status_transitions_and_coverage_only_applied(fo_db):
    fe = flow.insert_fixed_expense(
        name="Jardín",
        category="education",
        currency="ARS",
        expected_monthly_amount=100_000,
        coverage_order=1,
        is_essential=True,
    )
    rid = flow.insert_investment_cashflow(
        month="2026-07",
        account_name="Veta",
        strategy_type="covered_call",
        currency="ARS",
        gross_income=80_000,
        commissions=0,
        taxes=0,
        financing_cost=0,
        cash_status="generated",
    )
    cov = build_fixed_expense_coverage(month="2026-07", currency="ARS")
    assert cov["items"][0]["assigned_cashflow"] == 0
    assert cov["items"][0]["covered"] == 0

    flow.transition_investment_cash_status(rid, to_status="settled")
    flow.transition_investment_cash_status(
        rid, to_status="applied", fixed_expense_id=fe
    )
    row = flow.get_investment_cashflow(rid)
    assert row is not None
    assert row["cash_status"] == "applied"
    hist = flow.list_status_history(rid)
    assert len(hist) >= 3

    cov2 = build_fixed_expense_coverage(month="2026-07", currency="ARS")
    assert cov2["items"][0]["covered"] == 0
    assert cov2["items"][0]["assigned_cashflow"] == 0

    income_id = flow.insert_cashflow_entry(
        date="2026-07-10",
        month="2026-07",
        entry_type="income",
        category="dividend",
        source_unit="investments",
        currency="ARS",
        amount=80_000,
    )
    from services.family_office import create_cashflow_allocation

    create_cashflow_allocation(
        month="2026-07",
        currency="ARS",
        source_cashflow_entry_id=income_id,
        destination_type="fixed_expense",
        destination_id=fe,
        allocated_amount=80_000,
    )
    cov3 = build_fixed_expense_coverage(month="2026-07", currency="ARS")
    assert cov3["items"][0]["covered"] == 80_000
    assert cov3["items"][0]["fully_covered"] is False  # commitment 100k

    # applied without fixed_expense_id fails
    rid2 = flow.insert_investment_cashflow(
        month="2026-07",
        account_name="Veta",
        strategy_type="dividend",
        currency="ARS",
        gross_income=10,
        cash_status="settled",
    )
    try:
        flow.transition_investment_cash_status(rid2, to_status="applied")
        ok = False
    except ValueError:
        ok = True
    assert ok


def test_partial_withdraw_modeled_as_withdrawn_status(fo_db):
    rid = flow.insert_investment_cashflow(
        month="2026-07",
        account_name="Veta",
        strategy_type="interest",
        currency="ARS",
        gross_income=1000,
        cash_status="settled",
        notes="retiro parcial documentado en notes",
    )
    out = flow.transition_investment_cash_status(
        rid, to_status="withdrawn", notes="retiro parcial a caja familiar"
    )
    assert out["cash_status"] == "withdrawn"
    assert out.get("withdrawal_date")


def test_debt_simulation_complete_and_approximate(fo_db):
    lid = repo.insert_liability(
        name="Descubierto",
        liability_type="overdraft",
        currency="ARS",
        original_amount=800_000,
        outstanding_balance=800_000,
        installment_amount=20_000,
        installments_remaining=24,
        nominal_annual_rate=18.5,
        rate_type="variable",
        allows_partial_prepayment=True,
    )
    full = simulate_debt_scenario(
        liability_id=lid,
        prepayment_amount=800_000,
        scenario_type="full_cancel",
    )
    assert full["balance_after"] == 0
    assert full["monthly_cashflow_freed"] == 20_000

    lid2 = repo.insert_liability(
        name="Sin tasa",
        liability_type="personal_loan",
        currency="ARS",
        original_amount=100_000,
        outstanding_balance=100_000,
        installment_amount=0,
        installments_remaining=0,
        nominal_annual_rate=0,
    )
    approx = simulate_debt_scenario(
        liability_id=lid2,
        prepayment_amount=50_000,
        scenario_type="reduce_installment",
        assumptions={"assumed_annual_rate": 18.5, "assumed_months": 12},
    )
    assert approx["approximate"] is True
    assert any("APROXIMADO" in w or "faltante" in w.lower() or "asume" in w.lower() for w in approx["warnings"]) or approx["assumptions_used"]

    analysis = build_debt_analysis()
    assert "ARS" in analysis["by_currency"]


def test_salva_product_margin_hours_payback(fo_db):
    uid = biz.insert_business_unit(
        name="Salva Foods", unit_type="salva", currency="ARS"
    )
    pid = biz.insert_product(
        business_unit_id=uid,
        name="Pasta de maní 360 g",
        unit="jar",
        sale_price=2600,
        variable_cost=1878,
    )
    products = biz.list_products(uid)
    p = next(x for x in products if x["id"] == pid)
    assert p["gross_margin"] == 722

    biz.upsert_metric(
        business_unit_id=uid,
        month="2026-07",
        currency="ARS",
        revenue=260_000,
        variable_costs=187_800,
        fixed_costs=20_000,
        owner_hours=40,
        outsourced_hours=10,
        units_sold=100,
    )
    summary = build_business_unit_summary(uid)
    assert summary["gross_profit"] == 260_000 - 187_800
    assert summary["operating_profit"] == (260_000 - 187_800 - 20_000)
    assert abs(summary["profit_per_owner_hour"] - ((260_000 - 187_800 - 20_000) / 40)) < 1e-6
    assert abs(summary["founder_dependency_index"] - (40 / 50)) < 1e-9

    cid = biz.insert_investment_case(
        business_unit_id=uid,
        name="Automatización",
        currency="ARS",
        investment_amount=300_000,
        investment_type="automation",
        bottleneck="founder_dependency",
        expected_monthly_profit_increment=50_000,
        expected_hours_saved=10,
    )
    case = next(c for c in biz.list_investment_cases(uid) if c["id"] == cid)
    assert case["payback_months"] == 6.0


def test_scenario_compare_and_currency_isolation(fo_db):
    s1 = biz.insert_scenario(
        name="Veta aportes",
        month="2026-07",
        currency="ARS",
        available_capital=300_000,
        destination_type="portfolio",
        allocation_amount=250_000,
        expected_monthly_cashflow=20_000,
        expected_annual_return=0.55,
        liquidity_score=40,
        risk_score=70,
        confidence="low",
        assumptions="Proyección covered call 55% NO es resultado realizado.",
    )
    s2 = biz.insert_scenario(
        name="Bajar descubierto",
        month="2026-07",
        currency="ARS",
        available_capital=300_000,
        destination_type="debt",
        allocation_amount=300_000,
        expected_monthly_cashflow=5_000,
        liquidity_score=80,
        risk_score=20,
        confidence="medium",
        expected_hours_saved=0,
    )
    biz.insert_scenario(
        name="USD cash",
        month="2026-07",
        currency="USD",
        available_capital=1000,
        destination_type="cash",
        allocation_amount=1000,
        expected_monthly_cashflow=0,
        liquidity_score=100,
        risk_score=5,
        confidence="high",
    )
    cmp_ars = compare_allocation_scenarios(month="2026-07", currency="ARS")
    assert len(cmp_ars["scenarios"]) == 2
    assert cmp_ars["highlights"]["highest_expected_cashflow"]["id"] == s1
    assert cmp_ars["highlights"]["lowest_risk_score"]["id"] == s2
    assert all(s["currency"] == "ARS" for s in cmp_ars["scenarios"])


def test_isolation_portfolio_tables_unchanged_by_fo_stage3(fo_db):
    from persistence.sqlite.connection import connection_scope

    biz.insert_business_unit(name="Salva Foods", unit_type="salva", currency="ARS")
    with connection_scope() as conn:
        # FO writes must not create portfolio rows
        pos = conn.execute("SELECT COUNT(*) AS c FROM positions").fetchone()["c"]
    assert int(pos) == 0
