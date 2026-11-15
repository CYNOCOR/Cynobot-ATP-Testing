"""Voice pipeline: browser mic (WebRTC) -> speech AI -> browser speaker.

Two interchangeable brains, picked per session:
  ONLINE   Gemini Live (speech-to-speech, natural voice)
  OFFLINE  Whisper (STT) -> Ollama (LLM) -> Kokoro (TTS), all on the laptop

Pipeline events are mirrored onto the StateBus so the face and chest displays
show THINKING / SPEAKING / captions in sync with the audio.
"""

import asyncio
import os
import re
import time

from loguru import logger

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InterruptionFrame,
    LLMRunFrame,
    SpeechOutputAudioRawFrame,
    TranscriptionFrame,
    TTSTextFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.google.gemini_live.llm import ContextWindowCompressionParams, GeminiLiveLLMService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.workers.runner import WorkerRunner

from cyno import assistant, greeting, knowledge, offline_models
from cyno.bus import DEFAULT_STATE, StateBus
from cyno.stats import stats

PERSONA = """
Your name is Cynobot; never shorten it to Cyno. You are the robot receptionist at the
entrance of the Informatics Institute of Technology (IIT). You were built by Cynocor, the
team's own startup.
Pronunciation: say Cynobot as "Sigh-no-bot" and Cynocor as "Sigh-no-core". Visitors' speech
may be transcribed as "Sinocor", "Cyno core", "Psycho core" or "Synecdoche"; they mean Cynocor.

How you speak:
- Always reply in English, even if the visitor speaks Sinhala, Tamil or another
  language. In that case, kindly say in English that Sinhala and Tamil support is
  coming soon, then help them in English.
- Warm, friendly and concise: one or two short sentences per reply, like a real
  receptionist. Never use lists, markdown or emojis; everything you say is spoken.
- If asked, say honestly that you are a robot.
- Do not give medical, legal or emergency decisions; direct people to staff.
"""

# Both brains get every confirmed fact in their instructions. Online used to look facts
# up with a tool call, but Gemini Live sometimes stayed silent after the tool result:
# the card appeared on the chest and nothing was spoken.
FACT_RULES = """
Keep every reply to one or two short sentences.
Answer questions about IIT, Cynobot and Cynocor ONLY from the facts below. If the answer
is not in the facts, say you are not sure and suggest asking the staff at the front desk.
Never invent rooms, names, times or phone numbers.
Your chest screen shows the matching fact while you talk; the list after the facts says which
facts come with a picture or QR code. When a visitor asks to see a map, picture or QR code that
a fact has, tell them it is on your chest screen. Do not send them to the front desk for it.
When you mention a QR code, say what that fact's code does, exactly as the list says: an email
code is for emailing, a website code opens the website, and only a directions code gives
directions (for example, "Here's the map on my screen, and the code gives you directions", or
"Scan the code on my screen to email admissions").
That list is a note for you: never read it, its brackets or its wording aloud.
Do not end every reply with "Is there anything else I can help you with?"; ask it rarely.

Facts:
{facts}
"""

GEMINI_HOST = "generativelanguage.googleapis.com"


async def is_online(timeout: float = 2.0) -> bool:
    """Can we reach Gemini right now? (DNS + TCP to its API host.)"""
    if os.getenv("CYNO_FORCE_OFFLINE") == "1" or _gemini_blocked:
        return False
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(GEMINI_HOST, 443), timeout)
        writer.close()
        return True
    except Exception:
        return False


