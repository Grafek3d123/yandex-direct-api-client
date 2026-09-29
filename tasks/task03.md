# ЗАДАЧА: РАСШИРИТЬ ПОКРЫТИЕ `yandex-direct-api-client` — ТРЕКИ A И B

Репозиторий:

https://github.com/Grafek3d123/yandex-direct-api-client

Контекст: task01 (построение клиента), task02 (стабилизация как reusable
capability, v0.4.1). Эта задача — расширить покрытие API, оставаясь в границах
capability-слоя из `tasks/task02.md`.

---

## 0. Текущее покрытие (v0.4.1) — точка отсчёта

| Сервис | Методы | Пробел |
|---|---|---|
| `campaigns` | list, get, create, update, delete | нет suspend/resume/archive/unarchive |
| `ads` | list, get, create, update, update_text, create_with_payload, delete | нет suspend/resume/archive/moderate |
| `ad_groups` | list, get | **read-only**: нет create/update/delete |
| `ad_group_items` (API `criteria`) | list, get, add, set_bid, set_bids, delete | — (критерии/ключи покрыты) |
| `retargeting_adjustments` | list, get, add, update, delete | это корректировки ставок, НЕ условия ретаргетинга |
| `reports` | get + 5 обёрток | — |

Задача делится на два независимых трека. Их можно выполнять в любом порядке,
но каждый — отдельным набором коммитов и отдельным прогоном проверок.

---

## 1. Общие границы (наследуются из task02, обязательны)

Клиент остаётся тонким capability-слоем:

* typed модели скрывают raw Yandex JSON;
* вся HTTP/pagination/retry/rate-limit механика — внутри транспорта;
* мутации под `readonly=True`; необратимые/массовые — под `confirm=True`;
* секреты не логируются;
* НЕ добавлять: бизнес-стратегию, оптимизацию, approval-workflow, AI/LLM, MCP,
  Metrika-клиент, cross-system workflows.

Каждый новый публичный метод обязан иметь unit-тест с mock HTTP (`responses`).
Живые запросы — только в ручных smoke-скриптах (`scripts/`), вне `pytest`.

---

# ТРЕК A — завершить жизненный цикл существующих ресурсов

Цель: довести уже представленные ресурсы до полного CRUD + управления
состоянием, чтобы оркестратор мог строить и останавливать кампанию, не
трогая raw API.

## A.1. `ad_groups` — мутации (сейчас только чтение)

Добавить в `services/ad_groups.py`:

* `create(ad_group)` → `adgroups/add`
* `update(ad_group)` → `adgroups/update`
* `delete(ids, confirm=False)` → `adgroups/delete` (под `confirm`)

Модель `AdGroup`: добавить `to_new_payload()` / `to_update_payload()` по
образцу `Campaign`.

## A.2. `campaigns` — управление состоянием

Добавить batch-методы (по образцу `delete`, авто-чанкинг, `confirm` для
необратимого):

* `suspend(ids)` / `resume(ids)` → `campaigns/suspend`, `campaigns/resume`
* `archive(ids, confirm=False)` / `unarchive(ids)` → `campaigns/archive`,
  `campaigns/unarchive`

## A.3. `ads` — управление состоянием и модерация

* `suspend(ids)` / `resume(ids)` → `ads/suspend`, `ads/resume`
* `archive(ids, confirm=False)` / `unarchive(ids)` → `ads/archive`,
  `ads/unarchive`
* `moderate(ids)` → `ads/moderate` (отправка на модерацию)

## A.4. Критерии готовности трека A

* каждый метод — typed, с docstring на русском, с unit-тестом (mock HTTP);
* payload соответствует официальной схеме (методы `add/update/suspend/...`
  принимают массив объектов, `delete/suspend/...` — `SelectionCriteria.Ids`);
* item-level ошибки поднимают `ApiError` (хелпер `check_item_errors`);
* `confirm` требуется для `delete`/`archive`; `suspend/resume/moderate` — без.

---

# ТРЕК B — добавить новые ресурсы API

Цель: закрыть ресурсы, отсутствующие полностью. Каждый — отдельный сервис в
`services/` + модель в `models/` + свойство в `client.py` + тесты. Имена
эндпоинтов сверить с официальным справочником перед реализацией.

## B.1. Negative keywords — `client.negative_keywords`

* API-сервис: `negativekeywordsharedsets`
* методы: `list`, `get`, `create`, `update`, `delete(confirm)`
* модель: `NegativeKeywordSharedSet` (`Name`, `NegativeKeywords[]`)
* привязка набора к группе — через `adgroups.update` (полем `...SetIds`),
  не отдельным сервисом.

