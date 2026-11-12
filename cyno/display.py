"""Face display alignment, saved in data/display.json.

The glowing frame around the face is inset from each screen edge. Once the real
head screen is mounted behind its cut-out, each side can be nudged from Cyno
Control so the ring lines up with the opening. Values are pixels.
"""

import json
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "display.json"
DEFAULT_FRAME = {"top": 16, "right": 16, "bottom": 16, "left": 16, "radius": 36}
LIMITS = {"top": (0, 600), "right": (0, 600), "bottom": (0, 600), "left": (0, 600), "radius": (0, 400)}


def _clean(frame: dict) -> dict:
    out = dict(DEFAULT_FRAME)
    for key, (lo, hi) in LIMITS.items():
        try:
            out[key] = max(lo, min(hi, int(round(float(frame.get(key, out[key]))))))
        except (TypeError, ValueError):
            pass
    return out


def load_frame() -> dict:
    try:
        return _clean(json.loads(PATH.read_text(encoding="utf-8")).get("face_frame") or {})
    except (OSError, ValueError):
        return dict(DEFAULT_FRAME)


def save_frame(frame: dict) -> dict:
    frame = _clean(frame)
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data["face_frame"] = frame
    PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return frame


# ---- chest background (the particle scene) ----
# auto: full scene, and the page lowers the particle count by itself if the frame rate drops.
# full / light: a fixed particle count. off: a plain still background (no 3D at all).
SCENES = ("auto", "full", "light", "off")

# What the chest page last reported about its own speed (shown in Cyno Control).
chest_stats: dict = {}


def load_scene() -> str:
    try:
        value = json.loads(PATH.read_text(encoding="utf-8")).get("chest_scene")
    except (OSError, ValueError):
        value = None
    return value if value in SCENES else "auto"


def save_scene(value: str) -> str:
    if value not in SCENES:
        raise ValueError("Unknown background setting")
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data["chest_scene"] = value
    PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return value
