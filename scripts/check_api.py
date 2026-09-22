"""Ручная проверка живого API: список кампаний + фильтр «за 2026 год».

Запуск из корня проекта:
    .venv\\Scripts\\python.exe scripts/check_api.py

Секреты читаются из .env (не выводятся).
"""
from __future__ import annotations

import os
import pathlib
import sys

# ---- загрузка .env без внешних зависимостей ----
_env_path = pathlib.Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if key and key not in os.environ:
            os.environ[key] = val

from yandex_direct_api_client import YandexDirectClient  # noqa: E402

YEAR = 2026


def main() -> int:
    client = YandexDirectClient(readonly=True)  # mutating-методы заблокированы

    campaigns = client.campaigns.list()
    print(f"Всего кампаний у клиента: {len(campaigns)}")
    print("=" * 100)
    print(f"{'ID':>10}  {'Status':<12} {'State':<10} {'StartDate':<12} "
          f"{'EndDate':<12} Name")
    print("-" * 100)

    in_2026 = []
    for c in sorted(campaigns, key=lambda x: x.id):
        sd = c.start_date.isoformat() if c.start_date else "-"
        ed = c.end_date.isoformat() if c.end_date else "-"
        print(f"{c.id:>10}  {c.status or '-':<12} {c.state or '-':<10} "
              f"{sd:<12} {ed:<12} {c.name}")
        if (c.start_date and c.start_date.year == YEAR) or (
            c.end_date and c.end_date.year == YEAR
        ):
            in_2026.append(c)

    print("=" * 100)
    print(f"Кампаний, затронутых {YEAR} годом "
          f"(начато ИЛИ завершено в {YEAR}): {len(in_2026)}")
    for c in in_2026:
        reason = []
        if c.start_date and c.start_date.year == YEAR:
            reason.append(f"начата {c.start_date}")
        if c.end_date and c.end_date.year == YEAR:
            reason.append(f"завершена {c.end_date}")
        print(f"  - [{c.id}] {c.name} ({', '.join(reason)}, {c.status})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
