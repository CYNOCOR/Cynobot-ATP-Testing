"""Recorded online greeting.

Asking Gemini Live to greet on its own (text kickoff, no visitor speech yet) often
returns the full greeting text with little or no audio: in tests 3-6 of 8 kickoffs
were silent, while spoken questions were answered every time. So Cyno records the
greeting once in the Gemini voice, keeps the first complete take, and replays it
for every visitor. A changed greeting, voice or model gets a new recording.
"""

import asyncio
import hashlib
import json
import os
from pathlib import Path

from loguru import logger

from cyno import assistant

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "greeting_cache"
SAMPLE_RATE = 24000  # Gemini Live speaks 24 kHz, 16-bit mono
DEFAULT_MODEL = "models/gemini-3.1-flash-live-preview"  # Cyno's default; see voice._build_online
ATTEMPTS = 10

_lock = asyncio.Lock()


def _key() -> str:
    from cyno.voice import PERSONA  # a new name or persona needs a new recording too

    parts = [PERSONA, assistant.load()["greeting"], os.getenv("GEMINI_VOICE", "Aoede"), os.getenv("GEMINI_MODEL") or DEFAULT_MODEL]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def load() -> tuple[str, bytes] | None:
    """(text, 24 kHz PCM) for the current greeting, if it has been recorded."""
    meta, pcm = CACHE_DIR / f"{_key()}.json", CACHE_DIR / f"{_key()}.pcm"
    if not (meta.exists() and pcm.exists()):
        return None
    return json.loads(meta.read_text(encoding="utf-8"))["text"], pcm.read_bytes()


def _plausible(text: str, pcm: bytes) -> bool:
    """A complete take: speech length fits the number of words (silent or runaway takes fail)."""
    words, secs = len(text.split()), len(pcm) / (SAMPLE_RATE * 2)
    return words >= 3 and words / 4.5 <= secs <= words / 1.2 + 1.5


async def _take(client, config, model: str) -> tuple[str, bytes] | None:
    from google.genai import types

    async with client.aio.live.connect(model=model, config=config) as session:

        async def room_noise():  # Gemini Live expects a live mic; an idle input stream helps it finish turns
            silence = bytes(3200)
            while True:
                await session.send_realtime_input(audio=types.Blob(data=silence, mime_type="audio/pcm;rate=16000"))
                await asyncio.sleep(0.1)

        mic = asyncio.create_task(room_noise())
        text, pcm = "", bytearray()
        try:
            prompt = assistant.load()["greeting"]
            await session.send_client_content(turns=[types.Content(role="user", parts=[types.Part(text=prompt)])], turn_complete=True)
            await session.send_realtime_input(text=" ")

            async def collect():
                nonlocal text
                async for msg in session.receive():
                    sc = msg.server_content
                    if not sc:
                        continue
                    for part in (sc.model_turn.parts if sc.model_turn else []):
                        if part.inline_data and part.inline_data.data:
                            pcm.extend(part.inline_data.data)
                    if sc.output_transcription and sc.output_transcription.text:
                        text += sc.output_transcription.text
                    if sc.turn_complete:
                        return True
                return False

            done = await asyncio.wait_for(collect(), 20)
        except Exception as e:
            logger.debug(f"Greeting take failed: {e}")
            return None
        finally:
            mic.cancel()
    text = " ".join(text.split())
    return (text, bytes(pcm)) if done and _plausible(text, bytes(pcm)) else None


async def prepare() -> bool:
    """Record the current greeting if it isn't cached yet. Safe to call often."""
    if not os.getenv("GOOGLE_API_KEY"):
        return False
    async with _lock:
        if load():
            return True
        from google import genai
        from google.genai import types

        from cyno.voice import _facts_prompt

        model = os.getenv("GEMINI_MODEL") or DEFAULT_MODEL
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=_facts_prompt(),
            temperature=assistant.temperature(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=os.getenv("GEMINI_VOICE", "Aoede"))
                )
            ),
        )
        client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        for attempt in range(1, ATTEMPTS + 1):
            take = await _take(client, config, model)
            if take:
                text, pcm = take
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                key = _key()
                for old in CACHE_DIR.glob("*"):  # recordings of earlier greetings
                    if old.stem != key:
                        old.unlink(missing_ok=True)
                (CACHE_DIR / f"{key}.pcm").write_bytes(pcm)
                (CACHE_DIR / f"{key}.json").write_text(json.dumps({"text": text}), encoding="utf-8")
                logger.info(f"Greeting recorded on take {attempt} ({len(pcm) / (SAMPLE_RATE * 2):.1f}s): {text}")
                return True
            logger.info(f"Greeting take {attempt} was incomplete, retrying")
        logger.warning("Could not record a complete greeting; Cyno will ask Gemini to greet live")
        return False
