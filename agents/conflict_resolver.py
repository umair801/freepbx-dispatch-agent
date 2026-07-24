from core.config import get_settings
from core.models import (
    DispatchMatchResult,
    TechnicianMatch,
)
from core.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


def resolve_dispatch_conflict(
    match_result: DispatchMatchResult,
    session_id: str,
    rejected_technician_ids: list[str] | None = None,
) -> tuple[list[TechnicianMatch], str]:
    """
    NEW in AgAI-33, ported pattern from AgAI-7's resolve_conflict. When there's
    no single clear best technician (or the customer/dispatcher rejects the
    top match), return up to 3 ranked alternatives and a natural language
    response, same shape as the base project's slot alternatives.
    """
    rejected_technician_ids = rejected_technician_ids or []

    remaining = [
        m for m in match_result.candidates
        if m.technician.technician_id not in rejected_technician_ids
    ]

    logger.info(
        "conflict_resolver.start",
        session_id=session_id,
        total_candidates=len(match_result.candidates),
        rejected_count=len(rejected_technician_ids),
        remaining=len(remaining),
    )

    if not remaining:
        logger.warning(
            "conflict_resolver.no_technicians_remaining",
            session_id=session_id,
        )
        return [], _build_no_match_response(match_result)

    alternatives = remaining[: settings.max_alternative_technicians]
    response_text = _build_alternatives_response(alternatives, match_result.job_type)

    logger.info(
        "conflict_resolver.resolved",
        session_id=session_id,
        alternatives_count=len(alternatives),
    )

    return alternatives, response_text


def select_technician_from_alternatives(
    alternatives: list[TechnicianMatch],
    choice: str,
) -> TechnicianMatch | None:
    """
    Ported pattern from AgAI-7's select_slot_from_alternatives. Matches an
    ordinal choice ("first", "1", "option 1") or a technician name mention
    to one of the offered alternatives.
    """
    normalized = choice.lower().strip()

    ordinal_map = {
        "first": 0, "1st": 0, "one": 0, "1": 0, "option 1": 0,
        "second": 1, "2nd": 1, "two": 1, "2": 1, "option 2": 1,
        "third": 2, "3rd": 2, "three": 2, "3": 2, "option 3": 2,
    }

    if normalized in ordinal_map:
        idx = ordinal_map[normalized]
        if idx < len(alternatives):
            return alternatives[idx]

    for match in alternatives:
        if match.technician.name.lower() in normalized:
            return match

    return None


def build_confirmation_prompt(match: TechnicianMatch, job_type: str) -> str:
    """Build a confirmation message before finalizing a dispatch."""
    distance_note = (
        f", approximately {match.distance_km:.1f} km away"
        if match.distance_km is not None
        else ""
    )
    return (
        f"I'd like to dispatch {match.technician.name} for your {job_type.upper()} job"
        f"{distance_note}. Shall I confirm this dispatch? Please say yes or no."
    )


# ── Response Builders ─────────────────────────────────────────────────────────

def _build_alternatives_response(alternatives: list[TechnicianMatch], job_type: str) -> str:
    if not alternatives:
        return "I'm sorry, there are no available technicians for that job type right now."

    lines = [f"Here are the available technicians for {job_type} service:"]

    for i, match in enumerate(alternatives, 1):
        distance_note = (
            f", ~{match.distance_km:.1f} km away"
            if match.distance_km is not None
            else ""
        )
        lines.append(f"Option {i}: {match.technician.name}{distance_note}")

    lines.append("Which technician would you like to dispatch?")
    return "\n".join(lines)


def _build_no_match_response(match_result: DispatchMatchResult) -> str:
    return (
        f"I'm sorry, there are no available technicians for {match_result.job_type} "
        f"service right now. I'll flag this job as unassigned so dispatch can "
        f"follow up manually. Would you like me to log the job anyway?"
    )
