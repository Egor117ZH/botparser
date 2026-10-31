import logging
from datetime import datetime

from telethon import TelegramClient

from . import config
from .models import Item

log = logging.getLogger(__name__)


def _normalize(channel: str) -> str:
    channel = channel.strip()
    if channel.startswith("t.me/"):
        channel = "https://" + channel
    return channel


class TgParser:
    """Читает каналы из-под твоего аккаунта (userbot через Telethon)."""

    def __init__(self) -> None:
        self.client = TelegramClient(str(config.SESSION_PATH), config.TG_API_ID, config.TG_API_HASH)

    async def start(self) -> None:
        # при первом запуске спросит код из телеги (и пароль 2FA, если есть) прямо в консоли
        await self.client.start(phone=config.TG_PHONE)
        me = await self.client.get_me()
        log.info("userbot вошёл как %s", me.username or me.first_name)

    async def stop(self) -> None:
        await self.client.disconnect()

    async def fetch(self, channel: str, since: datetime, limit: int) -> list[Item]:
        entity = await self.client.get_entity(_normalize(channel))
        username = getattr(entity, "username", None)
        name = f"@{username}" if username else getattr(entity, "title", channel)

        items: list[Item] = []
        async for m in self.client.iter_messages(entity, limit=limit):
            if m.date < since:
                break
            text = (m.message or "").strip()
            if len(text) < config.MIN_TEXT_LEN:
                continue

            reactions = 0
            if m.reactions and m.reactions.results:
                reactions = sum(r.count for r in m.reactions.results)

            url = f"https://t.me/{username}/{m.id}" if username else f"https://t.me/c/{entity.id}/{m.id}"
            items.append(
                Item(
                    kind="tg",
                    key=f"tg:{entity.id}:{m.id}",
                    source=name,
                    url=url,
                    text=text,
                    date=m.date,
                    views=m.views or 0,
                    reactions=reactions,
                    forwards=m.forwards or 0,
                    replies=m.replies.replies if m.replies else 0,
                    media_msg=m if m.photo else None,
                )
            )
        return items

    async def download_photo(self, item: Item) -> bytes | None:
        if item.media_msg is None:
            return None
        try:
            return await self.client.download_media(item.media_msg, file=bytes)
        except Exception as e:  # noqa: BLE001
            log.warning("не скачал фото %s: %s", item.url, e)
            return None
