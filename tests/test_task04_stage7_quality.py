"""Тесты этапа 7 STAGE_05, часть 2: OAuth и сервисные ветки (tasks/task04.md, §9).

Продолжение `tests/test_task04_stage7.py`: закрываются непокрытые ветви
`auth` (OAuth-хелперы), а также «прочитанные, но не проверенные» пути
`ad_extensions`, `audience_targets` и `retargeting_conditions`.

Особенность OAuth: реальные обращения к `oauth.yandex.ru` недопустимы
(AGENTS.md §5), поэтому сетевой слой подменяется, а HTTP-обработчик
callback проверяется вызовом `do_GET` напрямую — без сокетов.
"""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from decimal import Decimal
from typing import Any, Dict, List

import pytest
import responses

from yandex_direct_api_client import YandexDirectClient
from yandex_direct_api_client import auth as auth_module
from yandex_direct_api_client.exceptions import ApiError, AuthError, ValidationError
from yandex_direct_api_client.models.ad import (
    RESPONSIVE_AD_EXTENSIONS_MAX,
    RESPONSIVE_DISPLAY_URL_PATH_MAX,
    AdText,
    BannerAd,
    CpmBannerAdBuilderAd,
    ImageAdRef,
    ResponsiveAd,
)

V5 = "https://api.direct.yandex.com/json/v5"
UNIFIED = "https://api.direct.yandex.com/json/v501"
SITELINKS_URL = f"{V5}/sitelinks/"
ADEXTENSIONS_URL = f"{V5}/adextensions/"
AUDIENCE_URL = f"{V5}/audiencetargets/"
CAMPAIGNS_URL = f"{V5}/campaigns/"
UNIFIED_URL = f"{UNIFIED}/campaigns/"
TOKEN_URL = auth_module.OAUTH_TOKEN_URL


class _FakeResponse:
    """Минимальный контекстный менеджер вместо `urlopen`."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def read(self) -> bytes:
        """Вернуть подготовленные байты ответа."""
        return self._payload


def _token_json(**extra: Any) -> bytes:
    """Тело успешного ответа OAuth."""
    data: Dict[str, Any] = {
        "access_token": "t1.token-value",
        "refresh_token": "y0_refresh-value",
        "expires_in": 43200,
    }
    data.update(extra)
    return json.dumps(data).encode("utf-8")


def _client() -> YandexDirectClient:
    """Клиент с тестовыми настройками."""
    return YandexDirectClient(token="t", rate_limit_rps=1000.0, max_retries=1)


# ---------------- OAuth: refresh_token ----------------


def test_refresh_token_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Успешный обмен refresh-токена: возвращается модель `TokenResponse`."""
    seen: Dict[str, Any] = {}

    def fake_urlopen(request: urllib.request.Request, timeout: float) -> _FakeResponse:
        seen["body"] = request.data.decode("utf-8")
        seen["timeout"] = timeout
        return _FakeResponse(_token_json())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    token = auth_module.refresh_token("cid", "secret", "y0_refresh")

    assert token.access_token == "t1.token-value"
    assert token.refresh_token == "y0_refresh-value"
    assert "grant_type=refresh_token" in seen["body"]
    assert "client_secret=secret" in seen["body"]


def test_refresh_token_requires_arguments() -> None:
    """Пустые аргументы отвергаются до сети."""
    with pytest.raises(AuthError, match="требует"):
        auth_module.refresh_token("", "secret", "y0_refresh")
    with pytest.raises(AuthError, match="требует"):
        auth_module.refresh_token("cid", "", "y0_refresh")
    with pytest.raises(AuthError, match="требует"):
        auth_module.refresh_token("cid", "secret", "")


def test_refresh_token_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP-ошибка Яндекса превращается в `AuthError` с кодом."""
    def fake_urlopen(request: Any, timeout: float) -> Any:
        raise urllib.error.HTTPError(
            TOKEN_URL, 401, "Unauthorized", {}, io.BytesIO(b"invalid_client")
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(AuthError) as info:
        auth_module.refresh_token("cid", "secret", "y0_refresh")
    assert info.value.status_code == 401
    assert "invalid_client" in str(info.value)


def test_refresh_token_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сетевая ошибка даёт `AuthError` с причиной."""
    def fake_urlopen(request: Any, timeout: float) -> Any:
        raise urllib.error.URLError("таймаут")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(AuthError, match="Сетевая ошибка"):
        auth_module.refresh_token("cid", "secret", "y0_refresh")


