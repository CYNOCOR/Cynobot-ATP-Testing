"""Voice pipeline: browser mic (WebRTC) -> speech AI -> browser speaker.

Two interchangeable brains, picked per session:
  ONLINE   Gemini Live (speech-to-speech, natural voice, campus info via tool call)
  OFFLINE  Whisper (STT) -> Ollama (LLM) -> Kokoro (TTS), all on the laptop

Pipeline events are mirrored onto the StateBus so the face and chest displays
show THINKING / SPEAKING / captions in sync with the audio.
"""

import asyncio
import os

from loguru import logger

from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    FunctionCallInProgressFrame,
    InterruptionFrame,
    LLMRunFrame,
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
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.workers.runner import WorkerRunner

from cyno import assistant, knowledge, offline_models
from cyno.bus import StateBus
from cyno.stats import stats

PERSONA = """
You are Cyno, the robot receptionist at the entrance of the Informatics Institute
of Technology (IIT). You were built by Team Cynocor.

How you speak:
- Always reply in English, even if the visitor speaks Sinhala, Tamil or another
  language. In that case, kindly say in English that Sinhala and Tamil support is
  coming soon, then help them in English.
- Warm, friendly and concise: one or two short sentences per reply, like a real
  receptionist. Never use lists, markdown or emojis; everything you say is spoken.
- If asked, say honestly that you are a robot.
- Do not give medical, legal or emergency decisions; direct people to staff.
"""

ONLINE_RULES = """
What you know:
- For ANY question about IIT (places, offices, directions, courses, admissions,
  contacts, facilities), call lookup_campus_info first and answer only from its result.
- If the tool finds nothing, say you are not sure and suggest asking the staff at
  the front desk. Never invent rooms, names, times or phone numbers.
"""

