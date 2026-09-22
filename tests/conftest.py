"""Общие фикстуры для тестов."""
from __future__ import annotations

from typing import Iterator

import pytest
import responses

from yandex_direct_api_client import YandexDirectClient

API_URL = "https://api.direct.yandex.com/json/v5"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[YandexDirectClient]:
    """Клиент с тестовыми настройками (не трогает реальные env)."""
    for var in (
        "YANDEX_DIRECT_TOKEN",
        "YANDEX_DIRECT_CLIENT_LOGIN",
        "YANDEX_DIRECT_API_URL",
        "YANDEX_DIRECT_READONLY",
    ):
        monkeypatch.delenv(var, raising=False)

    c = YandexDirectClient(
        token="test_token",
        client_login="TESTLOGIN",
        rate_limit_rps=1000.0,
        max_retries=2,
    )
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def mock_api() -> Iterator[responses.RequestsMock]:
    """Включает mock HTTP (requests перехватывается библиотекой `responses`)."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps
