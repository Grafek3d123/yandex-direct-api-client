# STAGE_02 — Отчёт

## 1. Что реализовано

Поверх архитектуры этапа 1 (facade + Transport + services + models) добавлены
два новых полнофункциональных ресурса и расширены существующие:

- **Ключевые фразы** (`client.ad_group_items`, API-сервис `criteria`) —
  полный CRUD-набор: чтение, добавление, изменение ставок, удаление.
- **Ретаргетинг-корректировки** (`client.retargeting_adjustments`, API-сервис
  `retargetingadjustments`) — чтение, добавление, массовое обновление, удаление.
- **Типизированное создание объявлений** — `ads.create_with_payload()` +
  модели `AdText.to_payload()` / `AdImage`.

Отчёт построен по разделам задания (STAGE_02.md, пункты 1–15).

## 2. Какие ресурсы поддерживаются

| Ресурс | API-сервис | Состояние |
|---|---|---|
| Кампании | `campaigns` | полный (этап 1) |
| Объявления | `ads` | полный + типизированное создание (этап 2) |
| Группы объявлений | `adgroups` | чтение (этап 1) |
| Ключевые фразы | `criteria` | полный (этап 2) |
| Ретаргетинг-корректировки | `retargetingadjustments` | полный (этап 2) |
| Статистика | `reports` | AD_PERFORMANCE_REPORT (этап 1) |

Редкие возможности ради количества не добавлялись: sitelinks, vcards, метки,
расписания показов — доступны через `raw`-поле моделей и существующий
Transport, добавляются по мере необходимости на следующих этапах.

## 3. Какие операции поддерживаются

| Namespace | Операции |
|---|---|
| `campaigns` | list, get, create, update, delete(confirm) |
| `ads` | list, get, create, create_with_payload, update(confirm), update_text, delete(confirm) |
| `ad_groups` | list, get |
| `ad_group_items` | list, get, add, set_bid, set_bids(confirm), delete(confirm) |
| `retargeting_adjustments` | list, get, add, update(confirm), delete(confirm) |
| `reports` | get_ad_stats |

## 4. Какие ограничения API учтены

- `criteria` get по `Ids`: чанкинг по **1000** (`MAX_GET_IDS`).
- Мутации (`add`, `setbids`, `delete`): чанкинг по **200** (`MAX_MUTATE_IDS`).
- `get`-методы: максимум 10 000 объектов за запрос → авто-пагинация через
  `Page`/`LimitedBy` (fetch_all_pages).
- Стратегия «один чанкинг-хелпер на все ресурсы» — см. раздел 5.
- Rate limiting (token bucket) и retry (429/Retry-After, 202 polling) на
  уровне Transport — не дублируются в сервисах.

## 5. Как реализованы batching/chunking

Вся batching-логика живёт в `services/_base.py` и переиспользуется:

- `chunked(seq, size)` — универсальный генератор чанков.
- `fetch_all_pages(transport, service, payload, page_limit)` — пагинация
  get-запросов по `LimitedBy`. Новый ресурс получает пагинацию одной строкой,
  без копипасты.
- `ensure_confirmed(method_name, confirm)` — guard перед любым HTTP-запросом.
- Каждый сервис определяет только свой payload (ключи `AdGroupItems`,
  `RetargetingAdjustments`, `Bids` и т.д.) и делегирует чанкинг общим хелперам.

Сервис `criteria` использует `setbids` (метод API) для изменения ставок и
разбивает батч на чанки по 200 — как и `add`/`delete` того же сервиса.

## 6. Как реализована безопасность изменений

Единый трёхуровневый механизм (без изменений с этапа 1):

1. **readonly** — все mutating-методы новых сервисов проверяют
   `_ensure_writable` (созданы с параметром `readonly`, как campaigns/ads).
2. **confirm=True** — массовые и необратимые операции:
   - `ad_group_items.set_bids(..., confirm=True)` (bulk-изменение ставок)
   - `ad_group_items.delete(..., confirm=True)`
   - `retargeting_adjustments.update(..., confirm=True)`
   - `retargeting_adjustments.delete(..., confirm=True)`
   Одиночная точечная `set_bid` не требует confirm (аналогично `update_text`).
3. **Понятные ошибки** — item-level `Errors` из ответа API поднимаются как
   `ApiError` с полным телом элемента (`response_body=item`) и `details`;
   ничего из ответа API не теряется.

## 7. Какие модели добавлены/изменены

**Новые:**
- `AdGroupItem` — ключевая фраза (`Id`, `CampaignId`, `AdGroupId`, вложенный
  `Item{Type, Phrase}`, вложенный `Bid{Bid, Currency}`, `Context`) +
  `to_new_payload()` для criteria/add.
- `AdGroupItemBids` — ставка для `setbids` (`Id` + вложенный `Bids{Bid,
  AutoBidFixed}`) + `to_payload()`.
- `RetargetingBidAdjustment` — корректировка по ретаргетинг-сегменту +
  `to_new_payload()` / `to_update_payload()`.
- `AdImage` — картинка объявления (`ImageId`, `Autofocus`) + `to_payload()`.