class EnglishGeminiLive(GeminiLiveLLMService):
    """Gemini Live with two Cyno fixes.

    1. Input transcription pinned to our languages. Pipecat leaves it on
       auto-detect, which turned an English demo into Sinhala captions.
       CYNO_LANGUAGES (BCP-47, comma separated) is the hint list; add "si-LK"
       when Sinhala support is turned on.
    2. is_connected for the session watchdog. When Gemini drops, Pipecat 1.15's
       reconnect cancels its own task and the robot goes silent forever (seen in
       the simulated Wi-Fi drop test), so run_voice_session watches this instead.
    """

    async def _connection_task_handler(self, config):
        from google.genai.types import AudioTranscriptionConfig

        codes = [c.strip() for c in os.getenv("CYNO_LANGUAGES", "en-US").split(",") if c.strip()]
        config.input_audio_transcription = AudioTranscriptionConfig(language_codes=codes)
        logger.info(f"Gemini input transcription languages: {codes}")
        if _gemini_blocked:
            raise ConnectionError("simulated outage: Gemini unreachable")
        _active_llms.add(self)
        try:
            await super()._connection_task_handler(config)
        finally:
            _active_llms.discard(self)

    async def _handle_server_message(self, message):
        # Google closes each connection after ~10 min and warns first; Pipecat then
        # reconnects with its saved resumption handle. Logged so long runs can be checked.
        if getattr(message, "go_away", None):
            logger.info(f"Gemini GoAway: connection closing in {message.go_away.time_left}, will resume")
        await super()._handle_server_message(message)

    @property
    def is_connected(self) -> bool:
        return self._session is not None and self in _active_llms


# ---- Outage simulation (CYNO_DEBUG=1 /api/debug/outage): rehearse a Wi-Fi drop without touching the OS ----
# (Patching DNS doesn't work: uvicorn runs on uvloop, which resolves names in C.)

_active_llms: set[EnglishGeminiLive] = set()
_gemini_blocked = False


async def simulate_outage(blocked: bool):
    """Make Gemini unreachable for new connections and, if blocking, cut any live Gemini socket."""
    global _gemini_blocked
    _gemini_blocked = blocked
    logger.warning(f"SIMULATED OUTAGE {'ON' if blocked else 'OFF'}")
    if blocked:
        for llm in list(_active_llms):
            if llm._session:
                await llm._session.close()


# How speech recognition spelled "Cynocor" in tests: cynochar, signocker, Cynocker, sinocor,
# cyno core, psycho core... (first half "sigh-no", second half "core").
CYNOCOR_SOUNDALIKE = re.compile(
    r"\b(?:cyno|sino|sinno|signo|syno|sygno|psycho|cino|saino|sai no)[\s-]?(?:core?|cor|car|char|chor|cker|ker|ckar|kor)\b", re.I
)


# What the visitor said that deserves a face moment on the head screen.
THANKS = re.compile(
    r"\b(thank(s| you)|thx|cheers|you('?re| are) (so |very |really )?(cute|sweet|awesome|amazing|great|smart|cool|helpful|the best)"
    r"|(so|very|really) (cute|sweet|helpful)|love you|good (job|robot|bot)|well done|nice (job|work))\b",
    re.IGNORECASE,
)
GOODBYE = re.compile(r"\b(good ?bye|bye( bye)?(?![ -]?laws?)|see (you|ya)|have a (good|nice|great) (day|one)|take care|cya)\b", re.IGNORECASE)


def face_moment(text: str) -> str | None:
    if GOODBYE.search(text):
        return "wink"
    if THANKS.search(text):
        return "love"
    return None


