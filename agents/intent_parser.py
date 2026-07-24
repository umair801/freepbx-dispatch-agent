import json
import re
from datetime import datetime

from google import genai
from google.genai import types

from core.config import get_settings
from core.models import (
    NormalizedMessage,
    ParsedIntent,
    ExtractedEntities,
    Intent,
    ServiceType,
    Urgency,
)
from core.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

_client = genai.Client(api_key=settings.gemini_api_key)

# Ported from AgAI-7's intent_parser prompt shape. Intent set and entities are
# rewritten for dispatch: date/time extraction is dropped (dispatch is
# immediate, not scheduled), location and urgency are added since they drive
# technician ranking.
_SYSTEM_PROMPT = """You are an intent classification engine for a field service dispatch system.

Your job is to analyze a customer message and return a JSON object with exactly this structure:

{{
  "intent": "<one of: dispatch_request, check_status, cancel, general_inquiry, unknown>",
  "confidence": <float between 0.0 and 1.0>,
  "entities": {{
    "service_type": "<one of: hvac, plumbing, electrical, cleaning, pest_control, landscaping, security_alarm, general, or null>",
    "location": "<customer address or area mentioned or null>",
    "urgency": "<one of: emergency, urgent, routine, or null>",
    "notes": "<any special instructions or null>"
  }}
}}

Rules:
- Return ONLY valid JSON. No markdown, no explanation, no preamble.
- Today's date is {today}.
- If the customer mentions "AC", "air conditioning", "furnace", or "heating" -- service_type is "hvac".
- If the customer mentions words like "flooding", "no power", "gas smell", "burst pipe",
  "not working at all", "emergency" -- urgency is "emergency".
- If the customer expresses time pressure ("today", "ASAP", "as soon as possible") without
  describing a hazard -- urgency is "urgent".
- If no urgency signal is present, urgency is "routine".
- If intent is cancel or check_status, entities can be mostly null.
- Confidence below 0.5 means intent is "unknown".
"""


async def parse_intent(message: NormalizedMessage) -> ParsedIntent:
    """Ported from AgAI-7 -- same Gemini call shape, dispatch-specific prompt."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    prompt = _SYSTEM_PROMPT.format(today=today)
    user_content = f"Customer message: {message.raw_text}"

    logger.info(
        "intent_parser.start",
        session_id=message.session_id,
        channel=message.channel.value,
        text=message.raw_text[:100],
    )

    try:
        response = _call_gemini(prompt, user_content)
        parsed = _parse_gemini_response(response)

        logger.info(
            "intent_parser.success",
            session_id=message.session_id,
            intent=parsed.intent.value,
            confidence=parsed.confidence,
            service_type=str(parsed.entities.service_type),
            urgency=str(parsed.entities.urgency),
        )

        return parsed

    except Exception as e:
        logger.error(
            "intent_parser.failed",
            session_id=message.session_id,
            error=str(e),
        )
        return _fallback_intent(str(e))


def _call_gemini(system_prompt: str, user_content: str) -> str:
    full_prompt = f"{system_prompt}\n\n{user_content}"
    response = _client.models.generate_content(
        model=settings.gemini_model,
        contents=full_prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=512,
        ),
    )
    return response.text


def _parse_gemini_response(raw_response: str) -> ParsedIntent:
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw_response).strip()
    data = json.loads(cleaned)

    intent_str = data.get("intent", "unknown").lower()
    try:
        intent = Intent(intent_str)
    except ValueError:
        intent = Intent.UNKNOWN

    entities_data = data.get("entities", {})

    service_str = entities_data.get("service_type")
    try:
        service_type = ServiceType(service_str) if service_str else None
    except ValueError:
        service_type = ServiceType.GENERAL

    urgency_str = entities_data.get("urgency")
    try:
        urgency = Urgency(urgency_str) if urgency_str else Urgency.ROUTINE
    except ValueError:
        urgency = Urgency.ROUTINE

    entities = ExtractedEntities(
        service_type=service_type,
        location=entities_data.get("location"),
        urgency=urgency,
        notes=entities_data.get("notes"),
    )

    return ParsedIntent(
        intent=intent,
        confidence=float(data.get("confidence", 0.5)),
        entities=entities,
        raw_response=raw_response,
    )


def _fallback_intent(error_msg: str) -> ParsedIntent:
    return ParsedIntent(
        intent=Intent.UNKNOWN,
        confidence=0.0,
        entities=ExtractedEntities(),
        raw_response=f"ERROR: {error_msg}",
    )
