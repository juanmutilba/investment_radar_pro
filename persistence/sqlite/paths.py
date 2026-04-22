from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    """Raíz del repo (investment_radar_pro/)."""
    return Path(__file__).resolve().parent.parent.parent


def default_db_path() -> Path:
    """
    Ruta por defecto: data/investment_radar.db (misma carpeta que otros JSON locales).
    Override opcional: INVESTMENT_RADAR_DB_PATH.
    """
    override = os.getenv("INVESTMENT_RADAR_DB_PATH", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    d = project_root() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / "investment_radar.db"
