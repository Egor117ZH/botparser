"""Управление источниками прямо в боте: у каждой рубрики свой список."""
import logging
import re
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Message

from . import config

log = logging.getLogger(__name__)

CATS = config.CATEGORIES
BTN_SOURCES = "📋 Источники"
BTN_CANCEL = "✖️ Отмена"
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
# кнопки главного меню — их не принимаем за ссылку, даже если ждём источник
MENU_BUTTONS = {f"{c['emoji']} {c['name']}" for c in CATS.values()} | {BTN_SOURCES}

router = Router()
router.message.filter(F.from_user.id == config.ADMIN_ID)
router.callback_query.filter(F.from_user.id == config.ADMIN_ID)


class AddSource(StatesGroup):
    waiting = State()


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _short_src(src: str, limit: int = 40) -> str:
    s = src.removeprefix("https://").removeprefix("http://").removeprefix("www.").rstrip("/")
    return s if len(s) <= limit else s[: limit - 1] + "…"


# ---------- экраны ----------

def _root_view() -> tuple[str, InlineKeyboardMarkup]:
    lines = ["📋 <b>Источники</b>\n", "У каждой рубрики свои. Выбери, какие смотреть или править:"]
    rows = []
    for cat, c in CATS.items():
        n = len(config.sources(cat))
        rows.append([_btn(f"{c['emoji']} {c['name']} ({n})", f"src:v:{cat}")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def _cat_view(cat: str) -> tuple[str, InlineKeyboardMarkup]:
    c = CATS[cat]
    srcs = config.sources(cat)
    lines = [f"{c['emoji']} <b>{c['name']}</b> — источники ({len(srcs)})\n"]
    if not srcs:
        lines.append("пока пусто — жми «➕ Добавить»")
    for i, src in enumerate(srcs, 1):
        mark = "📢" if config.is_channel(src) else "🌐"
        off = " <i>(канал, пока не читается)</i>" if config.is_channel(src) and not config.TG_PARSER_ENABLED else ""
        lines.append(f"{i}. {mark} {escape(src)}{off}")
    rows = [[_btn("➕ Добавить", f"src:a:{cat}")]]
    if srcs:
        rows[0].append(_btn("🗑 Удалить", f"src:d:{cat}"))
    rows.append([_btn("⬅️ Назад", "src:r")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def _del_view(cat: str) -> tuple[str, InlineKeyboardMarkup]:
    c = CATS[cat]
    srcs = config.sources(cat)
    rows = [[_btn(f"❌ {i}. {_short_src(src)}", f"src:x:{cat}:{i - 1}")] for i, src in enumerate(srcs, 1)]
    rows.append([_btn("✅ Готово", f"src:v:{cat}")])
    text = f"{c['emoji']} <b>{c['name']}</b> — нажми на источник, чтобы удалить:"
    if not srcs:
        text = f"{c['emoji']} <b>{c['name']}</b> — источников больше нет"
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def _show(cb: CallbackQuery, view: tuple[str, InlineKeyboardMarkup]) -> None:
    text, kb = view
    try:
        await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML", link_preview_options=NO_PREVIEW)
    except TelegramBadRequest:  # «message is not modified» и т.п.
        pass


# ---------- обработчики ----------

@router.message(F.text == BTN_SOURCES)
@router.message(Command("sources"))
async def cmd_sources(msg: Message, state: FSMContext) -> None:
    await state.clear()
    text, kb = _root_view()
    await msg.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "src:r")
async def cb_root(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _show(cb, _root_view())
    await cb.answer()


@router.callback_query(F.data.startswith("src:v:"))
async def cb_view(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    cat = cb.data.split(":")[2]
    if cat in CATS:
        await _show(cb, _cat_view(cat))
    await cb.answer()


@router.callback_query(F.data.startswith("src:d:"))
async def cb_del_menu(cb: CallbackQuery) -> None:
    cat = cb.data.split(":")[2]
    if cat in CATS:
        await _show(cb, _del_view(cat))
    await cb.answer()


@router.callback_query(F.data.startswith("src:x:"))
async def cb_del(cb: CallbackQuery) -> None:
    _, _, cat, idx = cb.data.split(":")
    srcs = config.sources(cat) if cat in CATS else []
    i = int(idx)
    if i >= len(srcs):
        await cb.answer("уже удалён", show_alert=False)
        await _show(cb, _del_view(cat))
        return
    src = srcs[i]
    config.remove_from_list(CATS[cat]["file"], src)
    await cb.answer(f"удалил {_short_src(src)}")
    await _show(cb, _del_view(cat))


@router.callback_query(F.data.startswith("src:a:"))
async def cb_add(cb: CallbackQuery, state: FSMContext) -> None:
    cat = cb.data.split(":")[2]
    if cat not in CATS:
        await cb.answer()
        return
    await state.set_state(AddSource.waiting)
    await state.update_data(cat=cat)
    c = CATS[cat]
    await cb.message.answer(
        f"Кидай источники для «{c['emoji']} {c['name']}»:\n"
        "• сайт: <code>https://site.ru</code> или просто <code>site.ru</code>\n"
        "• раздел сайта или RSS-лента — тоже можно, RSS даже лучше\n"
        "• тг-канал: <code>@username</code> или <code>t.me/username</code>\n\n"
        "Можно сразу несколько — каждый с новой строки.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[_btn(BTN_CANCEL, f"src:v:{cat}")]]),
        link_preview_options=NO_PREVIEW,
    )
    await cb.answer()


# отдельные команды-шорткаты: /addnews site.ru  /addstory site.ru
@router.message(Command("addnews", "addstory"))
async def cmd_add(msg: Message, state: FSMContext) -> None:
    cat = "news" if msg.text.split()[0].lstrip("/").split("@")[0] == "addnews" else "stories"
    args = msg.text.split(maxsplit=1)[1:]
    if not args:
        await state.set_state(AddSource.waiting)
        await state.update_data(cat=cat)
        await msg.answer(f"Кидай ссылки для «{CATS[cat]['name']}», можно несколько, каждую с новой строки")
        return
    await msg.answer(_add_many(cat, args[0]), parse_mode="HTML", link_preview_options=NO_PREVIEW)


@router.message(AddSource.waiting, F.text, ~F.text.startswith("/"), ~F.text.in_(MENU_BUTTONS))
async def on_source_text(msg: Message, state: FSMContext) -> None:
    data = await state.get_data()
    cat = data.get("cat")
    await state.clear()
    if cat not in CATS:
        return
    await msg.answer(_add_many(cat, msg.text), parse_mode="HTML", link_preview_options=NO_PREVIEW)
    text, kb = _cat_view(cat)
    await msg.answer(text, reply_markup=kb, parse_mode="HTML", link_preview_options=NO_PREVIEW)


def _add_many(cat: str, raw: str) -> str:
    added, dup, bad = [], [], []
    for tok in re.split(r"[\s,]+", raw):
        if not tok:
            continue
        src = config.normalize_source(tok)
        if not src:
            bad.append(tok)
        elif config.append_to_list(CATS[cat]["file"], src):
            added.append(src)
        else:
            dup.append(src)

    c = CATS[cat]
    out = []
    if added:
        out.append(f"✅ добавил в «{c['name']}»:\n" + "\n".join(f"• {escape(s)}" for s in added))
    if dup:
        out.append("уже были:\n" + "\n".join(f"• {escape(s)}" for s in dup))
    if bad:
        out.append("❓ не понял, что это:\n" + "\n".join(f"• {escape(s)}" for s in bad[:10]))
    if any(config.is_channel(s) for s in added) and not config.TG_PARSER_ENABLED:
        out.append("⚠️ каналы пока не читаются — заработают, когда заполнишь TG_API_ID/TG_API_HASH/TG_PHONE")
    return "\n\n".join(out) or "ничего не прислал 🤔"
