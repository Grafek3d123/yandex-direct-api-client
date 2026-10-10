"""Единый модуль лимитов Yandex.Direct API v5.

Значения сверены с официальным справочником ограничений
(https://yandex.ru/dev/direct/doc/ref-v5/limits/):

- кампании добавляются по **10** за вызов, а не по 200, как остальные сущности;
- `SelectionCriteria.Ids` для `campaigns/get` — не более **1000**;
- `adgroups/get` и `ads/get` по `Ids` — до **10 000**;
- мутации (`add`/`update`/`delete`/`setbids`) — до **200** объектов;
- `negativekeywordsharedsets` — до **30**;
- размер страницы `Page.Limit` для списков — до **10 000**.

Раньше эти числа были разбросаны по сервисам и часть была захардкожена
(например, 10000 в двух местах `ad_groups.py`, 200 для `campaigns/add`).
"""
from __future__ import annotations

#: Максимум объектов в одном запросе на изменение (add/update/delete/setbids).
MUTATE_MAX = 200

#: Максимум `SelectionCriteria.Ids` в `campaigns/get`.
GET_IDS_MAX = 1000

#: Максимум `SelectionCriteria.Ids` в `adgroups/get`.
ADGROUPS_GET_MAX = 10000

#: Максимум `SelectionCriteria.Ids` в `ads/get`.
ADS_GET_MAX = 10000

#: Максимум `SelectionCriteria.Ids` в `criteria/get`.
CRITERIA_GET_MAX = 1000

#: Максимум `SelectionCriteria.Ids` в `audiencetargets/get`.
AUDIENCE_TARGETS_GET_MAX = 1000

#: Максимум `SelectionCriteria.Ids` в `retargetingadjustments/get`.
RETARGETING_ADJUSTMENTS_GET_MAX = 1000

#: Максимум объектов (и Ids) в одном вызове `negativekeywordsharedsets`.
NEGATIVE_KEYWORDS_MAX = 30

#: Максимум `SelectionCriteria.Ids` в `sitelinks/get` и `adextensions/get`.
AD_EXTENSIONS_GET_MAX = 1000

#: Максимум значений GeoIds/InterestIds в одном вызове `dictionaries`.
DICTIONARIES_GET_MAX = 1000

#: Максимум `SelectionCriteria.AdImageHashes` в `adimages/get` и `adimages/delete`.
ADIMAGES_GET_MAX = 10000

#: Максимум изображений в одном вызове `adimages/add`.
ADIMAGES_ADD_MAX = 100

#: Максимум `SelectionCriteria.Ids` в `creatives/get`.
CREATIVES_GET_MAX = 10000

#: Максимум кампаний в одном вызове `campaigns/add`.
CAMPAIGNS_ADD_MAX = 10

#: Максимум Ids в `campaigns/suspend|resume|archive|unarchive`.
CAMPAIGNS_STATE_MAX = 1000

#: Максимум строк на страницу (`Page.Limit`) в get-методах со списками.
GET_PAGE_MAX = 10000

#: Максимум целей Метрики (goals) в одном отчёте.
REPORT_MAX_GOALS = 10

#: Максимум значений в одном ID-фильтре отчёта.
REPORT_MAX_FILTER_IDS = 1000


__all__ = [
    "ADIMAGES_ADD_MAX",
    "ADIMAGES_GET_MAX",
    "AD_EXTENSIONS_GET_MAX",
    "ADGROUPS_GET_MAX",
    "ADS_GET_MAX",
    "AUDIENCE_TARGETS_GET_MAX",
    "CAMPAIGNS_ADD_MAX",
    "CAMPAIGNS_STATE_MAX",
    "CREATIVES_GET_MAX",
    "CRITERIA_GET_MAX",
    "DICTIONARIES_GET_MAX",
    "GET_IDS_MAX",
    "GET_PAGE_MAX",
    "MUTATE_MAX",
    "NEGATIVE_KEYWORDS_MAX",
    "REPORT_MAX_FILTER_IDS",
    "REPORT_MAX_GOALS",
    "RETARGETING_ADJUSTMENTS_GET_MAX",
]
