import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher

from bot import config, db
from bot.handlers import router, stranger_router
from bot.tg_parser import TgParser


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    missing = config.check()
    if missing:
        print("❌ Не заполнены в .env:", ", ".join(missing))
        print("Скопируй .env.example в .env и впиши значения.")
        sys.exit(1)

    db.conn()

    tg = TgParser()
    await tg.start()

    bot = Bot(config.BOT_TOKEN)
    dp = Dispatcher()
    dp["tg"] = tg  # прокидываем парсер в хендлеры
    dp.include_router(router)
    dp.include_router(stranger_router)

    if not config.ADMIN_ID:
        print("⚠️ ADMIN_ID не задан — напиши боту что угодно, он пришлёт твой id.")
    print("✅ Бот запущен. Пиши ему в телегу. Остановить — Ctrl+C")
    try:
        await dp.start_polling(bot)
    finally:
        await tg.stop()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
