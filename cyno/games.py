"""Chest-screen games: settings, content and today's best scores.

- data/games.json         on/off switches and time limit (set in Cyno Control)
- data/game_content.json  riddles and the Find Your Degree quiz (team-editable)
- data/game_scores.json   today's best per game; no names, cleared each day
- data/media/puzzles/     pictures for the picture puzzle (managed in Cyno Control)

Tap games run entirely in the chest page, so they work offline. Word Chain is played
by voice with the online brain and is hidden when Cynobot is offline.
"""

import json
import re
import time
from datetime import date
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
SETTINGS_PATH = DATA / "games.json"
CONTENT_PATH = DATA / "game_content.json"
SCORES_PATH = DATA / "game_scores.json"
PUZZLE_DIR = DATA / "media" / "puzzles"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

# id -> (title, one-line description, needs the online voice brain)
GAMES = {
    "riddles": ("Brain Riddles", "Five quick riddles. How many can you crack?", False),
    "memory": ("Memory Match", "Flip the cards and find every pair.", False),
    "puzzle": ("Picture Puzzle", "Put the broken picture back together.", False),
    "degree": ("Find Your Degree", "Answer a few questions and meet your IIT match.", False),
    "wordchain": ("Word Chain", "Play by voice: each word starts with the last letter.", True),
}
# Lower is better for these (moves or seconds); higher is better for the rest.
LOWER_IS_BETTER = {"memory", "puzzle"}

DEFAULT_SETTINGS = {
    "enabled": True,  # master switch
    "games": {g: True for g in GAMES},
    "time_limit_secs": 120,  # one game, then back to receptionist mode
    "idle_secs": 30,  # no touch for this long closes a tap game
}


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def load_settings() -> dict:
    data = _read(SETTINGS_PATH, {})
    out = {
        "enabled": bool(data.get("enabled", DEFAULT_SETTINGS["enabled"])),
        "games": {g: bool((data.get("games") or {}).get(g, True)) for g in GAMES},
    }
    for key, lo, hi in (("time_limit_secs", 30, 900), ("idle_secs", 10, 300)):
        try:
            out[key] = max(lo, min(hi, int(data.get(key, DEFAULT_SETTINGS[key]))))
        except (TypeError, ValueError):
            out[key] = DEFAULT_SETTINGS[key]
    return out


def save_settings(changes: dict) -> dict:
    current = load_settings()
    if "enabled" in changes:
        current["enabled"] = bool(changes["enabled"])
    for g, on in (changes.get("games") or {}).items():
        if g in GAMES:
            current["games"][g] = bool(on)
    for key in ("time_limit_secs", "idle_secs"):
        if key in changes:
            current[key] = changes[key]
    SETTINGS_PATH.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    return load_settings()  # re-read so limits are applied


def enabled_games(online: bool = True) -> list[str]:
    cfg = load_settings()
    if not cfg["enabled"]:
        return []
    return [g for g, (_, _, needs_online) in GAMES.items() if cfg["games"][g] and (online or not needs_online)]


def content() -> dict:
    return _read(CONTENT_PATH, {"riddles": [], "degree": {}})


# ---- picture puzzle images ----


def puzzle_images() -> list[str]:
    """URLs of the puzzle pictures; falls back to the campus photos until some are added."""
    own = sorted(p.name for p in PUZZLE_DIR.glob("*") if p.suffix.lower() in IMAGE_EXTS) if PUZZLE_DIR.is_dir() else []
    if own:
        return [f"/media/puzzles/{n}" for n in own]
    media = PUZZLE_DIR.parent
    photos = sorted(p.name for p in media.glob("*.jpg")) if media.is_dir() else []
    return [f"/media/{n}" for n in photos if "logo" not in n.lower()]


def puzzle_files() -> list[str]:
    return sorted(p.name for p in PUZZLE_DIR.glob("*") if p.suffix.lower() in IMAGE_EXTS) if PUZZLE_DIR.is_dir() else []


def add_puzzle_image(source: Path) -> str:
    import shutil

    if source.suffix.lower() not in IMAGE_EXTS:
        raise ValueError("Use a PNG, JPG or WebP picture.")
    PUZZLE_DIR.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", source.name).strip("-") or "picture" + source.suffix.lower()
    shutil.copyfile(source, PUZZLE_DIR / name)
    return name


def remove_puzzle_image(name: str):
    target = PUZZLE_DIR / Path(name).name  # never outside the puzzles folder
    if target.is_file():
        target.unlink()


# ---- today's best (no names) ----


