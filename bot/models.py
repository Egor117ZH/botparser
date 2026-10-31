from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Item:
    kind: str            # "tg" — пост из канала, "web" — статья с сайта
    key: str             # уникальный ключ, чтобы не присылать повторно
    source: str          # @канал или домен сайта
    url: str
    text: str
    title: str = ""
    date: datetime | None = None

    views: int = 0
    reactions: int = 0
    forwards: int = 0
    replies: int = 0

    engagement: float = 0.5  # 0..1, насколько пост «зашёл» относительно канала
    relevance: float = 0.0   # 0..10 от нейронки
    interest: float = 0.0    # 0..10 от нейронки
    topic: str = ""
    score: float = 0.0       # итоговая оценка 0..10

    post: str = ""                    # текст, который отправим тебе
    media_msg: Any = field(default=None, repr=False)  # сообщение telethon с фото
