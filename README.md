# yandex-direct-api-client

Typed, retry-aware Python client for [Yandex.Direct API](https://yandex.ru/dev/direct/doc/):
**v5** (классическая РСЯ) и **v501** (Единая перфоманс-кампания, ЕПК).

- **Sync** — built on `requests`, no asyncio required
- **Typed** — dataclasses + `py.typed`, IDE autocomplete out of the box
- **Resilient** — automatic retry on `429` (with `Retry-After`) and `202` (report polling)
- **Safe** — `readonly=True` blocks every mutating method; money mutations need `confirm=True`
- **Rate-limited** — token-bucket throttling so you rarely hit `429`
- **Paginated** — auto-follows `LimitedBy` to fetch all pages
- **Namespaced** — `client.campaigns.list()`, `client.ads.update()`, `client.reports.get_ad_stats()`
- **Geo-driven** — one `RegionSelector` for both APIs, no hard-coded business regions

## Architecture & Scope

This repository is a **pure capability layer** — a typed API client, nothing more:

```text
Private Orchestrator          ← business logic, strategy, user approval (NOT this repo)
        ↓
Yandex Direct Client          ← this repository
        ↓
Yandex Direct API v5
```

The client owns everything Direct-specific:

- authentication (OAuth helpers) and HTTP transport (headers, request IDs, timeouts)
- retry with `Retry-After`, token-bucket rate limiting, report polling (`201/202`)
- pagination (`LimitedBy`), batch limits and chunking
- typed request/response models (callers never touch raw Yandex JSON)
- typed errors (`AuthError`, `RateLimitError`, `ApiError`, ...)
- capability-level safety: `readonly=True` and `confirm=True` guards

Explicitly **out of scope** (belongs to the orchestrator above):

- advertising strategy, campaign optimization, budget decisions
- user-facing approval workflows (the client's `confirm` is a programmatic
  safety gate, not a business approval)
- AI / LLM integration, MCP, natural language
- Metrika client or any cross-capability code (report `goals` are plain
  Direct API fields — correlating them with Metrika data is the orchestrator's job)
- website changes, cross-system workflows

## Install

```bash
pip install yandex-direct-api-client
```

For local development:

```bash
git clone https://github.com/Grafek3d123/yandex-direct-api-client.git
cd yandex-direct-api-client
pip install -e ".[dev]"
```

## Quickstart

```python
from yandex_direct_api_client import YandexDirectClient

client = YandexDirectClient(
    token="00000000000000000000000000000000",
    client_login="DEG13",
)

campaigns = client.campaigns.list()
for c in campaigns:
    print(c.id, c.name, c.status)
```

### Environment-variable fallback

```python
# Reads YANDEX_DIRECT_TOKEN / YANDEX_DIRECT_CLIENT_LOGIN from env
client = YandexDirectClient()
```

### Context manager (session reuse, keep-alive)

```python
with YandexDirectClient() as client:
    ads = client.ads.list(campaign_ids=[123456789])
    stats = client.reports.get_ad_stats(ad_ids=[a.id for a in ads])
```

### Readonly mode

```python
client = YandexDirectClient(readonly=True)
client.ads.update_text(ad_id=1, headline="...", body="...")  # raises ValidationError
```

### Destructive operations require `confirm=True`

Irreversible operations (delete) and bulk mutations (batch update) require
an explicit `confirm=True` flag. This prevents accidental data loss:

```python
# Raises ValidationError — no request is sent
client.ads.delete([1, 2, 3])

# Explicit confirmation — request is sent
client.ads.delete([1, 2, 3], confirm=True)

# Bulk update also requires confirmation
client.ads.update([...], confirm=True)

# Single-ad update_text does NOT require confirm
client.ads.update_text(1, "New title", "New text")
```

### Pagination

All `list()` methods auto-follow `LimitedBy` to return all results:

```python
# Fetches all ads in the campaign, even if > 10 000
all_ads = client.ads.list(campaign_ids=[123])
```

### OAuth: obtain a fresh token

```python
from yandex_direct_api_client.auth import get_new_token

token = get_new_token(client_id="your_app_id", client_secret="your_secret")
print(token.access_token, token.refresh_token, token.expires_in)
```

### OAuth: refresh an existing token

```python
from yandex_direct_api_client.auth import refresh_token

new = refresh_token(
    client_id="your_app_id",
    client_secret="your_app_secret",
    refresh_token="...",
)
```

## API Reference

### Supported services

| Namespace | API service | v5 | v501 |
|---|---|---|---|
| `client.campaigns` | `campaigns` | yes | yes (`create_unified`, `update_unified`, `get_unified`, `delete_unified`) |
| `client.ad_groups` | `adgroups` | yes | yes (`UnifiedAdGroup`) |
| `client.ads` | `ads` | yes | yes (`ResponsiveAd`, `create_responsive_ad`) |
| `client.ad_group_items` | `criteria` | yes | no (keywords are search-only) |
| `client.ad_images` | `adimages` | yes | yes (images for `ResponsiveAd`) |
| `client.creatives` | `creatives` | read-only | read-only |
| `client.audience_targets` | `audiencetargets` | yes | — |
| `client.retargeting_conditions` | `audiencetargets` | yes | — |
| `client.retargeting_lists` | `retargetinglists` | yes | — |
| `client.retargeting_adjustments` | `retargetingadjustments` | yes | — |
| `client.negative_keywords` | `negativekeywordsharedsets` | yes | — |
| `client.ad_extensions` | `sitelinks`, `adextensions` | yes | — |
| `client.dictionaries` | `dictionaries` | yes | — |
| `client.clients` | `clients` | yes | — |
| `client.reports` | Reports API | yes | yes |

### v5 vs v501

The client keeps one namespace for both API versions. The version is chosen by
the model you pass, not by the call site:

| | Classic РСЯ (v5) | ЕПК (v501) |
|---|---|---|
| Campaign builder | `CpmBannerCampaign`, `TextCampaign` | `UnifiedCampaign` |
| Ad group builder | `CpmBannerAdGroup`, `TextAdGroup`, … | `UnifiedAdGroup` |
| Ad model | `CpmBannerAdBuilderAd` (нужен `CreativeId`) | `ResponsiveAd` (заголовки, тексты, изображения) |
| Service methods | `create`, `update`, `get` | `create_unified`, `update_unified`, `get_unified`, `delete_unified` |
| Images | — | `adimages/add` → `ResponsiveAd.AdImageHashes` |

```python
# Classic РСЯ — v5
client.campaigns.create(CpmBannerCampaign(...))          # → /json/v5/campaigns/
# ЕПК — v501, маршрутизация автоматическая
client.campaigns.create(UnifiedCampaign(...))            # → /json/v501/campaigns/
client.campaigns.create_unified(UnifiedCampaign(...))    # явный вызов v501
```

`api_version` можно задать один раз на клиенте (`YandexDirectClient(api_version="v501")`)
или передать в конкретный вызов (`client.ad_groups.create([...], api_version="v501")`).

> **Контракт проверен на снимке Direct API от 30.09.2026.** Поля и стратегии,
> добавленные после него, доступны через `dict`/`extra` escape-hatch до выхода
> типизированных обёрток.

### Client login (agent access)

`client_login` is optional (D4). Without it, the `Client-Login` header is not
sent at all — direct advertiser access. With it, the client works on behalf of
that customer:

```python
YandexDirectClient(token="...")                       # direct access
YandexDirectClient(token="...", client_login="DEG13")  # agent access
```

### Creating a classic РСЯ campaign

`CpmBannerAdBuilderAd` needs an existing `CreativeId`: the Direct API does not
create banner creatives (`creatives/add` only supports `VideoExtensionCreative`),
so the creative is created in the Direct web interface. The fully automatic
image-to-ad flow lives on ЕПК (see below).

```python
import datetime as dt
from yandex_direct_api_client import (
    CpmBannerAdGroup, CpmBannerCampaign, RegionSelector, YandexDirectClient,
)

client = YandexDirectClient(token="...", client_login="DEG13")

campaign = client.campaigns.create(
    CpmBannerCampaign(
        name="РСЯ — тест",
        start_date=dt.date.today() + dt.timedelta(days=1),
        weekly_budget=500,
    )
)
region_ids = RegionSelector(exclude=["Москва", "Московская область"]).resolve(
    client.dictionaries
)
group = client.ad_groups.create([
    CpmBannerAdGroup(
        name="РСЯ — тест — группа",
        campaign_id=int(campaign["Id"]),
        region_ids=region_ids,
    )
])[0]
ad = client.ads.create_rsya_banner(
    ad_group_id=int(group["Id"]),
    creative_id=123456,          # existing IMAGE_CREATIVE
    href="https://example.com",
)[0]
print("campaign", campaign["Id"], "group", group["Id"], "ad", ad["Id"])

# Weekly budget with read-back verification
client.campaigns.set_weekly_budget([int(campaign["Id"])], "500", confirm=True)
```

### Creating an ЕПК campaign (fully automatic image flow)

```python
from yandex_direct_api_client import (
    RegionSelector, UnifiedAdGroup, UnifiedCampaign, UnifiedStrategy,
    YandexDirectClient,
)

client = YandexDirectClient(token="...", client_login="DEG13")

image = client.ad_images.add_from_file("banner.jpg", name="SDK test banner")
image_hash = image["AdImageHash"]
region_ids = RegionSelector(include=["Тверская область", "Омская область"]).resolve(
    client.dictionaries
)

campaign = client.campaigns.create_unified(
    UnifiedCampaign(
        name="ЕПК — тест",
        start_date=dt.date.today() + dt.timedelta(days=1),
        search=UnifiedStrategy(
            strategy="SERVING_OFF",           # search off: display-only scenario
        ),
        network=UnifiedStrategy(
            strategy="WB_MAXIMUM_CLICKS",
            weekly_budget=500,                 # required by this strategy
        ),
        counter_ids=[123456],                # Metrika counter
    )
)
group = client.ad_groups.create([
    UnifiedAdGroup(
        name="ЕПК — тест — группа",
        campaign_id=int(campaign["Id"]),
        region_ids=region_ids,
    )
], api_version="v501")[0]

ad = client.ads.create_responsive_ad(
    ad_group_id=int(group["Id"]),
    titles=["Заголовок до 56 символов"],
    texts=["Текст объявления до 81 символа"],
    ad_image_hashes=[image_hash],
    href="https://example.com",
)[0]
print("campaign", campaign["Id"], "group", group["Id"], "ad", ad["Id"])
```

### `client.campaigns`

| Method | Description | Mutates? |
|---|---|---|
| `list(states=None, statuses=None)` | List campaigns (auto-paginated) | no |
| `get(ids)` | Get campaigns by IDs | no |
| `create(campaign)` | Create a campaign (`CpmBannerCampaign`/`TextCampaign`/`UnifiedCampaign` or dict) | **yes** |
| `create_many(campaigns)` | Create several campaigns (chunked by 10) | **yes** |
| `update(campaign)` | Update a campaign | **yes** |
| `delete(ids, confirm=False)` | Delete campaigns by IDs | **yes** |
| `suspend(ids)` | Stop campaign serving | **yes** |
| `resume(ids)` | Resume campaign serving | **yes** |
| `archive(ids, confirm=False)` | Move campaigns to archive | **yes** |
| `unarchive(ids)` | Restore campaigns from archive | **yes** |
| `create_unified(campaign)` | Create an ЕПК campaign (`v501`) | **yes** |
| `update_unified(campaign)` | Update an ЕПК campaign (`v501`) | **yes** |
| `get_unified(ids)` | Read ЕПК campaigns (`v501`) | no |
| `delete_unified(ids, confirm=False)` | Delete ЕПК campaigns (`v501`) | **yes** |
| `get_budgets(ids)` | Read weekly/daily budgets (v5, then v501 fallback) | no |
  | `set_weekly_budget(ids, budget, *, verify=True, confirm=False, strategy=None)` | Set the weekly budget with read-back verification (`strategy` — `MANUAL_CPM` for CPM, required to switch networks) | **yes** |
| `set_daily_budget(ids, budget, *, verify=True, confirm=False)` | Set the deprecated daily budget | **yes** |
  | `set_bid_strategy(ids, strategy, *, weekly_budget=None, confirm=False, verify=True)` | Change the bidding strategy (optionally with the weekly budget) | **yes** |

Money is passed in account currency (`"500"`, `500`, `Decimal("500.00")`) and
converted to API units (×1 000 000) on the wire; `from_money_units()` converts
back into a 6-decimal `Decimal`. Every money mutation requires `confirm=True`
and is bounded by `daily_budget_cap` (`YANDEX_DIRECT_BUDGET_CAP`).

### `client.ads`

| Method | Description | Mutates? |
|---|---|---|
| `list(campaign_ids=None, ...)` | List ads (auto-paginated) | no |
| `get(ids, include_text=False)` | Get ads by IDs | no |
| `create(ads)` | Create ads (batch, up to 200) | **yes** |
| `update(ads, confirm=False)` | Update ads (batch, up to 200) | **yes** |
| `update_text(ad_id, headline, body)` | Update Title/Text of a text ad | **yes** |
| `create_with_payload(campaign_id, text, image=None, ad_group_id=None)` | Create a text ad from typed models (`ad_group_id` required; the ad's campaign is derived from its group) | **yes** |
| `delete(ids, confirm=False)` | Delete ads by IDs | **yes** |
| `suspend(ids)` | Stop ad serving | **yes** |
| `resume(ids)` | Resume ad serving | **yes** |
| `archive(ids, confirm=False)` | Move ads to archive | **yes** |
| `unarchive(ids)` | Restore ads from archive | **yes** |
| `moderate(ids)` | Submit DRAFT ads for moderation | **yes** |
| `create_rsya_banner(ad_group_id, creative_id, *, href=None, ...)` | Create a classic РСЯ banner ad from an existing creative (`v5`) | **yes** |
| `create_responsive_ad(ad_group_id, titles, texts, *, href=None, ad_image_hashes=None, api_version="v501")` | Create a `ResponsiveAd` (ЕПК) | **yes** |

### `client.ad_images`

Images for ЕПК `ResponsiveAd`. `adimages/add|get|delete` only — the API has no
`update`/`unbind`.

| Method | Description | Mutates? |
|---|---|---|
| `list()` | List uploaded images (auto-paginated) | no |
| `get(hashes)` | Get images by `AdImageHash` | no |
| `add(name, image_base64, *, type_=None)` | Upload an image from base64 | **yes** |
| `add_from_file(path, *, name=None, type_=None)` | Upload an image from a file | **yes** |
| `add_from_stream(stream, name)` | Upload an image from a binary stream | **yes** |
| `delete(hashes, confirm=False)` | Delete images by hashes | **yes** |

### `client.ad_groups`

| Method | Description | Mutates? |
|---|---|---|
| `list(campaign_ids, statuses=None, serving_statuses=None)` | List ad groups (auto-paginated; `campaign_ids` required — adgroups/get needs a `CampaignIds`/`Ids` filter) | no |
| `get(ids)` | Get ad groups by IDs | no |
| `create(ad_groups)` | Create ad groups (typed `AdGroup` or raw dicts, up to 200; needs real `RegionIds`, `[0]` is rejected) | **yes** |
| `update(ad_groups)` | Update ad groups (typed model with `Id` or dicts; `CampaignId` is not sent) | **yes** |
| `delete(ids, confirm=False)` | Delete ad groups by IDs | **yes** |

### `client.ad_group_items` (keywords)

| Method | Description | Mutates? |
|---|---|---|
| `list(campaign_ids=None, ad_group_ids=None)` | List keywords (auto-paginated) | no |
| `get(ids)` | Get keywords by IDs | no |
| `add(items)` | Add keywords (typed `AdGroupItem` or raw dicts, up to 200) | **yes** |
| `set_bid(item_id, bid)` | Set a single keyword bid | **yes** |
| `set_bids(bids, confirm=False)` | Set keyword bids in bulk (up to 200) | **yes** |
| `delete(ids, confirm=False)` | Delete keywords by IDs | **yes** |

Keywords are a search-only concept. They are **not applicable to display
campaigns** (`CPM_BANNER_AD_GROUP`, `CPM_VIDEO_AD_GROUP`, `UNIFIED_AD_GROUP`):
in РСЯ targeting is done with audience segments, not phrases. Use
`check_keywords_allowed(ad_group_type)` to get the same `ValidationError` before
any request. Autotargeting for dynamic campaigns is a separate structure —
`AutotargetingSetting` on `DynamicSiteAdGroup` / `DynamicFeedAdGroup`
(`AutotargetingCategories`).

### `client.retargeting_adjustments`

| Method | Description | Mutates? |
|---|---|---|
| `list(campaign_ids=None)` | List retargeting bid adjustments | no |
| `get(ids)` | Get adjustments by IDs | no |
| `add(adjustments)` | Add adjustments (typed model or dicts) | **yes** |
| `update(adjustments, confirm=False)` | Bulk update adjustments | **yes** |
| `delete(ids, confirm=False)` | Delete adjustments by IDs | **yes** |

### `client.negative_keywords` (API `negativekeywordsharedsets`)

Shared negative-keyword sets. Bind a set to an ad group via
`AdGroup.NegativeKeywordSharedSetIds` through `client.ad_groups.update()`.

| Method | Description | Mutates? |
|---|---|---|
| `list()` | List all negative-keyword sets (auto-paginated) | no |
| `get(ids)` | Get sets by IDs (chunked by 30) | no |
| `create(sets)` | Create sets (typed `NegativeKeywordSharedSet` or dicts, up to 30) | **yes** |
| `update(sets)` | Update sets (typed model with `Id` or dicts) | **yes** |
| `delete(ids, confirm=False)` | Delete sets by IDs | **yes** |

### `client.audience_targets` (API `audiencetargets`)

| Method | Description | Mutates? |
|---|---|---|
| `list(campaign_ids=None, ad_group_ids=None, states=None)` | List audience targets (auto-paginated) | no |
| `get(ids)` | Get targets by IDs | no |
| `create(targets)` | Create targets (typed `AudienceTarget` or dicts) | **yes** |
| `suspend(ids)` | Stop target serving | **yes** |
| `resume(ids)` | Resume target serving | **yes** |
| `set_bids(bids)` | Set bids/priorities (audiencetargets has no `update`) | **yes** |
| `delete(ids, confirm=False)` | Delete targets by IDs | **yes** |

### `client.retargeting_conditions`

Retargeting conditions. The standalone `retargetingconditions` endpoint is not
in the current v5 reference — retargeting is managed via `audiencetargets`
(`RetargetingListId`), and this service wraps that. Not to be confused with
`retargeting_adjustments` (bid adjustments).

| Method | Description | Mutates? |
|---|---|---|
| `list(campaign_ids=None, ad_group_ids=None, retargeting_list_ids=None)` | List conditions (auto-paginated) | no |
| `get(ids)` | Get conditions by IDs | no |
| `create(conditions)` | Create conditions (typed `RetargetingCondition` or dicts) | **yes** |
| `delete(ids, confirm=False)` | Delete conditions by IDs | **yes** |

### `client.retargeting_lists` (API `retargetinglists`)

Retargeting segments. The list `Type` is set at creation and cannot be changed:
`RETARGETING` holds Metrica/Audience goals and segments, `AUDIENCE` holds any
segments — demographics, behaviour and user interests — and is the only way to
target those in the API.

| Method | Description | Mutates? |
|---|---|---|
| `get(ids=None, types=None)` | Get segments (auto-paginated, filter by `Ids`/`Types`) | no |
| `list_for_group_type(ad_group_type)` | Segments applicable to an ad group type (uses `AvailableForTargetsInAdGroupTypes`) | no |
| `create(lists)` | Create segments (typed `RetargetingList` or dicts, up to 200) | **yes** |
| `update(lists, confirm=False)` | Update segments (list type is immutable) | **yes** |
| `delete(ids, confirm=False)` | Delete segments by IDs | **yes** |
| `create_audience_segment(name, external_ids)` | Build (not send) an `AUDIENCE` segment payload from segment IDs | no |

### `client.targeting` (layer 4)

Resolves readable names into API IDs and assembles audience targets. Per the
API reference, `audiencetargets` only has `RetargetingListId` and `InterestId` —
demographics, behaviour and user interests exist solely as rules inside an
`AUDIENCE` retargeting list.

| Method | Description | Mutates? |
|---|---|---|
| `resolve_demographics(spec, name=None)` | Resolve `DemographicsSpec` (age ranges, gender) into segment IDs | no |
| `resolve_interest(name, importance="SHORT_TERM")` | Find a mobile-app interest by name | no |
| `demographic_segment_names(criteria_type="AGE")` | Available segment names for one characteristic | no |
| `retargeting_target(ad_group_id, spec, ...)` | Build `RetargetingTarget` from an existing segment | no |
| `interest_target(ad_group_id, interest, ...)` | Build `InterestTarget` (mobile-app groups only) | no |
| `create_audience_target(ad_group_id, target, ...)` | Create the `AUDIENCE` segment, then the audience target | **yes** |

```python
from yandex_direct_api_client import DemographicsSpec, GENDER_FEMALE

# Справочник названий половых сегментов читается из API — SDK не зашивает локаль
gender_names = client.targeting.demographic_segment_names("GENDER")
target = client.targeting.resolve_demographics(
    DemographicsSpec(
        age_ranges=["25-34"],
        gender=GENDER_FEMALE,
        gender_names=gender_names,  # обязательно при gender != GENDER_ALL
    ),
    name="Women 25-34",
)
created = client.targeting.create_audience_target(
    ad_group_id=123, target=target, context_bid=500_000,
)
print(created.retargeting_list_id, created.audience_target_id)
```

Incompatible campaign/ad-group combinations are rejected on the client before
any request (`yandex_direct_api_client.constants.is_allowed`): app-category
interests only work on `MOBILE_APP_AD_GROUP`, retargeting is not allowed for
dynamic groups, and a `CPM_BANNER_AD_GROUP` with the `KEYWORDS` subtype takes no
audience targets at all.

### `client.ad_extensions` (API `sitelinks`, `adextensions`)

Sitelinks (`SitelinksSet`/`Sitelink`) and callouts (`Callout`, type CALLOUT).
Update = create + delete (per API semantics).

| Method | Description | Mutates? |
|---|---|---|
| `list_sitelinks()` | List sitelink sets (auto-paginated) | no |
| `get_sitelinks(ids)` | Get sitelink sets by IDs | no |
| `create_sitelinks(sets)` | Create sitelink sets (typed `SitelinksSet` or dicts) | **yes** |
| `delete_sitelinks(ids, confirm=False)` | Delete sitelink sets by IDs | **yes** |
| `list_callouts()` | List callouts (auto-paginated) | no |
| `get_callouts(ids)` | Get callouts by IDs | no |
| `create_callouts(callouts)` | Create callouts (typed `Callout` or dicts) | **yes** |
| `delete_callouts(ids, confirm=False)` | Delete callouts by IDs | **yes** |

### `client.reports`

| Method | Description | Mutates? |
|---|---|---|
| `get(report_type, field_names, date_from/date_to or date_range_type, ...)` | Universal report: filters, order, goals, attribution, VAT, chunking | no |
| `account_stats(...)` | ACCOUNT_PERFORMANCE_REPORT | no |
| `campaign_stats(campaign_ids=None, ...)` | CAMPAIGN_PERFORMANCE_REPORT | no |
| `ad_group_stats(...)` | ADGROUP_PERFORMANCE_REPORT | no |
| `criteria_stats(...)` | CRITERIA_PERFORMANCE_REPORT (keywords) | no |
| `search_queries(...)` | SEARCH_QUERY_PERFORMANCE_REPORT | no |
| `get_ad_stats(ad_ids=None, ...)` | AD_PERFORMANCE_REPORT → `List[StatRow]` (legacy) | no |

Reports are async on the API side: the client polls `202/PROGRESS` with
`Retry-In` until ready (configurable `report_timeout`), retries `429` with
backoff, and converts errors to typed exceptions. Large requests are split
automatically: ID filters chunked by 1000 values, long date ranges split
into windows (`max_days`).

```python
from datetime import date
from yandex_direct_api_client.models import ReportFilter, ReportOrder

result = client.reports.campaign_stats(
    campaign_ids=[1, 2],
    date_from=date(2026, 9, 1),
    date_to=date(2026, 9, 15),
    goals=["12345"],                       # conversions by Metrika goal
    filters=[ReportFilter("Clicks", "GREATER_THAN", ["10"])],
    order_by=[ReportOrder("Clicks", ascending=False)],
)
for row in result.rows:
    print(row.get("CampaignName"), row.as_int("Clicks"), row.as_money("Cost"))

result.to_csv()      # CSV string
result.to_json()     # JSON string
result.to_dicts()    # list[dict]
result.to_dataframe()  # pandas (optional dependency)
```

## Exceptions

All inherit from `YandexDirectError` and carry the Yandex `request_id`
(`X-Request-Id`) when available — quote it in support tickets.

| Exception | Raised when |
|---|---|
| `AuthError` | HTTP 401/403 — token invalid, expired, or no access |
| `RateLimitError` | HTTP 429 after all retries are exhausted |
| `ReportNotReadyError` | Report stays in PROGRESS longer than `report_timeout` |
| `ApiError` | Any other non-2xx response, or `status=ERROR` in body |
| `ValidationError` | Client-side validation (readonly mode, bad args) |

## Configuration

| Parameter | Env var | Default | Notes |
|---|---|---|---|
| `token` | `YANDEX_DIRECT_TOKEN` | — | OAuth access token |
| `client_login` | `YANDEX_DIRECT_CLIENT_LOGIN` | — | Customer login |
| `api_url` | `YANDEX_DIRECT_API_URL` | `https://api.direct.yandex.com/json/v5` | |
| `timeout` | `YANDEX_DIRECT_TIMEOUT` | `30` | Per-HTTP-request seconds |
| `max_retries` | `YANDEX_DIRECT_MAX_RETRIES` | `5` | For 429 and 202 |
| `rate_limit_rps` | `YANDEX_DIRECT_RATE_LIMIT_RPS` | `5` | Token-bucket rate |
| `readonly` | `YANDEX_DIRECT_READONLY` | `False` | Block mutating methods |
| `validate` | `YANDEX_DIRECT_VALIDATE` | `True` | Client-side payload validation |
| `daily_budget_cap` | `YANDEX_DIRECT_BUDGET_CAP` | — | Money-mutation ceiling (account currency) |
| `require_confirm_for_money` | `YANDEX_DIRECT_REQUIRE_CONFIRM_MONEY` | `True` | `confirm=True` required for money mutations |
| `cache` | `YANDEX_DIRECT_CACHE_DIR` | `~/.yandex-direct-api-client/cache` | Directory of the dictionary cache (TTL 7 days) |

## Geo targeting

One selector for both API versions. It resolves names, codes and IDs **only**
through the Direct dictionary, so invented IDs are impossible and ambiguous
names fail with a hint instead of a silent wrong match:

```python
from yandex_direct_api_client import RegionSelector

# Five regions far from Moscow and St. Petersburg
RegionSelector(include=[
    "Тверская область", "Омская область", "Краснодарский край",
    "Иркутская область", "Калининградская область",
]).resolve(client.dictionaries)

# Whole Russia except the four excluded regions
RegionSelector(exclude=["Москва", "Московская область",
                        "Санкт-Петербург", "Ленинградская область"]).resolve(
    client.dictionaries
)
```

`client.regions(selector)` is a shortcut, and
`RegionSelector.current(ad_group)` reads the regions of an existing group.
There are no hard-coded business regions in the SDK.

## Tests

```bash
pip install -e ".[dev]"

pytest                            # unit tests: mocked HTTP, no live API needed
ruff check .
mypy yandex_direct_api_client
```

## Live smoke (manual, not part of pytest)

Scripts under `scripts/` hit the real Direct API and are run **by hand** with
credentials from `.env` (`YANDEX_DIRECT_TOKEN`, `YANDEX_DIRECT_CLIENT_LOGIN`).
Nothing here runs in `pytest`.

```bash
python scripts/check_api.py                    # read-only smoke over real campaigns
python scripts/smoke_create_campaign.py        # text-campaign lifecycle
python scripts/smoke_task03_live.py            # ad_groups CRUD + campaign/ad lifecycle

# Full STAGE_05 live verification (D9):
python scripts/smoke_campaign_live.py --scenario all \
    --creative-id 123456 --image banner.jpg --budget 1
```

`smoke_campaign_live.py` scenarios:

| Scenario | What it checks |
|---|---|
| `S-01` | authorization, client limits, dictionary of regions |
| `S-02` | geo: 5 regions outside MSK/SPb/LO/MO and "whole Russia minus four" |
| `S-03` | classic РСЯ lifecycle (`v5`) — needs a ready `CreativeId` |
| `S-04` | ЕПК lifecycle (`v501`) — `adimages/add` → `ResponsiveAd` → read → delete |
| `S-05` | campaign report: impressions, clicks, CTR, CPM |

End-to-end launchers with compensation (suspend → archive → delete → delete
images) live in `scripts/launch_rsy.py` and `scripts/launch_epk.py`:

```bash
python -m scripts.launch_epk --name "E2E TEST ЕПК" --image banner.jpg \
    --budget 1 --href https://example.com --dry-run
```

Safety rules baked into these scripts:

- entities are created with names containing `E2E`/`TEST`/`SMOKE` — any other
  name requires `--confirm` (an automated launch of a real business campaign is
  out of scope);
- everything stays in `DRAFT`, serving is never enabled by default;
- cleanup runs even on failure and returns a non-zero exit code on error;
- OAuth tokens are never printed; only entity IDs, `RequestId` and the failing
  step are logged.

**Live run status:** the L3 run requires credentials provided by the repository
owner; as of 1.0.0 the live scripts are prepared and mock-tested, but the run
against a real account is pending (`scripts/smoke_campaign_live.py --scenario all`).

## License

MIT © [Grafek3d123](https://github.com/Grafek3d123) — see [LICENSE](LICENSE).
