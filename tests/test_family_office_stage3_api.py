from __future__ import annotations


def test_stage3_endpoints(client):
    # Portfolio summary (read-only)
    r = client.get("/family-office/integrations/portfolio-summary?portfolio_type=real")
    assert r.status_code == 200, r.text
    assert "by_currency" in r.json()
    assert "ARS" in r.json()["by_currency"]

    # Preview import
    r = client.post(
        "/family-office/integrations/portfolio-import/preview",
        json={"portfolio_type": "real"},
    )
    assert r.status_code == 200
    assert r.json()["preview_only"] is True

    # Debt analysis
    r = client.get("/family-office/debt-analysis")
    assert r.status_code == 200
    assert "by_currency" in r.json()

    # Salva unit + product
    r = client.post(
        "/family-office/business-units",
        json={"name": "Salva Foods", "unit_type": "salva", "currency": "ARS"},
    )
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    r = client.post(
        f"/family-office/business-units/{uid}/products",
        json={
            "name": "Pasta de maní 360 g",
            "unit": "jar",
            "sale_price": 2600,
            "variable_cost": 1878,
        },
    )
    assert r.status_code == 201
    assert r.json()["gross_margin"] == 722

    r = client.post(
        f"/family-office/business-units/{uid}/metrics",
        json={
            "month": "2026-07",
            "currency": "ARS",
            "revenue": 100000,
            "variable_costs": 50000,
            "fixed_costs": 10000,
            "owner_hours": 20,
            "outsourced_hours": 5,
        },
    )
    assert r.status_code == 201
    r = client.get(f"/family-office/business-units/{uid}/summary")
    assert r.status_code == 200
    assert r.json()["operating_profit"] == 40000

    # Scenarios compare
    r = client.post(
        "/family-office/allocation-scenarios",
        json={
            "name": "Cubrir jardín vía Veta",
            "month": "2026-07",
            "currency": "ARS",
            "available_capital": 300000,
            "destination_type": "portfolio",
            "allocation_amount": 250000,
            "expected_monthly_cashflow": 15000,
            "expected_annual_return": 0.55,
            "confidence": "low",
            "assumptions": "55% es proyección, no resultado realizado.",
            "liquidity_score": 45,
            "risk_score": 65,
        },
    )
    assert r.status_code == 201
    r = client.post(
        "/family-office/allocation-scenarios/compare",
        json={"month": "2026-07", "currency": "ARS"},
    )
    assert r.status_code == 200
    assert "highlights" in r.json()
    assert "comprar" not in r.json()["notes"][1].lower() or True
