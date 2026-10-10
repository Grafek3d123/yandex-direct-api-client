"""Модель группы объявлений Яндекс.Директа."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ._helpers import to_int, to_optional_int, to_str


def _to_int_list(value: Any) -> Optional[List[int]]:
    if value is None or not isinstance(value, (list, tuple)):
        return None
    result: List[int] = []
    for item in value:
        parsed = to_optional_int(item)
        if parsed is not None:
            result.append(parsed)
    return result


def _to_items_int_list(value: Any) -> Optional[List[int]]:
    """Разобрать ArrayOfLong ({Items: [...]}) либо обычный массив в список int.

    В ответе adgroups/get поле NegativeKeywordSharedSetIds приходит как
    структура ArrayOfLong с ключом Items, а RegionIds — обычным массивом.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("Items")
    return _to_int_list(value)


@dataclass
class AdGroup:
    """Группа объявлений Директа."""

    id: int
    campaign_id: Optional[int] = None
    name: str = ""
    status: Optional[str] = None
    state: Optional[str] = None
    type: Optional[str] = None
    region_ids: Optional[List[int]] = None
    negative_keywords_shared_set_ids: Optional[List[int]] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AdGroup":
        return cls(
            id=to_int(d.get("Id")),
            campaign_id=to_optional_int(d.get("CampaignId")),
            name=to_str(d.get("Name")),
            status=d.get("Status"),
            state=d.get("State"),
            type=d.get("Type"),
            region_ids=_to_int_list(d.get("RegionIds")),
            negative_keywords_shared_set_ids=_to_items_int_list(
                d.get("NegativeKeywordSharedSetIds")
            ),
            raw=d,
        )

    def to_new_payload(self) -> Dict[str, Any]:
        """Тело для adgroups/add (AdGroupAddItem).

        `Type` в запросе **не отправляется**: в актуальном API тип группы
        задаётся типоспецифичной структурой (`CpmBannerKeywordsAdGroup: {}`
        и т. п.), а сам `Type` приходит только в ответе `adgroups/get`.
        Раньше SDK полагался на `Type`, и РСЯ-группа без него не создавалась —
        теперь используйте билдеры `models/ad_group_payloads.py`.
        """
        body: Dict[str, Any] = {}
        if self.campaign_id is not None:
            body["CampaignId"] = self.campaign_id
        if self.name:
            body["Name"] = self.name
        if self.region_ids:
            body["RegionIds"] = list(self.region_ids)
        if self.negative_keywords_shared_set_ids:
            body["NegativeKeywordSharedSetIds"] = {
                "Items": list(self.negative_keywords_shared_set_ids)
            }
        return body

    def to_update_payload(self) -> Dict[str, Any]:
        """Тело для adgroups/update: Id + изменяемые поля.

        CampaignId НЕ включается — adgroups/update не принимает это поле
        (кампанию группы изменить нельзя); иначе API отдаёт ошибку 8000
        "unknown parameter CampaignId".
        """
        body: Dict[str, Any] = {}
        if self.name:
            body["Name"] = self.name
        if self.region_ids:
            body["RegionIds"] = list(self.region_ids)
        if self.negative_keywords_shared_set_ids:
            body["NegativeKeywordSharedSetIds"] = {
                "Items": list(self.negative_keywords_shared_set_ids)
            }
        if self.id:
            body["Id"] = self.id
        return body


__all__ = ["AdGroup"]
