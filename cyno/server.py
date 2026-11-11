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

from cyno import devices, display, games, greeting, kiosk, knowledge, offline_models
from cyno.bus import StateBus
from cyno.voice import run_voice_session

ROOT = Path(__file__).resolve().parent
FACE_DIR = ROOT.parent.parent / "Facial Expression Demo"
CHEST_DIR = ROOT / "web" / "chest"

load_dotenv(ROOT.parent / ".env", override=True)

bus = StateBus()
bus.state["face_frame"] = display.load_frame()  # glow-ring alignment for the head screen
bus.state["devices"] = devices.load()  # chosen mic / speaker / camera names ("" = default)
webrtc = SmallWebRTCRequestHandler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    offline_models.start_preload()  # background thread; server is usable immediately
    asyncio.create_task(greeting.prepare())  # record the online greeting once
    kiosk.publish_token()  # lets Cyno Control open and close the locked chest screen
    yield
    kiosk.close()  # don't leave a locked window behind when Cyno stops
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


@app.get("/api/face-frame")
async def get_face_frame():
    return bus.state["face_frame"]


@app.post("/api/face-frame")
async def set_face_frame(frame: dict):
    """Cyno Control's alignment sliders: save and move the face's glow ring live."""
    frame = display.save_frame({**bus.state["face_frame"], **frame})
    await bus.update(face_frame=frame)
    return frame


# ---- games (chest screen) ----


@app.get("/api/games")
async def get_games():
    from cyno.voice import is_online

    online = bool(os.getenv("GOOGLE_API_KEY")) and await is_online(1.0)
    return games.public_config(online)


@app.post("/api/games/score")
async def post_game_score(body: dict):
    try:
        return games.submit_score(str(body.get("game")), str(body.get("level", "")), body.get("score", 0))
    except (ValueError, TypeError) as e:
        return Response(str(e), status_code=400)


@app.post("/api/games/reload")
async def reload_games():
    """Cyno Control changed the game settings or pictures: tell the chest to re-read them."""
    import time

    await bus.update(games_rev=int(time.time() * 1000))
    return {"ok": True}


# ---- mic / speaker / camera choice ----


@app.get("/api/devices")
async def get_devices():
    return {"seen": devices.seen, "chosen": bus.state["devices"]}


@app.post("/api/devices/seen")
async def devices_seen(found: dict):
    """The chest page reports the devices its browser can use."""
    return devices.report(found)


@app.post("/api/devices")
async def set_devices(choice: dict):
    chosen = devices.save(choice)
    await bus.update(devices=chosen)
    return chosen


@app.post("/api/devices/scan")
async def scan_devices():
    """Ask the chest page to look for devices again (it may ask for camera permission once)."""
    import time

    await bus.update(device_scan=int(time.time() * 1000))
    return {"ok": True}


# ---- locked chest screen (kiosk + PIN) ----


@app.get("/api/kiosk")
async def kiosk_status():
    return kiosk.status()


@app.post("/api/kiosk/open")
async def kiosk_open(body: dict):
    """From Cyno Control: open the chest screen in a locked, full-screen browser window."""
    if not kiosk.token_ok(body.get("token", "")):
        return Response("Not allowed", status_code=403)
    try:
        kiosk.open_locked(f"http://localhost:{os.getenv('PORT', '7860')}/chest/?kiosk=1")
    except ValueError as e:
        return Response(str(e), status_code=400)
    return kiosk.status()


@app.post("/api/kiosk/close")
async def kiosk_close(body: dict):
    """From Cyno Control (no PIN needed there)."""
    if not kiosk.token_ok(body.get("token", "")):
        return Response("Not allowed", status_code=403)
    kiosk.close()
    return kiosk.status()


@app.post("/api/kiosk/unlock")
async def kiosk_unlock(body: dict):
    """From the PIN pad on the chest screen: the right PIN closes the locked window."""
    result = kiosk.check_pin(str(body.get("pin", "")))
    if result["ok"]:
        asyncio.get_running_loop().call_later(0.6, kiosk.close)  # let the page show "Unlocked" first
    return result


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
