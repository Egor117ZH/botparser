import asyncio
import logging
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
import trafilatura
from bs4 import BeautifulSoup

from . import config, db
from .models import Item

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "ru,en;q=0.8",
}

# ссылки, которые точно не статьи
BAD_PARTS = (
    "/tag", "/tags", "/category", "/categories", "/author", "/page/", "/login", "/register",
    "/search", "/user", "/cart", "/basket", "/account", "/privacy", "/contacts", "/about",
    ".jpg", ".jpeg", ".png", ".gif", ".pdf", ".zip",
)


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _is_feed(content_type: str, body: str) -> bool:
    head = body[:500].lstrip().lower()
    return "xml" in content_type or "rss" in content_type or head.startswith(("<?xml", "<rss", "<feed"))


def _feed_links(body: str) -> list[tuple[str, str]]:
    feed = feedparser.parse(body)
    return [(e.link, e.get("title", "")) for e in feed.entries if e.get("link")]


def _find_feed(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.find_all("link", rel="alternate"):
        t = (link.get("type") or "").lower()
        if ("rss" in t or "atom" in t) and link.get("href"):
            return urljoin(base_url, link["href"])
    return None


def _html_links(html: str, base_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    base = _domain(base_url)
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0]
        p = urlparse(href)
        if p.scheme not in ("http", "https") or _domain(href) != base:
            continue
        path = p.path.rstrip("/").lower()
        if len(path) < 12 or any(b in path for b in BAD_PARTS):
            continue
        title = a.get_text(" ", strip=True)
        if len(title) < 20 or href in seen:
            continue
        seen.add(href)
        out.append((href, title))
    return out


async def _fetch_article(client: httpx.AsyncClient, url: str, title: str, source: str) -> Item | None:
    try:
        r = await client.get(url)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        log.info("не открылась статья %s: %s", url, e)
        return None

    html = r.text
    text = await asyncio.to_thread(
        trafilatura.extract, html, url=url, include_comments=False, include_tables=False, favor_precision=True
    )
    if not text or len(text) < 300:
        return None
    if not title:
        meta = await asyncio.to_thread(trafilatura.extract_metadata, html)
        title = (meta.title if meta else "") or ""

    return Item(kind="web", key=f"web:{url}", source=source, url=url, text=text[:6000], title=title)


async def fetch_site(client: httpx.AsyncClient, site_url: str, limit: int) -> list[Item]:
    if not site_url.startswith(("http://", "https://")):
        site_url = "https://" + site_url

    r = await client.get(site_url)
    r.raise_for_status()
    final_url = str(r.url)
    body = r.text

    links: list[tuple[str, str]] = []
    if _is_feed(r.headers.get("content-type", ""), body):
        links = _feed_links(body)
    else:
        feed_url = _find_feed(body, final_url)
        if feed_url:
            try:
                fr = await client.get(feed_url)
                links = _feed_links(fr.text)
            except Exception:  # noqa: BLE001
                links = []
        if not links:
            links = _html_links(body, final_url)

    links = [(u, t) for u, t in links if not db.is_seen(f"web:{u}")][:limit]
    source = _domain(final_url)
    results = await asyncio.gather(*(_fetch_article(client, u, t, source) for u, t in links))
    return [it for it in results if it]


async def fetch_sites(sites: list[str], limit: int, progress=None) -> tuple[list[Item], list[str]]:
    items: list[Item] = []
    errors: list[str] = []
    sem = asyncio.Semaphore(4)
    done = 0

    proxy = config.PROXY if (config.PROXY_FOR_SITES and config.PROXY) else None
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=25, proxy=proxy) as client:

        async def one(site: str) -> None:
            nonlocal done
            async with sem:
                try:
                    items.extend(await fetch_site(client, site, limit))
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{site}: {e.__class__.__name__}")
                    log.warning("сайт %s: %s", site, e)
                done += 1
                if progress:
                    await progress(f"🌐 сайты {done}/{len(sites)}…")

        await asyncio.gather(*(one(s) for s in sites))
    return items, errors
