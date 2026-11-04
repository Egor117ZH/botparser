import asyncio
import logging
import re
import statistics
from difflib import SequenceMatcher
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


def _similar(a: str, b: str) -> bool:
    a, b = _fingerprint(a), _fingerprint(b)
    return bool(a and b) and SequenceMatcher(None, a, b).ratio() > 0.85


async def collect(tg: TgParser, category: str, progress: Progress) -> tuple[list[Item], list[str]]:
    errors: list[str] = []
    items: list[Item] = []
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=config.HOURS_BACK)

    srcs = config.sources(category)
    channels = [s for s in srcs if config.is_channel(s)]
    sites = [s for s in srcs if not config.is_channel(s)]
    if channels and not tg.enabled:
        errors.append(f"каналы пропущены ({len(channels)} шт.) — чтение тг выключено")
        channels = []

    # 1. каналы
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
    if sites:
        await progress(f"🌐 сайты 0/{len(sites)}…")
        web_items, web_errors = await site_parser.fetch_sites(sites, config.ARTICLES_PER_SITE, progress)
        items.extend(it for it in web_items if not db.is_seen(it.key))
        errors.extend(web_errors)

    for it in items:
        it.category = category

    # новости — только свежие (если дата известна)
    if category == "news":
        max_age = timedelta(hours=config.NEWS_MAX_AGE_HOURS)
        old = [it for it in items if it.date and now - it.date > max_age]
        db.mark_seen([it.key for it in old])
        items = [it for it in items if not (it.date and now - it.date > max_age)]

    # 3. дубли: одинаковый текст + то, о чём уже писали раньше
    history = db.get_history(category, config.HISTORY_SIZE)
    hist_titles = [h["title"] for h in history if h["title"]]
    all_keys = [it.key for it in items]
    items = _dedupe(items)
    items = [it for it in items if not (it.title and any(_similar(it.title, t) for t in hist_titles))]
    if not items:
        db.mark_seen(all_keys)
        return [], errors

    # 4. оценка нейронкой
    await progress(f"🧠 оцениваю {len(items)} материалов…")
    await llm.score_items(items, category)
    db.mark_seen(all_keys)  # помечаем только после успешной оценки, чтобы при ошибке не потерять

    for it in items:
        it.score = W_INTEREST * it.interest + W_RELEVANCE * it.relevance + W_ENGAGEMENT * it.engagement * 10

    good = sorted((it for it in items if it.relevance >= config.MIN_RELEVANCE), key=lambda x: x.score, reverse=True)

    cands: list[Item] = []
    per_source: Counter[str] = Counter()
    for it in good:
        if per_source[it.source] >= config.MAX_PER_SOURCE:
            continue
        per_source[it.source] += 1
        cands.append(it)
        if len(cands) >= config.TOP_N * 2:
            break
    if not cands:
        return [], errors

    # 5. отбор без повторов: между собой и с тем, что уже выходило
    await progress(f"🧹 убираю повторы среди {len(cands)} лучших…")
    try:
        top = await llm.select_unique(cands, [h["gist"] for h in history], category, config.TOP_N)
    except Exception as e:  # noqa: BLE001
        log.warning("отбор без повторов упал: %s", e)
        errors.append(f"не смог проверить повторы нейронкой: {e.__class__.__name__}")
        top = cands[: config.TOP_N]
        for it in top:
            it.gist = it.title or it.text[:80]
    if not top:
        return [], errors

    # 6. пишем посты: один материал = один пост
    await progress(f"✍️ пишу {len(top)} постов…")
    results = await asyncio.gather(*(llm.write_post(it) for it in top), return_exceptions=True)
    done: list[Item] = []
    for it, res in zip(top, results):
        if isinstance(res, Exception):
            errors.append(f"пост по {it.url}: {res.__class__.__name__}")
            continue
        it.post = res
        db.add_history(category, it.gist, it.title, it.url)
        done.append(it)

    return done, errors
