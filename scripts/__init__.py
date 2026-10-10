"""Скрипты ручного запуска и E2E-проверок Yandex.Direct API.

Пакет `yandex_direct_api_client` остаётся набором атомарных операций,
а оркестрация запуска (слои E2E) собрана здесь:

- `launch_rsy` — классическая РСЯ (`CPM_BANNER_CAMPAIGN`, сценарий 2А);
- `launch_epk` — ЕПК (`UNIFIED_CAMPAIGN`, `v501`, сценарий 2Б);
- `_launch_common` — общие части: отчёт о запуске, компенсация, кэш.

Модули запускаются из корня репозитория как модули пакета:

    .venv\\Scripts\\python.exe -m scripts.launch_rsy --help
    .venv\\Scripts\\python.exe -m scripts.launch_epk --help
"""