class DisplayObserver(BaseObserver):
    """Turns pipeline frames into face/chest display state."""

    def __init__(self, bus: StateBus):
        super().__init__()
        self._bus = bus
        self._card_id = None  # fact shown for the current answer
        self._card_score = 0.0
        self._bot_text = ""
        self._user_text = ""
        self._new_bot_turn = True
        self._new_user_turn = True
        self.bot_speaking = False
        self.last_activity = asyncio.get_running_loop().time()  # visitor or Cyno talking

    def _touch(self):
        self.last_activity = asyncio.get_running_loop().time()

    def _choose_card(self):
        """Card for the answer so far: a dict, None to clear, or False for no change.

        Uses the visitor's latest sentence plus everything Cynobot has said this turn, so a
        stray keyword in the question can't put an unrelated picture up. A shown card only
        changes when another fact fits the answer clearly better (no flicker mid-sentence)."""
        heard = CYNOCOR_SOUNDALIKE.sub("Cynocor", self._user_text)
        sentences = [s for s in re.split(r"(?<=[.?!])\s+", heard) if s.strip()]
        best = knowledge.pick_card(sentences[-1] if sentences else heard, self._bot_text,
                                   confirmed_only=assistant.load()["strict"])
        if not best:
            if self._card_id and knowledge.DECLINE.search(self._bot_text):
                self._card_id, self._card_score = None, 0.0
                return None
            return False
        score, entry = best
        if entry["id"] == self._card_id:
            self._card_score = score
            return False
        if self._card_id and score < self._card_score + 1:
            return False
        if self._card_id is None:
            stats.kb_lookups += 1  # once per answer that showed a fact
        self._card_id, self._card_score = entry["id"], score
        return knowledge.card(entry)

    async def on_push_frame(self, data: FramePushed):
        if not data.first_push:
            return
        frame = data.frame

        if isinstance(frame, TranscriptionFrame):
            self._touch()
            stats.heard()
            if self._new_user_turn:
                self._user_text = ""
                self._card_id = None
                self._new_user_turn = False
                self._moment_done = False
            self._user_text = f"{self._user_text} {frame.text}".strip()
            # Hearts for thanks or a compliment, a wink for goodbye (once per question).
            if not getattr(self, "_moment_done", False):
                moment = face_moment(self._user_text)
                if moment:
                    self._moment_done = True
                    await self._bus.moment(moment)
            self._new_bot_turn = True
            # A new question clears the old card; the next one is chosen from Cynobot's answer.
            changes = {"expression": "THINKING", "flow_step": "CONVERSE", "user_text": self._user_text, "card": None}
            # "Let's play a game" / "word chain": the chest opens it (Cynobot just says it is open).
            from cyno import games

            wanted = games.voice_request(frame.text, online=self._bus.state.get("voice_mode") != "OFFLINE")
            if wanted:
                changes["game_request"] = {"id": wanted, "ts": int(time.time() * 1000)}
            await self._bus.update(**changes)

        elif isinstance(frame, TTSTextFrame):
            if self._new_bot_turn:
                self._bot_text = ""
                self._card_id, self._card_score = None, 0.0
                self._new_bot_turn = False
            sep = "" if getattr(frame, "includes_inter_frame_spaces", False) or not self._bot_text else " "
            self._bot_text += sep + frame.text
            changes = {"last_spoken_text": self._bot_text.strip()}
            card = self._choose_card()
            if card is not False:
                changes["card"] = card
            await self._bus.update(**changes)

        elif isinstance(frame, BotStartedSpeakingFrame):
            self.bot_speaking = True
            self._touch()
            stats.bot_started()
            self._new_user_turn = True
            await self._bus.update(expression="SPEAKING", flow_step="CONVERSE")

        elif isinstance(frame, BotStoppedSpeakingFrame):
            self.bot_speaking = False
            self._touch()
            self._new_bot_turn = True
            await self._bus.update(expression="IDLE")

        elif isinstance(frame, InterruptionFrame):
            # Visitor talked over the robot: stop the mouth and listen.
            self._new_bot_turn = True
            await self._bus.update(expression="IDLE")


def _facts_prompt(online: bool = True) -> str:
    from cyno import games

    return (
        PERSONA
        + FACT_RULES.format(facts=knowledge.as_prompt(confirmed_only=assistant.load()["strict"]))
        + games.prompt_block(online)  # Word Chain needs the online brain
        + assistant.instructions_block()
    )


