from supabase import create_client, Client
from core.config import get_settings
from core.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

_client: Client | None = None


def get_db() -> Client:
    """Return a singleton Supabase client. Ported unchanged from AgAI-7."""
    global _client
    if _client is None:
        _client = create_client(settings.supabase_url, settings.supabase_key)
        logger.info("database.connected", url=settings.supabase_url[:40])
    return _client


# ── Column mapping ─────────────────────────────────────────────────────────────
# Every Supabase column in this project is prefixed dispatch_ (frontend lives
# at dispatch.datawebify.com). Python-side models keep clean, unprefixed field
# names for readability; these two small translation layers convert at the
# database boundary only, so agents/models code never has to think about the
# prefix.

_DISPATCH_JOB_COLUMNS = {
    "job_id": "dispatch_job_id",
    "session_id": "dispatch_session_id",
    "customer_name": "dispatch_customer_name",
    "customer_phone": "dispatch_customer_phone",
    "customer_email": "dispatch_customer_email",
    "job_type": "dispatch_job_type",
    "customer_location": "dispatch_customer_location",
    "urgency": "dispatch_urgency",
    "assigned_technician_id": "dispatch_assigned_technician_id",
    "assigned_technician_name": "dispatch_assigned_technician_name",
    "assigned_technician_phone": "dispatch_assigned_technician_phone",
    "status": "dispatch_status",
    "notes": "dispatch_notes",
    "created_at": "dispatch_created_at",
}

_TECHNICIAN_COLUMNS = {
    "technician_id": "dispatch_technician_id",
    "name": "dispatch_technician_name",
    "phone": "dispatch_technician_phone",
    "skills": "dispatch_technician_skills",
    "status": "dispatch_technician_status",
    "current_lat": "dispatch_technician_current_lat",
    "current_lng": "dispatch_technician_current_lng",
    "current_queue_depth": "dispatch_technician_current_queue_depth",
    "shift_start": "dispatch_technician_shift_start",
    "shift_end": "dispatch_technician_shift_end",
}


def _to_db(data: dict, column_map: dict) -> dict:
    """Translate clean Python field names to dispatch_-prefixed DB columns."""
    return {column_map.get(k, k): v for k, v in data.items()}


def _from_db(row: dict, column_map: dict) -> dict:
    """Translate dispatch_-prefixed DB columns back to clean Python field names."""
    reverse_map = {v: k for k, v in column_map.items()}
    return {reverse_map.get(k, k): v for k, v in row.items()}


# ── Dispatch jobs ──────────────────────────────────────────────────────────────

async def save_dispatch(dispatch_data: dict) -> dict | None:
    """Insert a dispatch job record into Supabase."""
    try:
        db = get_db()
        db_row = _to_db(dispatch_data, _DISPATCH_JOB_COLUMNS)
        result = db.table("dispatch_jobs").insert(db_row).execute()
        logger.info("database.dispatch_saved", job_id=dispatch_data.get("job_id"))
        return _from_db(result.data[0], _DISPATCH_JOB_COLUMNS) if result.data else None
    except Exception as e:
        logger.error("database.save_dispatch_failed", error=str(e))
        return None


async def get_dispatch_by_id(job_id: str) -> dict | None:
    """Fetch a single dispatch job by ID."""
    try:
        db = get_db()
        result = (
            db.table("dispatch_jobs")
            .select("*")
            .eq("dispatch_job_id", job_id)
            .execute()
        )
        return _from_db(result.data[0], _DISPATCH_JOB_COLUMNS) if result.data else None
    except Exception as e:
        logger.error("database.get_dispatch_failed", error=str(e))
        return None


async def get_dispatches_by_phone(phone: str) -> list[dict]:
    """Fetch all dispatch jobs for a customer by phone number."""
    try:
        db = get_db()
        result = (
            db.table("dispatch_jobs")
            .select("*")
            .eq("dispatch_customer_phone", phone)
            .order("dispatch_created_at", desc=True)
            .execute()
        )
        return [_from_db(row, _DISPATCH_JOB_COLUMNS) for row in (result.data or [])]
    except Exception as e:
        logger.error("database.get_dispatches_failed", error=str(e))
        return []


