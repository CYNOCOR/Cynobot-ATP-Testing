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

Copy the **`cyno-brain` folder** (or clone it). It holds everything, including both screens' pages. Then, with internet on:

| | Install (once, ~15–30 min) | Start the robot |
|---|---|---|
| **Windows** | double-click `setup-windows.bat` | double-click `start-windows.bat` |
| **Mac** | in Terminal: `bash setup-mac.sh` | in Terminal: `bash start-mac.sh` |

The installer handles everything: uv, Python 3.12, all packages, Ollama and its model, your Gemini API key
(typed hidden, saved only to `.env`), the offline model downloads, and a speed benchmark. It is safe to re-run.
The start script launches Ollama and the server, then opens the chest and face pages in Chrome.
On the chest page tap **Tap to talk** and allow the mic; on the face page press **F** for fullscreen.

**After pulling new code**, double-click `update-windows.bat` (Windows) or run `bash update-mac.sh` (Mac). It installs
any new Python packages in a minute or two; the full `setup-*` is only needed the first time.

**If Start Cyno doesn't bring Cyno up,** the Overview page now says why in one sentence (a missing package, a busy port, a
missing folder); the full output is on the Activity page.

**If Cyno Control won't open:** it now says why. On Windows a message box names the problem (usually a missing
package: run `update-windows.bat`), and the full details are saved in `cyno-control-error.log` in the Cyno folder.

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
  *Social chat* (on by default) lets Cyno do friendly small talk and clean jokes. It keeps safety limits: no
  politics, religion, romance, insults or personal details, no made-up time, weather or news, and help for upset
  visitors. Campus facts still follow the strict rules. Turn it off for receptionist-only answers.
  The fact editor warns when a new fact overlaps existing ones, which is where contradictions start.
- **Games** (own page in Cyno Control): short games on the chest screen, opened with the Games button or by
  saying "play a game". Brain Riddles, Memory Match, Picture Puzzle and Find Your Degree are tap games and work
  offline; Word Chain is played by voice and is hidden when Cynobot is offline. Each game has an on/off switch,
  plus a master switch. A game ends at the time limit (default 2 minutes) and a tap game closes after 30 seconds
  with no touch. Today's best per game is kept with no names (`data/game_scores.json`). Riddles and the degree
  quiz live in `data/game_content.json`; puzzle pictures are added on the Games page (`data/media/puzzles/`).
  **A question mid-game:** when a visitor asks Cynobot something during a game, the game steps aside with its clock
  paused, so the answer, card and QR code show. A *Back to …* button brings it back; it also returns by itself 20 seconds
  after the answer, or when the visitor says "back to the game". In Word Chain a single word is a move, not a question.
- **Devices** (Controls page): choose the microphone, speaker and camera Cynobot uses. Press *Find devices* with
  the chest screen open and allow the mic and camera once. Only Cynobot is affected, not the computer's sound
  settings, and it works the same on macOS and Windows (choosing a speaker needs Chrome or Edge).
- **Locked chest screen** (Controls page): set a 4 to 8 digit staff PIN, then *Open locked* opens the chest
  screen in Chrome or Edge kiosk mode: full screen, no close button, tabs or address bar. Staff tap the CYNOBOT
  logo three times, then hold it for 10 seconds (a countdown shows), and enter the PIN to close it (five wrong tries lock the pad for a minute), or use *Unlock and close* in
  Cyno Control. The PIN is stored only as a salted hash in `data/kiosk.json`. A keyboard can still quit a kiosk
  browser (Alt+F4 / Cmd+Q), so don't leave one attached to the robot.
- **Chest screen design:** a particle scene (`particles.js`, plain WebGL, no downloads) sits behind minimal glass:
  a ribbon when idle, a ring that ripples with the visitor's voice, a swirl while thinking, a wave while answering,
  and a line drawing for the topic before its card. Facts pick their drawing automatically, or in the fact editor.
  The home screen has tap shortcuts (Find us, Courses, Apply, Games) that show a fact's card with no conversation.
  *Controls > Displays > Chest background* sets how much it draws (Automatic, Full, Light, Off) and shows the
  frame rate the chest screen reports. With no 3D in the browser the page uses a plain background by itself.
  The previous design is kept at `/chest/classic.html`.
- **Face (head screen):** big sparkly eyes with blush, random blinks and glances, and a slow "breath". It listens
  with a head tilt, looks up with "..." while thinking, and its mouth follows Cynobot's voice (the chest page sends
  the loudness as it plays). Moments: heart eyes when a visitor says thank you or pays a compliment, a wink for
  goodbye, surprised-then-happy when a game finishes, a glance down when a card appears, and it dozes off ("z z z")
  when nobody has talked to it for a while, waking with a stretch. *Controls > Displays* has a *Calm face* switch
  (no glances, breathing or hops) and *Face dozes off after* (1 to 10 minutes, or never), stored in `data/display.json`.
- **Colours (both screens):** the face and chest screens read their colours from one file,
  `cyno/web/shared/theme.css`, for the Red and the Blue theme: glow colour, text, background glow, glass tint and
  the chest's particle colours. Change a value there and both screens follow, so they always match.
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

`data/knowledge.json` is read when each conversation starts: both brains get every confirmed fact in
their instructions. Website facts came from iit.ac.lk (each entry has its `source`). Entries with
`"verified": false` are in-building directions copied from the old demo. Confirm them before the demo.

**Chest screen visuals.** A fact can also have a **picture** (a file in `data/media/`, shown across the
chest card) and a **link** (shown as a QR code visitors scan with their phone). Set both in Cyno Control
when editing a fact. The "IIT campuses" fact shows `data/media/main-campus-map.png` (map data
© OpenStreetMap contributors) and a QR code for directions.

**Greeting.** Online, Cyno records its greeting once in the Gemini voice (`data/greeting_cache/`) and
plays that recording to each visitor, because Gemini Live often went silent when asked to greet on its
own. Changing the greeting, voice or model records a new one.

**Visitor left.** If nobody speaks for `CYNO_IDLE_SECS` seconds after Cyno's last words, Cyno hangs up,
clears the chest screen and shows "Tap to talk" again.

## Settings (.env)

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_VOICE` | Aoede | Online voice: Puck, Charon, Kore, Fenrir, Aoede |
| `GEMINI_MODEL` | models/gemini-3.1-flash-live-preview | Online brain. In tests `gemini-3.8-live` often sent an answer's words without its sound; 3.1 Flash spoke every answer |
| `CYNO_LANGUAGES` | en-US | Languages the speech input is hinted to |
| `OLLAMA_MODEL` | llama3.2:3b | Offline brain, ~2.6 GB RAM |
| `WHISPER_MODEL` | small.en | Offline ears (`base.en` is faster, less accurate) |
| `KOKORO_VOICE` | af_heart | Offline voice |
| `KOKORO_THREADS` | cores ÷ 3 | CPU threads for the offline voice |
| `CYNO_IDLE_SECS` | 40 | Seconds of silence before Cyno returns to idle (`0` = never) |
| `CYNO_FORCE_OFFLINE` | (unset) | `1` = always use offline mode |

## Operator override

`POST /api/state` with JSON (e.g. `{"expression":"HAPPY"}`) pushes a state to both displays.
