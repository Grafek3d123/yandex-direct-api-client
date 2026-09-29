# task03 — ОТЧЁТ: живой прогон на реальном аккаунте

Дата: 2026-09-23. Аккаунт: клиент `DEG13` (токен из `.env`, не логируется).
Скрипт: `scripts/smoke_task03_live.py` (постоянный, вне pytest).

## 1. Цель и техника безопасности

Запрос: создать тестовую кампанию, загрузить несколько групп и объявлений,
проверить новые методы трека A через реальный API, написать отчёт.

Меры против списаний (показы = 0, стоимость = 0):
- кампания создаётся со **StartDate = завтра**, **Network = SERVING_OFF**;
- все объявления остаются в **DRAFT** (на модерацию НЕ отправляются);
- в конце **всё созданное удаляется** (ads → ad_groups → campaign, `confirm=True`),
  в т.ч. страховочный `finally` на случай падения;
- секретный токен в лог не попадает.

Итог по состоянию аккаунта: **кампаний снова 23** (как до теста), сирот нет
(`campaigns.get after delete: gone - OK`).

## 2. Результат прогона

```text
RESULT: 18 OK, 5 expected(API constraint), 0 FAIL   (exit code 0)
```

| Шаг | Результат |
|---|---|
| `campaigns.list` (readonly, до теста) | OK — 23 |
| `ad_groups.list` (проб региона) | OK — `RegionIds=[2]` |
| `campaigns.create` | OK — id 714914340 (state OFF) |
| `campaigns.get` | OK — OFF |
| `campaigns.suspend` / `resume` | **expected** — «Invalid object status» |
| `ad_groups.create #1 / #2` | OK — id 5806508619 / 5806508620 |
| `ad_groups.get` | OK — [5806508619, 5806508620] |
| `ad_groups.list(campaign_ids)` | OK — 2 |
| `ad_groups.update` | OK — id 5806508619 |
| `ads.create_with_payload #1` | OK — id 1922772939053841457 |
| `ads.create` (batch, 2) | OK — id …820 / …821 |
| `ads.get` | OK — 3 объявления |
| `ads.list(campaign_ids)` | OK — 3 |
| `ads.suspend` / `resume` | **expected** — «Invalid object status» |
| `campaigns.archive (confirm)` | **expected** — «Cannot archive object» |
| `campaigns.unarchive` | OK — 1 |
| `ads.delete / ad_groups.delete / campaigns.delete` | OK — 3 / 2 / 1 |
| `campaigns.get` (после удаления) | OK — нет записей |

Загружено и проверено: **1 кампания + 2 группы + 3 объявления**, затем удалено.

## 3. Реальные ограничения API (НЕ баги клиента)

1. **DRAFT-объекты нельзя приостанавливать/архивировать.** Свежесозданная
   кампания/объявление (ещё не стартовали) отвечают «Invalid object status» на
   suspend/resume и «Cannot archive object» на archive. Это семантика Директа:
   эти методы применимы к работающим объектам. Клиент корректно пробрасывает
   item-ошибку как `ApiError`.
2. **`adgroups/add`: `RegionIds=[0]` отвергается** («Geotargeting set
   incorrectly»), несмотря на формулировку «0 = во всех регионах» в описании
   поля ответа. Для создания группы нужны реальные ID регионов из словаря
   Regions (в аккаунте — `[2]`).
3. **`ads/add`: кампания и тип не передаются.** Обязателен `AdGroupId`;
   кампания выводится из группы, тип — из под-объекта (`TextAd`/`ImageAd`).
4. **Транзиентная ошибка** наблюдалась один раз: «The service is temporarily
   unavailable» на `ad_groups.delete` (HTTP 200 с body-ошибкой, на стороне
   Яндекса). Повторный прогон прошёл чисто. Не ретраится (не 429/5xx HTTP).

## 4. НАЙДЕННЫЕ И ИСПРАВЛЕННЫЕ БАГИ (главная ценность прогона)

Юнит-тесты (mock) этого не ловили — они зеркалят предположения кода, а не
реальный API. Живой прогон вскрыл 6 реальных дефектов в request-контрактах:

| # | Файл / метод | Симптом на живом API | Исправление |
|---|---|---|---|
| 1 | `services/ad_groups.py` `_DEFAULT_FIELDS` | `adgroups/get` отдавал 8000 «Not able to process JSON/XML» — запрашивалось несуществующее поле **`State`** (у группы есть только `Status`/`ServingStatus`) | убран `State`; валидный набор `Id, Name, CampaignId, Status, Type, RegionIds` |
| 2 | `services/ad_groups.py` `list()` | `SelectionCriteria` без `CampaignIds` → «filtration parameters incorrectly set» | понятный клиентский `ValidationError` при вызове без `campaign_ids` (вместо непрозрачной ошибки API) |
| 3 | `services/ad_groups.py` `list(states=…)` | `SelectionCriteria.States` невалиден для adgroups | заменено на `statuses`/`serving_statuses` (валидные `Statuses`/`ServingStatuses`) |
| 4 | `models/ad_group.py` `to_update_payload()` | `adgroups/update` 8000 «unknown parameter **CampaignId**» | `CampaignId` больше не отправляется при update (только `Id`+изменяемые поля) |
| 5 | `services/ads.py` `create_with_payload()` | `ads/add` 8000 «unknown parameter **CampaignId**» | `CampaignId` не отправляется; `ad_group_id` сделан обязательным (`ValidationError` если нет) |
| 6 | `services/ads.py` `create_with_payload()` | `ads/add` 8000 «unknown parameter **Type**» | `Type` не отправляется (тип из `TextAd`/`ImageAd`) |

Совместимость: публичные сигнатуры сохранены (`campaign_id`/`type_` приняты,
но не отправляются — задокументировано). Breaking changes нет.

### Затронутые тесты
- Добавлено 5 unit-тестов: `ad_groups.list`/`get` (regress: `FieldNames` без
  `State`; валидные критерии; get по `Ids`), guard `list()` без `campaign_ids`,
  ассерты отсутствия `CampaignId` в update-теле и в `to_update_payload`.
- Обновлено 2 существующих теста, которые закрепляли баг:
  `test_ads_create_with_payload` (было `assert sent["CampaignId"] == 10` →
  теперь `assert "CampaignId" not in sent` и `assert "Type" not in sent`).
- Проверки: `pytest` **160 passed**, `ruff` чистый, `mypy` чистый (35 файлов).

## 5. Вывод

- capability-слой работает на живом API: создание/чтение/обновление/удаление
  кампаний, групп и объявлений подтверждены end-to-end.
- Живой прогон выполнил роль, которую mock-тесты выполнить не могут: сверка
  имён полей и контрактов с реальным API. Обнаруженные расхождения исправлены
  и закрыты регресс-тестами.
- Постоянный скрипт `scripts/smoke_task03_live.py` можно перезапускать для
  периодической проверки живого контракта (сам всё за собой удаляет).
- Оговорка про `ad_group_items`/`retargeting_adjustments`: у них в `to_payload`
  тоже есть `CampaignId`; в этом прогоне они не участвовали и живьём НЕ
  проверены — рекомендуется отдельный живой прогон перед их использованием.
