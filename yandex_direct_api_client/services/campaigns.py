"""Сервис кампаний: list, get, create, update, delete + управление состоянием."""
from __future__ import annotations

from typing import (
    Any,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Sequence,
    Union,
    cast,
    overload,
)

from .._transport import Transport
from ..config import API_VERSION_V501
from ..exceptions import ApiError, ValidationError
from ..limits import CAMPAIGNS_ADD_MAX, CAMPAIGNS_STATE_MAX, GET_IDS_MAX, GET_PAGE_MAX
from ..models.batch import BatchResult
from ..models.bid_strategy import (
    STRATEGY_AVERAGE_CPC,
    STRATEGY_MANUAL_CPM,
    BidStrategyInput,
    strategy_payload,
)
from ..models.campaign import Campaign
from ..models.campaign_payloads import (
    CAMPAIGN_TYPE_CPM_BANNER,
    CampaignBase,
    UnifiedCampaign,
)
from ..money import Money, to_money_units
from ..validation import Validator
from ._base import (
    OnItemError,
    ResultCollector,
    chunked,
    empty_result,
    ensure_confirmed,
    ensure_writable,
    fetch_all_pages,
    run_batches,
)
from .budgets import (
    CampaignBudget,
    _validate_budget,
    ensure_money_confirmed,
    read_budget,
    set_weekly_budget_in_campaign,
    verify_weekly_budget,
)

_DEFAULT_FIELDS = [
    "Id",
    "Name",
    "Status",
    "State",
    "Type",
    "StartDate",
    "EndDate",
]

#: Поля `campaigns/get` для ЕПК: стратегии, недельный бюджет, Метрика.
_UNIFIED_FIELDS = [
    "Id",
    "Name",
    "Status",
    "State",
    "Type",
    "StartDate",
    "EndDate",
    "UnifiedCampaign",
]

#: Поля `campaigns/get` для чтения бюджета (v5-часть; тип кампании известен).
_BUDGET_FIELDS = [
    "Id",
    "Type",
    "DailyBudget",
    "CpmBannerCampaign",
    "TextCampaign",
]

#: Кампания для `campaigns.create`/`create_many`: билдер или сырой dict.
CampaignInput = Union[CampaignBase, Mapping[str, Any]]


