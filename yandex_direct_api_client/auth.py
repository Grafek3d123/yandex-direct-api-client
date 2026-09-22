"""OAuth-хелперы: получение и обновление токена Яндекс.ID.

- `get_new_token` — запускает локальный HTTP-сервер, открывает браузер,
  принимает authorization code и обменивает его на access/refresh токены.
- `refresh_token` — обновляет access_token по refresh_token.
- `run_cli` — точка входа `python -m yandex_direct_api_client.auth`.
"""
from __future__ import annotations

import argparse
import http.server
import json
import logging
import secrets
import socket
import socketserver
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from typing import Dict, List, Optional

from .exceptions import AuthError
from .models import TokenResponse

logger = logging.getLogger(__name__)

OAUTH_AUTHORIZE_URL = "https://oauth.yandex.ru/authorize"
OAUTH_TOKEN_URL = "https://oauth.yandex.ru/token"

DEFAULT_PORT = 8888


@dataclass
class _CodeCapture:
    """Хранит полученный authorization code между потоками."""

    code: Optional[str] = None
    state: Optional[str] = None
    error: Optional[str] = None


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Минимальный handler, извлекающий `code` и `state` из query-string."""

    capture: _CodeCapture  # подменяется на инстанс при старте сервера

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            self.capture.code = params["code"][0]
            self.capture.state = (
                params.get("state", [None])[0] if "state" in params else None
            )
            body = (
                "<html><body><h2>Авторизация завершена</h2>"
                "<p>Можно закрыть окно и вернуться в консоль.</p></body></html>"
            ).encode("utf-8")
        elif "error" in params:
            self.capture.error = params["error"][0]
            body = (
                "<html><body><h2>Ошибка авторизации</h2>"
                f"<p>{urllib.parse.quote_plus(self.capture.error)}</p>"
                "</body></html>"
            ).encode("utf-8")
        else:
            self.capture.error = "no_code_in_callback"
            body = "<html><body><h2>Неожиданный callback</h2></body></html>".encode(
                "utf-8"
            )

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        # Подавляем стандартный stderr-лог http.server
        return


def _find_free_port(preferred: int = DEFAULT_PORT) -> int:
    """Вернуть первый свободный TCP-порт начиная с `preferred`."""
    for offset in range(20):
        port = preferred + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise OSError(f"Не удалось найти свободный порт рядом с {preferred}")


def _post_token_request(
    form: Dict[str, str],
    *,
    error_context: str,
    timeout: float = 30.0,
) -> TokenResponse:
    """POST /token с form-данными и разбором ответа (общий путь)."""
    body = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(
        OAUTH_TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            payload = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise AuthError(
            f"{error_context}: HTTP {e.code}: {detail[:300]}",
            status_code=e.code,
        ) from e
    except urllib.error.URLError as e:
        raise AuthError(
            f"Сетевая ошибка ({error_context}): {e.reason}"
        ) from e

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        raise AuthError(f"OAuth вернул не-JSON: {payload[:200]}") from e

    if "access_token" not in data:
        raise AuthError(f"В ответе OAuth нет access_token: keys={list(data)}")

    return TokenResponse.from_dict(data)


def _exchange_code_for_token(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    timeout: float = 30.0,
) -> TokenResponse:
    """POST /token с grant_type=authorization_code."""
    return _post_token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        },
        error_context="Не удалось обменять code на токен",
        timeout=timeout,
    )


def get_new_token(
    client_id: str,
    client_secret: str,
    *,
    port: Optional[int] = None,
    open_browser: bool = True,
    timeout: float = 300.0,
) -> TokenResponse:
    """Получить новый access_token через OAuth code-flow.

    Запускает временный HTTP-сервер на localhost, открывает браузер,
    ждёт возврата authorization code, обменивает его на токен.

    :param client_id: OAuth application id.
    :param client_secret: OAuth application secret.
    :param port: явный порт; если None — подбирается свободный рядом с 8888.
    :param open_browser: открывать ли браузер автоматически.
    :param timeout: максимум секунд ожидания возврата из браузера.
    """
    if not client_id or not client_secret:
        raise AuthError("client_id и client_secret обязательны для get_new_token")

    chosen_port = port if port is not None else _find_free_port(DEFAULT_PORT)
    redirect_uri = f"http://localhost:{chosen_port}/callback"
    state = secrets.token_urlsafe(16)

    auth_url = OAUTH_AUTHORIZE_URL + "?" + urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "force_confirm": "yes",
            "state": state,
        }
    )

    capture = _CodeCapture()

    handler_cls = type(
        "_CallbackHandlerBound",
        (_CallbackHandler,),
        {"capture": capture},
    )

    with socketserver.TCPServer(("127.0.0.1", chosen_port), handler_cls) as httpd:
        httpd.timeout = timeout

        logger.info("OAuth: откройте в браузере: %s", auth_url)
        if open_browser:
            try:
                webbrowser.open(auth_url)
            except Exception:  # noqa: BLE001
                logger.warning("Не удалось открыть браузер автоматически")

        def _serve() -> None:
            while capture.code is None and capture.error is None:
                httpd.handle_request()

        thread = threading.Thread(target=_serve, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if capture.code is None and capture.error is None:
            raise AuthError(
                f"Таймаут ожидания OAuth callback ({timeout:.0f} секунд)"
            )
        if capture.error:
            raise AuthError(f"OAuth вернул ошибку: {capture.error}")
        if capture.state != state:
            raise AuthError("state в callback не совпадает — возможен CSRF")

    return _exchange_code_for_token(
        client_id, client_secret, capture.code or "", redirect_uri, timeout=timeout
    )


def refresh_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    *,
    timeout: float = 30.0,
) -> TokenResponse:
    """Обновить access_token по refresh_token."""
    if not (client_id and client_secret and refresh_token):
        raise AuthError(
            "refresh_token требует client_id, client_secret, refresh_token"
        )

    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        OAUTH_TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            payload = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise AuthError(
            f"Не удалось обновить токен: HTTP {e.code}: {detail[:300]}",
            status_code=e.code,
        ) from e
    except urllib.error.URLError as e:
        raise AuthError(f"Сетевая ошибка при refresh: {e.reason}") from e

    import json

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        raise AuthError(f"OAuth вернул не-JSON: {payload[:200]}") from e

    if "access_token" not in data:
        raise AuthError(f"В ответе OAuth нет access_token: keys={list(data)}")

    return TokenResponse.from_dict(data)


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m yandex_direct_api_client.auth",
        description="Получить или обновить OAuth-токен Яндекс.ID для Директа.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new", help="Получить новый токен через браузер")
    p_new.add_argument("--client-id", required=True)
    p_new.add_argument("--client-secret", required=True)
    p_new.add_argument("--port", type=int, default=None)
    p_new.add_argument(
        "--no-browser", action="store_true", help="Не открывать браузер сам"
    )

    p_ref = sub.add_parser("refresh", help="Обновить существующий токен")
    p_ref.add_argument("--client-id", required=True)
    p_ref.add_argument("--client-secret", required=True)
    p_ref.add_argument("--refresh-token", required=True)

    return parser.parse_args(argv)


def run_cli(argv: Optional[List[str]] = None) -> int:
    """Точка входа `python -m yandex_direct_api_client.auth`."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args(argv)

    try:
        if args.cmd == "new":
            tok = get_new_token(
                args.client_id,
                args.client_secret,
                port=args.port,
                open_browser=not args.no_browser,
            )
        else:
            tok = refresh_token(
                args.client_id,
                args.client_secret,
                args.refresh_token,
            )
    except AuthError as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        return 1

    print(f"access_token  = {tok.access_token}")
    if tok.refresh_token:
        print(f"refresh_token = {tok.refresh_token}")
    if tok.expires_in:
        print(f"expires_in    = {tok.expires_in} сек")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
