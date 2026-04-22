from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator
from contextlib import contextmanager

from persistence.sqlite.init import init_database
from persistence.sqlite.paths import default_db_path


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Conexión con foreign keys y filas tipo mapping (sqlite3.Row)."""
    path = db_path or default_db_path()
    init_database(path)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def connection_scope(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
