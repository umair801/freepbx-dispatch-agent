import math
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config import get_settings
from core.models import (
    ParsedIntent,
    DispatchMatchResult,
    TechnicianMatch,
    Technician,
    ServiceType,
    Urgency,
    TechnicianStatus,
)
from core.database import get_technicians_by_skill, get_technician_location
from core.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


# ── Retry Policy ──────────────────────────────────────────────────────────────
# Ported directly from AgAI-7's availability_agent retry policy: 3 attempts,
# exponential backoff, retry only on network-level failures.

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    reraise=True,
)
async def _fetch_geocode(client: httpx.AsyncClient, address: str) -> tuple[float, float] | None:
    """
    Resolve a free-text customer address into lat/lng for proximity ranking
    using the Google Geocoding API. Same defensive pattern as the rest of the
    ported agents: any failure (missing key, no results, API error) returns
    None rather than raising, so the dispatch agent falls back to
    skill+queue-only ranking without proximity rather than crashing the
    pipeline. Retries only on network-level failures, ported from AgAI-7's
    availability_agent retry policy.
    """
    if not settings.google_api_key:
        logger.warning("dispatch_agent.geocode_skipped_no_api_key")
        return None

    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": address, "key": settings.google_api_key}

    response = await client.get(url, params=params, timeout=10.0)
    response.raise_for_status()
    data = response.json()

    if data.get("status") != "OK" or not data.get("results"):
        logger.warning(
            "dispatch_agent.geocode_no_result",
            address=address,
            api_status=data.get("status"),
        )
        return None

    location = data["results"][0]["geometry"]["location"]
    return (location["lat"], location["lng"])


# ── Main Agent Function ───────────────────────────────────────────────────────

async def find_dispatch_candidates(
    parsed_intent: ParsedIntent,
    session_id: str,
) -> DispatchMatchResult:
    """
    NEW in AgAI-33. Replaces check_availability. Instead of querying a
    calendar for open slots, this queries the technician registry for
    skill-matched, available technicians and ranks them by proximity and
    current queue depth. Never crashes the pipeline -- returns an empty
    match result on any failure, same defensive pattern as AgAI-7.
    """
    entities = parsed_intent.entities

    job_type = entities.service_type.value if entities.service_type else ServiceType.GENERAL.value
    urgency = entities.urgency or Urgency.ROUTINE
    customer_location = entities.location

    logger.info(
        "dispatch_agent.start",
        session_id=session_id,
        job_type=job_type,
        urgency=urgency.value,
        has_location=bool(customer_location),
    )

    try:
        raw_technicians = await get_technicians_by_skill(job_type)
        candidates = [Technician(**t) for t in raw_technicians]

        # Filter to technicians who are actually available right now
        available = [t for t in candidates if t.status == TechnicianStatus.AVAILABLE]

        logger.info(
            "dispatch_agent.candidates_found",
            session_id=session_id,
            total_skill_matched=len(candidates),
            available=len(available),
        )

        if not available:
            return _empty_result(job_type, urgency)

        customer_coords = None
        if customer_location:
            async with httpx.AsyncClient() as client:
                customer_coords = await _fetch_geocode(client, customer_location)

        matches = await _rank_technicians(available, customer_coords)

        result = DispatchMatchResult(
            candidates=matches,
            has_match=len(matches) > 0,
            job_type=job_type,
            urgency=urgency,
        )

        logger.info(
            "dispatch_agent.success",
            session_id=session_id,
            candidate_count=len(matches),
            has_match=result.has_match,
        )

        return result

    except Exception as e:
        logger.error(
            "dispatch_agent.failed",
            session_id=session_id,
            error=str(e),
        )
        return _empty_result(job_type, urgency)


# ── Ranking ────────────────────────────────────────────────────────────────────

async def _rank_technicians(
    technicians: list[Technician],
    customer_coords: tuple[float, float] | None,
) -> list[TechnicianMatch]:
    """
    Rank available, skill-matched technicians by a weighted score of
    proximity and current queue depth. Technicians at or above
    technician_max_queue_depth are deprioritized but not excluded --
    conservative routing per the same "unclear beats misrouted" principle
    used in the base project's conflict handling.
    """
    matches: list[TechnicianMatch] = []

    for tech in technicians:
        distance_km = None
        if customer_coords and tech.current_lat is not None and tech.current_lng is not None:
            distance_km = _haversine_km(
                customer_coords[0], customer_coords[1],
                tech.current_lat, tech.current_lng,
            )

        rank_score = _score_technician(tech, distance_km)

        matches.append(
            TechnicianMatch(
                technician=tech,
                distance_km=distance_km,
                rank_score=rank_score,
                skill_match=True,
            )
        )

    matches.sort(key=lambda m: m.rank_score, reverse=True)
    return matches[: settings.max_alternative_technicians]


def _score_technician(tech: Technician, distance_km: float | None) -> float:
    """
    Higher score = better candidate. Combines normalized proximity and queue
    depth using the configured weights. When distance is unknown (no
    geocoding result), proximity contributes a neutral mid-score rather than
    zero, so an unranked-by-distance technician isn't unfairly punished.
    """
    if distance_km is not None:
        # Closer is better; 25km treated as a practical service-area ceiling.
        proximity_score = max(0.0, 1.0 - min(distance_km, 25.0) / 25.0)
    else:
        proximity_score = 0.5

    queue_score = max(
        0.0,
        1.0 - (tech.current_queue_depth / max(settings.technician_max_queue_depth, 1)),
    )

    return (
        settings.dispatch_proximity_weight * proximity_score
        + settings.dispatch_queue_weight * queue_score
    )


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two lat/lng points, in kilometers."""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def _empty_result(job_type: str, urgency: Urgency) -> DispatchMatchResult:
    """Return an empty result on no-match or failure -- never crash the pipeline."""
    return DispatchMatchResult(
        candidates=[],
        has_match=False,
        job_type=job_type,
        urgency=urgency,
    )