class CampaignService:
    """Операции над кампаниями Yandex.Direct."""

    def __init__(self, transport: Transport, *, readonly: bool = False) -> None:
        self._transport = transport
        self._readonly = readonly

    def _ensure_writable(self, method_name: str) -> None:
        ensure_writable("campaigns", method_name, self._readonly)

    def _validator(self) -> Validator:
        return Validator(self._transport.validate_enabled)

    @staticmethod
    def _campaign_body(campaign: CampaignInput) -> Dict[str, Any]:
        """Привести билдер или dict к телу `campaigns/add`.

        :param campaign: билдер кампании либо готовый словарь.
        :return: словарь для `params.Campaigns`.
        :raises ValidationError: неизвестный тип билдера или невалидные поля.
        """
        if isinstance(campaign, CampaignBase):
            campaign.validate()
            return campaign.to_payload()
        return dict(campaign)

    def list(
        self,
        *,
        states: Optional[Sequence[str]] = None,
        statuses: Optional[Sequence[str]] = None,
        page_limit: int = GET_PAGE_MAX,
    ) -> List[Campaign]:
        """Список кампаний клиента с авто-пагинацией.

        :param states: фильтр по State (ON, OFF, SUSPENDED, ENDED, ARCHIVED, CONVERTED).
        :param statuses: фильтр по Status (ACCEPTED, DRAFT, MODERATION, REJECTED).
        :param page_limit: размер страницы (до 10000).
        """
        criteria: Dict[str, Any] = {}
        if states:
            criteria["States"] = list(states)
        if statuses:
            criteria["Statuses"] = list(statuses)

        payload: Dict[str, Any] = {
            "method": "get",
            "params": {
                "SelectionCriteria": criteria,
                "FieldNames": _DEFAULT_FIELDS,
            },
        }
        raw_list = fetch_all_pages(
            self._transport, "campaigns", payload, page_limit=page_limit
        )
        return [Campaign.from_dict(c) for c in raw_list]

    def get(
        self,
        ids: Sequence[int],
        *,
        field_names: Optional[Sequence[str]] = None,
    ) -> List[Campaign]:
        """Получить кампании по ID (авто-чанкинг по 1000).

        :param ids: список ID кампаний.
        :param field_names: кастомный список полей для запроса.
        """
        if not ids:
            return []
        self._validator().ids(ids, field="Ids")
        fields = list(field_names) if field_names else _DEFAULT_FIELDS
        results: List[Campaign] = []
        for chunk in chunked(list(ids), GET_IDS_MAX):
            payload: Dict[str, Any] = {
                "method": "get",
                "params": {
                    "SelectionCriteria": {"Ids": list(chunk)},
                    "FieldNames": fields,
                },
            }
            result = self._transport.post_result("campaigns", payload)
            for raw in result.get("Campaigns") or []:
                results.append(Campaign.from_dict(raw))
        return results

    @overload
    def create(
        self,
        campaign: CampaignInput,
        *,
        on_item_error: Literal["raise"] = ...,
    ) -> Dict[str, Any]: ...

    @overload
    def create(
        self,
        campaign: CampaignInput,
        *,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def create(
        self,
        campaign: CampaignInput,
        *,
        on_item_error: OnItemError = "raise",
    ) -> Union[Dict[str, Any], BatchResult]:
        """Создать кампанию (campaigns/add).

        ЕПК (`UnifiedCampaign`) маршрутизируется на `v501` автоматически;
        для явного вызова используйте `create_unified`.

        :param campaign: типизированный билдер (`CpmBannerCampaign`,
            `TextCampaign`, `UnifiedCampaign`) либо словарь с телом кампании.
        :param on_item_error: `raise` — ошибка элемента бросает `ApiError`;
            `collect` — возвращает `BatchResult` с успешными и неуспешными.
        :return: элемент AddResults (или `BatchResult` в режиме `collect`).
        """
        self._ensure_writable("create")
        body = self._campaign_body(campaign)
        self._validator().name(body.get("Name"), field="Campaign.Name")
        api_version = (
            API_VERSION_V501 if isinstance(campaign, UnifiedCampaign) else None
        )
        payload: Dict[str, Any] = {
            "method": "add",
            "params": {"Campaigns": [body]},
        }
        result = self._transport.post_result(
            "campaigns", payload, api_version=api_version
        )
        add_results = result.get("AddResults") or []
        if not add_results:
            raise ApiError(
                "Пустой AddResults в ответе API",
                request_id=self._transport.last_request_id,
                status_code=200,
                response_body=result,
            )
        collector = ResultCollector(
            on_item_error, request_id=self._transport.last_request_id
        )
        collector.add(add_results, "создания кампании")
        finished = collector.finish()
        if on_item_error == "collect":
            return cast(BatchResult, finished)
        return cast(List[Dict[str, Any]], finished)[0]

    @overload
    def create_many(
        self,
        campaigns: Sequence[Dict[str, Any]],
        *,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def create_many(
        self,
        campaigns: Sequence[Dict[str, Any]],
        *,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def create_many(
        self,
        campaigns: Sequence[CampaignInput],
        *,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Создать несколько кампаний (лимит API — 10 за вызов, campaigns/add).

        :param campaigns: билдеры кампаний или тела по схеме campaigns/add.
        :param on_item_error: `raise` или `collect` (см. `create`).
        :return: список элементов AddResults (или `BatchResult`).
        """
        self._ensure_writable("create_many")
        validator = self._validator()
        bodies: List[Dict[str, Any]] = []
        for item in campaigns:
            body = self._campaign_body(item)
            validator.name(body.get("Name"), field="Campaign.Name")
            bodies.append(body)
        return run_batches(
            self._transport,
            "campaigns",
            method="add",
            params_key="Campaigns",
            items=bodies,
            on_item_error=on_item_error,
            action="создания кампании",
            result_key="AddResults",
            chunk_size=CAMPAIGNS_ADD_MAX,
        )

    @overload
    def update(
        self,
        campaign: Dict[str, Any],
        *,
        on_item_error: Literal["raise"] = ...,
    ) -> Dict[str, Any]: ...

    @overload
    def update(
        self,
        campaign: Dict[str, Any],
        *,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def update(
        self,
        campaign: Dict[str, Any],
        *,
        on_item_error: OnItemError = "raise",
    ) -> Union[Dict[str, Any], BatchResult]:
        """Обновить кампанию (campaigns/update).

        :param campaign: тело с Id и обновляемыми полями (campaigns/update).
        :param on_item_error: `raise` или `collect` (см. `create`).
        :return: элемент UpdateResults (или `BatchResult`).
        """
        self._ensure_writable("update")
        self._validator().ids([campaign.get("Id")], field="Campaign.Id")
        payload: Dict[str, Any] = {
            "method": "update",
            "params": {"Campaigns": [campaign]},
        }
        result = self._transport.post_result("campaigns", payload)
        update_results = result.get("UpdateResults") or []
        if not update_results:
            raise ApiError(
                "Пустой UpdateResults в ответе API",
                request_id=self._transport.last_request_id,
                status_code=200,
                response_body=result,
            )
        collector = ResultCollector(
            on_item_error, request_id=self._transport.last_request_id
        )
        collector.add(update_results, "обновления кампании")
        finished = collector.finish()
        if on_item_error == "collect":
            return cast(BatchResult, finished)
        return cast(List[Dict[str, Any]], finished)[0]

    @overload
    def delete(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: Literal["raise"] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def delete(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: Literal["collect"],
    ) -> BatchResult: ...

    def delete(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Удалить кампании по ID (авто-чанкинг по 200).

        :param ids: список ID кампаний.
        :param confirm: явное подтверждение необратимой операции удаления.
        :param on_item_error: `raise` или `collect` (см. `create`).
        :return: список элементов DeleteResults (или `BatchResult`).
        """
        self._ensure_writable("delete")
        ensure_confirmed("campaigns.delete", confirm)
        return self._ids_action("delete", "DeleteResults", "удаления кампании", ids, on_item_error)

    def _state_action(
        self,
        method_name: str,
        result_key: str,
        action_label: str,
        ids: Sequence[int],
        on_item_error: OnItemError = "raise",
        api_version: Optional[str] = None,
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Общий batch-вызов метода управления состоянием по SelectionCriteria.Ids.

        :param method_name: имя метода API (suspend/resume/archive/unarchive).
        :param result_key: ключ списка результатов в ответе.
        :param action_label: описание действия для сообщений об ошибках.
        :param ids: список ID кампаний.
        :param on_item_error: `raise` или `collect`.
        :param api_version: версия API для этого вызова (None — по умолчанию).
        :return: список элементов ActionResult (или `BatchResult`).
        """
        self._ensure_writable(method_name)
        return self._ids_action(
            method_name,
            result_key,
            action_label,
            ids,
            on_item_error,
            api_version=api_version,
        )

    def _ids_action(
        self,
        method_name: str,
        result_key: str,
        action_label: str,
        ids: Sequence[int],
        on_item_error: OnItemError,
        api_version: Optional[str] = None,
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Общий batch-вызов метода по SelectionCriteria.Ids (чанкинг по 1000).

        :param method_name: имя метода API (delete/suspend/resume/...).
        :param result_key: ключ списка результатов в ответе.
        :param action_label: описание действия для сообщений об ошибках.
        :param ids: список ID кампаний.
        :param on_item_error: `raise` или `collect`.
        :param api_version: версия API для этого вызова (None — по умолчанию).
        :return: список элементов результата (или `BatchResult`).
        """
        id_list = list(ids)
        if not id_list:
            return empty_result(on_item_error)
        self._validator().ids(id_list, field="SelectionCriteria.Ids")
        collector = ResultCollector(on_item_error)
        for chunk in chunked(id_list, CAMPAIGNS_STATE_MAX):
            payload: Dict[str, Any] = {
                "method": method_name,
                "params": {"SelectionCriteria": {"Ids": list(chunk)}},
            }
            result = self._transport.post_result(
                "campaigns", payload, api_version=api_version
            )
            collector.set_request_id(self._transport.last_request_id)
            collector.add(result.get(result_key) or [], f"{action_label} кампании")
        return collector.finish()

    @overload
    def suspend(
        self,
        ids: Sequence[int],
        *,
        on_item_error: Literal["raise"] = ...,
        api_version: Optional[str] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def suspend(
        self,
        ids: Sequence[int],
        *,
        on_item_error: Literal["collect"],
        api_version: Optional[str] = ...,
    ) -> BatchResult: ...

    def suspend(
        self,
        ids: Sequence[int],
        *,
        on_item_error: OnItemError = "raise",
        api_version: Optional[str] = None,
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Остановить показы кампаний (campaigns/suspend, до 1000 за запрос).

        :param ids: список ID кампаний.
        :param on_item_error: `raise` или `collect`.
        :param api_version: версия API (`v501` для кампаний ЕПК).
        :return: список элементов SuspendResults (или `BatchResult`).
        """
        return self._state_action(
            "suspend",
            "SuspendResults",
            "остановки",
            ids,
            on_item_error,
            api_version=api_version,
        )

    @overload
    def resume(
        self, ids: Sequence[int], *, on_item_error: Literal["raise"] = ...
    ) -> List[Dict[str, Any]]: ...

    @overload
    def resume(
        self, ids: Sequence[int], *, on_item_error: Literal["collect"]
    ) -> BatchResult: ...

    def resume(
        self, ids: Sequence[int], *, on_item_error: OnItemError = "raise"
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Возобновить показы кампаний (campaigns/resume, до 1000 за запрос).

        :param ids: список ID кампаний.
        :param on_item_error: `raise` или `collect`.
        :return: список элементов ResumeResults (или `BatchResult`).
        """
        return self._state_action(
            "resume", "ResumeResults", "возобновления", ids, on_item_error
        )

    @overload
    def archive(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: Literal["raise"] = ...,
        api_version: Optional[str] = ...,
    ) -> List[Dict[str, Any]]: ...

    @overload
    def archive(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: Literal["collect"],
        api_version: Optional[str] = ...,
    ) -> BatchResult: ...

    def archive(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: OnItemError = "raise",
        api_version: Optional[str] = None,
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Разместить кампании в архив (campaigns/archive, до 1000 за запрос).

        :param ids: список ID кампаний.
        :param confirm: явное подтверждение массового изменения.
        :param on_item_error: `raise` или `collect`.
        :param api_version: версия API (`v501` для кампаний ЕПК).
        :return: список элементов ArchiveResults (или `BatchResult`).
        """
        ensure_confirmed("campaigns.archive", confirm)
        return self._state_action(
            "archive",
            "ArchiveResults",
            "архивации",
            ids,
            on_item_error,
            api_version=api_version,
        )

    @overload
    def unarchive(
        self, ids: Sequence[int], *, on_item_error: Literal["raise"] = ...
    ) -> List[Dict[str, Any]]: ...

    @overload
    def unarchive(
        self, ids: Sequence[int], *, on_item_error: Literal["collect"]
    ) -> BatchResult: ...

    def unarchive(
        self, ids: Sequence[int], *, on_item_error: OnItemError = "raise"
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Разархивировать кампании (campaigns/unarchive, до 1000 за запрос).

        :param ids: список ID кампаний.
        :param on_item_error: `raise` или `collect`.
        :return: список элементов UnarchiveResults (или `BatchResult`).
        """
        return self._state_action(
            "unarchive", "UnarchiveResults", "разархивации", ids, on_item_error
        )


    # ---------------- слой 3: бюджеты и стратегии ----------------
    def get_budgets(
        self, ids: Sequence[int]
    ) -> List[CampaignBudget]:
        """Прочитать бюджеты кампаний (`campaigns/get`).

        ЕПК-кампании не видны в v5, поэтому запрос выполняется в два прохода:
        сначала v5, затем v501 для оставшихся ID. Ответы объединяются.

        :param ids: список ID кампаний.
        :return: список `CampaignBudget`.
        :raises ValidationError: пустой или некорректный список ID.
        """
        if not ids:
            return []
        self._validator().ids(ids, field="Ids")
        pending = list(ids)
        budgets: List[CampaignBudget] = []
        for version in (None, API_VERSION_V501):
            if not pending:
                break
            found: List[int] = []
            for chunk in chunked(pending, GET_IDS_MAX):
                payload: Dict[str, Any] = {
                    "method": "get",
                    "params": {
                        "SelectionCriteria": {"Ids": list(chunk)},
                        "FieldNames": _BUDGET_FIELDS,
                    },
                }
                result = self._transport.post_result(
                    "campaigns", payload, api_version=version
                )
                for raw in result.get("Campaigns") or []:
                    budgets.append(read_budget(raw))
                    campaign_id = raw.get("Id")
                    if isinstance(campaign_id, int):
                        found.append(campaign_id)
            pending = [i for i in pending if i not in set(found)]
        return budgets

    def set_weekly_budget(
        self,
        ids: Sequence[int],
        budget: Money,
        *,
        confirm: bool = False,
        verify: bool = True,
        strategy: Optional[str] = None,
    ) -> List[CampaignBudget]:
        """Задать недельный бюджет кампаний (`campaigns/update`).

        Недельный бюджет лежит внутри стратегии, поэтому SDK сначала читает
        текущую стратегию (`campaigns/get`), затем правит только поле
        `WeeklySpendLimit` и отправляет обновление. При `verify=True`
        (по умолчанию) выполняется повторное чтение и значения сверяются;
        расхождение — `ApiError` с обоими числами.

        :param ids: список ID кампаний.
        :param budget: недельный бюджет в валюте аккаунта.
        :param confirm: явное подтверждение денежной мутации.
        :param verify: перечитать бюджеты после обновления.
        :param strategy: сетевая стратегия CPM (сейчас всегда `MANUAL_CPM`).
            Передавайте явно, если тело кампании уже содержит иной
            `BiddingStrategyType` в сети — иначе вызов не перезапишет стратегию
            молча, а бросит `ValidationError`. Для CPM-кампании с живой сетевой
            стратегией, отличной от `MANUAL_CPM` (например `MAX_CLICKS`), вызов
            без явного `strategy` также бросит `ValidationError`: weekly budget
            поддерживается только при `MANUAL_CPM`, поэтому смена стратегии
            должна быть намеренной.
        :return: список `CampaignBudget` (актуальные значения при verify).
        :raises ValidationError: превышен `daily_budget_cap`, нет подтверждения
            или тип/стратегия не поддерживает недельный бюджет.
        :raises ApiError: бюджет не совпал после обновления.
        """
        self._ensure_writable("set_weekly_budget")
        if not ids:
            return []
        self._validator().ids(ids, field="Ids")
        cap = self._transport.settings.daily_budget_cap
        amount = _validate_budget(
            budget, cap=cap, field="Недельный бюджет"
        )
        ensure_money_confirmed(
            "campaigns",
            "set_weekly_budget",
            confirm,
            self._transport.settings.require_confirm_for_money,
        )
        current = {b.campaign_id: b for b in self.get_budgets(ids)}
        bodies: List[Dict[str, Any]] = []
        for campaign_id in ids:
            known = current.get(campaign_id)
            body: Dict[str, Any] = {"Id": int(campaign_id)}
            if known is not None and known.type:
                body["Type"] = known.type
            if (
                known is not None
                and known.type == "UNIFIED_CAMPAIGN"
                and known.strategy == STRATEGY_AVERAGE_CPC
            ):
                body["UnifiedCampaign"] = {
                    "BiddingStrategy": {
                        "Search": {
                            "BiddingStrategyType": STRATEGY_AVERAGE_CPC,
                            "AverageCpc": {"WeeklySpendLimit": to_money_units(amount)},
                        }
                    }
                }
            else:
                if (
                    known is not None
                    and known.type == CAMPAIGN_TYPE_CPM_BANNER
                    and known.strategy is not None
                    and known.strategy != STRATEGY_MANUAL_CPM
                    and strategy is None
                ):
                    raise ValidationError(
                        f"set_weekly_budget: CPM-кампания {campaign_id} имеет "
                        f"сетевую стратегию {known.strategy!r}; weekly budget "
                        "поддерживается только при MANUAL_CPM. Передайте "
                        f"strategy={STRATEGY_MANUAL_CPM!r} явно для смены "
                        "стратегии, либо измените стратегию кампании."
                    )
                body = set_weekly_budget_in_campaign(
                    body, amount, strategy=strategy
                )
            bodies.append(body)
        for body in bodies:
            self._transport.post_result(
                "campaigns",
                {"method": "update", "params": {"Campaigns": [body]}},
                api_version=API_VERSION_V501 if body.get("Type") == "UNIFIED_CAMPAIGN" else None,
            )
        if not verify:
            return list(current.values())
        updated = {b.campaign_id: b for b in self.get_budgets(ids)}
        verify_weekly_budget(
            updated, {int(i): amount for i in ids}
        )
        return list(updated.values())

    def set_daily_budget(
        self,
        ids: Sequence[int],
        budget: Money,
        *,
        confirm: bool = False,
        verify: bool = True,
    ) -> List[CampaignBudget]:
        """Задать дневной бюджет кампаний (`DailyBudget`, deprecated в API).

        Яндекс переводит кампании на недельные бюджета; дневной оставлен для
        совместимости и для клиентов, которым он ещё нужен. Проверка
        предостерегательного лимита и подтверждения — как у недельного.

        :param ids: список ID кампаний.
        :param budget: дневной бюджет в валюте аккаунта.
        :param confirm: явное подтверждение денежной мутации.
        :param verify: перечитать бюджеты после обновления.
        :return: список `CampaignBudget`.
        :raises ValidationError: превышен cap, нет подтверждения или бюджет
            неположителен.
        """
        self._ensure_writable("set_daily_budget")
        if not ids:
            return []
        self._validator().ids(ids, field="Ids")
        amount = _validate_budget(
            budget, cap=self._transport.settings.daily_budget_cap, field="Дневной бюджет"
        )
        ensure_money_confirmed(
            "campaigns",
            "set_daily_budget",
            confirm,
            self._transport.settings.require_confirm_for_money,
        )
        for campaign_id in ids:
            self._transport.post_result(
                "campaigns",
                {
                    "method": "update",
                    "params": {
                        "Campaigns": [
                            {
                                "Id": int(campaign_id),
                                "DailyBudget": {
                                    "Amount": to_money_units(amount),
                                    "Mode": "STANDARD",
                                },
                            }
                        ]
                    },
                },
            )
        if not verify:
            return self.get_budgets(ids)
        budgets = {b.campaign_id: b for b in self.get_budgets(ids)}
        mismatched = [
            f"CampaignId={cid}: ожидалось {amount}, получено "
            f"{budgets[cid].daily if budgets[cid].daily is not None else 'None'}"
            for cid in ids
            if cid in budgets and (budgets[cid].daily is None or budgets[cid].daily != amount)
        ]
        if mismatched:
            raise ApiError(
                "Дневной бюджет не совпал после обновления: " + "; ".join(mismatched)
            )
        return list(budgets.values())

    def set_bid_strategy(
        self,
        ids: Sequence[int],
        strategy: BidStrategyInput,
        *,
        weekly_budget: Optional[Money] = None,
        confirm: bool = False,
        verify: bool = True,
    ) -> List[CampaignBudget]:
        """Сменить стратегию показа кампаний (`campaigns/update`).

        Недельный бюджет можно передать сразу (`weekly_budget`) — тогда он
        уедет в ту же секцию стратегии, и отдельный вызов `set_weekly_budget`
        не потребуется.

        :param ids: список ID кампаний.
        :param strategy: `BidStrategy` либо готовая секция стратегии.
        :param weekly_budget: недельный бюджет внутри новой стратегии.
        :param confirm: явное подтверждение денежной мутации.
        :param verify: перечитать бюджеты после обновления.
        :return: список `CampaignBudget`.
        :raises ValidationError: превышен cap, нет подтверждения, неизвестный
            тип стратегии или не задан `weekly_budget` там, где он обязателен.
        """
        self._ensure_writable("set_bid_strategy")
        if not ids:
            return []
        self._validator().ids(ids, field="Ids")
        cap = self._transport.settings.daily_budget_cap
        if weekly_budget is not None:
            _validate_budget(weekly_budget, cap=cap, field="Недельный бюджет")
        ensure_money_confirmed(
            "campaigns",
            "set_bid_strategy",
            confirm,
            self._transport.settings.require_confirm_for_money,
        )
        block = strategy_payload(strategy, require_fields=weekly_budget is None)
        if weekly_budget is not None:
            block.setdefault("WeeklySpendLimit", to_money_units(weekly_budget))
        for campaign_id in ids:
            self._transport.post_result(
                "campaigns",
                {
                    "method": "update",
                    "params": {
                        "Campaigns": [
                            {
                                "Id": int(campaign_id),
                                "UnifiedCampaign": {"BiddingStrategy": {"Search": block}},
                            }
                        ]
                    },
                },
                api_version=API_VERSION_V501,
            )
        if not verify:
            return self.get_budgets(ids)
        return self.get_budgets(ids)

    # ---------------- ЕПК (UnifiedCampaign, v501) ----------------
    def create_unified(
        self,
        campaign: Union[UnifiedCampaign, Mapping[str, Any]],
        *,
        on_item_error: OnItemError = "raise",
    ) -> Union[Dict[str, Any], BatchResult]:
        """Создать ЕПК-кампанию (`campaigns/add` на `v501`).

        :param campaign: билдер `UnifiedCampaign` либо готовое тело.
        :param on_item_error: `raise` или `collect` (см. `create`).
        :return: элемент AddResults (или `BatchResult`).
        """
        self._ensure_writable("create_unified")
        body = self._campaign_body(campaign)
        self._validator().name(body.get("Name"), field="Campaign.Name")
        payload: Dict[str, Any] = {
            "method": "add",
            "params": {"Campaigns": [body]},
        }
        result = self._transport.post_result(
            "campaigns", payload, api_version=API_VERSION_V501
        )
        add_results = result.get("AddResults") or []
        if not add_results:
            raise ApiError(
                "Пустой AddResults в ответе API",
                request_id=self._transport.last_request_id,
                status_code=200,
                response_body=result,
            )
        collector = ResultCollector(
            on_item_error, request_id=self._transport.last_request_id
        )
        collector.add(add_results, "создания ЕПК-кампании")
        finished = collector.finish()
        if on_item_error == "collect":
            return cast(BatchResult, finished)
        return cast(List[Dict[str, Any]], finished)[0]

    def update_unified(
        self,
        campaign: Union[UnifiedCampaign, Mapping[str, Any]],
        *,
        on_item_error: OnItemError = "raise",
    ) -> Union[Dict[str, Any], BatchResult]:
        """Обновить ЕПК-кампанию (`campaigns/update` на `v501`).

        :param campaign: билдер `UnifiedCampaign` либо тело с `Id`.
        :param on_item_error: `raise` или `collect` (см. `create`).
        :return: элемент UpdateResults (или `BatchResult`).
        """
        self._ensure_writable("update_unified")
        body = self._campaign_body(campaign)
        self._validator().ids([body.get("Id")], field="Campaign.Id")
        payload: Dict[str, Any] = {
            "method": "update",
            "params": {"Campaigns": [body]},
        }
        result = self._transport.post_result(
            "campaigns", payload, api_version=API_VERSION_V501
        )
        update_results = result.get("UpdateResults") or []
        if not update_results:
            raise ApiError(
                "Пустой UpdateResults в ответе API",
                request_id=self._transport.last_request_id,
                status_code=200,
                response_body=result,
            )
        collector = ResultCollector(
            on_item_error, request_id=self._transport.last_request_id
        )
        collector.add(update_results, "обновления ЕПК-кампании")
        finished = collector.finish()
        if on_item_error == "collect":
            return cast(BatchResult, finished)
        return cast(List[Dict[str, Any]], finished)[0]

    def get_unified(
        self,
        ids: Sequence[int],
        *,
        field_names: Optional[Sequence[str]] = None,
    ) -> List[Campaign]:
        """Прочитать ЕПК-кампании (`campaigns/get` на `v501`).

        По умолчанию запрашивается секция `UnifiedCampaign`: стратегии,
        недельный бюджет, счётчики Метрики и ключевые цели.

        :param ids: список ID ЕПК-кампаний (чанкинг по 1000).
        :param field_names: кастомный список полей.
        :return: список кампаний.
        """
        if not ids:
            return []
        self._validator().ids(ids, field="Ids")
        fields = list(field_names or _UNIFIED_FIELDS)
        results: List[Campaign] = []
        for chunk in chunked(list(ids), GET_IDS_MAX):
            payload: Dict[str, Any] = {
                "method": "get",
                "params": {
                    "SelectionCriteria": {"Ids": list(chunk)},
                    "FieldNames": fields,
                },
            }
            result = self._transport.post_result(
                "campaigns", payload, api_version=API_VERSION_V501
            )
            for raw in result.get("Campaigns") or []:
                results.append(Campaign.from_dict(raw))
        return results

    def delete_unified(
        self,
        ids: Sequence[int],
        *,
        confirm: bool = False,
        on_item_error: OnItemError = "raise",
    ) -> Union[List[Dict[str, Any]], BatchResult]:
        """Удалить ЕПК-кампании (`campaigns/delete` на `v501`).

        :param ids: список ID ЕПК-кампаний.
        :param confirm: явное подтверждение необратимой операции.
        :param on_item_error: `raise` или `collect` (см. `create`).
        :return: список DeleteResults (или `BatchResult`).
        """
        self._ensure_writable("delete_unified")
        ensure_confirmed("campaigns.delete_unified", confirm)
        return self._ids_action(
            "delete",
            "DeleteResults",
            "удаления ЕПК-кампании",
            ids,
            on_item_error,
            api_version=API_VERSION_V501,
        )


__all__ = ["CampaignService"]
