import asyncio
import logging
from datetime import datetime
from urllib.parse import unquote, urlparse

from telethon import TelegramClient, connection

from . import config
from .models import Item

log = logging.getLogger(__name__)


def _normalize(channel: str) -> str:
    channel = channel.strip()
    if channel.startswith("t.me/"):
        channel = "https://" + channel
    return channel


def _proxy_kwargs() -> dict:
    if config.MTPROXY:
        host, port, secret = config.MTPROXY.split(":", 2)
        return {
            "connection": connection.ConnectionTcpMTProxyRandomizedIntermediate,
            "proxy": (host, int(port), secret),
        }
    if config.PROXY:
        u = urlparse(config.PROXY)
        scheme = u.scheme.lower().replace("socks5h", "socks5")
        if scheme not in ("socks5", "socks4", "http", "https"):
            raise ValueError(f"не понимаю тип прокси: {u.scheme} (нужен socks5:// или http://)")
        return {
            "proxy": {
                "proxy_type": "http" if scheme == "https" else scheme,
                "addr": u.hostname,
                "port": u.port,
                "username": unquote(u.username) if u.username else None,
                "password": unquote(u.password) if u.password else None,
                "rdns": True,
            }
        }
    return {}


class TgParser:
    """Читает каналы из-под твоего аккаунта (userbot через Telethon).

    Если TG_API_ID / TG_API_HASH / TG_PHONE не заполнены — работает как заглушка:
    ничего не подключает, каналы не читает.
    """

    def __init__(self) -> None:
        self.enabled = config.TG_PARSER_ENABLED
        self.client: TelegramClient | None = None
        if not self.enabled:
            return
        self.client = TelegramClient(
            str(config.SESSION_PATH),
            config.TG_API_ID,
            config.TG_API_HASH,
            timeout=15,
            connection_retries=3,
            retry_delay=2,
            **_proxy_kwargs(),
        )

    async def start(self) -> None:
        if not self.enabled:
            return
        await asyncio.wait_for(self.client.connect(), timeout=90)
        if not self.client.is_connected():
            raise ConnectionError("не подключился к серверам телеги")
        # при первом запуске спросит код из телеги (и пароль 2FA, если есть) прямо в консоли
        await self.client.start(phone=config.TG_PHONE)
        me = await self.client.get_me()
        log.info("userbot вошёл как %s", me.username or me.first_name)

    async def stop(self) -> None:
        if self.client:
            await self.client.disconnect()

    async def fetch(self, channel: str, since: datetime, limit: int) -> list[Item]:
        if not self.enabled:
            return []
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
        if not self.enabled or item.media_msg is None:
            return None
        try:
            return await self.client.download_media(item.media_msg, file=bytes)
        except Exception as e:  # noqa: BLE001
            log.warning("не скачал фото %s: %s", item.url, e)
            return None