async def update_dispatch_status(job_id: str, status: str, extra: dict | None = None) -> bool:
    """Update dispatch status (assigned, en_route, in_progress, completed, cancelled)."""
    try:
        db = get_db()
        update_data = _to_db({"status": status, **(extra or {})}, _DISPATCH_JOB_COLUMNS)
        db.table("dispatch_jobs").update(update_data).eq("dispatch_job_id", job_id).execute()
        logger.info("database.dispatch_updated", job_id=job_id, status=status)
        return True
    except Exception as e:
        logger.error("database.update_dispatch_failed", error=str(e))
        return False


# ── Technician registry ──────────────────────────────────────────────────────

async def get_technicians_by_skill(skill: str) -> list[dict]:
    """Fetch all technicians whose skills array contains the given service type."""
    try:
        db = get_db()
        result = (
            db.table("dispatch_technicians")
            .select("*")
            .contains("dispatch_technician_skills", [skill])
            .execute()
        )
        return [_from_db(row, _TECHNICIAN_COLUMNS) for row in (result.data or [])]
    except Exception as e:
        logger.error("database.get_technicians_by_skill_failed", error=str(e))
        return []


async def get_technician_location(technician_id: str) -> dict | None:
    """Fetch the most recent location ping for a technician."""
    try:
        db = get_db()
        result = (
            db.table("dispatch_technician_locations")
            .select("*")
            .eq("dispatch_technician_id", technician_id)
            .order("dispatch_location_updated_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        row = result.data[0]
        return {
            "technician_id": row["dispatch_technician_id"],
            "lat": row["dispatch_location_lat"],
            "lng": row["dispatch_location_lng"],
            "updated_at": row["dispatch_location_updated_at"],
        }
    except Exception as e:
        logger.error("database.get_technician_location_failed", error=str(e))
        return None


async def update_technician_status(technician_id: str, status: str, queue_depth: int | None = None) -> bool:
    """Update a technician's status and optionally their current queue depth."""
    try:
        db = get_db()
        update_data = {"dispatch_technician_status": status}
        if queue_depth is not None:
            update_data["dispatch_technician_current_queue_depth"] = queue_depth
        db.table("dispatch_technicians").update(update_data).eq(
            "dispatch_technician_id", technician_id
        ).execute()
        logger.info("database.technician_updated", technician_id=technician_id, status=status)
        return True
    except Exception as e:
        logger.error("database.update_technician_failed", error=str(e))
        return False


# ── Session persistence ──────────────────────────────────────────────────────

_SESSION_COLUMNS = {
    "session_id": "dispatch_session_id",
    "channel": "dispatch_channel",
    "customer_phone": "dispatch_customer_phone",
    "customer_email": "dispatch_customer_email",
    "customer_name": "dispatch_customer_name",
    "conversation_history": "dispatch_conversation_history",
    "current_intent": "dispatch_current_intent",
    "turn_count": "dispatch_turn_count",
    "is_active": "dispatch_is_active",
    "updated_at": "dispatch_updated_at",
}


async def save_session(session_data: dict) -> bool:
    """Upsert session state."""
    try:
        db = get_db()
        db_row = _to_db(session_data, _SESSION_COLUMNS)
        db.table("dispatch_sessions").upsert(db_row).execute()
        return True
    except Exception as e:
        logger.error("database.save_session_failed", error=str(e))
        return False


async def get_session(session_id: str) -> dict | None:
    """Retrieve session by ID."""
    try:
        db = get_db()
        result = (
            db.table("dispatch_sessions")
            .select("*")
            .eq("dispatch_session_id", session_id)
            .execute()
        )
        return _from_db(result.data[0], _SESSION_COLUMNS) if result.data else None
    except Exception as e:
        logger.error("database.get_session_failed", error=str(e))
        return None


async def log_agent_event(
    session_id: str,
    event: str,
    channel: str | None = None,
    intent: str | None = None,
    job_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Write an agent event to the logs table."""
    try:
        db = get_db()
        db.table("dispatch_agent_logs").insert({
            "dispatch_session_id": session_id,
            "dispatch_event": event,
            "dispatch_channel": channel,
            "dispatch_intent": intent,
            "dispatch_job_id": job_id,
            "dispatch_metadata": metadata or {},
        }).execute()
    except Exception as e:
        logger.error("database.log_event_failed", error=str(e))
