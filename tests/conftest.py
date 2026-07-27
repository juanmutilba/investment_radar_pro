from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def fo_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "family_office_test.db"
    monkeypatch.setenv("INVESTMENT_RADAR_DB_PATH", str(db_path))
    # Ensure modules that cached nothing re-read path via env.
    from persistence.sqlite.init import init_database

    init_database(db_path)
    return db_path


@pytest.fixture()
def client(fo_db: Path) -> TestClient:
    # Import after env override so lifespan/init use the temp DB.
    from api.app import app

    with TestClient(app) as c:
        yield c
