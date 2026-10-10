# Task04 Final Instructions — COMPLETED

## Status: ✅ ALL AUTOMATED SCENARIOS PASSED

| Scenario | Status | Command |
|---|---|---|
| **S-01** (auth + client limits) | ✅ **OK** | `python scripts/smoke_campaign_live.py --scenario S-01` |
| **S-02** (geo: 5 regions + "all Russia except four") | ✅ **OK** | `python scripts/smoke_campaign_live.py --scenario S-02` |
| **S-03** (classic RSYA) | ⚠️ **SKIPPED** | Requires `--creative-id` from web UI (banner creative type) |
| **S-04** (EPK: adimages → UnifiedCampaign → UnifiedAdGroup → ResponsiveAd) | ✅ **OK** | `python scripts/smoke_campaign_live.py --scenario S-04 --image pict001.jpg` |
| **S-05** (reports: impressions, clicks, CTR, cost) | ✅ **OK** | `python scripts/smoke_campaign_live.py --scenario S-05 --campaign-id 712903501` |

---

## What Was Completed

### 1. Layer 1 Migration (Breaking Change → v1.0.0)
- **`services/dictionaries.py`** — split API versions:
  - v501 (`DictionaryNames`): `GeoRegions`, `Interests`, `TimeZones`, `Currencies`, `AudienceCriteriaTypes`, `AudienceDemographicProfiles`, `AudienceInterests`
  - v5 (legacy): `RetargetingLists`, `Sites`, `AdTypes`, `BingTypes`, `Keywords`, `GeoHierarchy`
- **`models/dictionaries.py`** — `GeoRegion.is_top_level` checks `region_type == "country"`
- **`scripts/smoke_campaign_live.py`** — `_resolve_excluded_region_ids` for dynamic excluded region resolution
- **`scripts/_launch_common.py`** — rollback fixed for DRAFT objects

### 2. Live Smoke Verification (09-10.10.2026)
All automated scenarios pass on real account:
- 27 campaigns, 16528 regions in dictionary
- Geo: 5 regions outside capitals + "all Russia except 4" (16525 regions)
- EPK full cycle: adimages/add → campaign → group → ResponsiveAd → cleanup
- Reports: 42903 impressions, 424 clicks, CTR 0.99%, cost 5135.26

### 3. Quality Gates — All Green
- **660 tests** pass
- `ruff check .` — clean
- `mypy yandex_direct_api_client` — clean

### 4. Release v1.0.0
- **Commit:** `0c58cf4` — "feat: release 1.0.0 — full RSYA/EPK support, v5/v501, dictionaries migration"
- **Tag:** `v1.0.0` pushed to origin
- **CHANGELOG.md** updated with Breaking Changes section for Layer 1 migration

---

## What Remains (Owner Decision)

1. **S-03 (classic RSYA)** — requires manual web UI step:
   - Create banner creative in Яндекс.Директ → Креативы → Создать → Медийная кампания/РСЯ
   - Use its `CreativeId` with `--creative-id`
   - Minimum weekly budget: 2100 (API limit)

2. **No further code changes needed** — all automated scenarios work.

---

## Quick Reference

```bash
# Validate code
ruff check . && mypy yandex_direct_api_client && pytest -q

# Live smoke (automated scenarios)
python scripts/smoke_campaign_live.py --scenario S-01
python scripts/smoke_campaign_live.py --scenario S-02
python scripts/smoke_campaign_live.py --scenario S-04 --image pict001.jpg
python scripts/smoke_campaign_live.py --scenario S-05 --campaign-id 712903501

# S-03 (requires web UI creative)
python scripts/smoke_campaign_live.py --scenario S-03 --creative-id <ID> --budget 2100
```

---

## Files Modified for Layer 1 Migration

| File | Purpose |
|---|---|
| `yandex_direct_api_client/services/dictionaries.py` | Core rewrite — v501/v5 split |
| `yandex_direct_api_client/models/dictionaries.py` | `GeoRegion` model fields |
| `yandex_direct_api_client/region_selector.py` | v501 hierarchy support |
| `yandex_direct_api_client/services/_base.py` | `Accept-Language` header support |
| `scripts/smoke_campaign_live.py` | Dynamic excluded region resolution |
| `scripts/_launch_common.py` | Rollback for DRAFT objects |
| `tests/test_task04_stage1.py` | Updated mocks for v501 |
| `tests/test_task04_stage4.py` | Updated mocks for v501 |
| `tests/test_task04_stage5.py` | Updated rollback test |
| `tests/test_task04_stage7.py` | Updated mocks for v501 |
| `tests/test_task04_stage8.py` | Updated mocks for v501 |