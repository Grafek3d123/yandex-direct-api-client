# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Migration guide: 0.1.x → 0.4.x

The client was restructured into a namespace API. Summary of breaking changes
with migration examples:

| 0.1.x | 0.4.x |
|---|---|
| `client.get_campaigns()` | `client.campaigns.list()` |
| `client.get_ads(ad_ids=..., campaign_ids=...)` | `client.ads.get(ids=...)` / `client.ads.list(campaign_ids=...)` |
| `client.get_ads_text_batch(ids)` | `client.ads.get(ids, include_text=True)` |
| `client.get_stats(...)` | `client.reports.get_ad_stats(...)` (unchanged) or `client.reports.get(...)` |
| `client.update_ad(id, h, b)` | `client.ads.update_text(id, h, b)` |
| `client.add_campaign(payload)` | `client.campaigns.create(payload)` |
| `client.delete_ad(ids)` | `client.ads.delete(ids, confirm=True)` |
| `YandexDirectClient(chunk_size=...)` | parameter removed (auto chunking/pagination) |
| model `AdTextEntry` | `Ad` with `include_text=True` |
| `parse_stats_tsv` importable from `client.py` | `yandex_direct_api_client` (re-exported) |

New safety semantics:

- `delete` and bulk mutations now require explicit `confirm=True`
  (raises `ValidationError` before any HTTP request is sent).
- `StatRow.merged_with` computes weighted-average `bounce_rate` (was: sum).

## [Unreleased]

## [0.5.0] - 2026-09-23

### Added
- **Track A — full lifecycle of existing resources:**
  - `client.ad_groups` gained mutations: `create` (typed `AdGroup` or raw),
    `update`, `delete` (requires `confirm=True`). Endpoint `adgroups/add|update|delete`.
  - `client.campaigns` state management: `suspend`, `resume`, `archive`
    (requires `confirm=True`), `unarchive`. Endpoints `campaigns/suspend|resume|archive|unarchive`.
  - `client.ads` state management and moderation: `suspend`, `resume`,
    `archive` (requires `confirm=True`), `unarchive`, `moderate`.
    Endpoints `ads/suspend|resume|archive|unarchive|moderate`.
  - `AdGroup.to_new_payload()` / `to_update_payload()`.
- **Track B — new API resources:**
  - `client.negative_keywords` service (API `negativekeywordsharedsets`):
    `list`, `get`, `create`, `update`, `delete` (requires `confirm=True`).
    Model `NegativeKeywordSharedSet`.
  - `client.audience_targets` service (API `audiencetargets`): `list`, `get`,
    `create`, `delete` (requires `confirm=True`), `suspend`, `resume`, `set_bids`.
    Model `AudienceTarget`. (audiencetargets has no `update`; bids change via
    `set_bids`.)
  - `client.retargeting_conditions` service: `list`, `get`, `create`,
    `delete` (requires `confirm=True`). Model `RetargetingCondition`. Wraps the
    `audiencetargets` service (the standalone `retargetingconditions` endpoint is
    not in the current v5 reference; retargeting is managed via
    `audiencetargets` + `RetargetingListId`).
  - `client.ad_extensions` service: `list_sitelinks`, `get_sitelinks`,
    `create_sitelinks`, `delete_sitelinks` (API `sitelinks`) and
    `list_callouts`, `get_callouts`, `create_callouts`, `delete_callouts`
    (API `adextensions`, type CALLOUT). Models `Sitelink`, `SitelinksSet`, `Callout`.
- New models: `NegativeKeywordSharedSet`, `AudienceTarget`,
  `RetargetingCondition`, `Sitelink`, `SitelinksSet`, `Callout`.
- 51 new tests (Track A: 23, Track B: 28): request construction, response
  parsing, item-level errors, `confirm`/`readonly` guards, typed/raw payloads.
- 5 regression tests from the live-account run (see below): `ad_groups`
  `list`/`get` field/criteria contracts and guards.
