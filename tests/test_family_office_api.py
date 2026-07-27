from __future__ import annotations


def test_asset_crud_and_dashboard(client):
    r = client.post(
        "/family-office/assets",
        json={
            "name": "Auto",
            "category": "vehicle",
            "ownership_status": "owned",
            "currency": "USD",
            "estimated_value": 15000,
            "valuation_date": "2026-07-01",
            "liquidity": "medium",
            "generates_cashflow": False,
            "monthly_cashflow": 0,
        },
    )
    assert r.status_code == 201, r.text
    asset = r.json()
    assert asset["id"] > 0
    assert asset["currency"] == "USD"

    r = client.post(
        "/family-office/liabilities",
        json={
            "name": "Prestamo auto",
            "liability_type": "vehicle_loan",
            "currency": "USD",
            "original_amount": 10000,
            "outstanding_balance": 4000,
            "installment_amount": 300,
            "installments_remaining": 14,
            "nominal_annual_rate": 12,
            "linked_asset_id": asset["id"],
        },
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/family-office/policies",
        json={
            "name": "Ahorro casa",
            "destination": "house",
            "minimum_monthly_amount": 100,
            "maximum_monthly_amount": 500,
            "priority": 1,
            "is_mandatory": True,
        },
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/family-office/house-projects",
        json={
            "name": "Pintura",
            "priority": "aesthetic",
            "estimated_cost": 800,
            "paid_amount": 0,
            "currency": "USD",
            "status": "planned",
        },
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/family-office/snapshots",
        json={
            "month": "2026-07",
            "active_income": 5000,
            "fixed_expenses": 2000,
            "debt_payments": 300,
            "house_spending": 100,
            "investment_contributions": 400,
            "currency": "USD",
        },
    )
    assert r.status_code == 201, r.text
    snap = r.json()
    assert snap["free_cashflow"] == 2200.0

    r = client.get("/family-office/dashboard")
    assert r.status_code == 200, r.text
    dash = r.json()
    assert dash["assets_by_currency"]["USD"] == 15000
    assert dash["liabilities_by_currency"]["USD"] == 4000
    assert dash["net_worth_by_currency"]["USD"] == 11000
    assert dash["latest_free_cashflow"] == 2200.0
    assert "ARS" in dash["net_worth_by_currency"]
    assert "UVA" in dash["net_worth_by_currency"]


def test_reject_negative_amount(client):
    r = client.post(
        "/family-office/assets",
        json={
            "name": "Bad",
            "category": "cash",
            "ownership_status": "owned",
            "currency": "ARS",
            "estimated_value": -10,
            "valuation_date": "2026-07-01",
            "liquidity": "high",
        },
    )
    assert r.status_code == 422


def test_reject_invalid_currency(client):
    r = client.post(
        "/family-office/assets",
        json={
            "name": "Bad FX",
            "category": "cash",
            "ownership_status": "owned",
            "currency": "EUR",
            "estimated_value": 10,
            "valuation_date": "2026-07-01",
            "liquidity": "high",
        },
    )
    assert r.status_code == 422


def test_soft_delete_asset(client):
    r = client.post(
        "/family-office/assets",
        json={
            "name": "Temp",
            "category": "other",
            "ownership_status": "owned",
            "currency": "ARS",
            "estimated_value": 1,
            "valuation_date": "2026-07-01",
            "liquidity": "low",
        },
    )
    assert r.status_code == 201
    aid = r.json()["id"]
    r = client.delete(f"/family-office/assets/{aid}")
    assert r.status_code == 200
    assert r.json()["is_active"] is False
    r = client.get("/family-office/assets")
    assert all(a["id"] != aid for a in r.json())
    r = client.get("/family-office/assets?active_only=false")
    assert any(a["id"] == aid and a["is_active"] is False for a in r.json())


def test_policy_min_max_validation(client):
    r = client.post(
        "/family-office/policies",
        json={
            "name": "Bad policy",
            "destination": "debt",
            "minimum_monthly_amount": 500,
            "maximum_monthly_amount": 100,
            "priority": 1,
        },
    )
    assert r.status_code == 422
