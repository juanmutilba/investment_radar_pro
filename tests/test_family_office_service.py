from __future__ import annotations

import sqlite3

import pytest

from persistence.sqlite import family_office_repo as repo
from persistence.sqlite.connection import connection_scope
from services.family_office import build_dashboard, compute_snapshot_free_cashflow


def test_compute_snapshot_free_cashflow():
    fcf = compute_snapshot_free_cashflow(
        active_income=1000,
        consulting_income=200,
        scalable_income=50,
        fixed_expenses=400,
        debt_payments=100,
        house_spending=50,
        investment_contributions=100,
    )
    assert fcf == 600.0


def test_dashboard_separates_currencies(fo_db):
    repo.insert_asset(
        name="Depto ARS",
        category="real_estate",
        ownership_status="mortgaged",
        currency="ARS",
        estimated_value=100_000_000,
        valuation_date="2026-07-01",
        liquidity="low",
        generates_cashflow=False,
    )
    repo.insert_asset(
        name="Caja USD",
        category="cash",
        ownership_status="owned",
        currency="USD",
        estimated_value=10_000,
        valuation_date="2026-07-01",
        liquidity="high",
        generates_cashflow=False,
    )
    repo.insert_asset(
        name="Alquiler",
        category="real_estate",
        ownership_status="owned",
        currency="USD",
        estimated_value=80_000,
        valuation_date="2026-07-01",
        liquidity="low",
        generates_cashflow=True,
        monthly_cashflow=500,
    )
    repo.insert_liability(
        name="Hipoteca UVA",
        liability_type="mortgage_uva",
        currency="UVA",
        original_amount=50_000,
        outstanding_balance=40_000,
        installment_amount=300,
    )
    repo.insert_liability(
        name="Prestamo USD",
        liability_type="personal_loan",
        currency="USD",
        original_amount=5_000,
        outstanding_balance=2_000,
    )
    repo.insert_house_project(
        name="Cocina",
        priority="necessary",
        estimated_cost=2_000_000,
        paid_amount=200_000,
        currency="ARS",
        status="in_progress",
    )
    repo.upsert_snapshot(
        month="2026-07",
        active_income=1_000_000,
        fixed_expenses=400_000,
        debt_payments=100_000,
        currency="ARS",
    )

    dash = build_dashboard()

    assert dash["assets_by_currency"]["ARS"] == 100_000_000
    assert dash["assets_by_currency"]["USD"] == 90_000
    assert dash["liabilities_by_currency"]["UVA"] == 40_000
    assert dash["liabilities_by_currency"]["USD"] == 2_000
    assert dash["net_worth_by_currency"]["ARS"] == 100_000_000
    assert dash["net_worth_by_currency"]["USD"] == 88_000
    assert dash["net_worth_by_currency"]["UVA"] == -40_000
    assert dash["liquid_assets_by_currency"]["USD"] == 10_000
    assert dash["monthly_cashflow_by_currency"]["USD"] == 500
    assert dash["house_projects_by_status"]["in_progress"] == 1
    assert dash["latest_free_cashflow"] == 500_000.0
    assert dash["latest_snapshot_currency"] == "ARS"
    assert "Totales separados por moneda" in dash["notes"][0]


def test_rejects_negative_via_repo_constraints(fo_db):
    with pytest.raises(sqlite3.IntegrityError):
        with connection_scope() as conn:
            conn.execute(
                """
                INSERT INTO family_assets (
                  name, category, ownership_status, currency, estimated_value,
                  valuation_date, liquidity, generates_cashflow, monthly_cashflow,
                  is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 1, datetime('now'), datetime('now'))
                """,
                ("Bad", "cash", "owned", "USD", -1, "2026-07-01", "high"),
            )
