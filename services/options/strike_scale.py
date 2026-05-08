"""
Diagnóstico de escala de strikes entre fuentes (p. ej. Allaria vs Rava).

No altera OptionContract ni normalizer; solo infiere factores multiplicativos candidatos.
"""

from __future__ import annotations

import math
from typing import Any

# Factores conservadores a probar (candidato × factor ≈ referencia).
STRIKE_SCALE_FACTORS: tuple[float, ...] = (0.01, 0.1, 1.0, 10.0, 100.0)


def _log(msg: str) -> None:
    print(f"[OPTIONS_STRIKE_SCALE] {msg}", flush=True)


def _unique_sorted(values: list[float]) -> list[float]:
    return sorted({float(x) for x in values if x == x})


def _reference_match_count(
    reference_strikes: list[float],
    scaled_candidates: list[float],
    *,
    tolerance: float,
) -> int:
    """Cuántos strikes de referencia tienen al menos un candidato escalado dentro de tolerance."""
    if not reference_strikes or not scaled_candidates:
        return 0
    hits = 0
    for r in reference_strikes:
        for s in scaled_candidates:
            if abs(s - r) <= tolerance:
                hits += 1
                break
    return hits


def scale_strike(value: float | None, factor: float | None) -> float | None:
    """Escala un strike; factor None o valor None → sin cambio de significado (devuelve value)."""
    if value is None:
        return None
    if factor is None:
        return float(value)
    try:
        out = float(value) * float(factor)
    except (TypeError, ValueError):
        return None
    if out != out:
        return None
    return out


def infer_strike_scale_factor(
    reference_strikes: list[float],
    candidate_strikes: list[float],
    *,
    tolerance: float = 0.01,
    log: bool = True,
) -> float | None:
    """
    Infiere factor F tal que candidate * F se alinee con reference_strikes dentro de tolerance.

    Prueba STRIKE_SCALE_FACTORS. Elige el que maximice referencias cubiertas.
    Si ningún factor mejora estrictamente respecto a 1.0, devuelve None (no sugerir escala).
    """
    ref = _unique_sorted(reference_strikes)
    cand = _unique_sorted(candidate_strikes)
    if not ref or not cand:
        if log:
            _log(f"infer skip: ref_n={len(ref)} cand_n={len(cand)} (vacío)")
        return None

    scores: dict[float, int] = {}
    for f in STRIKE_SCALE_FACTORS:
        scaled = [c * f for c in cand]
        scores[f] = _reference_match_count(ref, scaled, tolerance=tolerance)

    baseline = scores.get(1.0, 0)
    best_score = max(scores.values()) if scores else 0

    if best_score <= baseline:
        if log:
            _log(
                f"infer factor=None (sin mejora estricta vs 1.0) baseline={baseline} best={best_score} "
                f"scores={scores} ref_n={len(ref)} cand_n={len(cand)} tol={tolerance}"
            )
        return None

    winners = [f for f in STRIKE_SCALE_FACTORS if scores.get(f, -1) == best_score]
    if 1.0 in winners:
        if log:
            _log(
                f"infer factor=None (empate con 1.0 en mejor score) scores={scores} "
                f"ref_n={len(ref)} cand_n={len(cand)} tol={tolerance}"
            )
        return None

    def _dist_from_one(f: float) -> float:
        if f <= 0:
            return float("inf")
        return abs(math.log10(f))

    best_f = min(winners, key=_dist_from_one)

    if log:
        _log(
            f"infer factor={best_f} matches_ref={best_score}/{len(ref)} vs_baseline={baseline} "
            f"scores={scores} tol={tolerance}"
        )
    return best_f


def compare_scaled_strikes(
    reference_strikes: list[float],
    candidate_strikes: list[float],
    *,
    tolerance: float = 0.01,
    log: bool = False,
) -> dict[str, Any]:
    """
    Diagnóstico detallado: scores por factor, matches antes/después, ejemplos escalados.

    ``inferred_factor`` es None si no hay mejora clara vs 1.0 (misma regla que infer_strike_scale_factor).
    """
    ref = _unique_sorted(reference_strikes)
    cand = _unique_sorted(candidate_strikes)

    scores_by_factor: dict[str, int] = {}
    for f in STRIKE_SCALE_FACTORS:
        scaled = [c * f for c in cand]
        scores_by_factor[str(f)] = _reference_match_count(ref, scaled, tolerance=tolerance)

    matches_before = scores_by_factor.get("1.0", 0)
    inferred = infer_strike_scale_factor(ref, cand, tolerance=tolerance, log=log)
    eff_factor = 1.0 if inferred is None else float(inferred)
    scaled_all = [c * eff_factor for c in cand]
    matches_after = _reference_match_count(ref, scaled_all, tolerance=tolerance)

    examples: list[dict[str, float]] = []
    for c in cand[:5]:
        examples.append({"candidate": c, "scaled": c * eff_factor})

    return {
        "tolerance": tolerance,
        "reference_count": len(ref),
        "candidate_count": len(cand),
        "scores_by_factor": scores_by_factor,
        "matches_reference_covered_factor_1": matches_before,
        "inferred_factor": inferred,
        "effective_factor_applied": eff_factor,
        "matches_reference_covered_after": matches_after,
        "examples_scaled": examples,
    }
