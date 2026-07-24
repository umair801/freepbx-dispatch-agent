import uuid

from core.config import get_settings
from core.models import (
    DispatchRecord,
    DispatchRequest,
    DispatchStatus,
    TechnicianMatch,
)
from core.database import save_dispatch, update_technician_status
from core.logger import get_logger
from notifications.email_sender import send_dispatch_confirmation_email
from notifications.sms_sender import send_dispatch_notification_sms

logger = get_logger(__name__)
settings = get_settings()


async def confirm_dispatch(
    request: DispatchRequest,
    match: TechnicianMatch,
    session_id: str,
) -> tuple[DispatchRecord | None, str]:
    """
    NEW in AgAI-33, ported pattern from AgAI-7's confirm_booking. Writes the
    dispatch record to Supabase (rather than POSTing to a mock CRM, since
    AgAI-33 owns the dispatch table directly), notifies the customer and the
    assigned technician, and returns the record plus response text.
    Returns (None, error_message) on failure -- pipeline never crashes on a
    downstream write or notification failure.
    """
    logger.info(
        "dispatch_confirmation_agent.start",
        session_id=session_id,
        customer=request.customer_name,
        job_type=request.job_type.value,
        technician_id=match.technician.technician_id,
    )

    try:
        record = await _write_dispatch(request, match)

        # Best-effort: bump the assigned technician's queue depth so the next
        # ranking pass reflects this job. Failure here does not fail the
        # dispatch itself.
        try:
            await update_technician_status(
                match.technician.technician_id,
                status="on_job" if match.technician.current_queue_depth == 0 else match.technician.status.value,
                queue_depth=match.technician.current_queue_depth + 1,
            )
        except Exception as e:
            logger.warning(
                "dispatch_confirmation_agent.queue_update_failed",
                technician_id=match.technician.technician_id,
                error=str(e),
            )

        await _send_notifications(record)

        response_text = _build_confirmation_response(record)

        logger.info(
            "dispatch_confirmation_agent.success",
            session_id=session_id,
            job_id=record.job_id,
        )

        return record, response_text

    except Exception as e:
        logger.error(
            "dispatch_confirmation_agent.failed",
            session_id=session_id,
            error=str(e),
        )
        return None, _build_failure_response()


async def _write_dispatch(request: DispatchRequest, match: TechnicianMatch) -> DispatchRecord:
    """Build and persist a DispatchRecord."""
    record = DispatchRecord(
        job_id=str(uuid.uuid4()),
        session_id=request.session_id,
        customer_name=request.customer_name,
        customer_phone=request.customer_phone,
        customer_email=request.customer_email,
        job_type=request.job_type.value,
        customer_location=request.customer_location,
        urgency=request.urgency.value,
        assigned_technician_id=match.technician.technician_id,
        assigned_technician_name=match.technician.name,
        assigned_technician_phone=match.technician.phone,
        status=DispatchStatus.ASSIGNED,
        notes=request.notes,
    )

    saved = await save_dispatch(record.model_dump(mode="json"))
    if not saved:
        raise RuntimeError("dispatch_confirmation_agent: save_dispatch returned no data")

    return record


async def _send_notifications(record: DispatchRecord) -> None:
    """Send email (customer) and SMS (technician) notifications. Never crash on failure."""
    if record.customer_email:
        try:
            await send_dispatch_confirmation_email(record)
        except Exception as e:
            logger.warning(
                "dispatch_confirmation_agent.email_failed",
                job_id=record.job_id,
                error=str(e),
            )

    try:
        await send_dispatch_notification_sms(record)
    except Exception as e:
        logger.warning(
            "dispatch_confirmation_agent.sms_failed",
            job_id=record.job_id,
            error=str(e),
        )


def _build_confirmation_response(record: DispatchRecord) -> str:
    return (
        f"Your {record.job_type.upper()} job has been dispatched to "
        f"{record.assigned_technician_name}. Job ID: {record.job_id}. "
        f"They will be notified and reach out shortly. "
        f"Is there anything else I can help you with?"
    )


def _build_failure_response() -> str:
    return (
        "I'm sorry, I was unable to complete the dispatch at this time. "
        "Please try again or call us directly and we'll get someone out to you."
    )
