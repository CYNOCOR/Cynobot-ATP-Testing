"""Download, warm up and BENCHMARK every offline model. Run on the robot laptop while online:

    python -m cyno.prepare_offline

It speaks a test question with Kokoro, transcribes it with Whisper, answers it with
Ollama using the real robot prompt, and reports whether the offline path meets the
~3 s response target from the proposal.
"""

import asyncio
import json
import os
import time
from pathlib import Path

import httpx
import numpy as np
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from cyno import offline_models  # noqa: E402

QUESTION = "How do I apply to IIT?"


def kokoro_bench():
    from pipecat.services.kokoro.tts import KOKORO_CACHE_DIR, _ensure_model_files

    model, voices = KOKORO_CACHE_DIR / "kokoro-v1.0.onnx", KOKORO_CACHE_DIR / "voices-v1.0.bin"
    _ensure_model_files(model, voices)
    offline_models._install_kokoro_cache()
    import pipecat.services.kokoro.tts as kokoro_tts

    kokoro = kokoro_tts.Kokoro(str(model), str(voices))
    voice = os.getenv("KOKORO_VOICE", "af_heart")
    kokoro.create("Hello.", voice=voice, lang="en-us")  # warm-up
    t = time.time()
    samples, rate = kokoro.create("Welcome to the Informatics Institute of Technology. " + QUESTION, voice=voice, lang="en-us")
    took, dur = time.time() - t, len(samples) / rate
    print(f"[ok] Kokoro: {took:.2f}s to make {dur:.1f}s of speech (real-time factor {took / dur:.2f}, lower is better)")
    q_samples, q_rate = kokoro.create(QUESTION, voice=voice, lang="en-us")
    return q_samples, q_rate, took


def whisper_bench(samples, rate):
    model = offline_models.get_whisper(offline_models.whisper_model_name(), "cpu", "int8")
    idx = np.round(np.arange(0, len(samples), rate / 16000)).astype(int)  # resample to 16 kHz
    audio = samples[idx[idx < len(samples)]].astype(np.float32)
    list(model.transcribe(np.zeros(16000, dtype=np.float32), language="en")[0])  # warm-up
    t = time.time()
    text = " ".join(s.text for s in model.transcribe(audio, language="en", beam_size=1)[0]).strip()
    took = time.time() - t
    print(f"[ok] Whisper '{offline_models.whisper_model_name()}': {took:.2f}s -> \"{text}\"")
    return took


def ollama_bench():
    from cyno.voice import _facts_prompt

    model = offline_models.ollama_model_name()
    try:
        names = [m["name"] for m in httpx.get("http://localhost:11434/api/tags", timeout=3).json().get("models", [])]
    except Exception:
        print("[!!] Ollama is not running. Start the Ollama app (or `ollama serve`).")
        return None
    if model not in names:
        print(f"[!!] Ollama model missing. Run: ollama pull {model}")
        return None
    system = _facts_prompt()
    body = {"model": model, "stream": True, "max_tokens": 90,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": QUESTION}]}
    httpx.post("http://localhost:11434/api/generate", json={"model": model, "prompt": "hi", "stream": False, "keep_alive": "24h"}, timeout=180)
    t, first_sentence, text = time.time(), None, ""
    with httpx.stream("POST", "http://localhost:11434/v1/chat/completions", json=body, timeout=180) as r:
        for line in r.iter_lines():
            if line.startswith("data: {"):
                text += json.loads(line[6:])["choices"][0]["delta"].get("content") or ""
                if first_sentence is None and any(p in text for p in ".?!"):
                    first_sentence = time.time() - t
    print(f"[ok] Ollama '{model}': first sentence after {first_sentence or 0:.2f}s, full answer {time.time() - t:.2f}s")
    print(f"     answer: {text.strip()}")
    return first_sentence


if __name__ == "__main__":
    q_samples, q_rate, tts_time = kokoro_bench()
    stt_time = whisper_bench(q_samples, q_rate)
    llm_time = ollama_bench()
    if llm_time is not None:
        # Kokoro speaks sentence by sentence, so the visitor waits for:
        # end-of-speech detection (~0.5s) + Whisper + first LLM sentence + first TTS sentence (~half the test clip).
        total = 0.5 + stt_time + llm_time + tts_time / 2
        verdict = "OK" if total <= 3.5 else "SLOW: try WHISPER_MODEL=base.en"
        print(f"\nEstimated offline reply delay: ~{total:.1f}s  ->  {verdict}")
