import { useEffect, useMemo, useState } from "react";

import { fetchRavaOptionChain } from "@/services/api";

const UNDERLYING_CHOICES = ["GFG", "COM", "ALU", "BYM"] as const;

type FlatRow = {
  activo: string;
  tipo: "CALL" | "PUT";
  strike: number;
  expiryCode: string;
  raw: Record<string, unknown>;
};

function fmtCell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number" && !Number.isFinite(v)) return "—";
  return String(v);
}

function flattenChain(chain: Record<string, unknown>, activo: string): FlatRow[] {
  const out: FlatRow[] = [];
  for (const [expiryCode, bucket] of Object.entries(chain)) {
    if (bucket === null || typeof bucket !== "object") continue;
    const b = bucket as { calls?: Record<string, unknown>; puts?: Record<string, unknown> };
    const calls = b.calls ?? {};
    const puts = b.puts ?? {};
    for (const [strikeKey, row] of Object.entries(calls)) {
      if (row === null || typeof row !== "object") continue;
      const strike = Number(strikeKey);
      if (!Number.isFinite(strike)) continue;
      out.push({ activo, tipo: "CALL", strike, expiryCode, raw: row as Record<string, unknown> });
    }
    for (const [strikeKey, row] of Object.entries(puts)) {
      if (row === null || typeof row !== "object") continue;
      const strike = Number(strikeKey);
      if (!Number.isFinite(strike)) continue;
      out.push({ activo, tipo: "PUT", strike, expiryCode, raw: row as Record<string, unknown> });
    }
  }
  out.sort((a, b) => a.strike - b.strike);
  return out;
}

export function OptionsPage() {
  const [selectedUnderlying, setSelectedUnderlying] = useState<string>("GFG");
  const [rows, setRows] = useState<FlatRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchRavaOptionChain(selectedUnderlying)
      .then((chain) => {
        if (cancelled) return;
        setRows(flattenChain(chain, selectedUnderlying));
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
        setRows([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedUnderlying]);

  const emptyHint = useMemo(() => {
    if (loading || error) return null;
    if (rows.length === 0) return "Sin filas (cadena vacía o sin opciones para este subyacente).";
    return null;
  }, [loading, error, rows.length]);

  return (
    <div className="page options-page">
      <header className="page__header">
        <h1>Opciones Rava</h1>
        <p className="page__subtitle">
          Activo: <strong>{selectedUnderlying}</strong>
        </p>
      </header>

      <div className="radar-toolbar" role="toolbar" aria-label="Opciones de cadena">
        <label className="radar-toolbar__field">
          <span className="radar-toolbar__label">Activo</span>
          <select
            className="radar-toolbar__select"
            value={selectedUnderlying}
            onChange={(ev) => setSelectedUnderlying(ev.target.value)}
            aria-label="Activo subyacente"
          >
            {UNDERLYING_CHOICES.map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
        </label>
      </div>

      {loading && <p>Cargando…</p>}
      {error && (
        <p role="alert">
          Error: {error}
        </p>
      )}
      {emptyHint && <p>{emptyHint}</p>}

      {!loading && !error && rows.length > 0 && (
        <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Activo</th>
              <th>Tipo</th>
              <th>Strike</th>
              <th>Vto</th>
              <th>Días</th>
              <th>Precio</th>
              <th>Bid</th>
              <th>Ask</th>
              <th>Volumen</th>
              <th>Ops</th>
              <th>ITM/OTM</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const o = r.raw;
              const key = `${r.expiryCode}-${r.tipo}-${r.strike}-${i}`;
              return (
                <tr key={key}>
                  <td>{r.activo}</td>
                  <td>{r.tipo}</td>
                  <td>{fmtCell(r.strike)}</td>
                  <td>{fmtCell(o.expiry_date)}</td>
                  <td>{fmtCell(o.days_to_expiry)}</td>
                  <td>{fmtCell(o.option_price)}</td>
                  <td>{fmtCell(o.bid)}</td>
                  <td>{fmtCell(o.ask)}</td>
                  <td>{fmtCell(o.volumen_float)}</td>
                  <td>{fmtCell(o.operaciones_int)}</td>
                  <td>{fmtCell(o.money_status)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        </div>
      )}
    </div>
  );
}