**Изменены:**
- `AdText` — добавлен `to_payload()`.
- `models/__init__.py`, `__init__.py` — экспорты новых моделей.

Вложенные структуры API (`Item`, `Bid`, `Bids`) распаковываются в плоские
атрибуты моделей; `raw` остаётся escape-hatch для нестандартных полей.
Все модели полностью типизированы (mypy --strict).

## 8. Какие тесты добавлены

Новый файл `tests/test_stage02_resources.py` — 22 теста:

- чтение: list с фильтрами, list с пагинацией (LimitedBy), get по IDs,
  get пустого списка — для обоих новых сервисов;
- создание: typed-модели и raw-словари (AdGroupItem, RetargetingBidAdjustment),
  проверка корректности сформированного payload (вложенные Item/Bid/Bids);
- изменение: set_bids (typed + raw, проверка `method=setbids`), set_bid
  (одиночная), retargeting update (проверка `Id` в payload);
- удаление: успешное + item-level ошибка → `ApiError`;
- confirmation: `set_bids`, `delete` (criteria), `update`, `delete`
  (retargetingadjustments) без `confirm=True` → `ValidationError`, ноль
  HTTP-запросов;
- readonly: все mutating-методы обоих сервисов блокируются;
- `ads.create_with_payload` — сборка TextAd + ImageAd из typed-моделей;
- вложенные модели: `Item.Phrase`, `Bid.Bid/Currency`, `SegmentId`.

Все тесты — mock HTTP через `responses`, реальные запросы запрещены и
отсутствуют. Итого: **80 passed** (было 58).

## 9. Список изменённых и созданных файлов

**Созданы:**
- `yandex_direct_api_client/models/ad_group_item.py`
- `yandex_direct_api_client/models/retargeting_adjustment.py`
- `yandex_direct_api_client/services/ad_group_items.py`
- `yandex_direct_api_client/services/retargeting_adjustments.py`
- `tests/test_stage02_resources.py`
- `STAGE_02_report.md` (этот файл)

**Изменены:**
- `yandex_direct_api_client/models/ad.py` — `AdText.to_payload()`, новая `AdImage`
- `yandex_direct_api_client/models/__init__.py` — экспорты
- `yandex_direct_api_client/services/ads.py` — `create_with_payload`
- `yandex_direct_api_client/services/__init__.py` — экспорты
- `yandex_direct_api_client/client.py` — новые неймспейсы
  `ad_group_items`, `retargeting_adjustments`
- `yandex_direct_api_client/__init__.py` — экспорты моделей
- `yandex_direct_api_client/_version.py` — 0.3.0
- `pyproject.toml` — version = 0.3.0 (версия, без изменения прочих полей)
- `README.md` — таблицы новых неймспейсов
- `CHANGELOG.md` — запись 0.3.0

## 10. Найденные проблемы

- `_check_item_errors` копировалась в каждом сервисе (3-кратное дублирование
  с этапа 1, стало 5-кратным). Выделение в `services/_base.py` — кандидат
  на следующий этап (не выносил сейчас, чтобы не трогать эталонные сервисы
  этапа 1 без необходимости; поведение идентично во всех копиях).
- `fetch_all_pages` по-прежнему находит список в ответе по эвристике
  «первый ключ-список» — для новых сервисов (`criteria`, `adgroups`) это
  работает, но при появлении ответа с несколькими списками потребуется
  явный ключ. Зафиксировано в STAGE_01, остаётся актуальным.
- Существовавшая проблема теста `test_readonly_blocks_ads_update_text` /
  конструктора readonly — не воспроизводилась; все guard'ы работают.

## 11. Сознательно не реализованные возможности

- **Статистика/отчёты/поисковые запросы** — прямо запрещены заданием этапа
  («не начинай статистику, отчёты и поисковые запросы»).
- Sitelinks, vcards, метки (labels), расписания показов, справочники
  (dictionaries) — не входят в минимально необходимый набор для работы с
  кампаниями; добавляются по мере потребности.
- Async-интерфейс, Pydantic, DI — как и на этапе 1, вне скоупа.
- Автотаргетинг-специфика (`AutotargetingSettings` и пр.) — доступна через
  `raw` и raw-dict-пейлоады; typed-модели отложены до появления потребности.

## 12. Результаты pytest

```
80 passed in 1.36s
```
(58 тестов этапа 1 + 22 новых; реальных HTTP-запросов нет — только `responses`.)

## 13. Результаты ruff

```
All checks passed!
```

## 14. Результаты type checking

```
mypy yandex_direct_api_client
Success: no issues found in 26 source files   (strict)
```

## 15. Что остаётся на следующие этапы

1. Статистика и отчёты (CAMPAIGN_PERFORMANCE_REPORT, SEARCH_QUERY_REPORT,
   построчная разбивка) — явно отложены заданием.
2. Sitelinks, vcards, метки, dictionaries — typed-сервисы по потребности.
3. Вынос `_check_item_errors` в `services/_base.py` (устранение дублирования).
4. Явный ключ списка для `fetch_all_pages` (ключ `result_key`).
5. Ленивая пагинация (итератор) для сверхбольших выборок.
6. Интеграционные smoke-тесты против sandbox (за флагом, вне CI).