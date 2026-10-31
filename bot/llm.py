import asyncio
import json
import logging
import re

from openai import AsyncOpenAI, BadRequestError

from . import config, prompts
from .models import Item

log = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=config.POLZA_API_KEY, base_url=config.POLZA_BASE_URL, timeout=120, max_retries=2)

SCORE_BATCH = 12
_sem = asyncio.Semaphore(3)


async def chat(system: str, user: str, temperature: float = 0.7, json_mode: bool = False) -> str:
    kwargs = dict(
        model=config.POLZA_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
    )
    async with _sem:
        if json_mode:
            try:
                resp = await client.chat.completions.create(response_format={"type": "json_object"}, **kwargs)
                return resp.choices[0].message.content or ""
            except BadRequestError:
                pass  # модель не умеет json_mode — просим просто текстом
        resp = await client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""


def _parse_json(s: str) -> dict:
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {}


def _clean(text: str) -> str:
    text = text.strip().strip('"«»').strip()
    return re.sub(r"^(пост|текст поста)\s*:\s*", "", text, flags=re.I)


async def _score_batch(batch: list[Item]) -> None:
    lines = []
    for i, it in enumerate(batch):
        body = (it.title + "\n" if it.title else "") + it.text[:700]
        lines.append(f"### id={i}\n{body}")
    raw = await chat(prompts.SCORE_SYSTEM, "\n\n".join(lines), temperature=0.1, json_mode=True)
    data = _parse_json(raw)
    for row in data.get("items", []):
        try:
            it = batch[int(row["id"])]
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        it.relevance = float(row.get("relevance", 0) or 0)
        it.interest = float(row.get("interest", 0) or 0)
        it.topic = str(row.get("topic", "") or "")


async def score_items(items: list[Item]) -> None:
    batches = [items[i : i + SCORE_BATCH] for i in range(0, len(items), SCORE_BATCH)]
    results = await asyncio.gather(*(_score_batch(b) for b in batches), return_exceptions=True)
    errors = [r for r in results if isinstance(r, Exception)]
    if errors and len(errors) == len(batches):
        raise errors[0]
    for e in errors:
        log.warning("батч оценки упал: %s", e)


async def write_post(item: Item) -> str:
    user = f"Заголовок: {item.title}\n\n{item.text}"
    return _clean(await chat(prompts.WRITE_SYSTEM, user, temperature=0.8))


async def uniqualize(text: str) -> str:
    return _clean(await chat(prompts.UNIQ_SYSTEM, text, temperature=0.9))