def test_refresh_token_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """Не-JSON ответ не превращается в «пустой токен»."""
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda request, timeout: _FakeResponse(b"<html>")
    )
    with pytest.raises(AuthError, match="не-JSON"):
        auth_module.refresh_token("cid", "secret", "y0_refresh")


def test_refresh_token_without_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ответ без `access_token` — ошибка, а не токен с None."""
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout: _FakeResponse(b'{"error": "bad"}'),
    )
    with pytest.raises(AuthError, match="нет access_token"):
        auth_module.refresh_token("cid", "secret", "y0_refresh")


# ---------------- OAuth: обмен code ----------------


def test_exchange_code_for_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Code-flow обменивает код на токен с `redirect_uri`."""
    seen: Dict[str, Any] = {}

    def fake_urlopen(request: urllib.request.Request, timeout: float) -> _FakeResponse:
        seen["body"] = request.data.decode("utf-8")
        return _FakeResponse(_token_json())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    token = auth_module._exchange_code_for_token(
        "cid", "secret", "the-code", "http://localhost:8888/callback"
    )
    assert token.access_token == "t1.token-value"
    assert "grant_type=authorization_code" in seen["body"]
    assert "redirect_uri=" in seen["body"]


def test_get_new_token_requires_credentials() -> None:
    """Без `client_id`/`client_secret` code-flow не стартует."""
    with pytest.raises(AuthError, match="обязательны"):
        auth_module.get_new_token("", "secret", open_browser=False)
    with pytest.raises(AuthError, match="обязательны"):
        auth_module.get_new_token("cid", "", open_browser=False)


def _play_browser(path_query: str, port: int) -> None:
    """Сыграть роль браузера: вернуть callback на локальный сервер.

    :param path_query: query-строка callback (`?code=...&state=...`).
    :param port: порт запущенного callback-сервера.
    """
    import http.client

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", f"/callback{path_query}")
        conn.getresponse().read()
    finally:
        conn.close()


def _play_browser_async(path_query: str, port: int) -> None:
    """Запустить «браузер» в фоне: callback не должен блокировать вызов.

    `get_new_token` открывает браузер до старта потока обслуживания, поэтому
    синхронный HTTP-вызов внутри `webbrowser.open` взаимно блокируется.

    :param path_query: query-строка callback.
    :param port: порт callback-сервера.
    """
    import threading

    threading.Thread(
        target=_play_browser, args=(path_query, port), daemon=True
    ).start()


def test_get_new_token_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Полный сценарий code-flow: браузер возвращает code, клиент — токен."""
    import urllib.parse

    seen: Dict[str, Any] = {}

    def fake_urlopen(request: urllib.request.Request, timeout: float) -> _FakeResponse:
        seen["body"] = request.data.decode("utf-8")
        return _FakeResponse(_token_json())

    def fake_open(url: str) -> bool:
        """Открыть «браузер»: сразу вернуть code с корректным state."""
        state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
        _play_browser_async(f"?code=the-code&state={state}", port)
        return True

    port = auth_module._find_free_port(19000)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(auth_module.webbrowser, "open", fake_open)

    token = auth_module.get_new_token("cid", "secret", port=port, timeout=10)

    assert token.access_token == "t1.token-value"
    assert token.refresh_token == "y0_refresh-value"
    assert "grant_type=authorization_code" in seen["body"]
    assert "code=the-code" in seen["body"]


def test_get_new_token_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если callback не пришёл за отведённое время — понятная ошибка."""
    port = auth_module._find_free_port(19500)
    with pytest.raises(AuthError, match="Таймаут"):
        auth_module.get_new_token(
            "cid", "secret", port=port, open_browser=False, timeout=0.5
        )


def test_get_new_token_rejects_state_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Чужой `state` в callback отвергается как возможная CSRF-атака."""
    port = auth_module._find_free_port(19100)

    def fake_open(url: str) -> bool:
        """Вернуть code с подделанным state."""
        _play_browser_async("?code=the-code&state=forged", port)
        return True

    monkeypatch.setattr(auth_module.webbrowser, "open", fake_open)
    with pytest.raises(AuthError, match="state"):
        auth_module.get_new_token("cid", "secret", port=port, timeout=10)


def test_get_new_token_reports_oauth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ошибка Яндекса в callback доходит до пользователя как `AuthError`."""
    port = auth_module._find_free_port(19300)

    def fake_open(url: str) -> bool:
        """Вернуть ошибку `access_denied` вместо кода."""
        _play_browser_async("?error=access_denied", port)
        return True

    monkeypatch.setattr(auth_module.webbrowser, "open", fake_open)
    with pytest.raises(AuthError, match="access_denied"):
        auth_module.get_new_token("cid", "secret", port=port, timeout=10)


