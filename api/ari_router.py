"""
NEW in AgAI-33 -- replaces api/voice_router.py's role. Where AgAI-7's voice
router receives a Twilio webhook POST with a ready-made transcript, this
module owns the Asterisk ARI call lifecycle end to end: a call enters our
Stasis app, we answer it, bridge it to an externalMedia channel to receive
audio, buffer that audio until an utterance completes, transcribe it, run
the SAME core.orchestrator.run_agent() pipeline the rest of the project
uses, synthesize the reply, and play it back. The pipeline downstream of
"we have a transcript" is unchanged from the ported architecture -- only
everything upstream of that (getting a transcript at all) is new.
"""

from fastapi import APIRouter
import asyncio

from core.ari_client import AriClient
from core.normalizer import normalize_asterisk_event
from core.orchestrator import run_agent
from core.session_manager import close_session
from core.logger import get_logger
from core.config import get_settings
from notifications.voice_bridge import (
    RtpAudioBuffer,
    transcribe_speech_asterisk,
    synthesize_speech_asterisk,
)

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/ari", tags=["Asterisk ARI"])

_ari = AriClient()

# Per-call audio buffers, keyed by Asterisk channel ID. A call's buffer lives
# only as long as the call itself -- cleaned up on StasisEnd.
_buffers: dict[str, RtpAudioBuffer] = {}

_GREETING = (
    "Thank you for calling. I can dispatch a technician for you, "
    "check on an existing job, or cancel a job. How can I help?"
)

_TERMINAL_PHRASES = [
    "has been dispatched",
    "has been cancelled",
    "anything else i can help",
    "goodbye",
]


def _is_terminal(reply: str) -> bool:
    lower = reply.lower()
    return any(phrase in lower for phrase in _TERMINAL_PHRASES)


async def _speak(channel_id: str, text: str) -> None:
    """Synthesize and play a reply into the call. Falls back to logging-only
    (never crashes the call) if synthesis fails -- matches the defensive
    pattern used throughout the ported agents."""
    audio_bytes = await synthesize_speech_asterisk(text)
    if not audio_bytes:
        logger.warning("ari_router.tts_failed_no_playback", channel_id=channel_id, text=text[:80])
        return

    # In a full deployment this audio would be written to a location ARI's
    # `play` endpoint can fetch (e.g. a short-lived static file route, same
    # pattern as AgAI-7's voice_router _audio_cache). Wiring that static
    # serve route is a Phase 1 Step 4 integration-testing task once a local
    # Asterisk instance exists to play audio back into.
    media_uri = f"sound:agai33-dynamic-{channel_id}"
    await _ari.play_media_uri(channel_id, media_uri)


async def _handle_stasis_start(event: dict) -> None:
    """A new call has entered our Stasis application -- answer it and start
    receiving audio."""
    channel = event.get("channel", {})
    channel_id = channel.get("id", "")
    caller_number = channel.get("caller", {}).get("number", "unknown")

    logger.info("ari_router.stasis_start", channel_id=channel_id, caller=caller_number)

    await _ari.answer_channel(channel_id)
    _buffers[channel_id] = RtpAudioBuffer()

    await _speak(channel_id, _GREETING)

    # Start the externalMedia bridge so we begin receiving raw audio for
    # this call. The RTP/WebSocket receiver that feeds _buffers[channel_id]
    # runs as a separate always-on listener (see run_external_media_server
    # below); this call just tells Asterisk to start streaming to it.
    await _ari.start_external_media(
        channel_id_prefix=channel_id,
        external_host=f"{settings.app_host}:{settings.app_port + 1}",
    )


async def _handle_stasis_end(event: dict) -> None:
    """Call ended -- clean up buffer and session state."""
    channel = event.get("channel", {})
    channel_id = channel.get("id", "")

    logger.info("ari_router.stasis_end", channel_id=channel_id)
    _buffers.pop(channel_id, None)
    await close_session(channel_id)


async def _process_utterance(channel_id: str, caller_number: str) -> None:
    """
    Called once the RTP receiver detects a completed utterance for this
    channel. Transcribes, runs the shared agent pipeline, and speaks the
    reply back -- this is the point where AgAI-33's new call-handling layer
    hands off to the ported orchestrator, unchanged from AgAI-7's shape.
    """
    buffer = _buffers.get(channel_id)
    if not buffer:
        return

    audio = buffer.get_audio_and_reset()
    transcript = await transcribe_speech_asterisk(audio)

    if not transcript:
        await _speak(channel_id, "Sorry, I didn't catch that. Could you repeat?")
        return

    message = normalize_asterisk_event(
        transcript=transcript,
        channel_id=channel_id,
        caller_number=caller_number,
    )

    result = await run_agent(message)
    reply = result.get("response_text") or "I'm sorry, could you say that again?"

    await _speak(channel_id, reply)

    if _is_terminal(reply):
        await asyncio.sleep(1.0)
        await _ari.hangup_channel(channel_id)


def register_handlers() -> None:
    """Wire ARI events to their handlers. Called once at app startup."""
    _ari.on("StasisStart", _handle_stasis_start)
    _ari.on("StasisEnd", _handle_stasis_end)


async def start_ari_listener() -> None:
    """Long-running task: connect to ARI's event WebSocket and stay
    connected (with reconnect/backoff, handled inside AriClient) for the
    lifetime of the app."""
    register_handlers()
    await _ari.connect_and_listen()


@router.get("/health")
async def ari_health() -> dict:
    return {
        "status": "ok",
        "router": "ari",
        "active_calls": len(_buffers),
        "ari_app": settings.asterisk_ari_app_name,
    }
