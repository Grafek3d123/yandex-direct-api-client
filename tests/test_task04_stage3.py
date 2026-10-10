"""Тесты слоя 3 STAGE_05: стратегии, недельный и дневной бюджеты, предохранители.

Идентификаторы критериев приёмки:
- F-3.2 — `models/bid_strategy.py`: стратегии с `to_payload()`/`from_dict()` и
  escape-hatch для редких полей;
- F-3.3 — `set_weekly_budget(ids, budget, verify=True)`: точное значение в
  единицах ×1 000 000 и сверка после обновления; `set_daily_budget`,
  `get_budgets`, `set_bid_strategy`;
- F-3.4 — `daily_budget_cap` (0 вызовов при превышении) и
  `require_confirm_for_money`; `readonly=True` → 0 вызовов.
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Dict

import pytest
import responses

from yandex_direct_api_client import YandexDirectClient
from yandex_direct_api_client.exceptions import ApiError, ValidationError
from yandex_direct_api_client.models.ad_group_item import (
    BID_TYPE_NETWORK,
    AdGroupItemBids,
)
from yandex_direct_api_client.models.bid_strategy import (
    STRATEGY_AVERAGE_CPA,
    STRATEGY_AVERAGE_CPC,
    STRATEGY_MANUAL_CPM,
    BidStrategy,
    strategy_payload,
    weekly_budget_of,
)
from yandex_direct_api_client.money import monthly_to_weekly, to_money_units
from yandex_direct_api_client.services.budgets import (
    CampaignBudget,
    read_budget,
    set_weekly_budget_in_campaign,
)

CAMPAIGNS_V5_URL = "https://api.direct.yandex.com/json/v5/campaigns/"
CAMPAIGNS_V501_URL = "https://api.direct.yandex.com/json/v501/campaigns/"
CRITERIA_URL = "https://api.direct.yandex.com/json/v5/criteria/"


def _body_of(call: Any) -> Dict[str, Any]:
    """Разобрать JSON-тело исходящего запроса."""
    return json.loads(call.request.body)


def _client(**kwargs: Any) -> YandexDirectClient:
    """Клиент с тестовыми настройками."""
    params: Dict[str, Any] = {
        "token": "test_token",
        "client_login": "TESTLOGIN",
        "rate_limit_rps": 1000.0,
        "max_retries": 1,
    }
    params.update(kwargs)
    return YandexDirectClient(**params)


# ---------------- F-3.2: стратегии ----------------


def test_bid_strategy_to_payload_in_money_units() -> None:
    strategy = BidStrategy(
        strategy=STRATEGY_AVERAGE_CPA, weekly_budget=5000, goal_id=182
    )
    assert strategy.to_strategy_block() == {
        "BiddingStrategyType": "AVERAGE_CPA",
        "WeeklySpendLimit": 5_000_000_000,
        "GoalId": 182,
    }
    assert strategy.weekly_spend_limit == 5_000_000_000


def test_bid_strategy_roundtrip() -> None:
    strategy = BidStrategy(
        strategy=STRATEGY_AVERAGE_CPA, weekly_budget="1234.56", goal_id=182
    )
    parsed = BidStrategy.from_dict(strategy.to_strategy_block())
    assert parsed.strategy == STRATEGY_AVERAGE_CPA
    assert parsed.goal_id == 182
    assert parsed.weekly_budget == Decimal("1234.56")
    assert parsed.extra == {}


def test_bid_strategy_unknown_fields_go_to_extra() -> None:
    parsed = BidStrategy.from_dict(
        {
            "BiddingStrategyType": "AVERAGE_CPA",
            "WeeklySpendLimit": 1_000_000,
            "GoalId": 7,
            "BudgetType": "CUSTOM_PERIOD_BUDGET",
        }
    )
    assert parsed.extra == {"BudgetType": "CUSTOM_PERIOD_BUDGET"}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"strategy": "MAGIC"},
        {"strategy": STRATEGY_AVERAGE_CPA, "weekly_budget": -1},
        {"strategy": STRATEGY_AVERAGE_CPA, "weekly_budget": 10, "goal_id": 0},
    ],
)
def test_bid_strategy_validation(kwargs: Dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        BidStrategy(**kwargs)


@pytest.mark.parametrize(
    "strategy",
    [
        BidStrategy(strategy=STRATEGY_AVERAGE_CPA),
        BidStrategy(strategy=STRATEGY_AVERAGE_CPC),
        BidStrategy(strategy=STRATEGY_MANUAL_CPM),
    ],
)
def test_missing_required_strategy_fields_fail_on_payload(
    strategy: BidStrategy,
) -> None:
    with pytest.raises(ValidationError):
        strategy.to_strategy_block()


def test_bid_strategy_allows_partial_then_filled() -> None:
    strategy = BidStrategy(strategy=STRATEGY_AVERAGE_CPA)
    assert strategy.to_strategy_block(require_fields=False) == {
        "BiddingStrategyType": "AVERAGE_CPA"
    }
    strategy.weekly_budget = Decimal("100")
    strategy.goal_id = 182
    assert strategy.to_strategy_block()["WeeklySpendLimit"] == 100_000_000


def test_bid_strategy_parse_empty_returns_none() -> None:
    assert BidStrategy.parse(None) is None


def test_strategy_payload_accepts_dict_escape_hatch() -> None:
    assert strategy_payload({"BiddingStrategyType": "MAX_PROFIT"}) == {
        "BiddingStrategyType": "MAX_PROFIT"
    }
    with pytest.raises(ValidationError):
        strategy_payload("nope")  # type: ignore[arg-type]


def test_weekly_budget_of_finds_nested_block() -> None:
    assert weekly_budget_of({"AverageCpa": {"WeeklySpendLimit": 1_000_000}}) == Decimal(
        "1"
    )
    assert weekly_budget_of(None) is None


def test_monthly_to_weekly_is_explicit() -> None:
    weekly = monthly_to_weekly(20000)
    assert weekly == Decimal("4599.59")
    assert to_money_units(weekly) == 4_599_590_000


# ---------------- ставки (F-3.3) ----------------


def test_ad_group_item_bids_bid_type_maps_field() -> None:
    search = AdGroupItemBids(id=1, bid=40)
    network = AdGroupItemBids(id=2, bid=7.5, bid_type=BID_TYPE_NETWORK)
    assert search.to_payload() == {"Id": 1, "Bids": {"Bid": 40}}
    assert network.to_payload() == {"Id": 2, "Bids": {"ContextBid": 7.5}}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"id": 0, "bid": 1},
        {"id": 1, "bid": 0},
        {"id": 1, "bid": -5},
        {"id": 1, "bid": 1, "bid_type": "search-engines"},
        {"id": 1, "bid": 1, "auto_bid_fixed": -1},
    ],
)
def test_ad_group_item_bids_validation(kwargs: Dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        AdGroupItemBids(**kwargs)


@responses.activate
def test_set_bid_with_network_bid_type() -> None:
    responses.add(
        responses.POST,
        CRITERIA_URL,
        json={"result": {"SetBidsResults": [{"Id": 9}]}},
    )
    with _client() as c:
        result = c.ad_group_items.set_bid(9, 3.25, bid_type=BID_TYPE_NETWORK)
    assert result["Id"] == 9
    sent = _body_of(responses.calls[0])["params"]["AdGroupItems"][0]
    assert sent["Bids"] == {"ContextBid": 3.25}


def test_set_bid_rejects_bad_type_without_network() -> None:
    with _client() as c:
        with pytest.raises(ValidationError):
            c.ad_group_items.set_bid(1, 1, bid_type="nope")
    assert len(responses.calls) == 0


# ---------------- чтение бюджета ----------------


def test_read_budget_parses_cpm_campaign() -> None:
    budget = read_budget(
        {
            "Id": 5,
            "Type": "CPM_BANNER_CAMPAIGN",
            "CpmBannerCampaign": {
                "BiddingStrategy": {
                    "Search": {"BiddingStrategyType": "SERVING_OFF"},
                    "Network": {
                        "BiddingStrategyType": "MANUAL_CPM",
                        "ManualCpm": {"WeeklySpendLimit": 900_000_000},
                    },
                }
            },
        }
    )
    assert isinstance(budget, CampaignBudget)
    assert budget.weekly == Decimal("900")
    assert budget.strategy == "MANUAL_CPM"
    assert budget.as_dict()["Weekly"] == "900.000000"


def test_set_weekly_budget_in_campaign_cpm_path() -> None:
    body = set_weekly_budget_in_campaign(
        {"Id": 5, "Type": "CPM_BANNER_CAMPAIGN"}, 1500
    )
    network = body["CpmBannerCampaign"]["BiddingStrategy"]["Network"]
    assert network["BiddingStrategyType"] == STRATEGY_MANUAL_CPM
    assert network["ManualCpm"]["WeeklySpendLimit"] == 1_500_000_000


def test_set_weekly_budget_in_campaign_does_not_silently_overwrite_strategy() -> None:
    body = {
        "Id": 5, "Type": "CPM_BANNER_CAMPAIGN",
        "CpmBannerCampaign": {
            "BiddingStrategy": {
                "Network": {"BiddingStrategyType": "SERVING_OFF"},
            }
        },
    }
    with pytest.raises(ValidationError) as exc:
        set_weekly_budget_in_campaign(body, 1500)
    assert "не перезаписывает стратегию молча" in str(exc.value)
    assert body["CpmBannerCampaign"]["BiddingStrategy"]["Network"][
        "BiddingStrategyType"
    ] == "SERVING_OFF"


def test_set_weekly_budget_in_campaign_explicit_strategy_keeps_existing() -> None:
    body = {
        "Id": 5, "Type": "CPM_BANNER_CAMPAIGN",
        "CpmBannerCampaign": {
            "BiddingStrategy": {
                "Network": {"BiddingStrategyType": "MANUAL_CPM"},
            }
        },
    }
    set_weekly_budget_in_campaign(
        body, 1500, strategy=STRATEGY_MANUAL_CPM
    )
    network = body["CpmBannerCampaign"]["BiddingStrategy"]["Network"]
    assert network["BiddingStrategyType"] == STRATEGY_MANUAL_CPM
    assert network["ManualCpm"]["WeeklySpendLimit"] == 1_500_000_000


# ---------------- F-3.3: D2 — service-level guard для CPM ----------------


def _cpm_campaign_raw(network_strategy: str) -> Dict[str, Any]:
    """Сырая запись CPM-кампании из `campaigns/get`."""
    return {
        "Id": 5,
        "Type": "CPM_BANNER_CAMPAIGN",
        "CpmBannerCampaign": {
            "BiddingStrategy": {
                "Search": {"BiddingStrategyType": "SERVING_OFF"},
                "Network": {"BiddingStrategyType": network_strategy},
            }
        },
    }


@responses.activate
def test_set_weekly_budget_cpm_with_other_strategy_requires_explicit() -> None:
    """CPM с `MAX_CLICKS` и без `strategy=` должен бросить `ValidationError`."""
    responses.add(
        responses.POST,
        CAMPAIGNS_V5_URL,
        json={"result": {"Campaigns": [_cpm_campaign_raw("MAX_CLICKS")]}},
    )
    with _client() as c:
        with pytest.raises(ValidationError) as exc:
            c.campaigns.set_weekly_budget([5], 5000, confirm=True)
    assert "MAX_CLICKS" in str(exc.value)
    assert "strategy='MANUAL_CPM'" in str(exc.value) or "MANUAL_CPM" in str(exc.value)
    assert len(responses.calls) == 1  # только get_budgets, без update


@responses.activate
def test_set_weekly_budget_cpm_explicit_manual_cpm_overwrites_other() -> None:
    """CPM с `MAX_CLICKS`, но `strategy='MANUAL_CPM'` — намеренная смена стратегии."""
    responses.add(
        responses.POST,
        CAMPAIGNS_V5_URL,
        json={"result": {"Campaigns": [_cpm_campaign_raw("MAX_CLICKS")]}},
    )
    responses.add(
        responses.POST,
        CAMPAIGNS_V5_URL,
        json={"result": {"UpdateResults": [{"Id": 5}]}},
    )
    responses.add(
        responses.POST,
        CAMPAIGNS_V5_URL,
        json={
            "result": {
                "Campaigns": [
                    {
                        "Id": 5,
                        "Type": "CPM_BANNER_CAMPAIGN",
                        "CpmBannerCampaign": {
                            "BiddingStrategy": {
                                "Network": {
                                    "BiddingStrategyType": "MANUAL_CPM",
                                    "ManualCpm": {
                                        "WeeklySpendLimit": 5_000_000_000
                                    },
                                }
                            }
                        },
                    }
                ]
            }
        },
    )
    with _client() as c:
        budgets = c.campaigns.set_weekly_budget(
            [5], 5000, confirm=True, strategy=STRATEGY_MANUAL_CPM
        )
    sent = _body_of(responses.calls[1])["params"]["Campaigns"][0]
    assert (
        sent["CpmBannerCampaign"]["BiddingStrategy"]["Network"]["BiddingStrategyType"]
        == STRATEGY_MANUAL_CPM
    )
    assert budgets[0].weekly == Decimal("5000")


@responses.activate
def test_set_weekly_budget_cpm_already_manual_cpm_succeeds() -> None:
    """CPM с `MANUAL_CPM` и без `strategy=` — успешно (нет конфликта)."""
    responses.add(
        responses.POST,
        CAMPAIGNS_V5_URL,
        json={"result": {"Campaigns": [_cpm_campaign_raw("MANUAL_CPM")]}},
    )
    responses.add(
        responses.POST,
        CAMPAIGNS_V5_URL,
        json={"result": {"UpdateResults": [{"Id": 5}]}},
    )
    responses.add(
        responses.POST,
        CAMPAIGNS_V5_URL,
        json={
            "result": {
                "Campaigns": [
                    {
                        "Id": 5,
                        "Type": "CPM_BANNER_CAMPAIGN",
                        "CpmBannerCampaign": {
                            "BiddingStrategy": {
                                "Network": {
                                    "BiddingStrategyType": "MANUAL_CPM",
                                    "ManualCpm": {
                                        "WeeklySpendLimit": 5_000_000_000
                                    },
                                }
                            }
                        },
                    }
                ]
            }
        },
    )
    with _client() as c:
        budgets = c.campaigns.set_weekly_budget([5], 5000, confirm=True)
    assert budgets[0].weekly == Decimal("5000")
    assert budgets[0].strategy == "MANUAL_CPM"


def test_set_weekly_budget_in_campaign_unified_path() -> None:
    body = set_weekly_budget_in_campaign(
        {
            "Id": 6,
            "Type": "UNIFIED_CAMPAIGN",
            "UnifiedCampaign": {
                "BiddingStrategy": {
                    "Search": {
                        "BiddingStrategyType": "AVERAGE_CPA",
                        "AverageCpa": {"WeeklySpendLimit": 1, "GoalId": 182},
                    }
                }
            },
        },
        2500,
    )
    assert body["UnifiedCampaign"]["BiddingStrategy"]["Search"]["AverageCpa"][
        "WeeklySpendLimit"
    ] == 2_500_000_000


def test_set_weekly_budget_in_campaign_rejects_unsupported() -> None:
    with pytest.raises(ValidationError):
        set_weekly_budget_in_campaign({"Id": 1, "Type": "TEXT_CAMPAIGN"}, 10)
    with pytest.raises(ValidationError):
        set_weekly_budget_in_campaign({"Id": 1, "Type": "UNIFIED_CAMPAIGN"}, 10)
    with pytest.raises(ValidationError):
        set_weekly_budget_in_campaign({"Id": 1, "Type": "CPM_BANNER_CAMPAIGN"}, 0)


# ---------------- F-3.3/F-3.4: операции ----------------


@responses.activate
def test_set_weekly_budget_updates_and_verifies() -> None:
    responses.add(
        responses.POST,
        CAMPAIGNS_V5_URL,
        json={
            "result": {
                "Campaigns": [
                    {
                        "Id": 5,
                        "Type": "CPM_BANNER_CAMPAIGN",
                        "CpmBannerCampaign": {
                            "BiddingStrategy": {
                                "Network": {
                                    "BiddingStrategyType": "MANUAL_CPM",
                                    "ManualCpm": {"WeeklySpendLimit": 1_000_000_000},
                                }
                            }
                        },
                    }
                ]
            }
        },
    )
    responses.add(
        responses.POST,
        CAMPAIGNS_V5_URL,
        json={"result": {"UpdateResults": [{"Id": 5}]}},
    )
    responses.add(
        responses.POST,
        CAMPAIGNS_V5_URL,
        json={
            "result": {
                "Campaigns": [
                    {
                        "Id": 5,
                        "Type": "CPM_BANNER_CAMPAIGN",
                        "CpmBannerCampaign": {
                            "BiddingStrategy": {
                                "Network": {
                                    "BiddingStrategyType": "MANUAL_CPM",
                                    "ManualCpm": {"WeeklySpendLimit": 5_000_000_000},
                                }
                            }
                        },
                    }
                ]
            }
        },
    )
    with _client() as c:
        budgets = c.campaigns.set_weekly_budget([5], 5000, confirm=True)
    assert budgets[0].weekly == Decimal("5000")
    sent = _body_of(responses.calls[1])["params"]["Campaigns"][0]
    assert sent["CpmBannerCampaign"]["BiddingStrategy"]["Network"]["ManualCpm"][
        "WeeklySpendLimit"
    ] == 5_000_000_000


@responses.activate
def test_set_weekly_budget_verify_detects_mismatch() -> None:
    responses.add(
        responses.POST,
        CAMPAIGNS_V5_URL,
        json={
            "result": {
                "Campaigns": [
                    {
                        "Id": 5,
                        "Type": "CPM_BANNER_CAMPAIGN",
                        "CpmBannerCampaign": {
                            "BiddingStrategy": {
                                "Network": {
                                    "BiddingStrategyType": "MANUAL_CPM",
                                    "ManualCpm": {"WeeklySpendLimit": 1_000_000},
                                }
                            }
                        },
                    }
                ]
            }
        },
    )
    responses.add(
        responses.POST,
        CAMPAIGNS_V5_URL,
        json={"result": {"UpdateResults": [{"Id": 5}]}},
    )
    responses.add(
        responses.POST,
        CAMPAIGNS_V5_URL,
        json={
            "result": {
                "Campaigns": [
                    {
                        "Id": 5,
                        "Type": "CPM_BANNER_CAMPAIGN",
                        "CpmBannerCampaign": {
                            "BiddingStrategy": {
                                "Network": {
                                    "BiddingStrategyType": "MANUAL_CPM",
                                    "ManualCpm": {"WeeklySpendLimit": 1_000_000},
                                }
                            }
                        },
                    }
                ]
            }
        },
    )
    with _client() as c:
        with pytest.raises(ApiError) as exc:
            c.campaigns.set_weekly_budget([5], 5000, confirm=True)
    assert "5000" in str(exc.value)


@responses.activate
def test_set_weekly_budget_without_verify_makes_two_calls() -> None:
    responses.add(
        responses.POST,
        CAMPAIGNS_V5_URL,
        json={
            "result": {
                "Campaigns": [
                    {
                        "Id": 5,
                        "Type": "CPM_BANNER_CAMPAIGN",
                        "CpmBannerCampaign": {
                            "BiddingStrategy": {
                                "Network": {
                                    "BiddingStrategyType": "MANUAL_CPM",
                                    "ManualCpm": {"WeeklySpendLimit": 1_000_000},
                                }
                            }
                        },
                    }
                ]
            }
        },
    )
    responses.add(
        responses.POST,
        CAMPAIGNS_V5_URL,
        json={"result": {"UpdateResults": [{"Id": 5}]}},
    )
    with _client() as c:
        c.campaigns.set_weekly_budget([5], 5000, confirm=True, verify=False)
    assert len(responses.calls) == 2


def test_budget_cap_blocks_before_network() -> None:
    with _client(daily_budget_cap=Decimal("1000")) as c:
        with pytest.raises(ValidationError) as exc:
            c.campaigns.set_weekly_budget([5], 5000, confirm=True)
    assert "daily_budget_cap" in str(exc.value)
    assert len(responses.calls) == 0


def test_money_mutations_require_confirm() -> None:
    with _client() as c:
        with pytest.raises(ValidationError) as exc:
            c.campaigns.set_weekly_budget([5], 100)
    assert "confirm=True" in str(exc.value)
    with _client() as c:
        with pytest.raises(ValidationError):
            c.campaigns.set_daily_budget([5], 100)
    with _client() as c:
        with pytest.raises(ValidationError):
            c.campaigns.set_bid_strategy(
                [5], BidStrategy(strategy=STRATEGY_AVERAGE_CPC, average_cpc=10)
            )
    assert len(responses.calls) == 0


@responses.activate
def test_readonly_blocks_budget_mutations() -> None:
    with _client(readonly=True) as c:
        with pytest.raises(ValidationError):
            c.campaigns.set_weekly_budget([5], 100, confirm=True)
        with pytest.raises(ValidationError):
            c.campaigns.set_daily_budget([5], 100, confirm=True)
    assert len(responses.calls) == 0


@responses.activate
def test_get_budgets_reads_v5_then_v501() -> None:
    responses.add(
        responses.POST,
        CAMPAIGNS_V5_URL,
        json={
            "result": {
                "Campaigns": [
                    {
                        "Id": 5,
                        "Type": "CPM_BANNER_CAMPAIGN",
                        "DailyBudget": {"Amount": 2_000_000, "Mode": "STANDARD"},
                    }
                ]
            }
        },
    )
    responses.add(
        responses.POST,
        CAMPAIGNS_V501_URL,
        json={
            "result": {
                "Campaigns": [
                    {
                        "Id": 6,
                        "Type": "UNIFIED_CAMPAIGN",
                        "UnifiedCampaign": {
                            "BiddingStrategy": {
                                "Search": {
                                    "BiddingStrategyType": "AVERAGE_CPA",
                                    "AverageCpa": {
                                        "WeeklySpendLimit": 3_000_000,
                                        "GoalId": 1,
                                    },
                                }
                            }
                        },
                    }
                ]
            }
        },
    )
    with _client() as c:
        budgets = {b.campaign_id: b for b in c.campaigns.get_budgets([5, 6])}
    assert budgets[5].daily == Decimal("2")
    assert budgets[6].weekly == Decimal("3")
    assert responses.calls[0].request.url == CAMPAIGNS_V5_URL
    assert responses.calls[1].request.url == CAMPAIGNS_V501_URL


@responses.activate
def test_read_budget_text_campaign_weekly() -> None:
    """TEXT_CAMPAIGN: недельный бюджет читается из вложенного AverageCpc."""
    responses.add(
        responses.POST,
        CAMPAIGNS_V5_URL,
        json={
            "result": {
                "Campaigns": [
                    {
                        "Id": 7,
                        "Type": "TEXT_CAMPAIGN",
                        "TextCampaign": {
                            "BiddingStrategy": {
                                "Search": {
                                    "BiddingStrategyType": "AVERAGE_CPC",
                                    "AverageCpc": {"WeeklySpendLimit": 6_000_000},
                                }
                            }
                        },
                    }
                ]
            }
        },
    )
    with _client() as c:
        budgets = {b.campaign_id: b for b in c.campaigns.get_budgets([7])}
    assert budgets[7].type == "TEXT_CAMPAIGN"
    assert budgets[7].strategy == STRATEGY_AVERAGE_CPC
    assert budgets[7].weekly == Decimal("6")
    assert responses.calls[0].request.url == CAMPAIGNS_V5_URL


@responses.activate
def test_set_weekly_budget_text_campaign_rejected() -> None:
    """D1: для TEXT_CAMPAIGN недопустимо писать тело UnifiedCampaign в v5.

    Текстовая кампания обновляется на v5, а UnifiedCampaign-блок ей не
    подходит — должно падать ValidationError, а не отправляться на v5.
    """
    responses.add(
        responses.POST,
        CAMPAIGNS_V5_URL,
        json={
            "result": {
                "Campaigns": [
                    {
                        "Id": 7,
                        "Type": "TEXT_CAMPAIGN",
                        "TextCampaign": {
                            "BiddingStrategy": {
                                "Search": {
                                    "BiddingStrategyType": "AVERAGE_CPC",
                                    "AverageCpc": {"WeeklySpendLimit": 6_000_000},
                                }
                            }
                        },
                    }
                ]
            }
        },
    )
    with _client() as c:
        with pytest.raises(ValidationError):
            c.campaigns.set_weekly_budget([7], 7000, confirm=True)
    assert len(responses.calls) == 1  # только чтение get_budgets, без update


@responses.activate
def test_set_bid_strategy_sends_unified_strategy() -> None:
    responses.add(
        responses.POST,
        CAMPAIGNS_V501_URL,
        json={"result": {"UpdateResults": [{"Id": 6}]}},
    )
    responses.add(
        responses.POST,
        CAMPAIGNS_V5_URL,
        json={"result": {"Campaigns": []}},
    )
    responses.add(
        responses.POST,
        CAMPAIGNS_V501_URL,
        json={
            "result": {
                "Campaigns": [
                    {
                        "Id": 6,
                        "Type": "UNIFIED_CAMPAIGN",
                        "UnifiedCampaign": {
                            "BiddingStrategy": {
                                "Search": {
                                    "BiddingStrategyType": STRATEGY_AVERAGE_CPA,
                                    "WeeklySpendLimit": 4_000_000_000,
                                    "GoalId": 182,
                                }
                            }
                        },
                    }
                ]
            }
        },
    )
    with _client() as c:
        budgets = c.campaigns.set_bid_strategy(
            [6],
            BidStrategy(strategy=STRATEGY_AVERAGE_CPA, goal_id=182),
            weekly_budget=4000,
            confirm=True,
        )
    assert budgets[0].weekly == Decimal("4000.000000")
    sent = _body_of(responses.calls[0])["params"]["Campaigns"][0]
    search = sent["UnifiedCampaign"]["BiddingStrategy"]["Search"]
    assert search["BiddingStrategyType"] == STRATEGY_AVERAGE_CPA
    assert search["WeeklySpendLimit"] == 4_000_000_000
    assert responses.calls[0].request.url == CAMPAIGNS_V501_URL
