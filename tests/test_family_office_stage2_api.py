from __future__ import annotations


def test_stage2_endpoints_and_soft_delete_house(client):
    # Fixed expense
    r = client.post(
        "/family-office/fixed-expenses",
        json={
            "name": "Jardín",
            "category": "education",
            "currency": "ARS",
            "expected_monthly_amount": 100000,
            "coverage_order": 1,
            "is_essential": True,
        },
    )
    assert r.status_code == 201, r.text
    fe_id = r.json()["id"]

    # Cashflow ARS + USD same month
    r = client.post(
        "/family-office/cashflow-entries",
        json={
            "date": "2026-07-01",
            "month": "2026-07",
            "entry_type": "income",
            "category": "salary",
            "source_unit": "employment",
            "currency": "ARS",
            "amount": 500000,
        },
    )
    assert r.status_code == 201, r.text
    r = client.post(
        "/family-office/cashflow-entries",
        json={
            "date": "2026-07-01",
            "month": "2026-07",
            "entry_type": "income",
            "category": "salary",
            "source_unit": "employment",
            "currency": "USD",
            "amount": 1000,
        },
    )
    assert r.status_code == 201, r.text

    r = client.get("/family-office/monthly-summary?month=2026-07&currency=ARS")
    assert r.status_code == 200
    assert r.json()["free_cashflow"] == 500000
    r = client.get("/family-office/monthly-summary?month=2026-07&currency=USD")
    assert r.json()["free_cashflow"] == 1000

    # Investment net cashflow
    r = client.post(
        "/family-office/investment-cashflow-records",
        json={
            "month": "2026-07",
            "account_name": "Veta",
            "strategy_type": "covered_call",
            "currency": "ARS",
            "gross_income": 100000,
            "commissions": 2000,
            "taxes": 3000,
            "financing_cost": 5000,
            "fixed_expense_id": fe_id,
            "notes": "Proyección 55% NO es resultado realizado; este registro es bruto/neto real.",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["net_cashflow"] == 90000
    inv_id = r.json()["id"]
    r = client.post(
        f"/family-office/investment-cashflow-records/{inv_id}/status",
        json={"to_status": "applied", "fixed_expense_id": fe_id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["cash_status"] == "applied"

    # Leverage
    r = client.post(
        "/family-office/leverage-records",
        json={
            "month": "2026-07",
            "currency": "ARS",
            "average_balance_used": 800000,
            "days_used": 20,
            "nominal_annual_rate": 18.5,
            "interest_paid": 10000,
            "taxes_and_fees": 500,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["total_financing_cost"] == 10500

    r = client.get("/family-office/leverage-performance?month=2026-07")
    assert r.status_code == 200
    assert "by_currency" in r.json()

    # Allocation ok then over-allocation blocked
    r = client.post(
        "/family-office/capital-allocations",
        json={
            "month": "2026-07",
            "currency": "ARS",
            "available_amount": 500000,
            "destination": "investments",
            "allocated_amount": 200000,
            "status": "proposed",
            "rationale": "Aporte manual a Veta (objetivo 200k-300k).",
            "expected_return": 0.55,
            "notes": None,
        },
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/family-office/capital-allocations",
        json={
            "month": "2026-07",
            "currency": "ARS",
            "available_amount": 500000,
            "destination": "house",
            "allocated_amount": 400000,
            "status": "proposed",
        },
    )
    assert r.status_code == 400, r.text

    r = client.get("/family-office/allocation-board?month=2026-07&currency=ARS")
    assert r.status_code == 200
    assert r.json()["amount_allocated"] == 200000

    r = client.get("/family-office/fixed-expense-coverage?month=2026-07&currency=ARS")
    assert r.status_code == 200
    cov = r.json()["items"][0]
    assert cov["assigned_cashflow"] == 0
    assert cov["covered"] == 0

    income_id = client.get("/family-office/cashflow-entries?month=2026-07&currency=ARS").json()[0]["id"]
    r = client.post(
        "/family-office/cashflow-allocations",
        json={
            "month": "2026-07",
            "currency": "ARS",
            "source_cashflow_entry_id": income_id,
            "destination_type": "fixed_expense",
            "destination_id": fe_id,
            "allocated_amount": 90000,
        },
    )
    assert r.status_code == 201, r.text

    r = client.get("/family-office/fixed-expense-coverage?month=2026-07&currency=ARS")
    assert r.status_code == 200
    cov2 = r.json()["items"][0]
    assert cov2["assigned_cashflow"] == 0
    assert cov2["covered"] == 90000

    # Close / reopen
    r = client.post("/family-office/month-closures/2026-07/ARS/close")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "closed"
    r = client.post("/family-office/month-closures/2026-07/ARS/reopen")
    assert r.status_code == 200
    assert r.json()["status"] == "reopened"

    # House soft delete
    r = client.post(
        "/family-office/house-projects",
        json={
            "name": "Pintura",
            "priority": "aesthetic",
            "estimated_cost": 1000,
            "paid_amount": 0,
            "currency": "ARS",
        },
    )
    assert r.status_code == 201
    hid = r.json()["id"]
    r = client.delete(f"/family-office/house-projects/{hid}")
    assert r.status_code == 200
    assert r.json()["is_active"] is False
    r = client.get("/family-office/house-projects")
    assert all(p["id"] != hid for p in r.json())

    # Isolation: portfolio endpoints still empty / unaffected
    r = client.get("/portfolio/positions/open?portfolio_type=all")
    assert r.status_code == 200
    assert r.json() == []