def test_get_new_token_survives_browser_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если браузер не открылся, код всё равно можно ввести вручную."""
    port = auth_module._find_free_port(19200)

    def broken_open(url: str) -> bool:
        """Имитировать сбой открытия браузера."""
        raise RuntimeError("нет GUI")

    monkeypatch.setattr(auth_module.webbrowser, "open", broken_open)
    with pytest.raises(AuthError, match="Таймаут"):
        auth_module.get_new_token(
            "cid", "secret", port=port, open_browser=True, timeout=1
        )


# ---------------- OAuth: обработчик callback ----------------


def _run_handler(path: str) -> auth_module._CodeCapture:
    """Вызвать `do_GET` обработчика callback без сокетов.

    :param path: путь с query-строкой, как его прислал бы браузер.
    :return: заполненный объект захвата кода.
    """
    capture = auth_module._CodeCapture()
    handler_cls = type("_Bound", (auth_module._CallbackHandler,), {"capture": capture})
    handler = handler_cls.__new__(handler_cls)
    handler.path = path
    handler.wfile = io.BytesIO()
    handler.send_response = lambda *args, **kwargs: None
    handler.send_header = lambda *args, **kwargs: None
    handler.end_headers = lambda: None
    handler.do_GET()
    return capture


def test_callback_handler_captures_code() -> None:
    """Успешный callback сохраняет `code` и `state`."""
    capture = _run_handler("/callback?code=abc123&state=xyz")
    assert capture.code == "abc123"
    assert capture.state == "xyz"
    assert capture.error is None


def test_callback_handler_captures_error() -> None:
    """Ошибка OAuth сохраняется и попадает в сообщение пользователю."""
    capture = _run_handler("/callback?error=access_denied")
    assert capture.code is None
    assert capture.error == "access_denied"


def test_callback_handler_without_params() -> None:
    """Callback без параметров — понятная ошибка, а не зависание."""
    capture = _run_handler("/callback")
    assert capture.error == "no_code_in_callback"


def test_callback_handler_suppresses_access_log() -> None:
    """Стандартный лог http.server подавлен — иначе callback шумит в stderr."""
    handler_cls = auth_module._CallbackHandler
    assert handler_cls.log_message(handler_cls, "%s", "x") is None


def test_find_free_port_returns_bindable_port() -> None:
    """Подобранный порт действительно свободен."""
    port = auth_module._find_free_port(19700)
    assert port >= 19700
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))


def test_find_free_port_raises_when_exhausted() -> None:
    """Если все 20 портов заняты — `OSError`, а не бесконечный цикл."""
    import socket

    holders: List[socket.socket] = []
    try:
        for offset in range(20):
            busy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            busy.bind(("127.0.0.1", 19900 + offset))
            busy.listen(1)
            holders.append(busy)
        with pytest.raises(OSError, match="свободный порт"):
            auth_module._find_free_port(19900)
    finally:
        for busy in holders:
            busy.close()


# ---------------- OAuth: CLI ----------------


def test_cli_refresh_success(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """CLI печатает токены и возвращает 0."""
    monkeypatch.setattr(
        auth_module,
        "refresh_token",
        lambda *args, **kwargs: auth_module.TokenResponse.from_dict(
            {
                "access_token": "t1.value",
                "refresh_token": "y0.value",
                "expires_in": 3600,
            }
        ),
    )
    code = auth_module.run_cli(
        ["refresh", "--client-id", "cid", "--client-secret", "s", "--refresh-token", "r"]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "t1.value" in out
    assert "y0.value" in out
    assert "3600" in out


def test_cli_reports_auth_error(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Ошибка авторизации печатается в stderr, код возврата — 1."""

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AuthError("не получилось")

    monkeypatch.setattr(auth_module, "refresh_token", boom)
    code = auth_module.run_cli(
        ["refresh", "--client-id", "cid", "--client-secret", "s", "--refresh-token", "r"]
    )
    assert code == 1
    assert "ОШИБКА" in capsys.readouterr().err


def test_cli_requires_subcommand() -> None:
    """Без подкоманды argparse завершает работу с кодом 2."""
    with pytest.raises(SystemExit) as info:
        auth_module._parse_args([])
    assert info.value.code == 2


# ---------------- сервисные ветки: ad_extensions ----------------


