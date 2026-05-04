import { useEffect, useMemo, useState } from "react";

import { fetchRavaOptionChain } from "@/services/api";

const UNDERLYING_DEFAULT = "GFG";

type FlatRow = {
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

function flattenChain(chain: Record<string, unknown>): FlatRow[] {
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
      out.push({ tipo: "CALL", strike, expiryCode, raw: row as Record<string, unknown> });
    }
    for (const [strikeKey, row] of Object.entries(puts)) {
      if (row === null || typeof row !== "object") continue;
      const strike = Number(strikeKey);
      if (!Number.isFinite(strike)) continue;
      out.push({ tipo: "PUT", strike, expiryCode, raw: row as Record<string, unknown> });
    }
  }
  out.sort((a, b) => a.strike - b.strike);
  return out;
}

export function OptionsPage() {
  const [rows, setRows] = useState<FlatRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchRavaOptionChain(UNDERLYING_DEFAULT)
      .then((chain) => {
        if (cancelled) return;
        setRows(flattenChain(chain));
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
  }, []);

  const emptyHint = useMemo(() => {
    if (loading || error) return null;
    if (rows.length === 0) return "Sin filas (cadena vacía o sin opciones para este subyacente).";
    return null;
  }, [loading, error, rows.length]);

  return (
    <div className="page options-page">
      <header className="page__header">
        <h1>Opciones (Rava)</h1>
        <p className="page__subtitle">
          Subyacente: <strong>{UNDERLYING_DEFAULT}</strong> — GET /options/rava/chain
        </p>
      </header>

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
              <th>tipo</th>
              <th>strike</th>
              <th>expiry_date</th>
              <th>days_to_expiry</th>
              <th>option_price</th>
              <th>bid</th>
              <th>ask</th>
              <th>volumen_float</th>
              <th>operaciones_int</th>
              <th>money_status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const o = r.raw;
              const key = `${r.expiryCode}-${r.tipo}-${r.strike}-${i}`;
              return (
                <tr key={key}>
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
