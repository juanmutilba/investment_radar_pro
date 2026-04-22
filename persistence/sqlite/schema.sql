-- Esquema v1: cartera (positions), historial de scans (scan_runs + scan_metrics).
-- Idempotente: CREATE IF NOT EXISTS + índices IF NOT EXISTS.

PRAGMA foreign_keys = ON;

-- Cartera: una fila por posición; compra manual + cierre total (sin ventas parciales).
CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  asset_type TEXT NOT NULL CHECK (asset_type IN ('USA', 'Argentina', 'CEDEAR')),
  quantity REAL NOT NULL,
  buy_date TEXT NOT NULL,
  buy_price_ars REAL,
  buy_price_usd REAL,
  notes TEXT,
  buy_price_cedear_usd REAL,
  buy_price_usa REAL,
  buy_gap REAL,
  score_at_buy REAL,
  signalstate_at_buy TEXT,
  techscore_at_buy REAL,
  fundscore_at_buy REAL,
  riskscore_at_buy REAL,
  sell_date TEXT,
  sell_price_ars REAL,
  sell_price_usd REAL,
  sell_notes TEXT,
  sell_price_cedear_usd REAL,
  sell_price_usa REAL,
  sell_gap REAL,
  score_at_sell REAL,
  signalstate_at_sell TEXT,
  techscore_at_sell REAL,
  fundscore_at_sell REAL,
  riskscore_at_sell REAL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
  realized_return_pct REAL,
  holding_days INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  market TEXT,
  side TEXT DEFAULT 'long',
  avg_price REAL,
  currency TEXT,
  opened_at TEXT,
  closed_at TEXT,
  meta_json TEXT
);

CREATE INDEX IF NOT EXISTS ix_positions_ticker ON positions (ticker);
CREATE INDEX IF NOT EXISTS ix_positions_buy_date ON positions (buy_date);
CREATE INDEX IF NOT EXISTS ix_positions_status ON positions (status);

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
