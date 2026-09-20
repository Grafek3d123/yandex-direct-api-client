"""readonly-guard блокирует все mutating-методы."""
from __future__ import annotations

import pytest

from yandex_direct_api_client import YandexDirectClient
from yandex_direct_api_client.exceptions import ValidationError


@pytest.fixture
def ro_client(monkeypatch: pytest.MonkeyPatch) -> YandexDirectClient:
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
    yield c  # type: ignore[misc]
    c.close()


def test_readonly_blocks_update_ad(ro_client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError) as exc:
        ro_client.update_ad(1, "T", "B")
    assert "readonly" in str(exc.value)


def test_readonly_blocks_add_campaign(
    ro_client: YandexDirectClient,
) -> None:
    with pytest.raises(ValidationError):
        ro_client.add_campaign({"Name": "X"})


def test_readonly_blocks_delete_ad(ro_client: YandexDirectClient) -> None:
    with pytest.raises(ValidationError):
        ro_client.delete_ad([1, 2, 3])


def test_readonly_property_ro() -> None:
    assert ro_client_readonly() is True


def ro_client_readonly() -> bool:
    c = YandexDirectClient(
        token="t", client_login="L", readonly=True, rate_limit_rps=1000.0
    )
    try:
        return c.readonly
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
