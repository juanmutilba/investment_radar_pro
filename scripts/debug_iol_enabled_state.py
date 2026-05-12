"""
Estado de credenciales IOL en memoria y entorno (sin imprimir secretos ni token).

Uso (raíz del repo):
    python scripts/debug_iol_enabled_state.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

ENV_PATH = ROOT / ".env"
_dotenv_loaded = load_dotenv(ENV_PATH)


def main() -> int:
    print(f"[DEBUG_IOL_STATE] dotenv_path={ENV_PATH!s} dotenv_loaded={_dotenv_loaded}", flush=True)
    print(f"[DEBUG_IOL_STATE] cwd={os.getcwd()!r}", flush=True)

    u_env = bool(os.getenv("IOL_USERNAME", "").strip())
    p_env = bool(os.getenv("IOL_PASSWORD", "").strip())
    print(
        f"[DEBUG_IOL_STATE] env IOL_USERNAME_set={u_env} IOL_PASSWORD_set={p_env}",
        flush=True,
    )

    from services.market_data.providers.iol import (  # noqa: E402
        ensure_iol_credentials_from_env,
        get_iol_token,
        is_iol_enabled,
    )

    before = is_iol_enabled()
    print(f"[DEBUG_IOL_STATE] is_iol_enabled_before_ensure={before}", flush=True)

    ensure_iol_credentials_from_env()
    after = is_iol_enabled()
    print(f"[DEBUG_IOL_STATE] is_iol_enabled_after_ensure={after}", flush=True)
    print(
        f"[DEBUG_IOL_STATE] ensure_iol_credentials_from_env_populated={after and not before}",
        flush=True,
    )

    if not after:
        reason = "missing_env_vars" if not (u_env and p_env) else "configure_rejected_or_failed"
        print(f"[DEBUG_IOL_STATE] configure_iol_credentials_effective=False reason={reason}", flush=True)
        print("[DEBUG_IOL_STATE] get_iol_token_skipped reason=not_enabled", flush=True)
        return 0

    print("[DEBUG_IOL_STATE] configure_iol_credentials_effective=True (creds in memory)", flush=True)
    tok = get_iol_token()
    ok = isinstance(tok, str) and len(tok) > 0
    print(f"[DEBUG_IOL_STATE] get_iol_token_ok={ok} token_length={len(tok) if tok else 0}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
