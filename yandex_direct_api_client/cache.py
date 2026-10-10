"""Дисковый кэш справочников Yandex.Direct.

Справочники (регионы, интересы, ретаргетинг-списки, …) меняются крайне редко,
но забирать их каждый раз — платные запросы. Справочник стран и регионов РФ —
это порядка 100 записей и несколько сотен килобайт JSON, поэтому он кэшируется
на диске на 7 суток.

Особенности:

- кэш **вспомогательный**: любая проблема с файловой системой (нет прав,
  только чтение, битый файл) не должна ломать клиент — ошибки логируются
  на DEBUG и работа продолжается без кэша;
- каталог задаётся `YANDEX_DIRECT_CACHE_DIR`, по умолчанию
  `~/.yandex-direct-api-client/cache`;
- содержимое кэша — только публичные справочные данные, секретов там нет.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .logs import get_logger

logger = get_logger(__name__)

#: Имя переменной окружения с каталогом кэша.
ENV_CACHE_DIR = "YANDEX_DIRECT_CACHE_DIR"

#: Каталог кэша по умолчанию.
DEFAULT_CACHE_DIR = "~/.yandex-direct-api-client/cache"

#: TTL кэша справочников по умолчанию — 7 суток.
DEFAULT_TTL_SECONDS = 7 * 24 * 3600

#: Имя файла с ключами закешированных значений внутри каталога.
CACHE_FILE_NAME = "dictionary_cache.json"


def default_cache_dir() -> Path:
    """Каталог кэша: env-переменная или значение по умолчанию.

    :return: путь к каталогу (сам каталог может ещё не существовать).
    """
    raw = os.environ.get(ENV_CACHE_DIR) or DEFAULT_CACHE_DIR
    return Path(raw).expanduser()


def _hash_key(namespace: str, key: Any) -> str:
    """Детерминированный хэш ключа кэша.

    :param namespace: логическое пространство (имя метода справочника).
    :param key: параметры запроса (сериализуемый dict/str).
    :return: hex-хэш, пригодный для использования как ключ словаря.
    """
    payload = json.dumps(
        {"ns": namespace, "key": key}, sort_keys=True, default=str, ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


class JsonCache:
    """Простой JSON-кэш с TTL, хранящийся одним файлом в каталоге.

    :param ttl_seconds: время жизни записи; None — бессрочно.
    :param cache_dir: каталог хранения; None — взять из окружения
        (см. `default_cache_dir`) в момент каждой операции.
    """

    def __init__(
        self,
        *,
        ttl_seconds: Optional[int] = DEFAULT_TTL_SECONDS,
        cache_dir: Optional[Path] = None,
    ) -> None:
        self._ttl = ttl_seconds
        self._cache_dir = cache_dir

    @property
    def cache_dir(self) -> Path:
        """Каталог хранения кэша (создаётся при первой записи)."""
        if self._cache_dir is not None:
            return self._cache_dir
        return default_cache_dir()

    @property
    def ttl_seconds(self) -> Optional[int]:
        """Время жизни записи в секундах (None — бессрочно)."""
        return self._ttl

    @property
    def path(self) -> Path:
        """Путь к файлу кэша."""
        return self.cache_dir / CACHE_FILE_NAME

    # ---------------- внутреннее ----------------
    def _read_all(self) -> Dict[str, Any]:
        """Прочитать весь кэш; при любой проблеме — пустой dict."""
        path = self.path
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            logger.debug("кэш %s недоступен для чтения: %s", path, exc)
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _write_all(self, data: Dict[str, Any]) -> bool:
        """Записать кэш атомарно; вернуть признак успеха."""
        path = self.path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as exc:
            logger.debug("кэш %s недоступен для записи: %s", path, exc)
            return False
        return True

    # ---------------- публичное ----------------
    def get(self, namespace: str, key: Any) -> Optional[Any]:
        """Прочитать значение из кэша.

        :param namespace: пространство ключа (имя метода справочника).
        :param key: параметры запроса.
        :return: значение или None, если записи нет, она просрочена или
            кэш недоступен.
        """
        entry = self._read_all().get(_hash_key(namespace, key))
        if not isinstance(entry, dict) or "stored_at" not in entry:
            return None
        if self._ttl is not None:
            age = time.time() - float(entry["stored_at"])
            if age > self._ttl:
                return None
        return entry.get("value")

    def set(self, namespace: str, key: Any, value: Any) -> bool:
        """Сохранить значение в кэш.

        :param namespace: пространство ключа (имя метода справочника).
        :param key: параметры запроса.
        :param value: сериализуемое значение.
        :return: True, если значение записано.
        """
        data = self._read_all()
        data[_hash_key(namespace, key)] = {"stored_at": time.time(), "value": value}
        return self._write_all(data)

    def clear(self) -> bool:
        """Удалить файл кэша целиком.

        :return: True, если кэш очищен (или его не было).
        """
        try:
            self.path.unlink()
        except FileNotFoundError:
            return True
        except OSError as exc:
            logger.debug("не удалось очистить кэш %s: %s", self.path, exc)
            return False
        return True


__all__ = [
    "CACHE_FILE_NAME",
    "DEFAULT_CACHE_DIR",
    "DEFAULT_TTL_SECONDS",
    "ENV_CACHE_DIR",
    "JsonCache",
    "default_cache_dir",
]
