"""State bus: one shared robot state, pushed to every display over WebSocket.

The face display (Facial Expression Demo/index.html) and the chest display both
connect to /ws and receive the same CYNO_STATE_UPDATE messages.
"""

import asyncio
import json
import time

from fastapi import WebSocket
from loguru import logger

DEFAULT_STATE = {
    "theme": "RED",
    "flow_step": "IDLE",
    "expression": "IDLE",
    "eye_x": 0.0,
    "eye_y": 0.0,
    "last_spoken_text": "Tap the screen to talk to Cyno.",
    "user_text": "",
    "card": None,  # {"title": str, "body": str} shown on the chest display
    "voice_status": "OFFLINE",  # OFFLINE | CONNECTING | LIVE  (is a voice session running?)
    "voice_mode": None,  # ONLINE (Gemini) | OFFLINE (local Whisper/Ollama/Kokoro)
}


class StateBus:
    def __init__(self):
        self.state = dict(DEFAULT_STATE)
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    def _payload(self, sticky: bool) -> str:
        return json.dumps(
            {
                "type": "CYNO_STATE_UPDATE",
                "state": self.state,
                "speak": False,  # audio comes from the voice pipeline, not browser TTS
                "sticky": sticky,
                "action": None,
                "ts": int(time.time() * 1000),
            }
        )

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._clients.add(ws)
        await ws.send_text(self._payload(sticky=True))

    def disconnect(self, ws: WebSocket):
        self._clients.discard(ws)

    async def update(self, sticky: bool = True, **changes):
        """Merge changes into the state and broadcast if anything changed."""
        if all(self.state.get(k) == v for k, v in changes.items()):
            return
        self.state.update(changes)
        payload = self._payload(sticky)
        async with self._lock:
            dead = []
            for ws in self._clients:
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._clients.discard(ws)
        logger.debug(f"state -> {changes}")
