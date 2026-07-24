"""
NEW in AgAI-33 -- no AgAI-7 equivalent. Speech-to-text and text-to-speech
bridge for calls arriving via Asterisk ARI.

Honest scope note: Twilio's <Gather input="speech"> does STT for you and
hands back a finished transcript. Asterisk's externalMedia gives us a raw
RTP/ulaw audio stream instead -- we own turning that into text ourselves.
This module provides two pieces:

1. synthesize_speech_asterisk() -- TTS via ElevenLabs, returns audio bytes
   in a format Asterisk's `play` endpoint can serve (reuses the same
   provider as the base project's voice replies, so no new API signup).

2. RtpAudioBuffer -- accumulates raw RTP payload chunks arriving over the
   externalMedia UDP/WebSocket stream and exposes them as a single audio
   buffer once silence (end of utterance) is detected, ready to hand to a
   streaming STT call.

The RTP buffering and silence-detection logic here is written against the
Asterisk externalMedia audio contract (raw ulaw, 8kHz, no RTP header when
using the websocket variant) documented by Asterisk, but has not been
exercised against a live PBX yet -- there is no PBX access at this stage of
the project. This is flagged explicitly rather than presented as verified;
validating it is Phase 1 Step 1's first concrete task once the local
Dockerized FreePBX environment is up (see docker/ and README "Verify Before
Continuing").
"""

import audioop
import time

import httpx

from core.config import get_settings
from core.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

_ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
_ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"

# Silence detection tuning -- ulaw RMS threshold and how long silence must
# persist before we consider an utterance finished. These are starting
# values; real calibration requires audio from an actual Asterisk instance.
_SILENCE_RMS_THRESHOLD = 400
_SILENCE_DURATION_SECONDS = 1.2


async def synthesize_speech_asterisk(text: str) -> bytes | None:
    """
    Synthesize speech via ElevenLabs and return audio bytes in 8kHz ulaw --
    the format Asterisk's externalMedia / play pipeline expects for phone
    audio. Reuses ELEVENLABS_API_KEY already present in the shared .env.
    Returns None on any failure so the caller can fall back to a pre-recorded
    prompt rather than crash the call.
    """
    if not settings.elevenlabs_api_key:
        logger.warning("tts_bridge.no_elevenlabs_key")
        return None

    voice_id = settings.elevenlabs_voice_id
    url = _ELEVENLABS_TTS_URL.format(voice_id=voice_id)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={
                    "xi-api-key": settings.elevenlabs_api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": "eleven_turbo_v2",
                    "output_format": "ulaw_8000",
                },
                timeout=15.0,
            )
            response.raise_for_status()
            audio_bytes = response.content

        logger.info("tts_bridge.synthesized", text_length=len(text), audio_bytes=len(audio_bytes))
        return audio_bytes

    except Exception as e:
        logger.error("tts_bridge.synthesis_failed", error=str(e))
        return None


async def transcribe_speech_asterisk(audio_bytes: bytes) -> str | None:
    """
    Transcribe a completed utterance (ulaw 8kHz PCM, converted to WAV below)
    via ElevenLabs STT. Returns None on failure -- caller should prompt the
    customer to repeat rather than pass an empty transcript into the intent
    parser, which would otherwise misclassify silence as an unknown intent.
    """
    if not settings.elevenlabs_api_key:
        logger.warning("stt_bridge.no_elevenlabs_key")
        return None

    try:
        wav_bytes = _ulaw_to_wav(audio_bytes)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                _ELEVENLABS_STT_URL,
                headers={"xi-api-key": settings.elevenlabs_api_key},
                files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                data={"model_id": "scribe_v1"},
                timeout=15.0,
            )
            response.raise_for_status()
            data = response.json()

        transcript = data.get("text", "").strip()
        logger.info("stt_bridge.transcribed", transcript_length=len(transcript))
        return transcript or None

    except Exception as e:
        logger.error("stt_bridge.transcription_failed", error=str(e))
        return None


def _ulaw_to_wav(ulaw_bytes: bytes, sample_rate: int = 8000) -> bytes:
    """Convert raw 8-bit ulaw payload to a 16-bit PCM WAV container."""
    import io
    import wave

    pcm_bytes = audioop.ulaw2lin(ulaw_bytes, 2)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)

    return buffer.getvalue()


class RtpAudioBuffer:
    """
    Accumulates raw ulaw audio chunks from an externalMedia stream and
    signals when an utterance appears complete (silence held for
    _SILENCE_DURATION_SECONDS after some speech was captured).

    NOT YET VALIDATED against live Asterisk RTP output -- see module
    docstring. The chunk-append and silence-timer logic itself is
    straightforward and unit-testable independent of a live PBX; what
    specifically needs live validation is (a) whether externalMedia frames
    arrive with any header bytes to strip, and (b) real-world RMS thresholds
    for actual phone-line audio versus the placeholder values above.
    """

    def __init__(self):
        self._chunks: list[bytes] = []
        self._last_voice_time: float | None = None
        self._has_speech = False

    def append(self, chunk: bytes) -> None:
        self._chunks.append(chunk)

        rms = audioop.rms(audioop.ulaw2lin(chunk, 2), 2)
        now = time.monotonic()

        if rms > _SILENCE_RMS_THRESHOLD:
            self._has_speech = True
            self._last_voice_time = now

    def is_utterance_complete(self) -> bool:
        if not self._has_speech or self._last_voice_time is None:
            return False
        return (time.monotonic() - self._last_voice_time) >= _SILENCE_DURATION_SECONDS

    def get_audio_and_reset(self) -> bytes:
        combined = b"".join(self._chunks)
        self._chunks = []
        self._has_speech = False
        self._last_voice_time = None
        return combined