@responses.activate
def test_get_sitelinks_and_callouts_by_ids() -> None:
    """Чтение по ID возвращает типизированные модели."""
    responses.add(
        responses.POST,
        SITELINKS_URL,
        json={
            "result": {
                "SitelinksSets": [
                    {"Id": 1, "Name": "набор", "Sitelinks": [{"Id": 11}]}
                ]
            }
        },
    )
    responses.add(
        responses.POST,
        ADEXTENSIONS_URL,
        json={
            "result": {
                "AdExtensions": [
                    {"Id": 2, "Type": "CALLOUT", "Text": "уточнение"}
                ]
            }
        },
    )
    with _client() as client:
        sets = client.ad_extensions.get_sitelinks([1])
        callouts = client.ad_extensions.get_callouts([2])
    assert sets[0].id == 1
    assert callouts[0].id == 2


@responses.activate
def test_get_extensions_empty_ids_makes_no_request() -> None:
    """Пустой список ID не вызывает API."""
    mark = len(responses.calls)
    with _client() as client:
        assert client.ad_extensions.get_sitelinks([]) == []
        assert client.ad_extensions.get_callouts([]) == []
    assert len(responses.calls) == mark


@responses.activate
def test_get_extensions_chunks_large_id_list() -> None:
    """Списки ID больше лимита разбиваются на чанки."""
    for _ in range(3):
        responses.add(
            responses.POST, SITELINKS_URL, json={"result": {"SitelinksSets": []}}
        )
    with _client() as client:
        client.ad_extensions.get_sitelinks(list(range(1, 2501)))
    assert len(responses.calls) == 3
    for call in responses.calls:
        criteria = json.loads(call.request.body)["params"]["SelectionCriteria"]
        assert len(criteria["Ids"]) <= 1000


# ---------------- сервисные ветки: audience_targets ----------------


@responses.activate
def test_audience_targets_get_by_ids() -> None:
    """Чтение условий нацеливания по ID."""
    responses.add(
        responses.POST,
        AUDIENCE_URL,
        json={
            "result": {
                "AudienceTargets": [
                    {"Id": 5, "AdGroupId": 7, "RetargetingListId": 9, "State": "ACTIVE"}
                ]
            }
        },
    )
    with _client() as client:
        targets = client.audience_targets.get([5])
    assert targets[0].id == 5
    assert targets[0].retargeting_list_id == 9


@responses.activate
def test_audience_targets_get_empty_ids() -> None:
    """Пустой список ID — без сетевого вызова."""
    mark = len(responses.calls)
    with _client() as client:
        assert client.audience_targets.get([]) == []
    assert len(responses.calls) == mark


@responses.activate
def test_audience_targets_custom_field_names() -> None:
    """Кастомный `FieldNames` уходит в запрос как есть."""
    responses.add(responses.POST, AUDIENCE_URL, json={"result": {"AudienceTargets": []}})
    with _client() as client:
        client.audience_targets.get([1], field_names=["Id", "State"])
    body = json.loads(responses.calls[0].request.body)
    assert body["params"]["FieldNames"] == ["Id", "State"]


# ---------------- сервисные ветки: retargeting_conditions ----------------


@responses.activate
def test_retargeting_conditions_get_by_ids() -> None:
    """Условия ретаргетинга читаются из `audiencetargets`."""
    responses.add(
        responses.POST,
        AUDIENCE_URL,
        json={
            "result": {
                "AudienceTargets": [
                    {"Id": 3, "AdGroupId": 4, "RetargetingListId": 6, "State": "ACTIVE"}
                ]
            }
        },
    )
    with _client() as client:
        conditions = client.retargeting_conditions.get([3])
    assert conditions[0].id == 3


@responses.activate
def test_retargeting_conditions_get_empty_ids() -> None:
    """Пустой список ID — без сетевого вызова."""
    mark = len(responses.calls)
    with _client() as client:
        assert client.retargeting_conditions.get([]) == []
    assert len(responses.calls) == mark


@responses.activate
def test_retargeting_conditions_create_roundtrip() -> None:
    """Создание условия уходит в `audiencetargets/add` и возвращает AddResults."""
    responses.add(
        responses.POST,
        AUDIENCE_URL,
        json={"result": {"AddResults": [{"Id": 77}]}},
    )
    with _client() as client:
        results = client.retargeting_conditions.create(
            [{"AdGroupId": 4, "RetargetingListId": 6}]
        )
    assert _ids_of(results) == [77]
    body = json.loads(responses.calls[0].request.body)
    assert body["params"]["AudienceTargets"] == [
        {"AdGroupId": 4, "RetargetingListId": 6}
    ]


