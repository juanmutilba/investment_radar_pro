from __future__ import annotations

from persistence.sqlite import family_office_flow_repo as flow
from services.family_office import (
    create_cashflow_allocation,
    delete_cashflow_allocation,
    income_available_amount,
)


def test_allocation_available_and_overallocate(fo_db):
    income = flow.insert_cashflow_entry(
        date="2026-07-01",
        month="2026-07",
        entry_type="income",
        category="salary",
        source_unit="employment",
        currency="ARS",
        amount=100_000,
    )
    fe = flow.insert_fixed_expense(
        name="Luz",
        category="utilities",
        currency="ARS",
        expected_monthly_amount=80_000,
        coverage_order=1,
    )
    create_cashflow_allocation(
        month="2026-07",
        currency="ARS",
        source_cashflow_entry_id=income,
        destination_type="fixed_expense",
        destination_id=fe,
        allocated_amount=60_000,
    )
    assert income_available_amount(income) == 40_000
    try:
        create_cashflow_allocation(
            month="2026-07",
            currency="ARS",
            source_cashflow_entry_id=income,
            destination_type="fixed_expense",
            destination_id=fe,
            allocated_amount=50_000,
        )
        ok = False
    except ValueError:
        ok = True
    assert ok


def test_expense_cannot_be_allocation_source(fo_db):
    expense = flow.insert_cashflow_entry(
        date="2026-07-01",
        month="2026-07",
        entry_type="expense",
        category="utilities",
        source_unit="family",
        currency="ARS",
        amount=10_000,
    )
    fe = flow.insert_fixed_expense(
        name="Luz",
        category="utilities",
        currency="ARS",
        expected_monthly_amount=10_000,
        coverage_order=1,
    )
    try:
        create_cashflow_allocation(
            month="2026-07",
            currency="ARS",
            source_cashflow_entry_id=expense,
            destination_type="fixed_expense",
            destination_id=fe,
            allocated_amount=10_000,
        )
        ok = False
    except ValueError as exc:
        ok = True
        assert "egreso" in str(exc).lower() or "ingreso" in str(exc).lower()
    assert ok


def test_f1_rejects_non_fixed_expense_destination(fo_db):
    income = flow.insert_cashflow_entry(
        date="2026-07-01",
        month="2026-07",
        entry_type="income",
        category="salary",
        source_unit="employment",
        currency="ARS",
        amount=10_000,
    )
    try:
        create_cashflow_allocation(
            month="2026-07",
            currency="ARS",
            source_cashflow_entry_id=income,
            destination_type="debt",
            destination_id=1,
            allocated_amount=1_000,
        )
        ok = False
    except ValueError:
        ok = True
    assert ok


def test_delete_allocation_does_not_change_income(fo_db):
    income = flow.insert_cashflow_entry(
        date="2026-07-01",
        month="2026-07",
        entry_type="income",
        category="salary",
        source_unit="employment",
        currency="ARS",
        amount=50_000,
    )
    fe = flow.insert_fixed_expense(
        name="Gas",
        category="utilities",
        currency="ARS",
        expected_monthly_amount=20_000,
        coverage_order=1,
    )
    row = create_cashflow_allocation(
        month="2026-07",
        currency="ARS",
        source_cashflow_entry_id=income,
        destination_type="fixed_expense",
        destination_id=fe,
        allocated_amount=20_000,
    )
    delete_cashflow_allocation(int(row["id"]))
    src = flow.get_cashflow_entry(income)
    assert src is not None
    assert float(src["amount"]) == 50_000
    assert income_available_amount(income) == 50_000


def test_schema_v10_has_allocations_table(fo_db):
    from persistence.sqlite.connection import connection_scope

    with connection_scope() as conn:
        ver = int(conn.execute("PRAGMA user_version").fetchone()[0])
        assert ver >= 10
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='family_cashflow_allocations'"
        ).fetchone()
        assert row is not None
        cols = {
            str(r[1])
            for r in conn.execute("PRAGMA table_info(family_cashflow_entries)").fetchall()
        }
        assert "is_fixed_expense" in cols
