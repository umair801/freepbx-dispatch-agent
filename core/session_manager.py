from datetime import datetime
from core.database import save_session, get_session
from core.models import NormalizedMessage, Channel
from core.logger import get_logger

logger = get_logger(__name__)


async def load_session(session_id: str) -> dict:
    """
    Load existing session from Supabase. Ported unchanged from AgAI-7.
    Returns empty session dict if none found.
    """
    existing = await get_session(session_id)

    if existing:
        logger.info(
            "session_manager.loaded",
            session_id=session_id,
            turn_count=existing.get("turn_count", 0),
        )
        return existing

    logger.info("session_manager.new_session", session_id=session_id)
    return _empty_session(session_id)


async def save_session_state(
    session_id: str,
    message: NormalizedMessage,
    agent_state: dict,
) -> bool:
    """
    Persist current session state after each agent run. Ported unchanged from
    AgAI-7 -- the session shape doesn't care whether the terminal action is a
    booking or a dispatch, only that intent + turn history are tracked.
    """
    conversation_history = agent_state.get("conversation_history", [])
    intent = None
    if agent_state.get("parsed_intent"):
        intent = agent_state["parsed_intent"].intent.value

    session_data = {
        "session_id": session_id,
        "channel": message.channel.value,
        "customer_phone": message.customer_phone,
        "customer_email": message.customer_email,
        "customer_name": message.customer_name,
        "conversation_history": conversation_history,
        "current_intent": intent,
        "turn_count": agent_state.get("turn_count", 0),
        "is_active": True,
        "updated_at": datetime.utcnow().isoformat(),
    }

    success = await save_session(session_data)

    logger.info(
        "session_manager.saved",
        session_id=session_id,
        turn_count=session_data["turn_count"],
        intent=intent,
    )

    return success


async def close_session(session_id: str) -> bool:
    """Mark a session as inactive (call ended or conversation complete)."""
    session_data = {
        "session_id": session_id,
        "is_active": False,
        "updated_at": datetime.utcnow().isoformat(),
    }
    success = await save_session(session_data)
    logger.info("session_manager.closed", session_id=session_id)
    return success


def _empty_session(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "channel": None,
        "customer_phone": None,
        "customer_email": None,
        "customer_name": None,
        "conversation_history": [],
        "current_intent": None,
        "turn_count": 0,
        "is_active": True,
    }