@responses.activate
def test_retargeting_conditions_delete_collects_errors() -> None:
    """Частичный сбой в `audiencetargets/delete` собирается в `BatchResult`."""
    responses.add(
        responses.POST,
        AUDIENCE_URL,
        json={
            "result": {
                "DeleteResults": [
                    {"Id": 3},
                        {
                            "Errors": [
                                {
                                    "Code": "OBJECT_NOT_FOUND",
                                    "Message": "Нет такого ID",
                                }
                            ]
                        },
                    ]
            }
        },
    )
    with _client() as client:
        batch = client.retargeting_conditions.delete(
            [3, 999], confirm=True, on_item_error="collect"
        )
    assert _ids_of(batch.succeeded) == [3]
    assert len(batch.failed) == 1
    assert batch.failed[0].object_id is None
    assert batch.failed[0].code == "OBJECT_NOT_FOUND"


def _ids_of(results: List[Dict[str, Any]]) -> List[int]:
    """Достать ID из результатов batch-операции."""
    return [int(item["Id"]) for item in results]


# ---------------- campaigns: фильтры и пустые ответы ----------------


@responses.activate
def test_campaigns_list_passes_state_and_status_filters() -> None:
    """`states` и `statuses` попадают в `SelectionCriteria` кампаний."""
    responses.add(
        responses.POST, CAMPAIGNS_URL, json={"result": {"Campaigns": []}}
    )
    with _client() as client:
        assert client.campaigns.list(states=["ON"], statuses=["DRAFT"]) == []
    body = json.loads(responses.calls[0].request.body)
    assert body["params"]["SelectionCriteria"] == {
        "States": ["ON"],
        "Statuses": ["DRAFT"],
    }


@responses.activate
def test_campaigns_create_collect_returns_batch_result() -> None:
    """`create` в режиме `collect` отдаёт `BatchResult`, а не первый элемент."""
    responses.add(
        responses.POST,
        CAMPAIGNS_URL,
        json={
            "result": {
                "AddResults": [
                    {"Id": 1},
                    {"Errors": [{"Code": "ACTION_REFUSED", "Message": "нет"}]},
                ]
            }
        },
    )
    with _client() as client:
        batch = client.campaigns.create(
            {"Name": "a"}, on_item_error="collect"
        )
    assert _ids_of(batch.succeeded) == [1]
    assert batch.failed[0].code == "ACTION_REFUSED"


@responses.activate
def test_campaigns_update_collect_and_empty_results() -> None:
    """`update` собирает ошибки элементов и жалуется на пустой UpdateResults."""
    responses.add(
        responses.POST,
        CAMPAIGNS_URL,
        json={"result": {"UpdateResults": [{"Errors": [{"Message": "нет"}]}]}},
    )
    with _client() as client:
        batch = client.campaigns.update(
            {"Id": 1, "Name": "a"}, on_item_error="collect"
        )
    assert batch.succeeded == []
    assert len(batch.failed) == 1

    responses.reset()
    responses.add(responses.POST, CAMPAIGNS_URL, json={"result": {}})
    with _client() as client:
        with pytest.raises(ApiError, match="Пустой UpdateResults"):
            client.campaigns.update({"Id": 1, "Name": "a"})


@responses.activate
def test_campaigns_create_rejects_empty_add_results() -> None:
    """Пустой AddResults — явная ошибка, а None вместо ID."""
    responses.add(responses.POST, CAMPAIGNS_URL, json={"result": {}})
    with _client() as client:
        with pytest.raises(ApiError, match="Пустой AddResults"):
            client.campaigns.create({"Name": "a"})


def test_campaigns_state_methods_accept_empty_ids() -> None:
    """Массовые операции без ID не ходят в сеть."""
    with _client() as client:
        assert client.campaigns.suspend([]) == []
        assert client.campaigns.delete([], confirm=True) == []


# ---------------- campaigns: бюджеты и стратегии ----------------


