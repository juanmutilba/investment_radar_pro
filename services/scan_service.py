from __future__ import annotations

import secrets
from datetime import datetime, timezone

from core.alerts_engine import collect_detected_alerts, generate_alerts
from core.config import EXPORT_FOLDER, OUTPUT_EXCEL
from core.history import find_previous_export, merge_history
from core.signals import classify_priority
from engines.argentina_engine import run_argentina_engine
from engines.usa_engine import run_usa_engine
from services.alert_event_log import append_scan_alert_events


def _prepare_dataframe(df, previous_file, previous_sheet_name):
    df = merge_history(df, previous_file, previous_sheet_name)

    df["PrioridadRadar"] = df.apply(
        lambda row: classify_priority(
            row["TotalScore"],
            row["Evolucion"],
            row.get("score_anterior"),
        ),
        axis=1,
    )

    priority_order = {"ALTA": 0, "MEDIA": 1, "BAJA": 2, "IGNORAR": 3}
    df["PriorityOrder"] = df["PrioridadRadar"].map(priority_order)

    df = df.sort_values(
        by=["PriorityOrder", "TotalScore", "TechScore", "Upside_%"],
        ascending=[True, False, False, False],
    ).drop(columns=["PriorityOrder"])

    return df


def run_full_scan(*, verbose: bool = True) -> dict:
    """
    Orquesta el scan completo (USA + Argentina), merge con export previo,
    priorización y alertas. Misma secuencia que el CLI histórico.

    Parameters
    ----------
    verbose
        Si True, imprime el mismo progreso que el CLI (motores USA / Argentina).
        Usar False desde API u otros entornos sin consola.

    Returns
    -------
    dict
        Claves esperadas por export.exporter.export_all, más:
        - previous_file: Path | None del Excel usado para Evolución/score_anterior.
    """
    scan_ts = datetime.now(timezone.utc)
    scan_at_iso = scan_ts.isoformat()
    scan_id = f"{scan_ts.strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(4)}"

    if verbose:
        print("Corriendo motor USA...")
    usa_df, usa_universo, usa_sectores, _ = run_usa_engine()
    if verbose:
        print("\nCorriendo motor Argentina...")
    arg_df, arg_universo, arg_sectores = run_argentina_engine()

    previous_file = find_previous_export(EXPORT_FOLDER, exclude_path=OUTPUT_EXCEL)

    usa_df = _prepare_dataframe(usa_df, previous_file, "Radar_Completo")
    arg_df = _prepare_dataframe(arg_df, previous_file, "Radar_Argentina_Completo")

    usa_top10 = usa_df.head(10).copy()
    arg_top10 = arg_df.head(10).copy()

    usa_alerts = generate_alerts(usa_df)
    arg_alerts = generate_alerts(arg_df)

    # Historial append-only: todas las alertas detectadas por fila en este scan (sin cooldown).
    usa_detected = collect_detected_alerts(usa_df)
    arg_detected = collect_detected_alerts(arg_df)
    try:
        append_scan_alert_events(
            scan_id=scan_id,
            scan_at=scan_at_iso,
            usa_alerts=usa_detected,
            arg_alerts=arg_detected,
            usa_df=usa_df,
            arg_df=arg_df,
        )
    except Exception:
        # No frenar el scan/export por un fallo de logging local.
        pass

    return {
        "usa_df": usa_df,
        "usa_universo": usa_universo,
        "usa_sectores": usa_sectores,
        "usa_top10": usa_top10,
        "usa_alerts": usa_alerts,
        "arg_df": arg_df,
        "arg_universo": arg_universo,
        "arg_sectores": arg_sectores,
        "arg_top10": arg_top10,
        "arg_alerts": arg_alerts,
        "previous_file": previous_file,
    }
