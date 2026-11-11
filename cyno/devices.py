"""Which microphone, speaker and camera Cynobot uses (data/devices.json).

The chest page runs in a browser, so the choice is applied there: it reports the devices
it can see, Cyno Control shows that list, and the page then opens the chosen ones. Only
Cynobot is affected; the computer's own sound settings and other apps are left alone,
and the same code works on macOS and Windows. Devices are remembered by name, because
browser device ids change.
"""

import json
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "devices.json"
KINDS = ("mic", "speaker", "camera")

# What the chest page last reported: {"mic": [names], "speaker": [...], "camera": [...]}
seen: dict[str, list[str]] = {k: [] for k in KINDS}


def load() -> dict:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {k: str(data.get(k) or "") for k in KINDS}  # "" = the browser's default


def save(choice: dict) -> dict:
    current = load()
    for k in KINDS:
        if k in choice:
            current[k] = str(choice[k] or "")[:200]
    PATH.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return current


def report(found: dict) -> dict:
    if not any(found.get(k) for k in KINDS):
        return seen  # a page without mic/camera permission sees no names: keep the last full list
    for k in KINDS:
        names = [str(n)[:200] for n in (found.get(k) or []) if str(n).strip()]
        seen[k] = list(dict.fromkeys(names))[:30]
    return seen
