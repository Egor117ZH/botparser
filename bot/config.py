import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", encoding="utf-8-sig")

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# старые файлы (до разделения на рубрики) — только чтобы предупредить при запуске
OLD_SOURCE_FILES = [ROOT / "channels.txt", ROOT / "sites.txt"]
DB_PATH = DATA_DIR / "bot.db"
SESSION_PATH = DATA_DIR / "userbot"


def _int(name: str, default: int = 0) -> int:
    val = os.getenv(name, "").strip()
    return int(val) if val else default


def _float(name: str, default: float) -> float:
    val = os.getenv(name, "").strip()
    return float(val) if val else default


# --- доступы ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = _int("ADMIN_ID")

TG_API_ID = _int("TG_API_ID")
TG_API_HASH = os.getenv("TG_API_HASH", "").strip()
TG_PHONE = os.getenv("TG_PHONE", "").strip()
# чтение каналов включается само, когда заполнены все три поля выше
TG_PARSER_ENABLED = bool(TG_API_ID and TG_API_HASH and TG_PHONE)

POLZA_API_KEY = os.getenv("POLZA_API_KEY", "").strip()
POLZA_BASE_URL = os.getenv("POLZA_BASE_URL", "https://polza.ai/api/v1").strip()
POLZA_MODEL = os.getenv("POLZA_MODEL", "openai/gpt-4o-mini").strip()

# --- прокси (для РФ) ---
# PROXY — socks5/http прокси для телеги: socks5://user:pass@1.2.3.4:1080 или http://user:pass@1.2.3.4:8080
PROXY = os.getenv("PROXY", "").strip()
# MTPROXY — MTProto-прокси только для чтения каналов, формат host:port:secret (если есть PROXY — не нужен)
MTPROXY = os.getenv("MTPROXY", "").strip()
# гнать ли через PROXY ещё и парсинг сайтов (нужно, если зарубежные сайты режут РФ)
PROXY_FOR_SITES = os.getenv("PROXY_FOR_SITES", "0").strip().lower() in ("1", "true", "yes", "да")

# --- рубрики ---
# у каждой рубрики свой файл источников: сайты и тг-каналы вперемешку, по одному на строку
CATEGORIES: dict[str, dict] = {
    "news": {
        "name": "Новости",
        "emoji": "📰",
        "file": ROOT / "sources_news.txt",
        "hashtag": os.getenv("NEWS_HASHTAG", "#Новости").strip(),
    },
    "stories": {
        "name": "Мышление",
        "emoji": "🧠",
        "file": ROOT / "sources_stories.txt",
        "hashtag": os.getenv("STORIES_HASHTAG", "").strip(),
    },
}

# --- настройки сбора ---
HOURS_BACK = _int("HOURS_BACK", 48)              # за сколько часов брать посты из каналов
POSTS_PER_CHANNEL = _int("POSTS_PER_CHANNEL", 50)  # максимум постов с одного канала
ARTICLES_PER_SITE = _int("ARTICLES_PER_SITE", 8)   # максимум новых статей с одного сайта
TOP_N = _int("TOP_N", 10)                         # сколько лучших присылать
MAX_PER_SOURCE = _int("MAX_PER_SOURCE", 3)        # не больше N штук с одного источника
MIN_RELEVANCE = _float("MIN_RELEVANCE", 6)        # порог "в тему" (0-10)
MIN_TEXT_LEN = _int("MIN_TEXT_LEN", 120)          # короче — не пост, а мусор
NEWS_MAX_AGE_HOURS = _int("NEWS_MAX_AGE_HOURS", 72)  # новости старше — не новости
HISTORY_SIZE = _int("HISTORY_SIZE", 150)          # сколько прошлых тем помнить, чтобы не повторяться


def is_channel(source: str) -> bool:
    s = source.strip().lower()
    return s.startswith("@") or "t.me/" in s


def sources(category: str) -> list[str]:
    return read_list(CATEGORIES[category]["file"])


def read_list(path: Path) -> list[str]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _same(a: str, b: str) -> bool:
    def norm(x: str) -> str:
        x = x.strip().lower().rstrip("/")
        for p in ("https://", "http://", "www."):
            x = x.removeprefix(p)
        return x
    return norm(a) == norm(b)


def normalize_source(raw: str) -> str | None:
    """Приводит ввод к нормальному виду. None — не похоже ни на сайт, ни на канал."""
    s = raw.strip().strip(",;()<>\"'«»").rstrip(".")
    if not s:
        return None
    low = s.lower()
    if s.startswith("@"):
        return s if len(s) > 2 and " " not in s else None
    if "t.me/" in low:
        return s if low.startswith("http") else "https://" + s.lstrip("/")
    if low.startswith(("http://", "https://")):
        return s
    if "." in s and " " not in s and not s.startswith("."):  # site.ru, site.ru/blog
        return "https://" + s
    return None


def remove_from_list(path: Path, value: str) -> bool:
    if not path.exists():
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [ln for ln in lines if ln.strip().startswith("#") or not _same(ln, value)]
    if len(kept) == len(lines):
        return False
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return True


def append_to_list(path: Path, value: str) -> bool:
    if any(_same(value, x) for x in read_list(path)):
        return False
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text + value + "\n", encoding="utf-8")
    return True


def check() -> list[str]:
    missing = []
    for name, val in [
        ("BOT_TOKEN", BOT_TOKEN),
        ("POLZA_API_KEY", POLZA_API_KEY),
    ]:
        if not val:
            missing.append(name)
    return missing
