import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

CHANNELS_FILE = ROOT / "channels.txt"
SITES_FILE = ROOT / "sites.txt"
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

POLZA_API_KEY = os.getenv("POLZA_API_KEY", "").strip()
POLZA_BASE_URL = os.getenv("POLZA_BASE_URL", "https://polza.ai/api/v1").strip()
POLZA_MODEL = os.getenv("POLZA_MODEL", "openai/gpt-4o-mini").strip()

# --- настройки сбора ---
HOURS_BACK = _int("HOURS_BACK", 48)              # за сколько часов брать посты из каналов
POSTS_PER_CHANNEL = _int("POSTS_PER_CHANNEL", 50)  # максимум постов с одного канала
ARTICLES_PER_SITE = _int("ARTICLES_PER_SITE", 8)   # максимум новых статей с одного сайта
TOP_N = _int("TOP_N", 10)                         # сколько лучших присылать
MAX_PER_SOURCE = _int("MAX_PER_SOURCE", 3)        # не больше N штук с одного источника
MIN_RELEVANCE = _float("MIN_RELEVANCE", 6)        # порог "в тему" (0-10)
MIN_TEXT_LEN = _int("MIN_TEXT_LEN", 120)          # короче — не пост, а мусор


def read_list(path: Path) -> list[str]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def append_to_list(path: Path, value: str) -> bool:
    if value in read_list(path):
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
        ("TG_API_ID", TG_API_ID),
        ("TG_API_HASH", TG_API_HASH),
        ("TG_PHONE", TG_PHONE),
        ("POLZA_API_KEY", POLZA_API_KEY),
    ]:
        if not val:
            missing.append(name)
    return missing