def _build_online(transport, recorded_greeting: bool):
    settings = EnglishGeminiLive.Settings(
        system_instruction=_facts_prompt(),
        voice=os.getenv("GEMINI_VOICE", "Aoede"),
        # Without compression Google ends audio sessions after 15 min, which would drop a
        # kiosk that sits connected all day into offline mode. With it, the oldest turns are
        # discarded and the session can run indefinitely.
        context_window_compression=ContextWindowCompressionParams(enabled=True),
        temperature=assistant.temperature(),
    )
    # 3.1 Flash Live spoke 6 of 6 test answers in full; 3.8 Live and 2.5 native audio each sent
    # the words of 3 answers with little or no sound (the "shows the answer but doesn't speak" bug).
    settings.model = os.getenv("GEMINI_MODEL") or greeting.DEFAULT_MODEL
    # With a recorded greeting, the opening context only tells Gemini what was already said;
    # it must not answer it.
    llm = EnglishGeminiLive(
        api_key=os.environ["GOOGLE_API_KEY"], settings=settings, inference_on_context_initialization=not recorded_greeting
    )

    context = LLMContext()
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(context)
    pipeline = Pipeline([transport.input(), user_aggregator, llm, transport.output(), assistant_aggregator])
    return pipeline, context, llm


async def _watch_gemini(llm: EnglishGeminiLive, runner: WorkerRunner, grace_secs: float = 4.0):
    """End the session if Gemini stays disconnected; the chest page then reconnects OFFLINE."""
    down_since = None
    while True:
        await asyncio.sleep(1)
        if llm.is_connected:
            down_since = None
            continue
        loop_time = asyncio.get_running_loop().time()
        down_since = down_since or loop_time
        if loop_time - down_since >= grace_secs:
            logger.error(f"Gemini unreachable for {grace_secs:.0f}s, ending session to fall back offline")
            stats.fallbacks += 1
            await runner.cancel()
            return


async def _watch_idle(observer: DisplayObserver, runner: WorkerRunner, bus: StateBus):
    """The visitor walked away: nobody has spoken for CYNO_IDLE_SECS after Cyno's last words."""
    idle_secs = float(os.getenv("CYNO_IDLE_SECS") or 40)
    if idle_secs <= 0:
        return
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(1)
        if not observer.bot_speaking and loop.time() - observer.last_activity >= idle_secs:
            logger.info(f"No one spoke for {idle_secs:.0f}s, returning to idle")
            stats.idle_ends += 1
            await bus.update(session_end="idle")  # tells the chest page not to reconnect
            await runner.cancel()
            return


def _build_offline(transport):
    # Models are preloaded and cached by offline_models; building these is instant.
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.services.kokoro.tts import KokoroTTSService
    from pipecat.services.ollama.llm import OLLamaLLMService
    from pipecat.services.whisper.stt import WhisperSTTService
    from pipecat.transcriptions.language import Language

    class CachedWhisperSTT(WhisperSTTService):
        def _load(self):
            self._model = offline_models.get_whisper(self._settings.model, self._device, self._compute_type)

    stt = CachedWhisperSTT(
        device="cpu",
        compute_type="int8",
        settings=WhisperSTTService.Settings(model=offline_models.whisper_model_name(), language=Language.EN),
    )
    llm = OLLamaLLMService(
        settings=OLLamaLLMService.Settings(
            model=offline_models.ollama_model_name(),
            max_tokens=90,  # keep spoken answers short; long ones are slow on a CPU-only laptop
            temperature=assistant.temperature(),
            system_instruction=_facts_prompt(online=False),
        ),
    )
    class SpokenNamesKokoro(KokoroTTSService):
        """Kokoro reads "Cynocor" as "Sin-o-cor"; spell the names the way they are said.
        Captions keep the real spelling: Pipecat takes them from the text, not from here."""

        async def run_tts(self, text, context_id):
            text = re.sub(r"(?i)cyno(?=cor|bot)", "Saino", text)
            # The small offline model sometimes adds stage directions like *wink* to jokes.
            text = re.sub(r"\*[^*]{1,30}\*", "", text).replace("*", "")
            if not text.strip():
                return
            async for frame in super().run_tts(text, context_id):
                yield frame

    tts = SpokenNamesKokoro(
        settings=KokoroTTSService.Settings(voice=os.getenv("KOKORO_VOICE", "af_heart")),
        # Pipecat drops a sentence whose audio takes >3 s to start. A busy CPU-only laptop took
        # over 10 s for a first sentence in tests, so wait longer: late is better than silent.
        stop_frame_timeout_s=20.0,
    )

    context = LLMContext()
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context, user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer())
    )
    pipeline = Pipeline(
        [transport.input(), stt, user_aggregator, llm, tts, transport.output(), assistant_aggregator]
    )
    return pipeline, context


