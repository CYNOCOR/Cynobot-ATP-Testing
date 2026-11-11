"""Cyno Control: a desktop app to run, watch and configure the robot brain.

    python -m cyno.control

A native window (pywebview: WebKit on macOS, Edge WebView2 on Windows) showing ui.html.
The methods of `Api` are callable from the page as window.pywebview.api.<name>().
"""

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from pathlib import Path

import httpx
import psutil
import webview

from cyno.control import envfile

ROOT = envfile.ROOT
UI = Path(__file__).resolve().parent / "ui.html"
PREFS = ROOT / ".cyno-control.json"
IS_WIN = platform.system() == "Windows"
OLLAMA = "http://localhost:11434"

GEMINI_VOICES = ["Aoede", "Puck", "Charon", "Kore", "Fenrir"]
WHISPER_MODELS = ["tiny.en", "base.en", "small.en", "medium.en"]

# (key, default) for every setting shown in the app, besides the API key.
SETTINGS = {
    "GEMINI_VOICE": "Aoede",
    "GEMINI_MODEL": "",
    "CYNO_LANGUAGES": "en-US",
    "OLLAMA_MODEL": "llama3.2:3b",
    "WHISPER_MODEL": "small.en",
    "KOKORO_VOICE": "af_heart",
    "KOKORO_THREADS": "",
    "PORT": "7860",
    "CYNO_IDLE_SECS": "40",
    "CYNO_FORCE_OFFLINE": "",
    "CYNO_DEBUG": "",
}


def _child_env() -> dict:
    env = dict(os.environ)
    # Cyno's settings come from .env (the server loads it); don't let stale shell values override it.
    for key in [*SETTINGS, "GOOGLE_API_KEY"]:
        env.pop(key, None)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONUTF8"] = "1"  # loguru prints non-ASCII; Windows consoles default to cp1252
    return env


