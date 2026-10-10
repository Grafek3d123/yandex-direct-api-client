"""Модели ключевых фраз (AdGroupItem) и ставок (AdGroupItemBids)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..validation import Validator
from ._helpers import to_float, to_int, to_optional_int


@dataclass
class AdGroupItem:
    """Ключевая фраза объявления (criteria/get)."""

    id: int
    campaign_id: Optional[int] = None
    ad_group_id: Optional[int] = None
    type: Optional[str] = None
    phrase: Optional[str] = None
    bid: Optional[float] = None
    currency: Optional[str] = None
    context: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AdGroupItem":
        item = d.get("Item") or {}
        bid_block = d.get("Bid") or {}
        bid_raw = bid_block.get("Bid")
        return cls(
            id=to_int(d.get("Id")),
            campaign_id=to_optional_int(d.get("CampaignId")),
            ad_group_id=to_optional_int(d.get("AdGroupId")),
            type=item.get("Type") or d.get("Type"),
            phrase=item.get("Phrase"),
            bid=to_float(bid_raw) if bid_raw is not None else None,
            currency=bid_block.get("Currency"),
            context=d.get("Context"),
            raw=d,
        )

    def to_new_payload(self) -> Dict[str, Any]:
        """Тело для criteria/add (AdGroupItemNew)."""
        body: Dict[str, Any] = {}
        if self.type is not None:
            body["Type"] = self.type
        if self.campaign_id is not None:
            body["CampaignId"] = self.campaign_id
        if self.ad_group_id is not None:
            body["AdGroupId"] = self.ad_group_id
        item: Dict[str, Any] = {}
        if self.type is not None:
            item["Type"] = self.type
        if self.phrase is not None:
            item["Phrase"] = self.phrase
        if item:
            body["Item"] = item
        if self.bid is not None:
            bid_block: Dict[str, Any] = {"Bid": self.bid}
            if self.currency is not None:
                bid_block["Currency"] = self.currency
            body["Bid"] = bid_block
        return body


#: Тип ставки: поиск (`Bid`) или РСЯ (`ContextBid`).
BID_TYPE_SEARCH = "search"
BID_TYPE_NETWORK = "network"
BID_TYPES = (BID_TYPE_SEARCH, BID_TYPE_NETWORK)

#: Имя поля в теле `criteria/setbids` для каждого типа ставки.
_BID_TYPE_FIELD = {
    BID_TYPE_SEARCH: "Bid",
    BID_TYPE_NETWORK: "ContextBid",
}


@dataclass
class AdGroupItemBids:
    """Ставка ключевой фразы для criteria/setbids.

    Точные минимальные и максимальные ставки зависят от валюты аккаунта и берутся
    из справочника `Currencies` (`dictionaries.get`). Локально проверяется только
    базовая корректность: положительная конечная сумма и известный тип ставки.
    """

    id: int
    bid: float
    auto_bid_fixed: Optional[float] = None
    bid_type: str = BID_TYPE_SEARCH

    def __post_init__(self) -> None:
        """Проверить ID, тип ставки и положительность суммы.

        :raises ValidationError: если поле некорректно.
        """
        validator = Validator(True)
        validator.ids([self.id], field="AdGroupItemBids.id")
        validator.one_of(self.bid_type, BID_TYPES, field="AdGroupItemBids.bid_type")
        validator.positive_amount(self.bid, field="AdGroupItemBids.bid")
        if self.auto_bid_fixed is not None:
            validator.positive_amount(
                self.auto_bid_fixed, field="AdGroupItemBids.auto_bid_fixed"
            )

    def to_payload(self) -> Dict[str, Any]:
        """Тело элемента setbids: Id + Bids.

        :return: словарь с полем ставки выбранного типа.
        """
        bids: Dict[str, Any] = {_BID_TYPE_FIELD[self.bid_type]: self.bid}
        if self.auto_bid_fixed is not None:
            bids["AutoBidFixed"] = self.auto_bid_fixed
        return {"Id": self.id, "Bids": bids}


__all__ = [
    "BID_TYPES",
    "BID_TYPE_NETWORK",
    "BID_TYPE_SEARCH",
    "AdGroupItem",
    "AdGroupItemBids",
]