async def run_voice_session(connection: SmallWebRTCConnection, bus: StateBus):
    online = bool(os.getenv("GOOGLE_API_KEY")) and await is_online()
    mode = "ONLINE" if online else "OFFLINE"
    logger.info(f"Starting voice session in {mode} mode")
    stats.session_start(mode)
    await bus.update(voice_status="CONNECTING", voice_mode=mode, session_end=None)

    if not online:
        await offline_models.ready()

    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    )
    recorded = greeting.load() if online else None
    if online and not recorded:
        asyncio.create_task(greeting.prepare())  # ready for the next visitor
    if online:
        pipeline, context, llm = _build_online(transport, recorded_greeting=bool(recorded))
    else:
        pipeline, context = _build_offline(transport)

    observer = DisplayObserver(bus)
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True),
        observers=[observer],
        idle_timeout_secs=None,  # a kiosk waits for visitors indefinitely
        processor_unusable_policy=ProcessorUnusablePolicy.END,
    )
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Chest display connected")
        await bus.update(voice_status="LIVE", expression="GREET", flow_step="GREET", card=None, user_text="")
        if recorded:
            text, pcm = recorded
            context.add_message({"role": "assistant", "content": text})
            await bus.update(last_spoken_text=text)
            step = greeting.SAMPLE_RATE * 2 // 25  # 40 ms chunks
            # Speech frames let the output detect talking, so the face moves its mouth. The
            # trailing silence lets it notice the end at once instead of after a timeout.
            pcm += bytes(step * 15)
            audio = [
                SpeechOutputAudioRawFrame(audio=pcm[i : i + step], sample_rate=greeting.SAMPLE_RATE, num_channels=1)
                for i in range(0, len(pcm), step)
            ]
            await worker.queue_frames([LLMRunFrame(), *audio])
            return
        # Ollama ignores the "developer" role, so use "user" for the kickoff there.
        context.add_message({"role": "developer" if online else "user", "content": assistant.load()["greeting"]})
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Chest display disconnected")
        await runner.cancel()

    watchdog = asyncio.create_task(_watch_gemini(llm, runner)) if online else None
    idle_watch = None

    @transport.event_handler("on_client_connected")
    async def start_idle_watch(transport, client):
        nonlocal idle_watch
        observer.last_activity = asyncio.get_running_loop().time()
        idle_watch = asyncio.create_task(_watch_idle(observer, runner, bus))

    try:
        await runner.run()
    finally:
        for task in (watchdog, idle_watch):
            if task:
                task.cancel()
        # If the brain died (e.g. Wi-Fi dropped mid-chat), hang up so the chest page
        # reconnects; the next session re-checks connectivity and can go OFFLINE.
        await connection.disconnect()
        # Back to the welcome screen: clear the last visitor's question, answer and card.
        await bus.update(
            voice_status="OFFLINE", expression="IDLE", flow_step="IDLE",
            card=None, user_text="", last_spoken_text=DEFAULT_STATE["last_spoken_text"],
        )
        stats.session_end()
        logger.info("Voice session ended")
