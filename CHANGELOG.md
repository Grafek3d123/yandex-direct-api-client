# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
