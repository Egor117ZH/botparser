import asyncio
import logging
import re
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from . import config, db, llm, site_parser
from .models import Item
from .tg_parser import TgParser

log = logging.getLogger(__name__)

Progress = Callable[[str], Awaitable[None]]

# веса итоговой оценки: нейронка (интерес + тема) + реакция аудитории
W_INTEREST = 0.45
W_RELEVANCE = 0.30
W_ENGAGEMENT = 0.25


def _engagement(posts: list[Item]) -> None:
    """Насколько пост зашёл относительно других постов этого же канала (0..1)."""
    if not posts:
        return
    now = datetime.now(timezone.utc)

    def adj_views(p: Item) -> float:
        # свежие посты ещё не набрали просмотры — немного докручиваем
        age_h = (now - p.date).total_seconds() / 3600 if p.date else 24
        return p.views / max(0.3, min(1.0, age_h / 24))

    median = statistics.median([adj_views(p) for p in posts]) or 1
    for p in posts:
        views_ratio = min(adj_views(p) / median, 3) / 3                     # 0..1
        er = (p.reactions + 2 * p.forwards + p.replies) / max(p.views, 1)   # вовлечённость
        er_norm = min(er / 0.05, 1)                                          # 5% и выше — топ
        p.engagement = 0.6 * views_ratio + 0.4 * er_norm


def _fingerprint(text: str) -> str:
    return re.sub(r"\W+", "", text.lower())[:120]


def _dedupe(items: list[Item]) -> list[Item]:
    seen: set[str] = set()
    out = []
    for it in items:
        fp = _fingerprint(it.text)
        if fp in seen:
            continue
        seen.add(fp)
        out.append(it)
    return out


async def collect(tg: TgParser, progress: Progress) -> tuple[list[Item], list[str]]:
    errors: list[str] = []
    items: list[Item] = []
    since = datetime.now(timezone.utc) - timedelta(hours=config.HOURS_BACK)

    # 1. каналы
    channels = config.read_list(config.CHANNELS_FILE)
    for i, ch in enumerate(channels, 1):
        await progress(f"📥 каналы {i}/{len(channels)}: {ch}")
        try:
            posts = await tg.fetch(ch, since, config.POSTS_PER_CHANNEL)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{ch}: {e.__class__.__name__}: {e}")
            log.warning("канал %s: %s", ch, e)
            continue
        _engagement(posts)  # считаем по всем постам канала, включая старые
        items.extend(p for p in posts if not db.is_seen(p.key))

    # 2. сайты
    sites = config.read_list(config.SITES_FILE)
    if sites:
        await progress(f"🌐 сайты 0/{len(sites)}…")
        web_items, web_errors = await site_parser.fetch_sites(sites, config.ARTICLES_PER_SITE, progress)
        items.extend(web_items)
        errors.extend(web_errors)

    all_keys = [it.key for it in items]
    items = _dedupe(items)
    if not items:
        return [], errors

    # 3. оценка нейронкой
    await progress(f"🧠 оцениваю {len(items)} материалов…")
    await llm.score_items(items)
    db.mark_seen(all_keys)  # помечаем только после успешной оценки, чтобы при ошибке не потерять

    for it in items:
        it.score = W_INTEREST * it.interest + W_RELEVANCE * it.relevance + W_ENGAGEMENT * it.engagement * 10

    good = sorted((it for it in items if it.relevance >= config.MIN_RELEVANCE), key=lambda x: x.score, reverse=True)

    top: list[Item] = []
    per_source: Counter[str] = Counter()
    for it in good:
        if per_source[it.source] >= config.MAX_PER_SOURCE:
            continue
        per_source[it.source] += 1
        top.append(it)
        if len(top) >= config.TOP_N:
            break

    # 4. из статей пишем посты, посты из каналов отдаём как есть (уникализация — по кнопке)
    web_top = [it for it in top if it.kind == "web"]
    if web_top:
        await progress(f"✍️ пишу посты по {len(web_top)} статьям…")
        results = await asyncio.gather(*(llm.write_post(it) for it in web_top), return_exceptions=True)
        for it, res in zip(web_top, results):
            if isinstance(res, Exception):
                errors.append(f"пост по {it.url}: {res}")
                top.remove(it)
            else:
                it.post = res
    for it in top:
        if it.kind == "tg":
            it.post = it.text

    return top, errors
