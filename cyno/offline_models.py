"""Load the offline models once (in a background thread at server start) and reuse them.

Pipecat services load their models in __init__, which took ~40 s and froze the
event loop when a session switched to offline mode. Here the heavy objects are
cached so each new session builds its pipeline instantly.
"""

import asyncio
import os

import httpx
from loguru import logger

_cache: dict = {}
_ready: asyncio.Task | None = None


def whisper_model_name() -> str:
    return os.getenv("WHISPER_MODEL", "small.en")


def ollama_model_name() -> str:
    return os.getenv("OLLAMA_MODEL", "llama3.2:3b")


def _install_kokoro_cache():
    import pipecat.services.kokoro.tts as kokoro_tts

    real = kokoro_tts.Kokoro
    if getattr(real, "_cyno_cached", False):
        return

    def cached_kokoro(model_path, voices_path):
        key = ("kokoro", model_path, voices_path)
        if key not in _cache:
            import onnxruntime as rt

            # By default ONNX grabs every core, starving Ollama and Whisper while Cyno speaks.
            opts = rt.SessionOptions()
            opts.intra_op_num_threads = int(os.getenv("KOKORO_THREADS", max(2, (os.cpu_count() or 4) // 3)))
            session = rt.InferenceSession(model_path, sess_options=opts, providers=["CPUExecutionProvider"])
            _cache[key] = real.from_session(session, voices_path)
        return _cache[key]

    cached_kokoro._cyno_cached = True
    kokoro_tts.Kokoro = cached_kokoro


def get_whisper(model: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel

    key = ("whisper", model, device, compute_type)
    if key not in _cache:
        _cache[key] = WhisperModel(model, device=device, compute_type=compute_type)
    return _cache[key]


def _preload():
    from pipecat.services.kokoro.tts import KOKORO_CACHE_DIR

    _install_kokoro_cache()
    import pipecat.services.kokoro.tts as kokoro_tts

    # Import the offline service modules now: the Whisper one pulls in heavy libraries
    # (~10 s), which otherwise lands on the visitor when the session falls back offline.
    import pipecat.audio.vad.silero  # noqa: F401
    import pipecat.services.ollama.llm  # noqa: F401
    import pipecat.services.whisper.stt  # noqa: F401

    import numpy as np

    # Load AND run each model once: the first inference is much slower than later ones.
    whisper = get_whisper(whisper_model_name(), "cpu", "int8")
    list(whisper.transcribe(np.zeros(16000, dtype=np.float32), language="en")[0])
    kokoro = kokoro_tts.Kokoro(str(KOKORO_CACHE_DIR / "kokoro-v1.0.onnx"), str(KOKORO_CACHE_DIR / "voices-v1.0.bin"))
    kokoro.create("Hello.", voice=os.getenv("KOKORO_VOICE", "af_heart"), lang="en-us")
    try:  # load the LLM into RAM and keep it there, so the first offline answer is fast
        httpx.post(
            "http://localhost:11434/api/generate",
            json={"model": ollama_model_name(), "prompt": "hi", "stream": False, "keep_alive": "24h"},
            timeout=120,
        )
    except Exception as e:
        logger.warning(f"Ollama not reachable, offline answers will fail until it runs: {e}")


async def _preload_task():
    try:
        await asyncio.to_thread(_preload)
        logger.info("Offline models loaded (Whisper, Kokoro, Ollama)")
    except Exception as e:
        logger.warning(f"Offline model preload failed (run `python -m cyno.prepare_offline`): {e}")


def start_preload():
    global _ready
    _ready = asyncio.create_task(_preload_task())


async def ready():
    if _ready:
        await _ready