def best_today() -> dict:
    data = _read(SCORES_PATH, {})
    return data.get("best", {}) if data.get("date") == date.today().isoformat() else {}


def submit_score(game: str, level: str, score: float) -> dict:
    """Record a finished game. Returns {"best": today's best for this game+level, "is_best": bool}."""
    if game not in GAMES:
        raise ValueError("Unknown game")
    score = float(score)
    if not (0 <= score <= 100000):
        raise ValueError("Score out of range")
    key = f"{game}:{re.sub(r'[^a-z0-9]', '', str(level).lower())[:12] or 'any'}"
    best = best_today()
    old = best.get(key)
    better = old is None or (score < old if game in LOWER_IS_BETTER else score > old)
    if better:
        best[key] = score
        SCORES_PATH.write_text(json.dumps({"date": date.today().isoformat(), "best": best}, indent=2) + "\n", encoding="utf-8")
    return {"best": best[key], "is_best": better}


# ---- what the chest page needs ----


def _admissions_link() -> str:
    """The QR shown with a Find Your Degree result: the link on the 'How to apply' fact."""
    from cyno import knowledge

    for entry in knowledge._load():
        if entry.get("id") == "admission_process":
            return entry.get("link", "")
    return ""


def public_config(online: bool) -> dict:
    cfg = load_settings()
    live = enabled_games(online)
    data = content()
    return {
        "enabled": bool(live),
        "games": [{"id": g, "title": GAMES[g][0], "about": GAMES[g][1], "voice": GAMES[g][2]} for g in live],
        "time_limit_secs": cfg["time_limit_secs"],
        "idle_secs": cfg["idle_secs"],
        "riddles": data.get("riddles", []),
        "degree": data.get("degree", {}),
        "puzzle_images": puzzle_images(),
        "admissions_link": _admissions_link(),
        "best": best_today(),
        "lower_is_better": sorted(LOWER_IS_BETTER),
        "ts": int(time.time() * 1000),
    }


# ---- voice: opening games and playing Word Chain ----

# What a visitor might say -> which screen to open ("menu" = the games list).
_VOICE = [
    ("wordchain", r"\bword\s?chain\b"),
    ("degree", r"\b(find (my|your|a) degree|which (degree|course|programme|program) (suits|fits|is (right|best) for)|what should i study)\b"),
    ("riddles", r"\b(riddles?|brain (puzzle|teaser|game)s?)\b"),
    ("memory", r"\bmemory (match|game|cards?)\b"),
    ("puzzle", r"\b(picture|jigsaw) puzzle\b"),
    # Any question about games shows the page with all of them.
    ("menu", r"\bgames\b|\bpuzzles\b|\b(play|open|show|start|have|any|about|want|a|the|another)\b.{0,25}\bgame\b(?! plan)|\bgame (menu|please|time)\b|\bplay (something|with (me|you))\b"),
]


def voice_request(text: str, online: bool = True) -> str | None:
    """'menu' or a game id if the visitor asked to play, else None."""
    live = enabled_games(online)
    if not live:
        return None
    text = text.lower()
    for game, pattern in _VOICE:
        if re.search(pattern, text) and (game == "menu" or game in live):
            return game
    return None


def prompt_block(online: bool = True) -> str:
    """Added to Cynobot's instructions while games are on."""
    live = enabled_games(online)
    if not live:
        return ""
    names = ", ".join(GAMES[g][0] for g in live)
    out = f"""
Games: visitors can play short games on your chest screen: {names}. When a visitor asks to play
a game, asks about games, or asks for one of these by name, the screen shows it by itself. If they
asked about games in general, the screen shows all of them: name the games in one short, cheerful
sentence and invite them to tap one. If they asked for one game, just say it is open on your chest screen. Tap games are played by touch, so do not try to
run them by voice, and do not read out puzzle answers. If someone seems bored or asks what you
can do, you may mention the games.
"""
    if "wordchain" in live:
        out += """
Word Chain is the one game you play by voice. When the visitor asks for Word Chain:
- Start with one easy English word, then tell them their letter.
- Each turn they say a word starting with the last letter of your word. If it does, and it was
  not used before, answer with a new easy word that starts with the last letter of THEIR word.
- Always answer in exactly this form and nothing else: "Robot. Your letter is T."
- If their word starts with the wrong letter or was already used, kindly say so in a few words
  and give them one more try with the same letter.
- Use common, friendly words a child would know. Never use rude words or names of people.
- Stop when they say stop or ask about something else, and tell them well played.
"""
    return out
