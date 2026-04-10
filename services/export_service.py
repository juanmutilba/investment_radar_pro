from __future__ import annotations

from export.exporter import export_all


def export_results(outputs: dict) -> None:
    """
    Persiste el resultado del scan (Excel + CSV) con la misma lógica que export.exporter.export_all.

    Parameters
    ----------
    outputs
        Dict compatible con export_all (sin clave ``previous_file``; debe quitarla el llamador).
    """
    excel_path, csv_path = export_all(outputs)

    print("\nEXPORTACIÓN COMPLETA")
    print(f"Excel generado: {excel_path}")
    print(f"CSV generado:   {csv_path}")
