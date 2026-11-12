"""Editable campus knowledge base (data/knowledge.json).

Simple keyword scoring for now; swap for SQLite + embeddings when the KB grows.
"""

import json
import re
from pathlib import Path

KB_PATH = Path(__file__).resolve().parent.parent / "data" / "knowledge.json"
MEDIA_DIR = KB_PATH.parent / "media"  # pictures shown on the chest card (served at /media/)


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


# ---- Chest card choice ---------------------------------------------------------------
# A keyword in the question alone is weak evidence (a visitor can say "library" in passing),
# so the card follows what Cynobot actually says: a fact is shown once the spoken answer
# contains words that only that fact has (names, numbers, emails), with the question's
# keywords only breaking ties. If Cynobot declines or talks about something else, no card.

ANSWER_STOPWORDS = {
    "the", "and", "for", "are", "was", "with", "you", "your", "can", "its", "it's", "has", "have", "that",
    "this", "from", "which", "who", "also", "one", "our", "there", "they", "their", "includes", "include",
    "offers", "offer", "other", "into", "out", "all", "any", "but", "not", "iit", "institute", "informatics",
    "technology", "colombo", "road", "university", "students", "student", "first", "best", "here", "phone",
}
DECLINE = re.compile(r"front desk|not sure|don't know|do not know|don't have that|no information", re.I)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]+|\d+", text.lower()) if t not in ANSWER_STOPWORDS and (len(t) > 2 or t.isdigit())}


def _answer_score(entry: dict, spoken: set[str], df: dict[str, int]) -> float:
    """How much of this fact's own wording Cynobot said; words shared by many facts count little."""
    return sum(1 / df[t] for t in _tokens(entry["answer"]) if t in spoken)


def pick_card(question: str, spoken: str, confirmed_only: bool = False) -> tuple[float, dict] | None:
    """The fact to show for this exchange, or None. Call again as more of the answer arrives."""
    if not spoken.strip() or DECLINE.search(spoken):
        return None
    entries = _entries(confirmed_only)
    df: dict[str, int] = {}
    for e in entries:
        for t in _tokens(e["answer"]):
            df[t] = df.get(t, 0) + 1
    said = _tokens(spoken)
    asked = {e["id"]: s for s, e in search_scored(question, limit=len(entries), confirmed_only=confirmed_only)}
    echoed = {e["id"]: s for s, e in search_scored(spoken, limit=len(entries), confirmed_only=confirmed_only)}
    best = None
    for e in entries:
        a, q, k = _answer_score(e, said, df), asked.get(e["id"], 0), echoed.get(e["id"], 0)
        # Shown when the answer clearly comes from this fact, or the answer and question agree on it.
        if a >= 2 or (a >= 1 and (q or k)) or (q and k):
            score = a + 0.5 * k + 0.75 * min(q, 2)
            if not best or score > best[0]:
                best = (score, e)
    return best


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
    # Optional chest visuals: a picture from data/media and a link shown as a QR code.
    if entry.get("icon") in ICONS:
        stored["icon"] = entry["icon"]
    image = (entry.get("image") or "").strip()
    link = (entry.get("link") or "").strip()
    if image:
        stored["image"] = Path(image).name
    if link:
        if not re.match(r"(https?://|mailto:)", link):
            raise ValueError("The QR code link must start with http://, https:// or mailto:")
        stored["link"] = link
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
    entries = _entries(confirmed_only)
    facts = "\n".join(f"- {e['title']}: {e['answer']}" for e in entries)
    screen = "\n".join(f"- {e['title']}: {_visual_note(e)}" for e in entries if _visual_note(e))
    if screen:
        facts += "\n\nWhat your chest screen shows with each fact (never read this list aloud):\n" + screen
    return facts


def _visual_note(entry: dict) -> str:
    """Tell the model what the chest shows with this fact, so it can say so instead of 'ask the front desk'."""
    parts = []
    if entry.get("image") and (MEDIA_DIR / entry["image"]).is_file():
        parts.append("picture of " + Path(entry["image"]).stem.replace("-", " ").replace("_", " "))
    if entry.get("link"):
        parts.append(qr_purpose(entry["link"]))
    return ", ".join(parts)


MAP_LINK = re.compile(r"https?://(?:share\.google|maps\.app\.goo\.gl|goo\.gl/maps|(?:www\.)?google\.[a-z.]+/maps|maps\.google\.)", re.I)


def qr_purpose(link: str) -> str:
    """What scanning this QR code does, in words Cynobot can say (so it never calls an email QR 'directions')."""
    if link.startswith("mailto:"):
        return f"QR code to send an email to {link[7:].split('?')[0]}"
    if MAP_LINK.match(link):
        return "QR code that opens directions in Google Maps"
    domain = re.sub(r"^https?://(www\.)?", "", link).split("/")[0]
    page = "contact page" if "contact" in link.lower() else "website"
    return f"QR code that opens the {domain} {page}"


# The line drawing the chest particles form for a fact. A fact can set its own with "icon";
# otherwise it is guessed from these words in the fact's id, title and keywords.
ICONS = ("pin", "cap", "mail", "phone", "book", "globe", "people", "chip", "building")
_ICON_WORDS = [  # first match wins, so the more specific topics come first
    ("people", ("dean", "team", "staff", "lecturer")),
    ("mail", ("apply", "admission process", "how to apply", "registration")),
    ("phone", ("contact", "hotline", "phone")),
    ("globe", ("partner", "universit")),
    ("chip", ("cynobot", "cynocor", "robot")),
    ("cap", ("degree", "undergraduate", "postgraduate", "foundation", "course", "programme")),
    ("book", ("facilit", "library")),
    ("pin", ("campus", "centre", "center", "office", "auditorium", "location", "address", "map")),
    ("building", ("about iit", "history", "founded")),
]


def icon_for(entry: dict) -> str:
    if entry.get("icon") in ICONS:
        return entry["icon"]
    text = " ".join([entry.get("id", ""), entry.get("title", ""), *entry.get("keywords", [])]).lower().replace("_", " ")
    return next((icon for icon, words in _ICON_WORDS if any(w in text for w in words)), "")


def card(entry: dict) -> dict:
    """What the chest display shows for a fact."""
    out = {"title": entry["title"], "body": entry["answer"]}
    if icon_for(entry):
        out["icon"] = icon_for(entry)
    if entry.get("image") and (MEDIA_DIR / entry["image"]).is_file():
        out["image"] = f"/media/{entry['image']}"
    if entry.get("link"):
        out["link"] = entry["link"]
    return out


def media_files() -> list[str]:
    exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
    return sorted(p.name for p in MEDIA_DIR.glob("*") if p.suffix.lower() in exts) if MEDIA_DIR.is_dir() else []
