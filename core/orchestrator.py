from langgraph.graph import StateGraph, END

from core.models import (
    Intent,
    NormalizedMessage,
    DispatchRequest,
    ServiceType,
    Urgency,
    DispatchStatus,
)
from core.config import get_settings
from core.logger import get_logger
from agents.intent_parser import parse_intent
from agents.dispatch_agent import find_dispatch_candidates
from agents.conflict_resolver import (
    resolve_dispatch_conflict,
    select_technician_from_alternatives,
    build_confirmation_prompt,
)
from agents.dispatch_confirmation_agent import confirm_dispatch
from agents.job_status_agent import (
    lookup_dispatch_jobs,
    cancel_dispatch,
    select_job_from_list,
)

logger = get_logger(__name__)
settings = get_settings()


# ── Node Functions ────────────────────────────────────────────────────────────
# Ported 1:1 from AgAI-7's orchestrator node shape. Each node still does one
# thing, mutates state, and returns it. Only the domain logic inside each node
# changed (dispatch instead of booking) -- the node/routing pattern itself did
# not need to be redesigned.

async def node_parse_intent(state: dict) -> dict:
    """Node 1: Parse intent from normalized message. Ported unchanged."""
    message: NormalizedMessage = state["message"]

    logger.info("orchestrator.node_parse_intent", session_id=message.session_id)

    parsed = await parse_intent(message)
    state["parsed_intent"] = parsed
    state["turn_count"] = state.get("turn_count", 0) + 1

    history = state.get("conversation_history", [])
    history.append({"role": "user", "content": message.raw_text})
    state["conversation_history"] = history

    return state


async def node_find_dispatch_candidates(state: dict) -> dict:
    """Node 2: Find candidate technicians. Replaces node_check_availability."""
    message: NormalizedMessage = state["message"]
    parsed_intent = state["parsed_intent"]

    logger.info("orchestrator.node_find_dispatch_candidates", session_id=message.session_id)

    match_result = await find_dispatch_candidates(parsed_intent, message.session_id)
    state["dispatch_match"] = match_result

    if not match_result.has_match:
        state["response_text"] = (
            f"I'm sorry, there are no available technicians for "
            f"{match_result.job_type} service right now. "
            f"I'll log this job as unassigned so dispatch can follow up."
        )

    return state


async def node_resolve_conflict(state: dict) -> dict:
    """Node 3: Offer alternative technicians. Replaces node_resolve_conflict (slots)."""
    message: NormalizedMessage = state["message"]
    match_result = state["dispatch_match"]
    rejected_ids = state.get("rejected_technician_ids", [])

    logger.info("orchestrator.node_resolve_conflict", session_id=message.session_id)

    alternatives, response_text = resolve_dispatch_conflict(
        match_result, message.session_id, rejected_ids
    )

    state["alternative_technicians"] = [a.model_dump() for a in alternatives]
    state["response_text"] = response_text

    return state


async def node_confirm_dispatch(state: dict) -> dict:
    """Node 4: Confirm and write the dispatch job. Replaces node_confirm_booking."""
    message: NormalizedMessage = state["message"]
    match_result = state["dispatch_match"]

    logger.info("orchestrator.node_confirm_dispatch", session_id=message.session_id)

    selected_match = None
    if state.get("selected_technician_match"):
        from core.models import TechnicianMatch
        selected_match = TechnicianMatch(**state["selected_technician_match"])
    elif match_result and match_result.candidates:
        selected_match = match_result.candidates[0]

    if not selected_match:
        state["response_text"] = "I was unable to find a suitable technician. Please try again."
        return state

    request = DispatchRequest(
        session_id=message.session_id,
        customer_name=message.customer_name or "Valued Customer",
        customer_phone=message.customer_phone or "",
        customer_email=message.customer_email,
        job_type=state["parsed_intent"].entities.service_type or ServiceType.GENERAL,
        customer_location=state["parsed_intent"].entities.location or "Not provided",
        urgency=state["parsed_intent"].entities.urgency or Urgency.ROUTINE,
        notes=state["parsed_intent"].entities.notes,
    )

    dispatch, response_text = await confirm_dispatch(request, selected_match, message.session_id)

    if dispatch:
        state["dispatch"] = dispatch.model_dump()

    state["response_text"] = response_text

    history = state.get("conversation_history", [])
    history.append({"role": "assistant", "content": response_text})
    state["conversation_history"] = history

    return state


async def node_lookup_jobs(state: dict) -> dict:
    """Node 5: Look up existing dispatch jobs for cancel/status. Replaces node_lookup_bookings."""
    message: NormalizedMessage = state["message"]

    logger.info("orchestrator.node_lookup_jobs", session_id=message.session_id)

    if not message.customer_phone:
        state["response_text"] = "I need your phone number to look up your jobs. Could you please provide it?"
        state["existing_jobs"] = []
        return state

    jobs, response_text = await lookup_dispatch_jobs(message.customer_phone, message.session_id)

    state["existing_jobs"] = [j.model_dump() for j in jobs]
    state["response_text"] = response_text

    return state