def _open_path(path: Path):
    if IS_WIN:
        os.startfile(path)  # noqa: S606
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class Api:
    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._started_at: float | None = None
        self._logs: deque[tuple[int, str]] = deque(maxlen=3000)
        self._log_seq = 0
        self._bench: deque[str] = deque(maxlen=200)
        self._bench_running = False
        self._gemini_ok: bool | None = None
        self._lock = threading.Lock()
        psutil.cpu_percent(None)  # prime the CPU meter
        threading.Thread(target=self._watch_gemini, daemon=True).start()

    # ---------- helpers ----------

    def _port(self) -> int:
        return int(envfile.read().get("PORT") or 7860)

    def _base(self) -> str:
        return f"http://localhost:{self._port()}"

    def _get(self, url: str, timeout=1.0):
        try:
            return httpx.get(url, timeout=timeout).json()
        except Exception:
            return None

    def _log(self, line: str):
        with self._lock:
            self._log_seq += 1
            self._logs.append((self._log_seq, line.rstrip()))

    def _pump(self, proc: subprocess.Popen):
        for line in proc.stdout:
            self._log(line)
        self._log(f"--- server exited (code {proc.wait()}) ---")

    def _watch_gemini(self):
        while True:
            try:
                socket.create_connection(("generativelanguage.googleapis.com", 443), timeout=3).close()
                self._gemini_ok = True
            except OSError:
                self._gemini_ok = False
            time.sleep(15)

    def _owned_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ---------- status ----------

    def get_status(self):
        state = self._get(f"{self._base()}/api/state")
        stats = self._get(f"{self._base()}/api/stats") if state else None
        tags = self._get(f"{OLLAMA}/api/tags")
        loaded = self._get(f"{OLLAMA}/api/ps")
        env = envfile.read()
        mem = psutil.virtual_memory()
        return {
            "server": {
                "running": state is not None,
                "owned": self._owned_running(),
                "starting": self._owned_running() and state is None,
                "uptime_s": round(time.time() - self._started_at) if self._owned_running() and self._started_at else None,
                "port": self._port(),
            },
            "state": state,
            "stats": stats,
            "gemini": {"reachable": self._gemini_ok, "key_set": bool(env.get("GOOGLE_API_KEY"))},
            "ollama": {
                "running": tags is not None,
                "models": [m["name"] for m in (tags or {}).get("models", [])],
                "loaded": [m["name"] for m in (loaded or {}).get("models", [])],
                "wanted": env.get("OLLAMA_MODEL") or SETTINGS["OLLAMA_MODEL"],
            },
            "offline_ready": any("Offline models loaded" in line for _, line in list(self._logs)),
            "system": {
                "cpu": psutil.cpu_percent(None),
                "mem_used_gb": round(mem.used / 1e9, 1),
                "mem_total_gb": round(mem.total / 1e9, 1),
                "mem_percent": mem.percent,
            },
            "force_offline": env.get("CYNO_FORCE_OFFLINE") == "1",
            "debug": env.get("CYNO_DEBUG") == "1",
        }

    # ---------- server ----------

    def start_server(self):
        if self._owned_running():
            return {"ok": True}
        if self._get(f"{self._base()}/api/state"):
            return {"ok": False, "error": f"Another Cyno server is already using port {self._port()}. Stop it first."}
        kwargs = {}
        if IS_WIN:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "cyno.server"],
            cwd=ROOT,
            env=_child_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **kwargs,
        )
        self._started_at = time.time()
        self._log("--- starting Cyno server ---")
        threading.Thread(target=self._pump, args=(self._proc,), daemon=True).start()
        return {"ok": True}

    def stop_server(self):
        if not self._owned_running():
            return {"ok": True}
        self._proc.terminate()
        try:
            self._proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        self._proc = None
        self._started_at = None
        return {"ok": True}

    def restart_server(self):
        self.stop_server()
        time.sleep(0.5)
        return self.start_server()

    # ---------- live controls ----------

    def set_state(self, changes: dict):
        try:
            httpx.post(f"{self._base()}/api/state", json=changes, timeout=2)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def simulate_outage(self, blocked: bool):
        try:
            r = httpx.post(f"{self._base()}/api/debug/outage", json={"blocked": bool(blocked)}, timeout=3)
            if r.status_code == 404:
                return {"ok": False, "error": "Turn on Debug tools in Settings and restart the server."}
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_face_frame(self):
        from cyno import display

        return {"frame": display.load_frame(), "default": display.DEFAULT_FRAME}

    def set_face_frame(self, frame: dict):
        """Move the face's glow ring; live on the face display when the server is running."""
        from cyno import display

        try:
            r = httpx.post(f"{self._base()}/api/face-frame", json=frame, timeout=1.5)
            if r.status_code == 200:
                return {"ok": True, "live": True, "frame": r.json()}
        except Exception:
            pass
        return {"ok": True, "live": False, "frame": display.save_frame(frame)}  # applied on next start

    # ---------- games ----------

    def _notify(self, path: str, body: dict | None = None):
        """Tell the running server about a change; fine if it is stopped (it reads the files on start)."""
        try:
            return httpx.post(f"{self._base()}{path}", json=body or {}, timeout=1.5)
        except Exception:
            return None

    def get_games(self):
        from cyno import games

        return {
            "settings": games.load_settings(),
            "games": [{"id": g, "title": t, "about": about, "voice": voice} for g, (t, about, voice) in games.GAMES.items()],
            "pictures": games.puzzle_files(),
            "best": games.best_today(),
        }

    def save_games(self, changes: dict):
        from cyno import games

        settings = games.save_settings(changes)
        self._notify("/api/games/reload")
        return {"ok": True, "settings": settings}

    def add_puzzle_pictures(self):
        from cyno import games

        picked = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=True, file_types=("Pictures (*.png;*.jpg;*.jpeg;*.webp)",)
        )
        if not picked:
            return {"ok": True, "pictures": games.puzzle_files()}
        try:
            for path in picked:
                games.add_puzzle_image(Path(path))
        except Exception as e:
            return {"ok": False, "error": str(e)}
        self._notify("/api/games/reload")
        return {"ok": True, "pictures": games.puzzle_files()}

    def remove_puzzle_picture(self, name: str):
        from cyno import games

        games.remove_puzzle_image(name)
        self._notify("/api/games/reload")
        return {"ok": True, "pictures": games.puzzle_files()}

    def puzzle_picture_data(self, name: str):
        """Small preview for the list (the app window can't load files from the data folder directly)."""
        import base64
        from cyno import games

        path = games.PUZZLE_DIR / Path(name).name
        if not path.is_file() or path.stat().st_size > 12_000_000:
            return {"ok": False}
        kind = {"png": "png", "webp": "webp"}.get(path.suffix.lower().lstrip("."), "jpeg")
        return {"ok": True, "src": f"data:image/{kind};base64," + base64.b64encode(path.read_bytes()).decode()}

    def open_game_content(self):
        from cyno import games

        _open_path(games.CONTENT_PATH)
        return {"ok": True}

    # ---------- microphone, speaker, camera ----------

    def get_devices(self):
        from cyno import devices

        data = self._get(f"{self._base()}/api/devices")
        if data and "seen" in data:
            return {"running": True, **data}
        return {"running": False, "seen": {k: [] for k in devices.KINDS}, "chosen": devices.load()}

    def set_devices(self, choice: dict):
        from cyno import devices

        r = self._notify("/api/devices", choice)
        if r is not None and r.status_code == 200:
            return {"ok": True, "live": True, "chosen": r.json()}
        return {"ok": True, "live": False, "chosen": devices.save(choice)}

    def scan_devices(self):
        r = self._notify("/api/devices/scan")
        if r is None:
            return {"ok": False, "error": "Start Cyno and open the chest screen first."}
        return {"ok": True}

    # ---------- locked chest screen ----------

    def kiosk_status(self):
        from cyno import kiosk

        live = self._get(f"{self._base()}/api/kiosk")
        if live and "open" in live:
            return {"running": True, **live}
        return {"running": False, "has_pin": kiosk.has_pin(), "open": False, "browser": bool(kiosk.find_browser())}

    def set_kiosk_pin(self, pin: str):
        from cyno import kiosk

        try:
            kiosk.set_pin(pin)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    def _kiosk(self, action: str):
        from cyno import kiosk

        try:
            r = httpx.post(f"{self._base()}/api/kiosk/{action}", json={"token": kiosk.read_token()}, timeout=6)
        except Exception:
            return {"ok": False, "error": "Start Cyno first."}
        if r.status_code != 200:
            return {"ok": False, "error": r.text or "Could not do that."}
        return {"ok": True, **r.json()}

    def open_kiosk(self):
        return self._kiosk("open")

    def close_kiosk(self):
        return self._kiosk("close")

    def open_display(self, page: str):
        webbrowser.open(f"{self._base()}/{'face' if page == 'face' else 'chest'}/")
        return {"ok": True}

    def open_url(self, url: str):
        if url.startswith("https://"):
            webbrowser.open(url)
        return {"ok": True}

    def open_knowledge(self):
        _open_path(ROOT / "data" / "knowledge.json")
        return {"ok": True}

    def knowledge_summary(self):
        from cyno import knowledge

        entries = knowledge._load()
        return {"total": len(entries), "unverified": [e["title"] for e in entries if not e.get("verified", True)]}

    # ---------- teaching Cyno (instructions + facts) ----------

    def get_knowledge(self):
        from cyno import knowledge

        return {"entries": knowledge._load(), "media": knowledge.media_files()}

    def add_picture(self):
        """Pick an image file and copy it into data/media so facts can show it on the chest."""
        from cyno import knowledge

        windows = webview.windows
        if not windows:
            return {"ok": False, "error": "No window"}
        picked = windows[0].create_file_dialog(
            webview.OPEN_DIALOG, file_types=("Images (*.png;*.jpg;*.jpeg;*.webp;*.gif;*.svg)",)
        )
        if not picked:
            return {"ok": False}
        src = Path(picked[0])
        knowledge.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        name = "".join(c if c.isalnum() or c in "-_." else "-" for c in src.name)
        shutil.copyfile(src, knowledge.MEDIA_DIR / name)
        return {"ok": True, "name": name, "media": knowledge.media_files()}

    def save_fact(self, entry: dict):
        from cyno import knowledge

        try:
            return {"ok": True, "entry": knowledge.upsert(entry)}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    def delete_fact(self, entry_id: str):
        from cyno import knowledge

        knowledge.delete(entry_id)
        return {"ok": True}

    def suggest_keywords(self, title: str):
        from cyno import knowledge

        return {"keywords": knowledge.suggest_keywords(title)}

    def check_overlaps(self, entry: dict):
        from cyno import knowledge

        return {"titles": knowledge.overlaps(entry)}

    def test_question(self, question: str):
        """Which facts Cyno's lookup finds for a question (what online mode would answer from)."""
        from cyno import assistant, knowledge

        strict = assistant.load()["strict"]
        scored = knowledge.search_scored(question, confirmed_only=strict)
        hidden = [] if not strict else [
            e["title"] for e in knowledge.search(question) if not e.get("verified", True)
        ]
        return {
            "results": [{"title": e["title"], "answer": e["answer"]} for _, e in scored],
            "tie": len(scored) > 1 and scored[0][0] == scored[1][0],
            "hidden_unconfirmed": hidden,
        }

    def get_assistant(self):
        from cyno import assistant

        return {**assistant.load(), "default_greeting": assistant.DEFAULTS["greeting"]}

    def save_assistant(self, greeting: str, instructions: str, strict: bool = True, on_topic: bool = False,
                       social: bool | None = None):
        from cyno import assistant

        assistant.save(greeting, instructions, strict, on_topic, social)
        try:  # record the new greeting now, so the next visitor already hears it
            httpx.post(f"{self._base()}/api/greeting/prepare", timeout=1.0)
        except Exception:
            pass  # server not running: it records the greeting when it starts
        return {"ok": True}

    # ---------- app preferences (kept outside .env: they are per computer, not per robot) ----------

    def get_prefs(self):
        try:
            return json.loads(PREFS.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"appearance": "auto"}

    def set_prefs(self, prefs: dict):
        PREFS.write_text(json.dumps({**self.get_prefs(), **prefs}), encoding="utf-8")
        return {"ok": True}

    def start_ollama(self):
        if self._get(f"{OLLAMA}/api/version"):
            return {"ok": True}
        exe = shutil.which("ollama")
        if IS_WIN:
            local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
            exe = str(local) if local.exists() else exe
        if platform.system() == "Darwin" and Path("/Applications/Ollama.app").exists():
            subprocess.Popen(["open", "-a", "Ollama"])
        elif exe:
            kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WIN else {"start_new_session": True}
            subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
        else:
            return {"ok": False, "error": "Ollama is not installed. Run the setup script or get it from ollama.com."}
        return {"ok": True}

    # ---------- benchmark ----------

    def run_benchmark(self):
        if self._bench_running:
            return {"ok": True}
        self._bench.clear()
        self._bench_running = True

        def work():
            kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WIN else {}
            proc = subprocess.Popen(
                [sys.executable, "-m", "cyno.prepare_offline"],
                cwd=ROOT, env=_child_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1, **kwargs,
            )
            for line in proc.stdout:
                if line.startswith(("[", "     answer", "Estimated")) or "Error" in line:
                    self._bench.append(line.rstrip())
            proc.wait()
            self._bench_running = False

        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    def get_benchmark(self):
        return {"running": self._bench_running, "lines": list(self._bench)}

    # ---------- logs ----------

    def get_logs(self, since: int = 0, include_debug: bool = False):
        with self._lock:
            rows = [(i, l) for i, l in self._logs if i > since]
        if not include_debug:
            rows = [(i, l) for i, l in rows if "| DEBUG" not in l]
        return {"last": self._log_seq, "lines": [l for _, l in rows[-500:]]}

    def clear_logs(self):
        with self._lock:
            self._logs.clear()
        return {"ok": True}

    # ---------- settings ----------

    def get_settings(self):
        env = envfile.read()
        key = env.get("GOOGLE_API_KEY", "")
        return {
            "values": {k: env.get(k, "") for k in SETTINGS},
            "defaults": SETTINGS,
            "api_key": {"set": bool(key), "hint": f"…{key[-4:]}" if len(key) >= 8 else ""},
            "options": {
                "GEMINI_VOICE": GEMINI_VOICES,
                "WHISPER_MODEL": WHISPER_MODELS,
                "OLLAMA_MODEL": [m["name"] for m in (self._get(f"{OLLAMA}/api/tags") or {}).get("models", [])],
                "KOKORO_VOICE": self._kokoro_voices(),
            },
        }

    def _kokoro_voices(self):
        path = Path.home() / ".cache" / "pipecat" / "kokoro-onnx" / "voices-v1.0.bin"
        try:
            import numpy as np

            return sorted(v for v in np.load(path).files if v.startswith(("af_", "am_", "bf_", "bm_")))
        except Exception:
            return ["af_heart"]

    def save_settings(self, values: dict, api_key: str | None = None, clear_api_key: bool = False):
        updates = {k: str(values.get(k, "")).strip() for k in SETTINGS if k in values}
        if api_key:
            updates["GOOGLE_API_KEY"] = api_key.strip()
        elif clear_api_key:
            updates["GOOGLE_API_KEY"] = ""
        envfile.write(updates)
        return {"ok": True, "restart_needed": self._owned_running() or bool(self._get(f"{self._base()}/api/state"))}

    # ---------- lifecycle ----------

    def shutdown(self):
        self.stop_server()


ASSETS = Path(__file__).resolve().parent / "assets"


def _brand_process():
    """Show the app as 'Cyno Control' with the Cynocor icon instead of as Python."""
    try:
        if IS_WIN:
            import ctypes

            # Own taskbar group, so Windows uses our window icon rather than pythonw's.
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Cynocor.CynoControl")
        elif platform.system() == "Darwin":
            from Foundation import NSBundle

            info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
            info["CFBundleName"] = "Cyno Control"  # menu bar app name
    except Exception:
        pass  # cosmetic only


def main():
    _brand_process()
    api = Api()
    window = webview.create_window(
        "Cyno Control · Cynocor",
        url=str(UI),
        js_api=api,
        width=1120,
        height=760,
        min_size=(900, 620),
        background_color="#F5F5F7",
        text_select=True,
    )
    window.events.closed += api.shutdown
    # Dock icon on macOS, window and taskbar icon on Windows (WinForms needs .ico).
    icon = ASSETS / ("cyno-control-icon.ico" if IS_WIN else "cyno-control-icon.png")
    webview.start(debug=os.getenv("CYNO_UI_DEBUG") == "1", icon=str(icon))


if __name__ == "__main__":
    main()
