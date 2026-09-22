"""readonly-guard блокирует все mutating-методы."""
from __future__ import annotations

from typing import Iterator

import pytest

from yandex_direct_api_client import YandexDirectClient
from yandex_direct_api_client.exceptions import ValidationError


@pytest.fixture
def ro_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[YandexDirectClient]:
    for var in (
        "YANDEX_DIRECT_TOKEN",
        "YANDEX_DIRECT_CLIENT_LOGIN",
        "YANDEX_DIRECT_READONLY",
    ):
        monkeypatch.delenv(var, raising=False)
    c = YandexDirectClient(
        token="t",
        client_login="L",
        readonly=True,
        rate_limit_rps=1000.0,
    )
    yield c
    c.close()


def test_readonly_blocks_ads_update_text(ro_client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError) as exc:
        ro_client.ads.update_text(1, "T", "B")
    assert "readonly" in str(exc.value)


def test_readonly_blocks_campaigns_create(ro_client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError):
        ro_client.campaigns.create({"Name": "X"})


def test_readonly_blocks_campaigns_update(ro_client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError):
        ro_client.campaigns.update({"Id": 1, "Name": "X"})


def test_readonly_blocks_campaigns_delete(ro_client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError):
        ro_client.campaigns.delete([1], confirm=True)


def test_readonly_blocks_ads_create(ro_client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError):
        ro_client.ads.create([{"TextAd": {"Title": "T", "Text": "B"}}])


def test_readonly_blocks_ads_update(ro_client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError):
        ro_client.ads.update([{"Id": 1}], confirm=True)


def test_readonly_blocks_ads_delete(ro_client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError):
        ro_client.ads.delete([1, 2, 3], confirm=True)


def test_readonly_property_ro() -> None:
    c = YandexDirectClient(
        token="t", client_login="L", readonly=True, rate_limit_rps=1000.0
    )
    try:
        assert c.readonly is True
    finally:
        c.close()


def test_readonly_false_by_default() -> None:
    c = YandexDirectClient(
        token="t", client_login="L", rate_limit_rps=1000.0
    )
    try:
        assert c.readonly is False
    finally:
        c.close()
