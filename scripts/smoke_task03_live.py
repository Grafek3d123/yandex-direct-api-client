"""Live smoke test for task03 Track A: ad_groups CRUD + campaigns/ads lifecycle.

Creates a text campaign (OFF, starts tomorrow), 2 ad groups and 3 ads in
DRAFT, exercises the new methods (ad_groups create/get/list/update, campaigns
suspend/resume/archive/unarchive, ads create/get/list/suspend/resume), then
deletes everything it created. Not part of pytest — run manually:

    .venv/bin/python scripts/smoke_task03_live.py

Secrets are read from .env and never printed. The campaign starts tomorrow and
all ads stay in DRAFT (never submitted to moderation), so impressions and
charges are zero. Everything created is deleted at the end (also in `finally`).

Notes discovered against the live API (documented, not client bugs):
  * A freshly created campaign (State=DRAFT/OFF, not started yet) cannot be
    suspended/resumed/archived — the API returns "Invalid object status" /
    "Cannot archive object". Such rejections are logged as EXPECTED.
  * Ad group RegionIds must be real region IDs from the Regions dictionary;
    RegionIds=[0] ("all regions") is rejected with "Geotargeting set
    incorrectly". We probe a real region from an existing group.
"""
from __future__ import annotations

import logging
import os
import pathlib
import sys
from datetime import date, timedelta
from typing import Any, Callable, List, Optional, Tuple

# ---- load .env without external deps ----
_env_path = pathlib.Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _, _v = _line.partition("=")
        _k, _v = _k.strip(), _v.strip()
        if _k and _k not in os.environ:
            os.environ[_k] = _v

from yandex_direct_api_client import YandexDirectClient  # noqa: E402
from yandex_direct_api_client.exceptions import ApiError  # noqa: E402
from yandex_direct_api_client.models import AdGroup, AdText  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("smoke_task03")

NAME = f"TASK03 LIVE TEST {date.today().isoformat()} (auto)"
# Real API state-constraint messages -> expected, not a client failure.
_EXPECTED_MARKERS = ("Invalid object status", "Cannot archive object")
RESULTS: List[Tuple[str, str, str]] = []  # (name, status, detail)


def _classify(err: Exception) -> str:
    msg = str(err)
    return "expected" if any(m in msg for m in _EXPECTED_MARKERS) else "FAIL"


def step(name: str, fn: Callable[[], Any], *, fatal: bool = False) -> Any:
    try:
        detail = fn()
        RESULTS.append((name, "OK", str(detail) if detail is not None else ""))
        logger.info("[OK]   %-40s %s", name, "" if detail is None else detail)
        return detail
    except ApiError as e:
        kind = _classify(e)
        RESULTS.append((name, kind, f"ApiError: {e}"))
        logger.log(
            logging.INFO if kind == "expected" else logging.WARNING,
            "[%s] %-40s %s",
            kind.upper(),
            name,
            e,
        )
        if kind == "FAIL" and fatal:
            raise
        return None
    except Exception as e:  # noqa: BLE001
        RESULTS.append((name, "FAIL", f"{type(e).__name__}: {e}"))
        logger.warning("[FAIL] %-40s %s: %s", name, type(e).__name__, e)
        if fatal:
            raise
        return None


