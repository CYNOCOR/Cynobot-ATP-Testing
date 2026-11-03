"""Runtime counters for the control app (served at /api/stats)."""

import time
from collections import deque


class Stats:
    def __init__(self):
        self.started_at = time.time()
        self.sessions = {"ONLINE": 0, "OFFLINE": 0}
        self.fallbacks = 0  # online sessions ended by the Gemini watchdog
        self.turns = 0  # visitor questions heard
        self.kb_lookups = 0
        self.session_started_at: float | None = None
        self.session_mode: str | None = None
        self._heard_at: float | None = None
        self._delays = deque(maxlen=20)  # seconds from visitor transcript to Cyno speaking

    def session_start(self, mode: str):
        self.sessions[mode] = self.sessions.get(mode, 0) + 1
        self.session_started_at, self.session_mode = time.time(), mode

    def session_end(self):
        self.session_started_at, self.session_mode, self._heard_at = None, None, None

    def heard(self):
        """Visitor speech transcribed; start timing the reply (first transcript piece of a turn)."""
        if self._heard_at is None:
            self.turns += 1
            self._heard_at = time.time()

    def bot_started(self):
        if self._heard_at is not None:
            self._delays.append(time.time() - self._heard_at)
            self._heard_at = None

    def snapshot(self) -> dict:
        now = time.time()
        delays = list(self._delays)
        return {
            "uptime_s": round(now - self.started_at),
            "sessions_online": self.sessions.get("ONLINE", 0),
            "sessions_offline": self.sessions.get("OFFLINE", 0),
            "fallbacks": self.fallbacks,
            "turns": self.turns,
            "kb_lookups": self.kb_lookups,
            "session_mode": self.session_mode,
            "session_s": round(now - self.session_started_at) if self.session_started_at else None,
            "last_delay_s": round(delays[-1], 2) if delays else None,
            "avg_delay_s": round(sum(delays) / len(delays), 2) if delays else None,
        }


stats = Stats()
