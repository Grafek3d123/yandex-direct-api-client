# АУДИТ `yandex-direct-api-client` (к задаче task02.md)

> Эталонный документ для проверки исполнения задачи «Стабилизировать как reusable capability».
> Дата аудита: 2026-09-23. **Ревизия 2:** списки файлов сверены с фактическим деревом
> репозитория (в черновике были неточные имена — исправлено). Классификация:
> **KEEP** / **REWRITE** / **DELETE** / **MERGE**.

## Контекст

- Ядро клиента (client, transport, retry, auth, exceptions, config, models, services) — зрелое, typed, без business-логики.
- git-репозиторий чист: артефакты сборки в `.gitignore` и не отслеживались. `DELETE` ниже = чистка файлов на диске, НЕ git-мутации.
- Фактические расхождения README с кодом отсутствуют (все методы из таблиц README существуют).

---

## 1. Корень пакета `yandex_direct_api_client/`

- [x] `__init__.py` — **KEEP**. Публичный API, `__all__` согласован с models.
- [x] `client.py` — **KEEP**. Фасад, ленивые свойства сервисов, readonly. Business-логики нет.
- [x] `_transport.py` — **KEEP**. HTTP-слой, нормализация ошибок, токен скрыт.
- [x] `retry.py` — **KEEP**. Token-bucket + backoff+jitter, retry 429.
- [x] `auth.py` — **KEEP**. OAuth (get_new_token/refresh_token), CLI `__main__`-блок.
- [x] `__main__.py` — **KEEP**. `python -m yandex_direct_api_client` → CLI auth.
- [x] `config.py` — **KEEP**. Settings + env-fallback, env-имена совпадают с `.env.example`.
- [x] `exceptions.py` — **KEEP**. Полная иерархия, без утечки токенов.
- [x] `_version.py` — **KEEP**. Один источник версии.
- [x] `py.typed` — **KEEP**.
- [x] `__pycache__/*.pyc`, `build/`, `*.egg-info/` — **DELETE (локально)** — удалено 2026-09-23, импорт проверен.

## 2. `models/` — **KEEP (все)**

- [x] `_helpers, ad, ad_group, ad_group_item, campaign, report, retargeting_adjustment, stats, token` — используются, экспортируются. `report.py` содержит `to_csv/to_json/to_dicts/to_dataframe` (README корректен).

## 3. `services/` — **KEEP (все)**

- [x] `_base, campaigns, ads, ad_groups, ad_group_items, retargeting_adjustments, reports` — тонкие typed-обёртки, мутации под guard. Business-логики нет.

## 4. `tests/` — фактический состав (дублей НЕТ, MERGE не требуется)

- [x] `conftest.py` — **KEEP**. Мок HTTP (responses), фикстуры.
- [x] `test_client.py` — **KEEP**. Старт, readonly, пагинация, ошибки.
- [x] `test_models.py` — **KEEP**. Модели, payload.
- [x] `test_readonly.py` — **KEEP**. Guards readonly + confirm.
- [x] `test_reports.py` — **KEEP**. Отчёты, polling 202, chunking.
- [x] `test_retry.py` — **KEEP**. Retry/backoff/rate-limit.
- [x] `test_stage02_resources.py` — **KEEP**. Ресурсы этапа 02.
- [x] `tests/__pycache__/` — **DELETE (локально)** — удалено.
- [ ] Опционально (не блокирует): `pytest-cov` в `[dev]` для замера покрытия.

## 5. `scripts/` — **KEEP** (ручные live-проверки, вне pytest)

- [x] `check_api.py` — readonly-смоук по реальному API. Задокументирован в README (Tests).
- [x] `smoke_create_campaign.py` — полный жизненный цикл кампании. Задокументирован в README (Tests).

## 6. Корневые файлы

- [x] `pyproject.toml` — **KEEP без изменений**. `[tool.pytest.ini_options]` есть (testpaths), `[dev]` содержит responses/pytest/ruff/mypy/types-requests. Правка pyproject без согласования запрещена AGENTS.md — не трогали.
- [x] `README.md` — **REWRITE (частично, выполнено)**. Добавлено: §Architecture & Scope (схема Orchestrator → Client → API + явные границы out-of-scope: business strategy, approval, AI/MCP, Metrika, website) и §Tests (unit + manual live scripts). Расхождений методов с кодом не найдено.
- [x] `.env.example` — **KEEP**. Переменные совпадают с `config.py` (ENV_*). `USE_SANDBOX` не существует — удалён из черновика аудита как ложный пункт.
- [x] `.gitignore` — **KEEP**. Покрывает артефакты.
- [x] `tasks/.DS_Store` — **DELETE (локально)** — удалён 2026-09-23.
- [x] `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/` — **DELETE (локально)** — удалены (пересоздаются).
- [x] `.venv/`, `.env`, `AGENTS.md`, `CHANGELOG.md`, `LICENSE` — **KEEP**.
- [x] `config.py.example` / `my_folder/` / `test_real_api.py` — в черновике аудита упомянуты ошибочно, **в репозитории отсутствуют** (пункт закрыт как невалидный).

---

## Acceptance-критерии (task02.md §20)

- [x] 1. Клиент импортируется как библиотека — `import OK 0.4.1` после чистки.
- [x] 2. Оркестратор не знает HTTP-деталей — transport внутри.
- [x] 3. Pagination внутри (`LimitedBy`, тесты test_client/test_stage02_resources).
- [x] 4. Retry внутри (`retry.py`, тесты test_retry).
- [x] 5. Readonly mode — `test_readonly.py`.
- [x] 6. Dangerous ops — `confirm=True` guard, тесты test_readonly.
- [x] 7. Business strategy отсутствует — grep optimize/recommend/budget пустой.
- [x] 8. AI layer отсутствует.
- [x] 9. MCP отсутствует.
- [x] 10. Metrika-зависимости нет (goals — строки ID; в README явно в out-of-scope).
- [x] 11. Site capability нет.
- [x] 12. Тесты на моках (responses), живой API только в scripts/.

## Команды финальной проверки (AGENTS.md §6.3)

- [x] `.venv/bin/ruff check .` — All checks passed (2026-09-23)
- [x] `.venv/bin/mypy yandex_direct_api_client` — Success, 27 source files (2026-09-23)
- [x] `.venv/bin/python -m pytest -q` — 105 passed (2026-09-23)

## Итог

Ядро: KEEP без изменений. DELETE: только gitignored-артефакты (выполнено). REWRITE: README (секции Architecture & Scope, Tests — выполнено). MERGE дублей тестов: не потребовалось (дублей нет).