- `scripts/smoke_task03_live.py` — permanent live smoke over a real account
  (campaign + groups + ads lifecycle); creates a DRAFT campaign starting
  tomorrow and deletes everything it creates. Not part of pytest.

### Fixed
- `AdGroup` model: field is `NegativeKeywordSharedSetIds` (singular) and it is
  an `ArrayOfLong` (`{Items: [...]}`) — `from_dict` now unwraps the `Items`
  wrapper and `to_new_payload` emits it. Previously used a wrong field name and
  a bare list.
- `client.ad_groups` service is now constructed with `readonly=ro`, so its
  mutations are correctly blocked in readonly mode (was wired without the flag).
- **Request-contract bugs found only against the live API (mocks could not
  catch them):**
  - `adgroups/get` requested a non-existent `State` field (ad groups have only
    `Status`/`ServingStatus`) → API error 8000 "Not able to process JSON/XML".
    Removed from `_DEFAULT_FIELDS`; `ad_groups.list`/`get` now send valid fields.
  - `ad_groups.list()` without `campaign_ids` produced an empty
    `SelectionCriteria` → API "filtration parameters incorrectly set". Now raises
    a clear client-side `ValidationError` (adgroups/get requires `CampaignIds`/`Ids`).
  - `ad_groups.list(states=…)` sent invalid `SelectionCriteria.States`; replaced
    with valid `statuses`/`serving_statuses` filters.
  - `AdGroup.to_update_payload()` sent `CampaignId`, which `adgroups/update`
    rejects (error 8000 "unknown parameter CampaignId"). No longer sent on update.
  - `ads.create_with_payload()` sent `CampaignId` and `Type`, both rejected by
    `ads/add` (error 8000 "unknown parameter …"). The ad's campaign is derived
    from `AdGroupId` (now required) and its type from the `TextAd`/`ImageAd`
    object. `campaign_id`/`type_` params are kept for compatibility but not sent.
  - Updated two existing tests that had codified the buggy payloads
    (`test_ads_create_with_payload`).

## [0.4.1] - 2026-09-22

### Changed
- Deduplicated service-level helpers: `check_item_errors` and `ensure_writable`
  moved to `services/_base.py` (was copy-pasted in 4 services).
- Deduplicated OAuth token exchange: `auth.refresh_token` and code exchange now
  share a single `_post_token_request` implementation.
- `services/_base.py`: `import copy` moved to module level.

### Fixed
- `auth._parse_args` no longer returns a 1-tuple (odd signature).

## [0.4.0] - 2026-09-22

### Added
- Full Reports API support: universal `client.reports.get()` with report type,
  date period (`date_from`/`date_to` or `date_range_type`), custom fields,
  filters (`ReportFilter`), ordering (`ReportOrder`), Metrika goals
  (conversions), attribution models, VAT/discount flags, page limit and
  per-call `report_timeout`.
- Typed convenience wrappers: `account_stats`, `campaign_stats`,
  `ad_group_stats`, `criteria_stats` (keywords/autotargeting),
  `search_queries` — all delegate to `get()` (single execution path).
- New models: `ReportFilter`, `ReportOrder`, `ReportRow` (typed accessors
  `as_int/as_float/as_money/as_date`), `ReportResult` with `to_dicts()`,
  `to_csv()`, `to_json()` and optional `to_dataframe()` (pandas optional).
- Auto-batching for large requests: ID filters chunked by 1000 values per
  report; long date ranges split into windows via `max_days` parameter.
- `report_timeout` override per call (`Transport.post` parameter).
- 25 new tests: parsing, filters/order/goals payload, 202 polling, timeout,
  429 retry, API errors, ID chunking, date-window splitting, wrappers,
  backward compatibility.

### Fixed
- `get_ad_stats` now sends ID filters via `SelectionCriteria.Filter`
  (per official v5 spec) instead of non-standard `AdIds`/`CampaignIds` fields.

