# Cyno Brain — voice demo

The laptop is the robot's brain. One Python server runs the voice pipeline and drives both displays.

```
Chest page (laptop touchscreen, Chrome)
  mic + speaker ──WebRTC──► voice session ─┬─ ONLINE : Gemini Live (speech-to-speech, free tier)
                                           └─ OFFLINE: Whisper → Ollama (llama3.2:3b) → Kokoro
                                 │  observer: THINKING / SPEAKING / captions / cards
                                 ▼
                       StateBus  /ws  ──► Face page (2nd screen)  +  Chest page
                                 ▲
                  data/knowledge.json (IIT facts, used by both modes)
```

**Online or offline?** Each session checks whether Gemini is reachable. If the Wi-Fi drops mid-conversation,
the session ends, the chest page reconnects automatically, and the new session runs fully offline.
The chest page shows an `OFFLINE MODE` badge while it does.

**All-day sessions:** Gemini context window compression is on, so a session isn't cut off at Google's
15-minute audio limit. Google also closes each connection after ~10 minutes; Pipecat resumes it with a saved handle
(you'll see `Gemini GoAway` in the log).

**Language:** speech is locked to English (`CYNO_LANGUAGES=en-US`). To try Sinhala later, set `CYNO_LANGUAGES=en-US,si-LK`
and relax the "Always reply in English" rule in `cyno/voice.py`.

## Quick install (teammates start here)

Copy the **whole `BOT` folder** (`cyno-brain` needs `Facial Expression Demo` next to it). Then, with internet on:

| | Install (once, ~15–30 min) | Start the robot |
|---|---|---|
| **Windows** | double-click `setup-windows.bat` | double-click `start-windows.bat` |
| **Mac** | in Terminal: `bash setup-mac.sh` | in Terminal: `bash start-mac.sh` |

The installer handles everything: uv, Python 3.12, all packages, Ollama and its model, your Gemini API key
(typed hidden, saved only to `.env`), the offline model downloads, and a speed benchmark. It is safe to re-run.
The start script launches Ollama and the server, then opens the chest and face pages in Chrome.
On the chest page tap **Tap to talk** and allow the mic; on the face page press **F** for fullscreen.

### Cyno Control (the app)

After setup, open **Cyno Control**: double-click `Cyno Control.command` (Mac) or `Cyno Control.bat` (Windows).
It runs everything without a terminal:

- **Overview:** start/stop/restart Cyno; live stats (online/offline, reply delay, questions heard, sessions,
  fallbacks, uptime, CPU, memory); the live conversation; and the Gemini, Ollama and offline-model status.
- **Knowledge:** teach Cyno without code. **Instructions** are free text added to Cyno's brief (e.g. "Today is
  Open Day…"), plus an editable greeting; they're stored in `data/assistant.json`. **Campus facts** can be added,
  edited, marked confirmed or deleted (stored in `data/knowledge.json`). **Try a question** shows which fact Cyno
  would answer from. All of this applies from the next conversation, with no restart.
  **Answer rules:** *Strict answers* (on by default) makes Cyno use only confirmed facts, never guess
  names, numbers or directions, and say "I'm not sure, please check with the front desk" when facts are missing
  or disagree; it also lowers the model's temperature. *Stay on topic* makes it decline non-IIT questions.
  The fact editor warns when a new fact overlaps existing ones, which is where contradictions start.
- **Appearance:** Auto / Light / Dark switch at the bottom of the sidebar (remembered on this computer).
- **Controls:** open the chest/face displays, set the face expression and color, start Ollama, run the speed
  benchmark, and simulate a Wi-Fi drop.
- **Settings:** every `.env` value, including the API key (hidden, never shown in full). Save, then Restart.
- **Activity:** the live server log, with a Problems filter.

Closing the app stops the server it started.

**Never share `.env`** (it holds the API key). Each person uses their own free key from https://aistudio.google.com/apikey.
If the benchmark at the end says SLOW, put the smaller models it suggests in `.env`.

## Manual setup (what the scripts do)

1. `uv venv --python 3.12 .venv` then `uv pip install --python .venv -r requirements.txt`
2. Install Ollama (https://ollama.com/download) and run `ollama pull llama3.2:3b`
3. `.venv/bin/python -m cyno.setup_env` (creates `.env`, asks for the key)
4. `.venv/bin/python -m cyno.prepare_offline` (downloads, warms up and benchmarks the offline models)
5. Run: `.venv/bin/python -m cyno.server`, then open http://localhost:7860/chest/ and http://localhost:7860/face/

On Windows use `.venv\Scripts\python` instead of `.venv/bin/python`.

To rehearse offline mode without turning off Wi-Fi: `CYNO_FORCE_OFFLINE=1 .venv/bin/python -m cyno.server`.

To rehearse a Wi-Fi drop **mid-conversation**, start with `CYNO_DEBUG=1`, talk to Cyno, then:
`curl -X POST localhost:7860/api/debug/outage -H 'content-type: application/json' -d '{"blocked":true}'`
(`{"blocked":false}` restores it). Within ~4 s a watchdog ends the dead Gemini session, the chest page reconnects
and Cyno carries on in OFFLINE MODE. The watchdog is needed because Pipecat 1.15's own reconnect goes silent
when the network is gone.

## Edit what Cyno knows

`data/knowledge.json` is re-read on every online question; offline mode reads it when each session starts.
Website facts came from iit.ac.lk (each entry has its `source`). Entries with `"verified": false`
are in-building directions copied from the old demo. Confirm them before the demo.

## Settings (.env)

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_VOICE` | Aoede | Online voice: Puck, Charon, Kore, Fenrir, Aoede |
| `CYNO_LANGUAGES` | en-US | Languages the speech input is hinted to |
| `OLLAMA_MODEL` | llama3.2:3b | Offline brain (`llama3.2:1b` is faster, less smart) |
| `WHISPER_MODEL` | small.en | Offline ears (`base.en` is faster, less accurate) |
| `KOKORO_VOICE` | af_heart | Offline voice |
| `KOKORO_THREADS` | cores ÷ 3 | CPU threads for the offline voice |
| `CYNO_FORCE_OFFLINE` | (unset) | `1` = always use offline mode |

## Operator override

`POST /api/state` with JSON (e.g. `{"expression":"HAPPY"}`) pushes a state to both displays.
