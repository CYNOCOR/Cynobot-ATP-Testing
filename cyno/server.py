"""Cyno brain server.

  /face/   head display (existing Facial Expression Demo, unchanged layout)
  /chest/  chest touchscreen: holds the mic/speaker WebRTC link + captions/cards
  /ws      state bus for both displays
  /api/offer  WebRTC signalling for the voice pipeline

Run:  .venv/bin/python -m cyno.server
"""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from loguru import logger

from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.request_handler import (
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)

from cyno import greeting, knowledge, offline_models
from cyno.bus import StateBus
from cyno.voice import run_voice_session

ROOT = Path(__file__).resolve().parent
FACE_DIR = ROOT.parent.parent / "Facial Expression Demo"
CHEST_DIR = ROOT / "web" / "chest"

load_dotenv(ROOT.parent / ".env", override=True)

bus = StateBus()
webrtc = SmallWebRTCRequestHandler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    offline_models.start_preload()  # background thread; server is usable immediately
    asyncio.create_task(greeting.prepare())  # record the online greeting once
    yield
    await webrtc.close()


app = FastAPI(title="Cyno Brain", lifespan=lifespan)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await bus.connect(ws)
    try:
        while True:
            await ws.receive_text()  # displays only listen; keep the socket open
    except WebSocketDisconnect:
        pass
    finally:
        bus.disconnect(ws)


@app.post("/api/offer")
async def offer(request: SmallWebRTCRequest, background_tasks: BackgroundTasks):
    async def on_connection(connection: SmallWebRTCConnection):
        background_tasks.add_task(run_voice_session, connection, bus)

    return await webrtc.handle_web_request(request=request, webrtc_connection_callback=on_connection)


@app.patch("/api/offer")
async def ice_candidate(request: SmallWebRTCPatchRequest):
    await webrtc.handle_patch_request(request)
    return {"status": "success"}


@app.get("/api/state")
async def get_state():
    return bus.state


@app.get("/api/stats")
async def get_stats():
    from cyno.stats import stats

    return {**stats.snapshot(), "debug": os.getenv("CYNO_DEBUG") == "1"}


@app.post("/api/state")
async def set_state(changes: dict):
    """Operator override (and testing): merge fields into the display state."""
    await bus.update(**changes)
    return bus.state


if os.getenv("CYNO_DEBUG") == "1":

    @app.post("/api/debug/outage")
    async def debug_outage(body: dict):
        """Rehearse a Wi-Fi drop: {"blocked": true} cuts Gemini, {"blocked": false} restores it."""
        from cyno.voice import simulate_outage

        await simulate_outage(bool(body.get("blocked")))
        return {"gemini_blocked": bool(body.get("blocked"))}


@app.post("/api/greeting/prepare")
async def prepare_greeting():
    """Cyno Control calls this after the greeting is edited."""
    asyncio.create_task(greeting.prepare())
    return {"ok": True}


@app.get("/api/qr")
async def qr(data: str):
    """QR code (SVG) for a fact's link, made locally so it also works offline."""
    import io

    import segno

    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="svg", scale=10, border=2, dark="#000", light="#fff")
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "max-age=3600"})


@app.get("/")
async def root():
    return RedirectResponse("/chest/")


app.mount("/face", StaticFiles(directory=FACE_DIR, html=True), name="face")
app.mount("/chest", StaticFiles(directory=CHEST_DIR, html=True), name="chest")
knowledge.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=knowledge.MEDIA_DIR), name="media")


if __name__ == "__main__":
    port = int(os.getenv("PORT", "7860"))
    logger.info(f"Chest display: http://localhost:{port}/chest/   Face display: http://localhost:{port}/face/")
    uvicorn.run(app, host="127.0.0.1", port=port)
