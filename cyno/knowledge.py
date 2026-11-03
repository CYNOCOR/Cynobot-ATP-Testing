"""Editable campus knowledge base (data/knowledge.json).

Simple keyword scoring for now; swap for SQLite + embeddings when the KB grows.
"""

import json
import re
from pathlib import Path

KB_PATH = Path(__file__).resolve().parent.parent / "data" / "knowledge.json"


def _load() -> list[dict]:
    return json.loads(KB_PATH.read_text(encoding="utf-8"))["entries"]


def _entries(confirmed_only: bool) -> list[dict]:
    entries = _load()  # re-read each call so edits apply without a restart
    return [e for e in entries if e.get("verified", True)] if confirmed_only else entries


def search_scored(query: str, limit: int = 3, confirmed_only: bool = False) -> list[tuple[int, dict]]:
    words = set(re.findall(r"[a-z]+", query.lower()))
    text = query.lower()
    scored = []
    for entry in _entries(confirmed_only):
        score = sum(2 if " " in k and k in text else (1 if k in words else 0) for k in entry["keywords"])
        if entry["title"].lower() in text:
            score += 3
        if score:
            scored.append((score, entry))
    scored.sort(key=lambda s: s[0], reverse=True)
    return scored[:limit]


def search(query: str, limit: int = 3, confirmed_only: bool = False) -> list[dict]:
    return [e for _, e in search_scored(query, limit, confirmed_only)]


def overlaps(entry: dict) -> list[str]:
    """Titles of other facts sharing keywords with this one: places where answers could contradict."""
    keywords = entry.get("keywords") or []
    if isinstance(keywords, str):
        keywords = keywords.split(",")
    mine = {k.strip().lower() for k in keywords if k.strip()} | set(suggest_keywords(entry.get("title") or ""))
    return [
        e["title"]
        for e in _load()
        if e["id"] != entry.get("id") and mine & ({k.lower() for k in e["keywords"]} | set(suggest_keywords(e["title"])))
    ]


STOPWORDS = {"the", "a", "an", "of", "and", "to", "in", "on", "at", "for", "is", "are", "iit", "where", "how", "what"}


def suggest_keywords(title: str, answer: str = "") -> list[str]:
    """Lowercase title words (minus filler), so a new fact is findable even if no keywords were typed."""
    words = [w for w in re.findall(r"[a-z]+", title.lower()) if w not in STOPWORDS and len(w) > 2]
    phrase = title.lower().strip()
    return list(dict.fromkeys(([phrase] if " " in phrase else []) + words))


def _save(entries: list[dict]):
    data = json.loads(KB_PATH.read_text(encoding="utf-8"))
    data["entries"] = entries
    KB_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def upsert(entry: dict) -> dict:
    """Add or update a fact from the control app. Returns the stored entry."""
    title = (entry.get("title") or "").strip()
    answer = (entry.get("answer") or "").strip()
    if not title or not answer:
        raise ValueError("A fact needs a title and an answer.")
    keywords = entry.get("keywords") or []
    if isinstance(keywords, str):
        keywords = keywords.split(",")
    keywords = [k.strip().lower() for k in keywords if k.strip()] or suggest_keywords(title, answer)

    entries = _load()
    entry_id = entry.get("id") or re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_") or "fact"
    if not entry.get("id"):  # new fact: make the id unique
        base, n, taken = entry_id, 2, {e["id"] for e in entries}
        while entry_id in taken:
            entry_id, n = f"{base}_{n}", n + 1
    stored = {
        "id": entry_id,
        "title": title,
        "keywords": keywords,
        "answer": answer,
        "source": (entry.get("source") or "Added in Cyno Control").strip(),
        "verified": bool(entry.get("verified", True)),
    }
    for i, e in enumerate(entries):
        if e["id"] == entry_id:
            entries[i] = stored
            break
    else:
        entries.append(stored)
    _save(entries)
    return stored


def delete(entry_id: str):
    _save([e for e in _load() if e["id"] != entry_id])


def topics() -> list[str]:
    return [e["title"] for e in _load()]


def as_prompt(confirmed_only: bool = False) -> str:
    """The whole KB as plain text, for the offline model's system prompt (small KB, no tool calls)."""
    return "\n".join(f"- {e['title']}: {e['answer']}" for e in _entries(confirmed_only))
