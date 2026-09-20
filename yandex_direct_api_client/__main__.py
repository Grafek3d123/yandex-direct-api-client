"""Поддержка `python -m yandex_direct_api_client` — проксирует в CLI auth-модуля."""
from __future__ import annotations

import sys

from .auth import run_cli

if __name__ == "__main__":
    raise SystemExit(run_cli(sys.argv[1:]))