## B.2. Audience targets — `client.audience_targets`

* API-сервис: `audiencetargets` (условия нацеливания на аудиторию)
* методы: `list`, `get`, `create`, `update`, `delete(confirm)`
* модель: `AudienceTarget` (`CampaignId`, `AudienceId`, `BidDelta`, `Enabled`).

## B.3. Retargeting conditions — `client.retargeting_conditions`

* API-сервис: `retargetingconditions` (условия ретаргетинга; НЕ путать с
  существующим `retargeting_adjustments` = корректировки ставок)
* методы: `list`, `get`, `create`, `update`, `delete(confirm)`
* модель: `RetargetingCondition`.

## B.4. Ad extensions — `client.ad_extensions`

* API-сервисы: `sitelinks`, `callouts` (быстрые ссылки / уточнения)
* методы: `list`, `get`, `create`, `delete(confirm)` (обновление =
  create+delete по семантике API)
* модели: `Sitelink`, `Callout`.

## B.5. Bidding strategies — справка (без нового сервиса)

Стратегия задаётся внутри `campaigns.create/update` (поле
`BiddingStrategy`). Проверить по `scripts/smoke_create_campaign.py`, что
валидные enum-значения задокументированы; отдельный сервис `biddingstrategies`
НЕ создавать — это reference-данные, не CRUD.

## B.6. Критерии готовности трека B

* каждый новый сервис подключён как свойство `client.<name>`;
* модели `from_dict` + `to_*_payload`, без `dict[str, Any]` в публичном API;
* unit-тесты: request construction, response parsing, item-level errors,
  `confirm`/`readonly` guards, pagination для `list`;
* имена эндпоинтов подтверждены по официальному справочнику (записать URL в
  docstring сервиса).

---

## 2. Порядок работ

1. **A** раньше **B**: треки B опираются на рабочие `ad_groups.create`
   (нужны группы под наборы/расширения).
2. Внутри трека — по одному ресурсу за коммит (Conventional Commits).
3. Перед завершением каждого трека:

```bash
ruff check .
mypy yandex_direct_api_client
pytest
```

Все три — без ошибок.

---

## 3. Версия и документация

* Трек A (новые методы на существующих сервисах) + трек B (новые сервисы) —
  **minor bump** (0.4.x → 0.5.0) по AGENTS.md §6.
* Каждое добавление — запись в `CHANGELOG.md` (секция `### Added`).
* `README.md`: обновить таблицу методов сервисов (A) и добавить секции новых
  сервисов (B).
* Breaking changes НЕ допускаются (только добавления). Если меняется
  существующая сигнатура — остановиться и согласовать (AGENTS.md §9).

---

## 4. Acceptance criteria

После трека A:

1. `ad_groups` имеет create/update/delete; delete под `confirm`.
2. `campaigns` и `ads` имеют suspend/resume/archive; archive под `confirm`.
3. Все новые методы типизированы, с unit-тестами; `pytest` зелёный.

После трека B:

4. Добавлены сервисы: negative keywords, audience targets, retargeting
   conditions, ad extensions — каждый как свойство клиента.
5. Имена эндпоинтов подтверждены официально (URL в docstring).
6. Нет бизнес-логики, нет Metrika/AI/MCP-зависимостей (grep пустой).
7. `ruff` + `mypy --strict` + `pytest` — без ошибок.
8. `CHANGELOG.md` и `README.md` обновлены; версия — minor bump.

---

## 5. Обязательный отчёт

Ровно один отчёт на задачу, рядом с этим файлом:

```text
tasks/task03_report.md
```

Содержание:

1. трек A: что добавлено по каждому ресурсу, какие эндпоинты;
2. трек B: какие сервисы подключены, подтверждение имён эндпоинтов;
3. список созданных/изменённых файлов;
4. сколько unit-тестов добавлено;
5. результаты `ruff` / `mypy` / `pytest`;
6. изменения версии и CHANGELOG/README;
7. что намеренно НЕ сделано (bidding strategies как reference, и т.п.);
8. ограничения и что остаётся для оркестратора.

Не создавать отдельные `_report.md` на файл.

---

## 6. Критически важно

* НЕ менять сигнатуры существующих публичных методов (breaking change вне
  объёма).
* НЕ делать git-мутации без явного разрешения в текущем сообщении (AGENTS.md §1).
* Имена эндпоинтов и enum-значения — сверять с официальным справочником
  Yandex Direct API v5 перед реализацией; не угадывать.