async def node_cancel_job(state: dict) -> dict:
    """Node 6: Cancel a dispatch job. Replaces node_cancel_booking."""
    message: NormalizedMessage = state["message"]

    logger.info("orchestrator.node_cancel_job", session_id=message.session_id)

    existing = state.get("existing_jobs", [])
    if not existing:
        state["response_text"] = "No active dispatch jobs found to cancel."
        return state

    from core.models import DispatchRecord
    job = DispatchRecord(**existing[0])

    success, response_text = await cancel_dispatch(job, message.session_id)
    state["response_text"] = response_text

    return state


async def node_general_response(state: dict) -> dict:
    """Node 7: Handle general inquiries. Ported, copy updated for dispatch."""
    message: NormalizedMessage = state["message"]

    logger.info("orchestrator.node_general_response", session_id=message.session_id)

    state["response_text"] = (
        "I can help you request a technician dispatch, check on an existing job, "
        "or cancel a job. What would you like to do today?"
    )
    return state


async def node_unknown_response(state: dict) -> dict:
    """Node 8: Handle unknown or unclassified intent. Ported, copy updated."""
    state["response_text"] = (
        "I'm sorry, I didn't quite understand that. "
        "I can help you request a technician, check job status, or cancel a job. "
        "Could you please rephrase your request?"
    )
    return state


# ── Routing Functions ─────────────────────────────────────────────────────────
# Ported unchanged in shape from AgAI-7 -- fully deterministic, no LLM judgment
# in the routing layer itself.

def route_by_intent(state: dict) -> str:
    intent = state["parsed_intent"].intent

    routes = {
        Intent.DISPATCH_REQUEST: "find_dispatch_candidates",
        Intent.CANCEL: "lookup_jobs",
        Intent.CHECK_STATUS: "lookup_jobs",
        Intent.GENERAL_INQUIRY: "general_response",
        Intent.UNKNOWN: "unknown_response",
    }

    route = routes.get(intent, "unknown_response")
    logger.info("orchestrator.route_by_intent", intent=intent.value, route=route)
    return route


def route_after_dispatch_match(state: dict) -> str:
    """Ported from route_after_availability."""
    match_result = state.get("dispatch_match")

    if not match_result or not match_result.has_match:
        return "resolve_conflict"

    return "confirm_dispatch"


# ── Graph Assembly ────────────────────────────────────────────────────────────
# Identical shape to AgAI-7's build_graph. Node names changed to reflect
# dispatch domain; the graph topology (entry point, conditional edges,
# terminal edges) is the same pipeline structure that was already validated.

def build_graph() -> StateGraph:
    graph = StateGraph(dict)

    graph.add_node("parse_intent", node_parse_intent)
    graph.add_node("find_dispatch_candidates", node_find_dispatch_candidates)
    graph.add_node("resolve_conflict", node_resolve_conflict)
    graph.add_node("confirm_dispatch", node_confirm_dispatch)
    graph.add_node("lookup_jobs", node_lookup_jobs)
    graph.add_node("cancel_job", node_cancel_job)
    graph.add_node("general_response", node_general_response)
    graph.add_node("unknown_response", node_unknown_response)

    graph.set_entry_point("parse_intent")

    graph.add_conditional_edges(
        "parse_intent",
        route_by_intent,
        {
            "find_dispatch_candidates": "find_dispatch_candidates",
            "lookup_jobs": "lookup_jobs",
            "general_response": "general_response",
            "unknown_response": "unknown_response",
        },
    )

    graph.add_conditional_edges(
        "find_dispatch_candidates",
        route_after_dispatch_match,
        {
            "confirm_dispatch": "confirm_dispatch",
            "resolve_conflict": "resolve_conflict",
        },
    )

    graph.add_edge("resolve_conflict", END)
    graph.add_edge("confirm_dispatch", END)
    graph.add_edge("lookup_jobs", "cancel_job")
    graph.add_edge("cancel_job", END)
    graph.add_edge("general_response", END)
    graph.add_edge("unknown_response", END)

    return graph.compile()


# ── Public Interface ──────────────────────────────────────────────────────────

_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


async def run_agent(message: NormalizedMessage) -> dict:
    """
    Main entry point. Ported unchanged in shape from AgAI-7. Pass a
    NormalizedMessage, get back the final state. response_text in the
    returned state is what gets sent to the customer or synthesized back
    to the caller via Asterisk TTS.
    """
    graph = get_graph()

    initial_state = {
        "message": message,
        "parsed_intent": None,
        "dispatch_match": None,
        "selected_technician_match": None,
        "dispatch": None,
        "response_text": "",
        "error": None,
        "turn_count": 0,
        "conversation_history": [],
        "existing_jobs": [],
        "alternative_technicians": [],
        "rejected_technician_ids": [],
    }

    logger.info(
        "orchestrator.run_start",
        session_id=message.session_id,
        channel=message.channel.value,
    )

    final_state = await graph.ainvoke(initial_state)

    logger.info(
        "orchestrator.run_complete",
        session_id=message.session_id,
        response_length=len(final_state.get("response_text", "")),
    )

    return final_state
