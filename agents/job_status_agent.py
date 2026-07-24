from core.config import get_settings
from core.models import DispatchRecord, DispatchStatus
from core.database import get_dispatches_by_phone, update_dispatch_status
from core.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


async def lookup_dispatch_jobs(
    customer_phone: str,
    session_id: str,
) -> tuple[list[DispatchRecord], str]:
    """
    NEW in AgAI-33, ported pattern from AgAI-7's lookup_bookings. Looks up
    active dispatch jobs for a customer by phone number. Unlike AgAI-7, there
    is no "cancellation window" policy check -- a dispatch is an in-progress
    or upcoming field job, not a scheduled slot with an advance-notice policy,
    so cancellation eligibility is status-based instead (see cancel_dispatch).
    """
    logger.info(
        "job_status_agent.lookup",
        session_id=session_id,
        customer_phone=customer_phone,
    )

    try:
        raw = await get_dispatches_by_phone(customer_phone)
        all_jobs = [DispatchRecord(**j) for j in raw]

        active_statuses = {
            DispatchStatus.PENDING,
            DispatchStatus.ASSIGNED,
            DispatchStatus.EN_ROUTE,
            DispatchStatus.IN_PROGRESS,
        }
        active = [j for j in all_jobs if j.status in active_statuses]

        logger.info(
            "job_status_agent.lookup_result",
            session_id=session_id,
            total=len(all_jobs),
            active=len(active),
        )

        if not active:
            return [], "I could not find any active dispatch jobs for your phone number. Would you like to request one?"

        response_text = _build_jobs_list_response(active)
        return active, response_text

    except Exception as e:
        logger.error(
            "job_status_agent.lookup_failed",
            session_id=session_id,
            error=str(e),
        )
        return [], "I was unable to retrieve your dispatch jobs at this time. Please try again."


async def cancel_dispatch(
    job: DispatchRecord,
    session_id: str,
    reason: str | None = None,
) -> tuple[bool, str]:
    """
    Cancel a dispatch job. Jobs already IN_PROGRESS cannot be cancelled
    through this flow -- that requires a human dispatcher, since a
    technician may already be on site.
    """
    logger.info(
        "job_status_agent.cancel_start",
        session_id=session_id,
        job_id=job.job_id,
    )

    if job.status == DispatchStatus.IN_PROGRESS:
        logger.warning(
            "job_status_agent.cancel_blocked_in_progress",
            session_id=session_id,
            job_id=job.job_id,
        )
        return False, (
            "That job is already in progress with a technician on site. "
            "Please call us directly if you need to make a change."
        )

    try:
        success = await update_dispatch_status(
            job.job_id,
            status=DispatchStatus.CANCELLED.value,
            extra={"notes": reason} if reason else None,
        )

        if not success:
            raise RuntimeError("update_dispatch_status returned False")

        logger.info(
            "job_status_agent.cancelled",
            session_id=session_id,
            job_id=job.job_id,
        )

        return True, _build_cancellation_response(job)

    except Exception as e:
        logger.error(
            "job_status_agent.cancel_failed",
            session_id=session_id,
            job_id=job.job_id,
            error=str(e),
        )
        return False, "I was unable to cancel that job at this time. Please call us directly."


def select_job_from_list(jobs: list[DispatchRecord], choice: str) -> DispatchRecord | None:
    """Ported pattern from AgAI-7's select_booking_from_list."""
    normalized = choice.lower().strip()

    ordinal_map = {
        "first": 0, "1st": 0, "1": 0, "one": 0,
        "second": 1, "2nd": 1, "2": 1, "two": 1,
        "third": 2, "3rd": 2, "3": 2, "three": 2,
    }

    if normalized in ordinal_map:
        idx = ordinal_map[normalized]
        if idx < len(jobs):
            return jobs[idx]

    for job in jobs:
        if job.job_id.lower() in normalized:
            return job

    return None


# ── Response Builders ─────────────────────────────────────────────────────────

def _build_jobs_list_response(jobs: list[DispatchRecord]) -> str:
    lines = ["I found the following active dispatch jobs for your account:"]
    for i, j in enumerate(jobs, 1):
        tech_note = f" -- assigned to {j.assigned_technician_name}" if j.assigned_technician_name else " -- awaiting assignment"
        lines.append(
            f"Job {i}: {j.job_type.upper()} ({j.status.value}){tech_note}. ID: {j.job_id}"
        )
    lines.append("Which job would you like to check on or cancel?")
    return "\n".join(lines)


def _build_cancellation_response(job: DispatchRecord) -> str:
    return (
        f"Your {job.job_type.upper()} dispatch job has been cancelled. "
        f"Job ID: {job.job_id}. Would you like to request a new dispatch?"
    )
