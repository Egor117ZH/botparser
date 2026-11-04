import asyncio
import logging
import sys
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramUnauthorizedError

from bot import config, db
from bot.handlers import router, stranger_router
from bot.sources_ui import router as sources_router
from bot.llm import client as llm_client
from bot.tg_parser import TgParser

if config.PROXY or config.MTPROXY:
    NO_PROXY_HINT = "   Прокси вписан, но не работает — проверь адрес, порт, логин/пароль или возьми другой."
else:
    NO_PROXY_HINT = (
        "   Скорее всего телега режется провайдером. Впиши прокси в .env:\n"
        "   PROXY=socks5://логин:пароль@ip:порт  (или http://...)"
    )


def say(text: str) -> None:
    print(text, flush=True)


def fail(text: str) -> None:
    say("\n❌ " + text)
    sys.exit(1)


async def _start_userbot(tg: TgParser, bot: Bot) -> None:
    say("[2/3] Подключаюсь к телеге аккаунтом для чтения каналов…")
    say("      (в первый раз спросит код — он придёт в приложение телеги, не в смс)")
    try:
        await tg.start()
    except (ConnectionError, asyncio.TimeoutError, OSError) as e:
        await bot.session.close()
        fail(f"Не подключился к серверам телеги ({e.__class__.__name__}: {e})\n" + NO_PROXY_HINT
             + "\n   или MTPROXY=host:port:secret")
    except Exception as e:  # noqa: BLE001 — неверный api_id, номер, код и т.п.
        await bot.session.close()
        fail(f"Не вошёл в аккаунт: {e.__class__.__name__}: {e}\n"
             "   Проверь TG_API_ID, TG_API_HASH и TG_PHONE (формат +79991234567). Если прокси кривой — тоже сюда.")
    tg_me = await tg.client.get_me()
    say(f"      ок, вошёл как {tg_me.first_name} (@{tg_me.username or '-'})")


async def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("bot").setLevel(logging.INFO)

    missing = config.check()
    if missing:
        fail("Не заполнены в .env: " + ", ".join(missing))

    if config.PROXY:
        say(f"🌍 прокси: {urlparse(config.PROXY).hostname}:{urlparse(config.PROXY).port}")
    elif config.MTPROXY:
        say(f"🌍 MTProto-прокси: {config.MTPROXY.split(':')[0]} (только для чтения каналов)")
    else:
        say("🌍 без прокси")
    db.conn()

    for old in config.OLD_SOURCE_FILES:
        if config.read_list(old):
            say(f"⚠️ {old.name} больше не используется — перенеси источники в "
                "sources_news.txt (новости) или sources_stories.txt (мышление)")

    # 1. бот
    say("[1/3] Проверяю бота (api.telegram.org)…")
    session = AiohttpSession(proxy=config.PROXY) if config.PROXY else AiohttpSession()
    bot = Bot(config.BOT_TOKEN, session=session)
    try:
        me = await asyncio.wait_for(bot.get_me(), timeout=30)
    except TelegramUnauthorizedError:
        await bot.session.close()
        fail("BOT_TOKEN неверный — возьми заново у @BotFather.")
    except Exception as e:  # noqa: BLE001 — сеть/прокси/таймаут
        await bot.session.close()
        fail(f"Не достучался до api.telegram.org ({e.__class__.__name__}: {e})\n" + NO_PROXY_HINT)
    say(f"      ок, бот @{me.username}")

    # 2. userbot
    tg = TgParser()
    if not tg.enabled:
        say("[2/3] Чтение тг-каналов выключено (TG_API_ID / TG_API_HASH / TG_PHONE пустые) — работаем только по сайтам")
    else:
        await _start_userbot(tg, bot)

    # 3. нейронка
    say("[3/3] Проверяю Polza AI…")
    try:
        await asyncio.wait_for(llm_client.models.list(), timeout=30)
        say(f"      ок, модель {config.POLZA_MODEL}")
    except Exception as e:  # noqa: BLE001
        say(f"      ⚠️ не смог проверить ({e.__class__.__name__}: {e}) — бот запустится, но посты писать может не выйти")

    dp = Dispatcher()
    dp["tg"] = tg  # прокидываем парсер в хендлеры
    dp.include_router(sources_router)  # раньше основного: там ввод ссылок
    dp.include_router(router)
    dp.include_router(stranger_router)

    say("")
    if not config.ADMIN_ID:
        say("⚠️ ADMIN_ID не задан — напиши боту что угодно, он пришлёт твой id. Впиши его в .env и перезапусти.")
    say(f"✅ Бот запущен. Открывай @{me.username} в телеге и жми /start. Остановить — Ctrl+C")
    try:
        await dp.start_polling(bot, handle_signals=False)
    finally:
        await tg.stop()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
