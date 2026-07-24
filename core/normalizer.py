from datetime import datetime
import uuid

from core.models import NormalizedMessage, Channel
from core.logger import get_logger

logger = get_logger(__name__)


def normalize_asterisk_event(
    transcript: str,
    channel_id: str,
    caller_number: str,
    metadata: dict | None = None,
) -> NormalizedMessage:
    """
    NEW in AgAI-33. Normalize an Asterisk ARI StasisStart/ChannelTalkingStarted
    event (with an attached transcript from the speech-to-text layer) into a
    standard message object. channel_id is Asterisk's channel identifier --
    unique per call, plays the same role CallSid played in AgAI-7.
    """
    message = NormalizedMessage(
        session_id=channel_id,
        channel=Channel.ASTERISK_VOICE,
        raw_text=transcript.strip(),
        customer_phone=_clean_phone(caller_number),
        timestamp=datetime.utcnow(),
        metadata=metadata or {},
    )

    logger.info(
        "normalizer.asterisk_event",
        session_id=message.session_id,
        phone=message.customer_phone,
        text_length=len(message.raw_text),
    )

    return message


def normalize_chat_input(
    raw_text: str,
    channel: Channel,
    customer_phone: str | None = None,
    customer_email: str | None = None,
    customer_name: str | None = None,
    session_id: str | None = None,
    metadata: dict | None = None,
) -> NormalizedMessage:
    """
    Ported unchanged from AgAI-7. Normalize a chat/SMS/WhatsApp message into a
    standard message object. Generates a new session_id if one is not provided.
    """
    resolved_session_id = session_id or _generate_session_id(channel, customer_phone)

    message = NormalizedMessage(
        session_id=resolved_session_id,
        channel=channel,
        raw_text=raw_text.strip(),
        customer_phone=_clean_phone(customer_phone) if customer_phone else None,
        customer_email=customer_email,
        customer_name=customer_name,
        timestamp=datetime.utcnow(),
        metadata=metadata or {},
    )

    logger.info(
        "normalizer.chat_input",
        session_id=message.session_id,
        channel=channel.value,
        phone=message.customer_phone,
        text_length=len(message.raw_text),
    )

    return message


def normalize_twilio_sms_webhook(form_data: dict) -> NormalizedMessage:
    """
    Ported and trimmed from AgAI-7's normalize_twilio_webhook. AgAI-33 keeps
    Twilio only for SMS (technician-facing and customer-facing text), not for
    inbound voice -- Asterisk owns that role now, see normalize_asterisk_event.
    """
    message_sid = form_data.get("MessageSid", "")
    caller = form_data.get("From", "")
    body = form_data.get("Body", "")

    channel = Channel.WHATSAPP if caller.startswith("whatsapp:") else Channel.SMS
    session_id = _generate_session_id(channel, caller)
    clean_phone = _clean_phone(caller)

    message = NormalizedMessage(
        session_id=session_id,
        channel=channel,
        raw_text=body.strip(),
        customer_phone=clean_phone,
        timestamp=datetime.utcnow(),
        metadata={
            "message_sid": message_sid,
            "raw_from": caller,
        },
    )

    logger.info(
        "normalizer.twilio_sms_webhook",
        session_id=message.session_id,
        channel=channel.value,
        has_text=bool(body.strip()),
    )

    return message


# ── Helpers (ported unchanged) ─────────────────────────────────────────────────

def _clean_phone(phone: str | None) -> str | None:
    """Strip whitespace and whatsapp: prefix from phone numbers."""
    if not phone:
        return None
    return phone.replace("whatsapp:", "").strip()


def _generate_session_id(channel: Channel, identifier: str | None) -> str:
    """
    Generate a deterministic session ID from channel + identifier.
    Falls back to a random UUID if no identifier is available.
    """
    if identifier:
        clean = identifier.replace("+", "").replace("-", "").replace(" ", "")
        return f"{channel.value}_{clean}"
    return f"{channel.value}_{uuid.uuid4().hex[:12]}"
