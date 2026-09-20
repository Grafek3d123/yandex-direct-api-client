"""`YandexDirectClient` — sync typed клиент Yandex.Direct API v5."""
from __future__ import annotations

import datetime as _dt
import logging
import threading
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests

from .config import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_REPORT_TIMEOUT,
    USER_AGENT,
    Settings,
)
from .exceptions import ApiError, ValidationError
from .models import Ad, AdTextEntry, Campaign, StatRow
from .retry import TokenBucket, request_with_retry

logger = logging.getLogger(__name__)

# Лимиты API (см. https://yandex.ru/dev/direct/doc/ref-v5/limits/)
_MAX_GET_IDS = 20000  # SelectionCriteria.Ids / CampaignIds для get-методов
_MAX_MUTATE_IDS = 200  # update/add/delete

# Лимиты TextAd (актуальные на 2026)
_TITLE_LIMIT = 56
_TEXT_LIMIT = 81


def _chunked(seq: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _clamp_text(value: str, limit: int) -> str:
    """Обрезать строку по символам с учётом лимита Директа."""
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


class YandexDirectClient:
    """Sync клиент Yandex.Direct API v5.

    :param token: OAuth access token. Если None — берётся из env.
    :param client_login: логин клиента Директа. Если None — из env.
    :param api_url: базовый URL API (default: https://api.direct.yandex.com/json/v5).
    :param timeout: таймаут одного HTTP-запроса, сек.
    :param max_retries: максимум повторов при 429 и 202.
    :param rate_limit_rps: rate limit на стороне клиента (token bucket).
    :param readonly: если True — все mutating-методы падают с ValidationError.
    :param chunk_size: размер чанка при авто-чанкинге Ids (<= 20000 для get).
    :param session: свой `requests.Session` (для переиспользования/тестов).
    :param report_timeout: максимум секунд ожидания готовности отчёта.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        client_login: Optional[str] = None,
        *,
        api_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        rate_limit_rps: Optional[float] = None,
        readonly: Optional[bool] = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        session: Optional[requests.Session] = None,
        report_timeout: float = DEFAULT_REPORT_TIMEOUT,
    ) -> None:
        env = Settings.from_env()
        self._settings: Settings = env.merged_with(
            token=token,
            client_login=client_login,
            api_url=api_url,
            timeout=timeout,
            max_retries=max_retries,
            rate_limit_rps=rate_limit_rps,
            readonly=readonly,
        )
        if not self._settings.token:
            raise ValidationError(
                "Не задан token (передан аргументом или через "
                "YANDEX_DIRECT_TOKEN)"
            )
        if not self._settings.client_login:
            raise ValidationError(
                "Не задан client_login (передан аргументом или через "
                "YANDEX_DIRECT_CLIENT_LOGIN)"
            )
        if chunk_size <= 0:
            raise ValidationError("chunk_size должен быть > 0")

        self._chunk_size = min(chunk_size, _MAX_GET_IDS)
        self._report_timeout = report_timeout
        self._bucket = TokenBucket(rate=self._settings.rate_limit_rps)
        self._session = session or requests.Session()
        self._session_owned = session is None
        self._lock = threading.Lock()
        self._closed = False

        self._session.headers.update(
            {
                "Authorization": f"Bearer {self._settings.token}",
                "Content-Type": "application/json; charset=utf-8",
                "Client-Login": self._settings.client_login,
                "User-Agent": USER_AGENT,
            }
        )

    # -------- context manager --------
    def __enter__(self) -> "YandexDirectClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Закрыть внутреннюю сессию (если она своя)."""
        if self._closed:
            return
        self._closed = True
        if self._session_owned:
            self._session.close()

    # -------- properties --------
    @property
    def readonly(self) -> bool:
        return self._settings.readonly

    @property
    def client_login(self) -> str:
        login = self._settings.client_login
        if login is None:  # pragma: no cover — уже проверено в __init__
            raise ValidationError("client_login не задан")
        return login

    @property
    def api_url(self) -> str:
        return self._settings.api_url.rstrip("/")

    # -------- internals --------
    def _ensure_writable(self, method_name: str) -> None:
        if self._settings.readonly:
            raise ValidationError(
                f"Метод {method_name} запрещён в readonly-режиме"
            )

    def _post(
        self,
        service: str,
        payload: Dict[str, Any],
        *,
        report: bool = False,
    ) -> requests.Response:
        url = f"{self.api_url}/{service}/"
        body_bytes = len(str(payload)) if logger.isEnabledFor(logging.DEBUG) else 0
        if body_bytes:
            logger.debug("POST %s payload_len=%d", url, body_bytes)

        def _do() -> requests.Response:
            with self._lock:
                return self._session.post(
                    url,
                    json=payload,
                    timeout=self._settings.timeout,
                )

        return request_with_retry(
            _do,
            max_retries=self._settings.max_retries,
            bucket=self._bucket,
            report=report,
            report_timeout=self._report_timeout,
        )

    @staticmethod
    def _check_body_errors(resp: requests.Response) -> Dict[str, Any]:
        """Проверить JSON-ответ на error-блок и вернуть result (или {})."""
        try:
            data: Dict[str, Any] = resp.json()
        except ValueError as e:
            raise ApiError(
                f"API вернул не-JSON: {resp.text[:200]}",
                status_code=resp.status_code,
                response_body=resp.text,
            ) from e

        if "error" in data:
            err = data["error"] or {}
            raise ApiError(
                f"API error: {err.get('error_string') or err.get('error_code')}",
                error_code=str(err.get("error_code")) if err.get("error_code") else None,
                details=err.get("details"),
                status_code=resp.status_code,
                response_body=data,
            )
        result = data.get("result") or {}
        if isinstance(result, dict) and result.get("status") == "ERROR":
            raise ApiError(
                "API вернул status=ERROR в result",
                status_code=resp.status_code,
                response_body=data,
            )
        return result

    # -------- campaigns --------
    def get_campaigns(
        self,
        *,
        statuses: Optional[Sequence[str]] = None,
    ) -> List[Campaign]:
        """Список кампаний клиента.

        :param statuses: опциональная фильтрация по `Status`
            (например, `["DRAFT", "READY", "CONVERTED", "ENDED"]`).
        """
        criteria: Dict[str, Any] = {}
        if statuses:
            criteria["Statuses"] = list(statuses)
        payload = {
            "method": "get",
            "params": {
                "SelectionCriteria": criteria,
                "FieldNames": [
                    "Id",
                    "Name",
                    "Status",
                    "State",
                    "StartDate",
                    "EndDate",
                ],
            },
        }
        resp = self._post("campaigns", payload)
        result = self._check_body_errors(resp)
        raw = result.get("Campaigns") or []
        return [Campaign.from_dict(c) for c in raw]

    # -------- ads --------
    def get_ads(
        self,
        *,
        ad_ids: Optional[Sequence[int]] = None,
        campaign_ids: Optional[Sequence[int]] = None,
        include_text: bool = False,
    ) -> List[Ad]:
        """Список объявлений. Авто-чанкинг больших списков Ids/CampaignIds.

        :param ad_ids: фильтр по ID объявлений.
        :param campaign_ids: фильтр по ID кампаний.
        :param include_text: подтянуть `TextAd` (Title/Text/Href).
        """
        if not ad_ids and not campaign_ids:
            raise ValidationError(
                "get_ads требует ad_ids или campaign_ids (минимум один)"
            )

        field_names = ["Id", "CampaignId", "AdGroupId", "Status", "State", "Type"]
        if include_text:
            field_names.append("TextAd")

        results: List[Ad] = []
        if ad_ids:
            ids = list(ad_ids)
            for chunk in _chunked(ids, self._chunk_size):
                params: Dict[str, Any] = {
                    "SelectionCriteria": {"Ids": list(chunk)},
                    "FieldNames": field_names,
                }
                if include_text:
                    params["TextAdFieldNames"] = ["Title", "Text", "Href"]
                payload: Dict[str, Any] = {"method": "get", "params": params}
                resp = self._post("ads", payload)
                result = self._check_body_errors(resp)
                for raw in result.get("Ads") or []:
                    results.append(Ad.from_dict(raw))
            return results

        # по campaign_ids
        ids = list(campaign_ids or [])
        for chunk in _chunked(ids, self._chunk_size):
            params = {
                "SelectionCriteria": {"CampaignIds": list(chunk)},
                "FieldNames": field_names,
            }
            if include_text:
                params["TextAdFieldNames"] = ["Title", "Text", "Href"]
            payload = {"method": "get", "params": params}
            resp = self._post("ads", payload)
            result = self._check_body_errors(resp)
            for raw in result.get("Ads") or []:
                results.append(Ad.from_dict(raw))
        return results

    def get_ads_text_batch(
        self, ad_ids: Sequence[int]
    ) -> Dict[int, AdTextEntry]:
        """Пакетно получить Title/Text/Href для списка объявлений.

        :return: словарь `{ad_id: AdTextEntry}`.
        """
        ids = list(ad_ids)
        out: Dict[int, AdTextEntry] = {}
        for chunk in _chunked(ids, self._chunk_size):
            payload = {
                "method": "get",
                "params": {
                    "SelectionCriteria": {"Ids": list(chunk)},
                    "FieldNames": ["Id", "Type"],
                    "TextAdFieldNames": ["Title", "Text", "Href"],
                },
            }
            resp = self._post("ads", payload)
            result = self._check_body_errors(resp)
            for raw in result.get("Ads") or []:
                entry = AdTextEntry.from_dict(raw)
                out[entry.id] = entry
        return out

    # -------- stats --------
    def get_stats(
        self,
        *,
        ad_ids: Optional[Sequence[int]] = None,
        period_days: int = 30,
        date_from: Optional[_dt.date] = None,
        date_to: Optional[_dt.date] = None,
        report_name: Optional[str] = None,
    ) -> List[StatRow]:
        """Статистика по объявлениям через Reports API (AD_PERFORMANCE_REPORT).

        :param ad_ids: фильтр; если None — все объявления клиента.
        :param period_days: период в днях, если date_from/date_to не заданы.
        :param date_from: явная дата начала (включительно).
        :param date_to: явная дата конца (включительно).
        :param report_name: имя отчёта (по умолчанию автогенерируемое).
        :return: агрегированные строки `StatRow` (по одной на AdId).
        """
        if date_from is None or date_to is None:
            today = _dt.date.today()
            date_to = date_to or today
            date_from = date_from or (date_to - _dt.timedelta(days=period_days))

        criteria: Dict[str, Any] = {
            "DateFrom": date_from.isoformat(),
            "DateTo": date_to.isoformat(),
        }
        if ad_ids:
            criteria["AdIds"] = [str(a) for a in ad_ids]

        payload = {
            "method": "build",
            "params": {
                "SelectionCriteria": criteria,
                "FieldNames": [
                    "AdId",
                    "Impressions",
                    "Clicks",
                    "Ctr",
                    "Cost",
                    "BounceRate",
                    "Bounces",
                ],
                "ReportName": (
                    report_name
                    or f"yandex-direct-api-client {datetime_now_str()}"
                ),
                "ReportType": "AD_PERFORMANCE_REPORT",
                "DateRangeType": "CUSTOM_DATE",
                "Format": "TSV",
                "IncludeVAT": "NO",
                "IncludeDiscount": "NO",
            },
        }

        resp = self._post("reports", payload, report=True)
        return parse_stats_tsv(resp.text)

    # -------- mutations --------
    def update_ad(
        self,
        ad_id: int,
        headline: str,
        body: str,
        *,
        href: Optional[str] = None,
        auto_clamp: bool = True,
    ) -> Dict[str, Any]:
        """Обновить Title/Text (и опционально Href) текстового объявления.

        :param auto_clamp: обрезать строки до лимитов Директа (56 / 81).
        :return: первый элемент `UpdateResults` из ответа API.
        """
        self._ensure_writable("update_ad")
        if auto_clamp:
            headline = _clamp_text(headline, _TITLE_LIMIT)
            body = _clamp_text(body, _TEXT_LIMIT)
        else:
            if len(headline) > _TITLE_LIMIT:
                raise ValidationError(
                    f"headline длиннее {_TITLE_LIMIT} символов (auto_clamp=False)"
                )
            if len(body) > _TEXT_LIMIT:
                raise ValidationError(
                    f"body длиннее {_TEXT_LIMIT} символов (auto_clamp=False)"
                )

        text_ad: Dict[str, Any] = {"Title": headline, "Text": body}
        if href is not None:
            text_ad["Href"] = href

        payload = {
            "method": "update",
            "params": {
                "Ads": [{"Id": int(ad_id), "TextAd": text_ad}],
            },
        }
        resp = self._post("ads", payload)
        result = self._check_body_errors(resp)
        results = result.get("UpdateResults") or []
        if not results:
            raise ApiError(
                "Пустой UpdateResults в ответе API",
                status_code=resp.status_code,
                response_body=result,
            )
        first: Dict[str, Any] = results[0]
        errors = first.get("Errors") or []
        if errors:
            raise ApiError(
                f"Ошибка обновления ad_id={ad_id}: "
                f"{errors[0].get('Message') or errors[0].get('Code')}",
                details=errors,
                status_code=resp.status_code,
                response_body=result,
            )
        return first

    def add_campaign(self, payload_campaign: Dict[str, Any]) -> Dict[str, Any]:
        """Создать кампанию.

        :param payload_campaign: тело одной кампании по схеме `campaigns/add`.
        :return: первый элемент `AddResults`.
        """
        self._ensure_writable("add_campaign")
        payload = {"method": "add", "params": {"Campaigns": [payload_campaign]}}
        resp = self._post("campaigns", payload)
        result = self._check_body_errors(resp)
        results = result.get("AddResults") or []
        if not results:
            raise ApiError(
                "Пустой AddResults в ответе API",
                status_code=resp.status_code,
                response_body=result,
            )
        first: Dict[str, Any] = results[0]
        errors = first.get("Errors") or []
        if errors:
            raise ApiError(
                f"Ошибка добавления кампании: "
                f"{errors[0].get('Message') or errors[0].get('Code')}",
                details=errors,
                status_code=resp.status_code,
                response_body=result,
            )
        return first

    def delete_ad(self, ad_ids: Sequence[int]) -> List[Dict[str, Any]]:
        """Удалить объявления по ID (авто-чанкинг по 200).

        :return: список элементов `DeleteResults`.
        """
        self._ensure_writable("delete_ad")
        ids = list(ad_ids)
        if not ids:
            return []
        mutate_chunk = min(self._chunk_size, _MAX_MUTATE_IDS)
        results: List[Dict[str, Any]] = []
        for chunk in _chunked(ids, mutate_chunk):
            payload = {"method": "delete", "params": {"Ids": list(chunk)}}
            resp = self._post("ads", payload)
            result = self._check_body_errors(resp)
            for item in result.get("DeleteResults") or []:
                errors = item.get("Errors") or []
                if errors:
                    raise ApiError(
                        f"Ошибка удаления ad_id={item.get('Id')}: "
                        f"{errors[0].get('Message') or errors[0].get('Code')}",
                        details=errors,
                        status_code=resp.status_code,
                        response_body=result,
                    )
                results.append(item)
        return results


def datetime_now_str() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def parse_stats_tsv(text: str) -> List[StatRow]:
    """Распарсить TSV-отчёт AD_PERFORMANCE_REPORT, агрегируя по AdId.

    Поддерживает произвольный порядок колонок — индексы берутся из
    строки-заголовка. Строки `Total...` пропускаются.
    """
    lines = text.splitlines()
    header_idx: Optional[int] = None
    for i, line in enumerate(lines):
        if "AdId" in line and "Impressions" in line:
            header_idx = i
            break
    if header_idx is None:
        return []

    header = lines[header_idx].split("	")

    aggregated: Dict[int, StatRow] = {}
    for line in lines[header_idx + 1 :]:
        if not line.strip() or line.startswith("Total"):
            continue
        parts = line.split("	")
        row = StatRow.from_tsv_row_by_header(parts, header)
        if row is None:
            continue
        prev = aggregated.get(row.ad_id)
        aggregated[row.ad_id] = prev.merged_with(row) if prev else row
    return list(aggregated.values())


__all__ = ["YandexDirectClient", "parse_stats_tsv"]
