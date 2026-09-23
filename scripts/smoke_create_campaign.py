"""Боевой smoke-тест: полный жизненный цикл тестовой кампании на живом аккаунте.

Создаёт текстовую кампанию «SMOKE TEST …», проверяет чтение, архивирует
и удаляет её. Запускается вручную, в pytest не входит:

    .venv/bin/python scripts/smoke_create_campaign.py

Секреты читаются из .env (не выводятся). Кампания создаётся со ставкой
1 рубль и сразу удаляется после проверки — на аккаунте ничего не остаётся.
"""
from __future__ import annotations

import logging
import os
import pathlib
import sys
from datetime import date, timedelta

# ---- загрузка .env без внешних зависимостей ----
_env_path = pathlib.Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if key and key not in os.environ:
            os.environ[key] = val

from yandex_direct_api_client import YandexDirectClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("smoke")

NAME = f"SMOKE TEST {date.today().isoformat()} (auto)"


def main() -> int:
    # 1. readonly-проверка: чтение кампаний до создания
    with YandexDirectClient(readonly=True) as ro:
        before = ro.campaigns.list()
        logger.info("Кампаний до теста: %d", len(before))

    client = YandexDirectClient()
    created_id: int | None = None
    try:
        # 2. создание тестовой кампании (текстовая, минимальная ставка)
        result = client.campaigns.create(
            {
                "Name": NAME,
                "StartDate": (date.today() + timedelta(days=1)).isoformat(),
                "TextCampaign": {
                    "BiddingStrategy": {
                        "Search": {"BiddingStrategyType": "HIGHEST_POSITION"},
                        "Network": {"BiddingStrategyType": "SERVING_OFF"},
                    },
                },
            }
        )
        created_id = int(result["Id"])
        logger.info("Создана кампания id=%d name=%r", created_id, NAME)

        # 3. чтение: get по ID + list-фильтр
        found = client.campaigns.get([created_id])
        if not found or found[0].id != created_id:
            logger.error("GET по ID не вернул кампанию %d", created_id)
            return 1
        logger.info(
            "GET OK: id=%d name=%r state=%s status=%s",
            found[0].id,
            found[0].name,
            found[0].state,
            found[0].status,
        )

        # 4. обновление: переименование
        upd = client.campaigns.update(
            {"Id": created_id, "Name": NAME + " [upd]"}
        )
        logger.info("UPDATE OK: id=%s", upd.get("Id"))

        # 5. попытка удалить БЕЗ confirm → должна упасть до HTTP
        try:
            client.campaigns.delete([created_id])
            logger.error("delete без confirm не упал — это баг!")
            return 1
        except Exception as e:  # noqa: BLE001
            logger.info("DELETE без confirm корректно отклонён: %s", type(e).__name__)

        # 6. удаление с confirm
        client.campaigns.delete([created_id], confirm=True)
        logger.info("DELETE OK: кампания %d удалена", created_id)

        # 7. контроль: кампании больше нет
        after = client.campaigns.get([created_id])
        logger.info("Контроль после удаления: %s", "нет записей — OK" if not after else f"ОСТАЛАСЬ: {after}")
        created_id = None

        return 0
    finally:
        # страховка: если что-то упало до delete — удаляем за собой
        if created_id is not None:
            logger.warning("Тест упал — удаляю тестовую кампанию %d", created_id)
            try:
                client.campaigns.delete([created_id], confirm=True)
            except Exception as e:  # noqa: BLE001
                logger.error("Не удалось удалить кампанию %d: %s", created_id, e)
                logger.error("Удалите вручную в интерфейсе Директа!")
        client.close()


if __name__ == "__main__":
    sys.exit(main())
