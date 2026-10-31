import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    LinkPreviewOptions,
    Message,
    ReplyKeyboardMarkup,
)

from . import collector, config, db, llm
from .models import Item
from .tg_parser import TgParser

log = logging.getLogger(__name__)

BTN_COLLECT = "🔎 Собрать посты"
BTN_SOURCES = "📋 Источники"

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096

TOPIC_EMOJI = {"style": "👔", "perfume": "🧴", "psychology": "🧠", "fitness": "💪"}

router = Router()
router.message.filter(F.from_user.id == config.ADMIN_ID)
router.callback_query.filter(F.from_user.id == config.ADMIN_ID)

stranger_router = Router()  # всем остальным — от ворот поворот

_collect_lock = asyncio.Lock()


def main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_COLLECT), KeyboardButton(text=BTN_SOURCES)]],
        resize_keyboard=True,
    )


def post_kb(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🔄 Уникализировать", callback_data=f"u:{post_id}"),
            InlineKeyboardButton(text="🗑", callback_data=f"x:{post_id}"),
        ]]
    )


def _short(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _footer(it: Item) -> str:
    parts = [f"⭐ {it.score:.1f}", TOPIC_EMOJI.get(it.topic, "📌") + " " + it.source]
    if it.kind == "tg":
        parts.append(f"👁 {_short(it.views)}  ❤️ {_short(it.reactions)}  🔁 {_short(it.forwards)}")
    else:
        parts.append("🌐 пост по статье")
    return "\n\n———\n" + " · ".join(parts) + f"\n{it.url}"


def _fit(text: str, footer: str, limit: int) -> str:
    room = limit - len(footer)
    if len(text) > room:
        text = text[: room - 1].rstrip() + "…"
    return text + footer


# ---------- команды ----------

@router.message(CommandStart())
async def cmd_start(msg: Message) -> None:
    await msg.answer(
        "Здарова 👋\n\n"
        f"«{BTN_COLLECT}» — соберу свежак из каналов и сайтов и пришлю лучшее.\n"
        f"«{BTN_SOURCES}» — что сейчас мониторю.\n\n"
        "Добавить источник:\n"
        "/addchannel @username\n"
        "/addsite https://site.ru\n\n"
        "/reset — забыть, что уже присылал (пришлю всё заново)",
        reply_markup=main_kb(),
    )


@router.message(F.text == BTN_SOURCES)
@router.message(Command("sources"))
async def cmd_sources(msg: Message) -> None:
    channels = config.read_list(config.CHANNELS_FILE)
    sites = config.read_list(config.SITES_FILE)
    text = "📢 <b>Каналы</b>\n" + ("\n".join(channels) or "пусто")
    text += "\n\n🌐 <b>Сайты</b>\n" + ("\n".join(sites) or "пусто")
    text += "\n\nПравить можно в файлах channels.txt и sites.txt"
    await msg.answer(text, parse_mode="HTML", link_preview_options=NO_PREVIEW)


@router.message(Command("addchannel"))
async def cmd_addchannel(msg: Message) -> None:
    arg = (msg.text or "").split(maxsplit=1)[1:]
    if not arg:
        await msg.answer("Пример: /addchannel @username")
        return
    ok = config.append_to_list(config.CHANNELS_FILE, arg[0].strip())
    await msg.answer("✅ добавил" if ok else "уже есть в списке")


@router.message(Command("addsite"))
async def cmd_addsite(msg: Message) -> None:
    arg = (msg.text or "").split(maxsplit=1)[1:]
    if not arg:
        await msg.answer("Пример: /addsite https://site.ru")
        return
    ok = config.append_to_list(config.SITES_FILE, arg[0].strip())
    await msg.answer("✅ добавил" if ok else "уже есть в списке", link_preview_options=NO_PREVIEW)


@router.message(Command("reset"))
async def cmd_reset(msg: Message) -> None:
    n = db.reset_seen()
    await msg.answer(f"🧹 забыл {n} материалов")


# ---------- сбор ----------

@router.message(F.text == BTN_COLLECT)
@router.message(Command("collect"))
async def cmd_collect(msg: Message, bot: Bot, tg: TgParser) -> None:
    if _collect_lock.locked():
        await msg.answer("⏳ уже собираю, погоди")
        return

    async with _collect_lock:
        status = await msg.answer("🚀 начинаю сбор…")
        last = {"text": ""}

        async def progress(text: str) -> None:
            if text == last["text"]:
                return
            last["text"] = text
            try:
                await status.edit_text(text)
            except TelegramBadRequest:
                pass

        try:
            top, errors = await collector.collect(tg, progress)
        except Exception as e:  # noqa: BLE001
            log.exception("сбор упал")
            await status.edit_text(f"❌ сбор упал: {e.__class__.__name__}: {e}")
            return

        if not top:
            text = "🤷 ничего нового и годного не нашёл"
        else:
            text = f"✅ готово, лучшие {len(top)}:"
        if errors:
            text += "\n\n⚠️ проблемы:\n" + "\n".join(f"• {e}" for e in errors[:10])
        await status.edit_text(text[:TEXT_LIMIT], link_preview_options=NO_PREVIEW)

        for it in top:
            try:
                await _send_item(bot, msg.chat.id, it, tg)
            except Exception as e:  # noqa: BLE001
                log.exception("не отправил %s", it.url)
                await msg.answer(f"⚠️ не смог отправить {it.url}: {e}", link_preview_options=NO_PREVIEW)
            await asyncio.sleep(0.4)  # чтобы телега не ругалась на флуд


async def _send_item(bot: Bot, chat_id: int, it: Item, tg: TgParser) -> None:
    post_id = db.save_post(it.kind, it.source, it.url, it.post)
    kb = post_kb(post_id)
    footer = _footer(it)

    photo = await tg.download_photo(it) if it.kind == "tg" else None
    if photo:
        file = BufferedInputFile(photo, filename="photo.jpg")
        if len(it.post) + len(footer) <= CAPTION_LIMIT:
            await bot.send_photo(chat_id, file, caption=it.post + footer, reply_markup=kb)
            return
        await bot.send_photo(chat_id, file)

    await bot.send_message(chat_id, _fit(it.post, footer, TEXT_LIMIT), reply_markup=kb, link_preview_options=NO_PREVIEW)


# ---------- кнопки ----------

@router.callback_query(F.data.startswith("u:"))
async def cb_uniq(cb: CallbackQuery) -> None:
    post_id = int(cb.data.split(":")[1])
    row = db.get_post(post_id)
    if not row:
        await cb.answer("пост не найден", show_alert=True)
        return
    await cb.answer("✍️ переписываю…")
    try:
        new_text = await llm.uniqualize(row["text"])
    except Exception as e:  # noqa: BLE001
        log.exception("уникализация упала")
        await cb.message.reply(f"❌ нейронка не ответила: {e}")
        return

    new_id = db.save_post(row["kind"], row["source"], row["url"], new_text)
    footer = f"\n\n———\n🔄 уникализировано · {row['source']}\n{row['url']}"
    await cb.message.reply(
        _fit(new_text, footer, TEXT_LIMIT), reply_markup=post_kb(new_id), link_preview_options=NO_PREVIEW
    )


@router.callback_query(F.data.startswith("x:"))
async def cb_delete(cb: CallbackQuery) -> None:
    try:
        await cb.message.delete()
    except TelegramBadRequest:
        pass
    await cb.answer()


# ---------- чужие ----------

@stranger_router.message()
async def stranger(msg: Message) -> None:
    if not config.ADMIN_ID:
        await msg.answer(f"Твой id: <code>{msg.from_user.id}</code>\nВпиши его в .env как ADMIN_ID и перезапусти бота.",
                         parse_mode="HTML")
    else:
        await msg.answer("⛔ бот приватный")


@stranger_router.callback_query()
async def stranger_cb(cb: CallbackQuery) -> None:
    await cb.answer("⛔", show_alert=True)