def main() -> int:
    # 1. readonly read before test
    with YandexDirectClient(readonly=True) as ro:
        step("campaigns.list (readonly, before)", lambda: len(ro.campaigns.list()))

    client = YandexDirectClient()
    campaign_id: Optional[int] = None
    group_ids: List[int] = []
    ad_ids: List[int] = []
    try:
        # 2. probe a valid region from an existing group (RegionIds=[0] is
        # rejected; adgroups/get also requires a campaign_ids filter)
        def _probe_region() -> str:
            camps = client.campaigns.list()
            for c in camps[:10]:
                for g in client.ad_groups.list(campaign_ids=[c.id]):
                    if g.region_ids:
                        return str(g.region_ids)
            raise RuntimeError("no existing group with RegionIds to probe")

        region_raw = step("ad_groups.list (probe region)", _probe_region, fatal=True)
        region_ids = [int(x) for x in region_raw.strip("[]").split(",") if x.strip()]

        # 3. create campaign (OFF, starts tomorrow, network off)
        def _create_campaign() -> int:
            res = client.campaigns.create(
                {
                    "Name": NAME,
                    "StartDate": (date.today() + timedelta(days=1)).isoformat(),
                    "EndDate": (date.today() + timedelta(days=2)).isoformat(),
                    "TextCampaign": {
                        "BiddingStrategy": {
                            "Search": {"BiddingStrategyType": "HIGHEST_POSITION"},
                            "Network": {"BiddingStrategyType": "SERVING_OFF"},
                        }
                    },
                }
            )
            return int(res["Id"])

        campaign_id = step("campaigns.create", _create_campaign, fatal=True)

        # 4. campaign read
        step("campaigns.get", lambda: client.campaigns.get([campaign_id])[0].state)

        # 5. campaign state (DRAFT campaign -> expected rejections)
        step("campaigns.suspend", lambda: len(client.campaigns.suspend([campaign_id])))
        step("campaigns.resume", lambda: len(client.campaigns.resume([campaign_id])))

        # 6. create ad groups (real region) — new functionality
        def _create_group(idx: int) -> int:
            g = AdGroup(
                id=0,
                campaign_id=campaign_id,
                name=f"{NAME} group {idx}",
                region_ids=region_ids,
            )
            res = client.ad_groups.create([g])
            return int(res[0]["Id"])

        for i in (1, 2):
            gid = step(f"ad_groups.create #{i}", lambda i=i: _create_group(i))
            if gid:
                group_ids.append(gid)
        if not group_ids:
            raise RuntimeError("no ad group created — aborting")

        # 7. read groups
        step("ad_groups.get", lambda: [g.id for g in client.ad_groups.get(group_ids)])
        step(
            "ad_groups.list(campaign_ids)",
            lambda: len(client.ad_groups.list(campaign_ids=[campaign_id])),
        )

        # 8. update group (rename)
        def _update_group() -> int:
            g = AdGroup(
                id=group_ids[0],
                campaign_id=campaign_id,
                name=f"{NAME} group 1 [upd]",
                region_ids=region_ids,
            )
            return int(client.ad_groups.update([g])[0]["Id"])

        step("ad_groups.update", _update_group)

        # 9. create ads (typed + batch)
        def _create_ad_typed(gid: int, idx: int) -> int:
            res = client.ads.create_with_payload(
                campaign_id,
                AdText(
                    title=f"Test product {idx}",
                    text="Test ad body for API smoke check.",
                    href="https://example.com/test",
                ),
                ad_group_id=gid,
            )
            return int(res["Id"])

        t1 = step(
            "ads.create_with_payload #1", lambda: _create_ad_typed(group_ids[0], 1)
        )
        if t1:
            ad_ids.append(t1)

        def _create_ads_batch() -> List[int]:
            body = [
                {
                    "AdGroupId": group_ids[1] if len(group_ids) > 1 else group_ids[0],
                    "TextAd": {
                        "Title": f"Test product {idx}",
                        "Text": "Batch ad for ads.create smoke check.",
                        "Href": "https://example.com/batch",
                    },
                }
                for idx in (2, 3)
            ]
            return [int(x["Id"]) for x in client.ads.create(body)]

        batch = step("ads.create (batch, 2)", _create_ads_batch)
        if batch:
            ad_ids.extend(batch)

        # 10. read ads
        step("ads.get", lambda: [a.id for a in client.ads.get(ad_ids)])
        step(
            "ads.list(campaign_ids)",
            lambda: len(client.ads.list(campaign_ids=[campaign_id])),
        )

        # 11. ads state (DRAFT ads -> possible rejections, expected)
        step("ads.suspend", lambda: len(client.ads.suspend(ad_ids)))
        step("ads.resume", lambda: len(client.ads.resume(ad_ids)))

        # 12. campaign archive/unarchive (DRAFT -> expected rejections)
        step(
            "campaigns.archive (confirm)",
            lambda: len(client.campaigns.archive([campaign_id], confirm=True)),
        )
        step(
            "campaigns.unarchive", lambda: len(client.campaigns.unarchive([campaign_id]))
        )

        # 13. cleanup: ads -> groups -> campaign (all confirm=True)
        step("ads.delete (confirm)", lambda: len(client.ads.delete(ad_ids, confirm=True)))
        step(
            "ad_groups.delete (confirm)",
            lambda: len(client.ad_groups.delete(group_ids, confirm=True)),
        )
        step(
            "campaigns.delete (confirm)",
            lambda: len(client.campaigns.delete([campaign_id], confirm=True)),
        )

        # 14. verify gone
        def _verify_gone() -> str:
            return "gone - OK" if not client.campaigns.get([campaign_id]) else "STILL EXISTS"

        step("campaigns.get (after delete)", _verify_gone)
        campaign_id = None
        return _summary()
    finally:
        if campaign_id is not None:
            logger.warning("Test did not finish cleanly — forcing cleanup")
            if ad_ids:
                _safe(client.ads.delete, ad_ids, confirm=True)
            if group_ids:
                _safe(client.ad_groups.delete, group_ids, confirm=True)
            _safe(client.campaigns.delete, [campaign_id], confirm=True)
        client.close()


def _safe(fn: Callable[..., Any], *args: Any, **kw: Any) -> None:
    try:
        fn(*args, **kw)
    except Exception as e:  # noqa: BLE001
        logger.error("forced cleanup %s failed: %s", getattr(fn, "__name__", fn), e)


def _summary() -> int:
    ok = sum(1 for _, s, _ in RESULTS if s == "OK")
    exp = sum(1 for _, s, _ in RESULTS if s == "expected")
    fail = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    print("\n" + "=" * 64)
    print(f"RESULT: {ok} OK, {exp} expected(API constraint), {fail} FAIL")
    print("=" * 64)
    for name, status, detail in RESULTS:
        print(f"[{status:8}] {name}: {detail}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