@responses.activate
def test_get_budgets_falls_back_to_v501_for_unified() -> None:
    """ЕПК-кампании читаются вторым проходом по v501."""
    responses.add(
        responses.POST,
        CAMPAIGNS_URL,
        json={
            "result": {
                "Campaigns": [
                    {
                        "Id": 1,
                        "Type": "CPM_BANNER_CAMPAIGN",
                        "CpmBannerCampaign": {
                            "BiddingStrategy": {
                                "Network": {
                                    "BiddingStrategyType": "MANUAL_CPM",
                                    "ManualCpm": {"WeeklySpendLimit": 1000000},
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
        UNIFIED_URL,
        json={
            "result": {
                "Campaigns": [
                    {
                        "Id": 2,
                        "Type": "UNIFIED_CAMPAIGN",
                        "UnifiedCampaign": {
                            "BiddingStrategy": {
                                "Search": {
                                    "BiddingStrategyType": "MAX_CLICKS",
                                    "WeeklySpendLimit": 2000000,
                                }
                            }
                        },
                    }
                ]
            }
        },
    )
    with _client() as client:
        budgets = client.campaigns.get_budgets([1, 2])
    assert [b.campaign_id for b in budgets] == [1, 2]
    second = json.loads(responses.calls[1].request.body)
    assert second["params"]["SelectionCriteria"]["Ids"] == [2]


def test_get_budgets_empty_ids() -> None:
    """Пустой список ID не вызывает API."""
    with _client() as client:
        assert client.campaigns.get_budgets([]) == []


def test_budget_mutations_accept_empty_ids() -> None:
    """Денежные методы с пустым списком ID — no-op без подтверждения."""
    with _client() as client:
        assert client.campaigns.set_weekly_budget([], "100", confirm=True) == []
        assert client.campaigns.set_daily_budget([], "10", confirm=True) == []
        assert client.campaigns.set_bid_strategy([], {"Search": {}}, confirm=True) == []


@responses.activate
def test_set_weekly_budget_skips_verify() -> None:
    """`verify=False` не делает повторное чтение после обновления."""
    responses.add(
        responses.POST,
        CAMPAIGNS_URL,
        json={
            "result": {
                "Campaigns": [
                    {
                        "Id": 1,
                        "Type": "CPM_BANNER_CAMPAIGN",
                        "CpmBannerCampaign": {
                            "BiddingStrategy": {
                                "Network": {
                                    "BiddingStrategyType": "MANUAL_CPM",
                                    "ManualCpm": {"WeeklySpendLimit": 1000000},
                                }
                            }
                        },
                    }
                ]
            }
        },
    )
    responses.add(
        responses.POST, CAMPAIGNS_URL, json={"result": {"UpdateResults": [{"Id": 1}]}}
    )
    with _client() as client:
        budgets = client.campaigns.set_weekly_budget(
            [1], "500", confirm=True, verify=False
        )
    assert len(responses.calls) == 2
    body = json.loads(responses.calls[1].request.body)
    network = body["params"]["Campaigns"][0]["CpmBannerCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network["ManualCpm"]["WeeklySpendLimit"] == 500000000
    assert budgets[0].weekly == Decimal("1.000000")


@responses.activate
def test_set_weekly_budget_routes_average_cpc_to_v501() -> None:
    """Кампания `AVERAGE_CPC` обновляется через v501 и `UnifiedCampaign`."""
    responses.add(
        responses.POST,
        CAMPAIGNS_URL,
        json={
            "result": {
                "Campaigns": [
                    {
                        "Id": 1,
                        "Type": "UNIFIED_CAMPAIGN",
                        "UnifiedCampaign": {
                            "BiddingStrategy": {
                                "Search": {
                                    "BiddingStrategyType": "AVERAGE_CPC",
                                    "WeeklySpendLimit": 1000000,
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
        UNIFIED_URL,
        json={
            "result": {
                "Campaigns": [
                    {
                        "Id": 1,
                        "Type": "UNIFIED_CAMPAIGN",
                        "UnifiedCampaign": {
                            "BiddingStrategy": {
                                "Search": {
                                    "BiddingStrategyType": "AVERAGE_CPC",
                                    "WeeklySpendLimit": 5000000,
                                }
                            }
                        },
                    }
                ]
            }
        },
    )
    with _client() as client:
        budgets = client.campaigns.set_weekly_budget(
            [1], "500", confirm=True, verify=False
        )
    body = json.loads(responses.calls[-1].request.body)
    campaign = body["params"]["Campaigns"][0]
    assert campaign["UnifiedCampaign"]["BiddingStrategy"]["Search"][
        "BiddingStrategyType"
    ] == "AVERAGE_CPC"
    assert budgets[0].strategy == "AVERAGE_CPC"


@responses.activate
def test_set_daily_budget_and_mismatch() -> None:
    """Дневной бюджет пишется в `DailyBudget`, несовпадение — `ApiError`."""
    def _daily_result(amount: int) -> Dict[str, Any]:
        return {
            "result": {
                "Campaigns": [
                    {
                        "Id": 1,
                        "Type": "CPM_BANNER_CAMPAIGN",
                        "DailyBudget": {"Amount": amount},
                    }
                ]
            }
        }

    responses.add(
        responses.POST, CAMPAIGNS_URL, json={"result": {"UpdateResults": [{"Id": 1}]}}
    )
    responses.add(responses.POST, CAMPAIGNS_URL, json=_daily_result(1000000))
    with _client() as client:
        budgets = client.campaigns.set_daily_budget(
            [1], "10", confirm=True, verify=False
        )
    body = json.loads(responses.calls[0].request.body)
    assert body["params"]["Campaigns"][0]["DailyBudget"]["Amount"] == 10000000
    assert budgets[0].daily == Decimal("1.000000")

    responses.reset()
    responses.add(
        responses.POST, CAMPAIGNS_URL, json={"result": {"UpdateResults": [{"Id": 1}]}}
    )
    responses.add(responses.POST, CAMPAIGNS_URL, json=_daily_result(1000000))
    with _client() as client:
        with pytest.raises(ApiError, match="не совпал"):
            client.campaigns.set_daily_budget([1], "10", confirm=True)


@responses.activate
def test_set_bid_strategy_without_verify() -> None:
    """`set_bid_strategy` пишет стратегию на v501 и перечитывает бюджет."""
    def _unified_result() -> Dict[str, Any]:
        return {
            "result": {
                "Campaigns": [
                    {
                        "Id": 1,
                        "Type": "UNIFIED_CAMPAIGN",
                        "UnifiedCampaign": {
                            "BiddingStrategy": {
                                "Search": {
                                    "BiddingStrategyType": "MAX_CLICKS",
                                    "WeeklySpendLimit": 7000000,
                                }
                            }
                        },
                    }
                ]
            }
        }

    responses.add(
        responses.POST,
        UNIFIED_URL,
        json={"result": {"UpdateResults": [{"Id": 1}]}},
    )
    responses.add(responses.POST, CAMPAIGNS_URL, json={"result": {"Campaigns": []}})
    responses.add(responses.POST, UNIFIED_URL, json=_unified_result())
    with _client() as client:
        budgets = client.campaigns.set_bid_strategy(
            [1], {"Search": {"BiddingStrategyType": "MAX_CLICKS"}},
            weekly_budget="700",
            confirm=True,
        )
    body = json.loads(responses.calls[0].request.body)
    search = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search["WeeklySpendLimit"] == 700000000
    assert budgets[0].weekly == Decimal("7.000000")


# ---------------- campaigns: ЕПК-методы ----------------


@responses.activate
def test_create_and_update_unified_edge_paths() -> None:
    """Пустые `AddResults`/`UpdateResults` и режим `collect` на v501."""
    responses.add(responses.POST, UNIFIED_URL, json={"result": {}})
    with _client() as client:
        with pytest.raises(ApiError, match="Пустой AddResults"):
            client.campaigns.create_unified({"Name": "epk"})

    responses.reset()
    responses.add(responses.POST, UNIFIED_URL, json={"result": {}})
    with _client() as client:
        with pytest.raises(ApiError, match="Пустой UpdateResults"):
            client.campaigns.update_unified({"Id": 1, "Name": "epk"})

    responses.reset()
    responses.add(
        responses.POST,
        UNIFIED_URL,
        json={"result": {"AddResults": [{"Errors": [{"Message": "нет"}]}]}},
    )
    with _client() as client:
        batch = client.campaigns.create_unified(
            {"Name": "epk"}, on_item_error="collect"
        )
    assert len(batch.failed) == 1

    responses.reset()
    responses.add(
        responses.POST,
        UNIFIED_URL,
        json={"result": {"UpdateResults": [{"Errors": [{"Message": "нет"}]}]}},
    )
    with _client() as client:
        batch = client.campaigns.update_unified(
            {"Id": 1, "Name": "epk"}, on_item_error="collect"
        )
    assert len(batch.failed) == 1


def test_get_unified_empty_ids() -> None:
    """Пустой список ID не вызывает v501."""
    with _client() as client:
        assert client.campaigns.get_unified([]) == []


def test_module_entrypoint_proxies_to_auth_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """`python -m yandex_direct_api_client` передаёт аргументы в CLI авторизации."""
    import runpy
    import sys

    monkeypatch.setattr(
        auth_module,
        "refresh_token",
        lambda *args, **kwargs: auth_module.TokenResponse.from_dict(
            {"access_token": "t1.value"}
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "yandex_direct_api_client",
            "refresh",
            "--client-id",
            "cid",
            "--client-secret",
            "secret",
            "--refresh-token",
            "y0.value",
        ],
    )
    with pytest.raises(SystemExit) as info:
        runpy.run_module(
            "yandex_direct_api_client",
            run_name="__main__",
            alter_sys=False,
        )
    assert info.value.code == 0
    assert "t1.value" in capsys.readouterr().out


# ---------------- модели объявлений ----------------


def test_ad_text_optional_fields_and_image_ref() -> None:
    """`AdText` и `ImageAdRef` обрабатывают пустые и альтернативные ключи."""
    assert AdText.from_dict(None).to_payload() == {"Title": "", "Text": ""}
    payload = AdText(
        title="T",
        text="X",
        href="https://site",
        ad_image_hash="hash1",
        display_url_path="site.ru",
    ).to_payload()
    assert payload["AdImageHash"] == "hash1"
    assert payload["DisplayUrlPath"] == "site.ru"

    assert ImageAdRef.from_dict(None).image_hash == ""
    assert ImageAdRef.from_dict({"ImageHash": "legacy"}).image_hash == "legacy"


def test_banner_ad_builder_extra_fields() -> None:
    """ErirAdDescription и TrackingPixels попадают в payload."""
    ad = CpmBannerAdBuilderAd(
        creative_id=10,
        href="https://site",
        eir_ad_description="Описание",
        tracking_pixels=["<img>"],
    )
    payload = ad.to_payload()
    assert payload["ErirAdDescription"] == "Описание"
    assert payload["TrackingPixels"] == {"Items": ["<img>"]}


def test_banner_ad_builder_rejects_bad_pixels_and_long_href() -> None:
    """Пустой пиксель и слишком длинный href — ошибки валидации."""
    with pytest.raises(ValidationError, match="TrackingPixels"):
        CpmBannerAdBuilderAd(
            creative_id=10, href="https://site", tracking_pixels=[""]
        ).to_payload()
    with pytest.raises(ValidationError, match="TrackingPixels"):
        CpmBannerAdBuilderAd(
            creative_id=10, href="https://site", tracking_pixels=["x" * 1100]
        ).to_payload()
    with pytest.raises(ValidationError, match="Href"):
        CpmBannerAdBuilderAd(
            creative_id=10, href="https://site.ru/" + "a" * 1100
        ).to_payload()


def test_responsive_ad_optional_sections() -> None:
    """Секции ЕПК-объявления сериализуются и валидируются."""
    ad = ResponsiveAd(
        titles=["Заголовок"],
        texts=["Текст объявления"],
        href="https://site",
        sitelink_set_id=5,
        ad_extension_ids=[1, 2],
        video_extension_ids=[7],
        eir_ad_description="Описание",
    )
    payload = ad.to_payload()
    assert payload["SitelinkSetId"] == 5
    assert payload["AdExtensionIds"] == [1, 2]
    assert payload["VideoExtensionIds"] == [7]
    assert payload["ErirAdDescription"] == "Описание"

    base = {"titles": ["T"], "texts": ["X"], "href": "https://site"}

    with pytest.raises(ValidationError, match="Href"):
        ResponsiveAd(
            titles=["T"], texts=["X"], href="https://site.ru/" + "a" * 1100
        ).to_payload()

    with pytest.raises(ValidationError, match="SitelinkSetId"):
        ResponsiveAd(**base, sitelink_set_id=0).to_payload()

    with pytest.raises(ValidationError, match="AdExtensionIds"):
        ResponsiveAd(
            **base, ad_extension_ids=list(range(RESPONSIVE_AD_EXTENSIONS_MAX + 1))
        ).to_payload()

    with pytest.raises(ValidationError, match="AdImageHashes"):
        ResponsiveAd(**base, ad_image_hashes=["  "]).to_payload()

    with pytest.raises(ValidationError, match="DisplayUrlPath"):
        ResponsiveAd(
            **base, display_url_path="d" * (RESPONSIVE_DISPLAY_URL_PATH_MAX + 1)
        ).to_payload()


def test_banner_ad_from_dict() -> None:
    """`BannerAd` читается из ответа API и tolerирует None."""
    assert BannerAd.from_dict(None).title == ""
    parsed = BannerAd.from_dict(
        {"Title": "T", "Text": "X", "Href": "https://s", "ImageId": 5}
    )
    assert parsed.image_id == 5
