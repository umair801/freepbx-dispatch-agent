from twilio.rest import Client

from core.config import get_settings
from core.models import DispatchRecord
from core.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


async def send_dispatch_notification_sms(record: DispatchRecord) -> None:
    """
    NEW in AgAI-33. AgAI-7 only ever texted the customer a booking
    confirmation. Dispatch requires notifying the assigned TECHNICIAN too --
    they're the one being sent to a job. assigned_technician_phone is
    populated on the DispatchRecord at write time (see
    dispatch_confirmation_agent._write_dispatch), so no extra lookup is
    needed here.
    """
    if record.assigned_technician_id and record.assigned_technician_phone:
        technician_body = (
            f"New job assigned. ID: {record.job_id}. "
            f"{record.job_type.upper()} at {record.customer_location}. "
            f"Urgency: {record.urgency.upper()}. "
            f"Customer: {record.customer_name}, {record.customer_phone}."
        )

        if settings.app_env.value == "development":
            logger.info(
                "sms_sender.dev_mode_skip_technician",
                job_id=record.job_id,
                to=record.assigned_technician_phone,
                body=technician_body,
            )
        else:
            client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
            message = client.messages.create(
                body=technician_body,
                from_=settings.twilio_phone_number,
                to=record.assigned_technician_phone,
            )
            logger.info(
                "sms_sender.sent_technician",
                job_id=record.job_id,
                to=record.assigned_technician_phone,
                message_sid=message.sid,
            )
    else:
        logger.warning(
            "sms_sender.technician_phone_missing",
            job_id=record.job_id,
            technician_id=record.assigned_technician_id,
        )

    # Customer-facing confirmation, ported pattern from AgAI-7
    if record.customer_phone:
        customer_body = (
            f"Your {record.job_type.upper()} job has been dispatched. "
            f"Job ID: {record.job_id}. "
            f"Technician: {record.assigned_technician_name or 'to be assigned'}. "
            f"Reply CANCEL to cancel."
        )

        if settings.app_env.value == "development":
            logger.info(
                "sms_sender.dev_mode_skip_customer",
                job_id=record.job_id,
                to=record.customer_phone,
                body=customer_body,
            )
            return

        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        message = client.messages.create(
            body=customer_body,
            from_=settings.twilio_phone_number,
            to=record.customer_phone,
        )

        logger.info(
            "sms_sender.sent_customer",
            job_id=record.job_id,
            to=record.customer_phone,
            message_sid=message.sid,
        )
