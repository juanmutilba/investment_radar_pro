-- Esquema v1: cartera (positions), historial de scans (scan_runs + scan_metrics).
-- Idempotente: CREATE IF NOT EXISTS + índices IF NOT EXISTS.

PRAGMA foreign_keys = ON;

-- Seguimiento de compras / cartera (módulo nuevo; no reemplaza Excel del radar).
CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  market TEXT,
  side TEXT NOT NULL DEFAULT 'long' CHECK (side IN ('long', 'short')),
  quantity REAL,
  avg_price REAL,
  currency TEXT,
  opened_at TEXT,
  closed_at TEXT,
  notes TEXT,
  meta_json TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_positions_ticker ON positions (ticker);
CREATE INDEX IF NOT EXISTS ix_positions_opened_at ON positions (opened_at);

-- Una fila por ejecución de scan (CLI, API, etc.).
CREATE TABLE IF NOT EXISTS scan_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('running', 'completed', 'failed')),
  source TEXT,
  export_file TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_scan_runs_finished_at ON scan_runs (finished_at DESC);

-- Métricas agregadas de una corrida (1:1 con scan_runs); columnas consultables + JSON completo.
CREATE TABLE IF NOT EXISTS scan_metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_run_id INTEGER NOT NULL UNIQUE REFERENCES scan_runs (id) ON DELETE CASCADE,
  total_scan_seconds REAL,
  usa_scan_seconds REAL,
  arg_scan_seconds REAL,
  cedear_scan_seconds REAL,
  alerts_seconds REAL,
  usa_total_activos INTEGER,
  arg_total_activos INTEGER,
  cedear_total_activos INTEGER,
  usa_alertas INTEGER,
  arg_alertas INTEGER,
  cedear_alertas INTEGER,
  metrics_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_scan_metrics_scan_run_id ON scan_metrics (scan_run_id);