## [0.3.0] - 2026-09-22

### Added
- `client.ad_group_items` service (keywords, API service `criteria`): `list`, `get`,
  `add` (typed `AdGroupItem` or raw dicts), `set_bid`, `set_bids` (bulk, requires
  `confirm=True`), `delete` (requires `confirm=True`).
- `client.retargeting_adjustments` service: `list`, `get`, `add`, `update`
  (bulk, requires `confirm=True`), `delete` (requires `confirm=True`).
- New models: `AdGroupItem`, `AdGroupItemBids`, `RetargetingBidAdjustment`,
  `AdImage`; `AdText.to_payload()` for typed ad creation.
- `client.ads.create_with_payload()` — create a text ad from typed
  `AdText`/`AdImage` models.
- Unit tests for all new services: pagination, batching, typed/raw payloads,
  item-level errors, confirm and readonly guards (22 new tests).

## [0.2.1] - 2026-09-22

### Added
- `confirm=True` guard for destructive operations: `ads.delete`, `campaigns.delete`,
  and bulk `ads.update` now raise `ValidationError` unless explicitly confirmed.
  Single-item operations (`update_text`, `campaigns.update`, `campaigns.create`,
  `ads.create`) do not require confirmation.

### Removed
- Unused `DEFAULT_CHUNK_SIZE` constant from `config.py`.

## [0.2.0] - 2026-09-22

### Breaking changes
- Client API restructured to namespace-based: `client.campaigns.list()` instead of `client.get_campaigns()`.
- `client.ads.update_text()` replaces `client.update_ad()`.
- `client.ads.delete()` replaces `client.delete_ad()`.
- `client.campaigns.create()` replaces `client.add_campaign()`.
- `client.reports.get_ad_stats()` replaces `client.get_stats()`.
- `chunk_size` parameter removed from constructor (pagination handles this internally).
- `AdTextEntry` model removed (use `Ad` with `include_text=True` instead).
- `StatRow.merged_with` now computes weighted-average `bounce_rate` instead of summing.

### Added
- Namespace services: `client.campaigns`, `client.ads`, `client.ad_groups`, `client.reports`.
- Auto-pagination via `Page`/`LimitedBy` in all `list()` methods.
- `AdGroup` model and `client.ad_groups` service (list, get).
- `client.campaigns.update()` and `client.campaigns.delete()`.
- `client.ads.create()` and `client.ads.update()` — batch operations (up to 200 per request).
- `client.ads.list()` — flexible filtering with auto-pagination.
- `Transport` class extracted for HTTP layer separation.
- `models/` package with per-entity modules.
- `services/` package with per-resource service classes.

### Changed
- `Campaign` model now includes `type` field.
- `requests.Session` lock removed (Session is thread-safe for independent requests).
- `DEFAULT_CHUNK_SIZE` constant removed from config.

## [0.1.0] - 2026-09-20

### Added
- `YandexDirectClient` — sync typed client for Yandex.Direct API v5.
- OAuth helpers: `get_new_token`, `refresh_token` in `yandex_direct_api_client.auth`.
- Built-in retry layer for HTTP 429 (with `Retry-After`) and 202 report polling.
- Token-bucket rate limiter (configurable `rate_limit_rps`).
- Typed responses as dataclasses (`Campaign`, `Ad`, `AdText`, `StatRow`).
- Custom exceptions with `request_id`: `AuthError`, `RateLimitError`,
  `ReportNotReadyError`, `ApiError`.
- `readonly=True` guard blocking all mutating methods.
- Auto-chunking for `get_ads`, `get_ads_text_batch`, `update_ad`, `delete_ad`.
- Context-manager support with shared `requests.Session` (keep-alive).
- Environment-variable fallback (`YANDEX_DIRECT_TOKEN`, `YANDEX_DIRECT_CLIENT_LOGIN`, ...).
- `py.typed` marker for mypy / PEP 561.