OFFLINE_RULES = """
Keep every reply to one or two short sentences.
Answer questions about IIT ONLY from the facts below. If the answer is not in the
facts, say you are not sure and suggest asking the staff at the front desk. Never
invent rooms, names, times or phone numbers.

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


class DisplayObserver(BaseObserver):
    """Turns pipeline frames into face/chest display state."""

    def __init__(self, bus: StateBus, cards_from_transcript: bool):
        super().__init__()
        self._bus = bus
        self._cards_from_transcript = cards_from_transcript  # offline: no tool call shows cards
        self._bot_text = ""
        self._user_text = ""
        self._new_bot_turn = True
        self._new_user_turn = True

    async def on_push_frame(self, data: FramePushed):
        if not data.first_push:
            return
        frame = data.frame

        if isinstance(frame, TranscriptionFrame):
            stats.heard()
            if self._new_user_turn:
                self._user_text = ""
                self._new_user_turn = False
            self._user_text = f"{self._user_text} {frame.text}".strip()
            self._new_bot_turn = True
            changes = {"expression": "THINKING", "flow_step": "CONVERSE", "user_text": self._user_text}
            if self._cards_from_transcript:
                hits = knowledge.search(self._user_text, limit=1, confirmed_only=assistant.load()["strict"])
                if hits:
                    changes["card"] = {"title": hits[0]["title"], "body": hits[0]["answer"]}
            await self._bus.update(**changes)

        elif isinstance(frame, FunctionCallInProgressFrame):
            await self._bus.update(expression="THINKING")

        elif isinstance(frame, TTSTextFrame):
            if self._new_bot_turn:
                self._bot_text = ""
                self._new_bot_turn = False
            sep = "" if getattr(frame, "includes_inter_frame_spaces", False) or not self._bot_text else " "
            self._bot_text += sep + frame.text
            await self._bus.update(last_spoken_text=self._bot_text.strip())

        elif isinstance(frame, BotStartedSpeakingFrame):
            stats.bot_started()
            self._new_user_turn = True
            await self._bus.update(expression="SPEAKING", flow_step="CONVERSE")

        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._new_bot_turn = True
            await self._bus.update(expression="IDLE")

        elif isinstance(frame, InterruptionFrame):
            # Visitor talked over the robot: stop the mouth and listen.
            self._new_bot_turn = True
            await self._bus.update(expression="IDLE")


def _build_online(transport, bus: StateBus):
    async def lookup_campus_info(params: FunctionCallParams):
        query = params.arguments.get("query", "")
        strict = assistant.load()["strict"]
        scored = knowledge.search_scored(query, confirmed_only=strict)  # strict: unconfirmed facts are never used
        results = [e for _, e in scored]
        logger.info(f"KB lookup '{query}' -> {[r['id'] for r in results]}")
        stats.kb_lookups += 1
        if results:
            top = results[0]
            await bus.update(card={"title": top["title"], "body": top["answer"]})
            reply = {"found": True, "results": [{"title": r["title"], "answer": r["answer"]} for r in results]}
            if len(scored) > 1 and scored[0][0] == scored[1][0]:
                # Equally good matches: the question is ambiguous or the facts may disagree.
                reply["note"] = (
                    "Several facts match equally. Only answer if one clearly answers the question; "
                    "otherwise ask which one the visitor means, or say you're not sure."
                )
            await params.result_callback(reply)
        else:
            await params.result_callback(
                {
                    "found": False,
                    "instruction": "No confirmed information. Tell the visitor you're not sure and suggest the front desk. Do not guess.",
                }
            )

    tools = ToolsSchema(
        standard_tools=[
            FunctionSchema(
                name="lookup_campus_info",
                description="Search the official IIT knowledge base for locations, offices, directions, courses, admissions, contacts and facilities.",
                properties={
                    "query": {"type": "string", "description": "What the visitor is asking about, e.g. 'admissions office'."}
                },
                required=["query"],
                handler=lookup_campus_info,
            )
        ]
    )

    settings = EnglishGeminiLive.Settings(
        system_instruction=PERSONA + ONLINE_RULES + assistant.instructions_block(),
        voice=os.getenv("GEMINI_VOICE", "Aoede"),
        # Without compression Google ends audio sessions after 15 min, which would drop a
        # kiosk that sits connected all day into offline mode. With it, the oldest turns are
        # discarded and the session can run indefinitely.
        context_window_compression=ContextWindowCompressionParams(enabled=True),
        temperature=assistant.temperature(),
    )
    if os.getenv("GEMINI_MODEL"):
        settings.model = os.environ["GEMINI_MODEL"]
    llm = EnglishGeminiLive(api_key=os.environ["GOOGLE_API_KEY"], settings=settings, tools=tools)

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
            system_instruction=PERSONA + OFFLINE_RULES.format(facts=knowledge.as_prompt(confirmed_only=assistant.load()["strict"])) + assistant.instructions_block(),
        ),
    )
    tts = KokoroTTSService(
        settings=KokoroTTSService.Settings(voice=os.getenv("KOKORO_VOICE", "af_heart")),
        # Pipecat drops a sentence whose audio takes >3 s to start; a CPU-only laptop can need longer.
        stop_frame_timeout_s=10.0,
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
    await bus.update(voice_status="CONNECTING", voice_mode=mode)

    if not online:
        await offline_models.ready()

    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    )
    if online:
        pipeline, context, llm = _build_online(transport, bus)
    else:
        pipeline, context = _build_offline(transport)

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True),
        observers=[DisplayObserver(bus, cards_from_transcript=not online)],
        idle_timeout_secs=None,  # a kiosk waits for visitors indefinitely
        processor_unusable_policy=ProcessorUnusablePolicy.END,
    )
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Chest display connected")
        await bus.update(voice_status="LIVE", expression="GREET", flow_step="GREET", card=None, user_text="")
        # Ollama ignores the "developer" role, so use "user" for the kickoff there.
        context.add_message({"role": "developer" if online else "user", "content": assistant.load()["greeting"]})
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Chest display disconnected")
        await runner.cancel()

    watchdog = asyncio.create_task(_watch_gemini(llm, runner)) if online else None
    try:
        await runner.run()
    finally:
        if watchdog:
            watchdog.cancel()
        # If the brain died (e.g. Wi-Fi dropped mid-chat), hang up so the chest page
        # reconnects; the next session re-checks connectivity and can go OFFLINE.
        await connection.disconnect()
        await bus.update(voice_status="OFFLINE", expression="IDLE", flow_step="IDLE")
        stats.session_end()
        logger.info("Voice session ended")
