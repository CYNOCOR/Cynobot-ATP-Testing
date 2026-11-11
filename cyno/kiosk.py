"""Locked chest screen (kiosk) with a PIN.

A web page cannot stop someone closing its browser window, so the lock works at the
browser level: Cyno opens the chest screen in Chrome or Edge kiosk mode, which is full
screen with no close button, tabs or address bar. The only way out on the touchscreen
is the PIN pad on the page (or Cyno Control). Entering the right PIN makes the server
close that browser window.

- data/kiosk.json        the PIN (salted hash, never the PIN itself)
- data/kiosk_profile/    the kiosk browser's own profile, so it is a separate window we
                         can close without touching the team's normal browser

Works on macOS and Windows. A keyboard can still quit a kiosk browser (Alt+F4, Cmd+Q),
so don't leave one attached to the robot.
"""

import hashlib
import hmac
import json
import os
import platform
import secrets
import shutil
import subprocess
import time
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
PATH = DATA / "kiosk.json"
PROFILE = DATA / "kiosk_profile"

MAX_TRIES = 5  # wrong PINs before the pad locks
LOCKOUT_SECS = 60

_proc: subprocess.Popen | None = None
_fails = 0
_locked_until = 0.0
# Cyno Control proves it is the operator (not the chest page) with this token, read from disk.
TOKEN = secrets.token_urlsafe(24)


def _read() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _hash(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200_000).hex()


def has_pin() -> bool:
    data = _read()
    return bool(data.get("pin_hash") and data.get("salt"))


def set_pin(pin: str):
    pin = str(pin).strip()
    if not (pin.isdigit() and 4 <= len(pin) <= 8):
        raise ValueError("The PIN must be 4 to 8 digits.")
    salt = secrets.token_hex(16)
    data = _read()
    data.update(salt=salt, pin_hash=_hash(pin, salt))
    PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def publish_token():
    """Called when the server starts: lets Cyno Control (same computer) open and close the kiosk."""
    data = _read()
    data["token"] = TOKEN
    PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def read_token() -> str:
    return _read().get("token", "")


def token_ok(token: str) -> bool:
    return bool(token) and hmac.compare_digest(str(token), TOKEN)


def check_pin(pin: str) -> dict:
    """{"ok": bool, "wait": seconds the pad is locked, "left": tries left}."""
    global _fails, _locked_until
    now = time.time()
    if now < _locked_until:
        return {"ok": False, "wait": int(_locked_until - now) + 1, "left": 0}
    data = _read()
    good = has_pin() and hmac.compare_digest(_hash(str(pin), data["salt"]), data["pin_hash"])
    if good:
        _fails = 0
        return {"ok": True, "wait": 0, "left": MAX_TRIES}
    _fails += 1
    if _fails >= MAX_TRIES:
        _fails, _locked_until = 0, now + LOCKOUT_SECS
        return {"ok": False, "wait": LOCKOUT_SECS, "left": 0}
    return {"ok": False, "wait": 0, "left": MAX_TRIES - _fails}


def find_browser() -> str | None:
    """Chrome or Edge: both have kiosk mode and let Cynobot choose its speaker."""
    system = platform.system()
    if system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
    elif system == "Windows":
        roots = [os.environ.get(v, "") for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        candidates = [str(Path(r) / sub) for r in roots if r for sub in (
            r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe")]
    else:
        candidates = []
    for name in ("google-chrome", "chrome", "chromium", "chromium-browser", "microsoft-edge", "msedge"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    return next((c for c in candidates if c and Path(c).is_file()), None)


def is_open() -> bool:
    return _proc is not None and _proc.poll() is None


def open_locked(url: str):
    """Open the chest screen in a kiosk window. Needs a PIN first, or nobody could get out."""
    global _proc
    if not has_pin():
        raise ValueError("Set a PIN first.")
    if is_open():
        return
    browser = find_browser()
    if not browser:
        raise ValueError("Google Chrome or Microsoft Edge is needed for the locked screen.")
    PROFILE.mkdir(parents=True, exist_ok=True)
    args = [
        browser,
        "--kiosk",
        f"--user-data-dir={PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-pinch",
        "--overscroll-history-navigation=0",
        "--disable-features=Translate,TouchpadOverscrollHistoryNavigation",
        "--disable-session-crashed-bubble",
        "--noerrdialogs",
        # The kiosk shows only Cynobot's own page, so let it use the mic and camera
        # without a permission pop-up nobody could answer on a locked screen.
        "--use-fake-ui-for-media-stream",
        "--autoplay-policy=no-user-gesture-required",
        url,
    ]
    _proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def close():
    global _proc
    if _proc is not None and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proc.kill()
    _proc = None


def status() -> dict:
    return {"has_pin": has_pin(), "open": is_open(), "browser": bool(find_browser())}
