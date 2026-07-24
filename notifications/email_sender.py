import sendgrid
from sendgrid.helpers.mail import Mail

from core.config import get_settings
from core.models import DispatchRecord
from core.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


async def send_dispatch_confirmation_email(record: DispatchRecord) -> None:
    """
    Ported pattern from AgAI-7's send_booking_confirmation_email. Sends the
    customer a confirmation that their job has been dispatched, with the
    assigned technician's name in place of an appointment date/time.
    """
    if not record.customer_email:
        logger.info("email_sender.skipped_no_email", job_id=record.job_id)
        return

    html_content = f"""
    <h2>Job Dispatched</h2>
    <p>Dear {record.customer_name},</p>
    <p>Your service request has been dispatched to a technician.</p>
    <table>
        <tr><td><strong>Job ID:</strong></td><td>{record.job_id}</td></tr>
        <tr><td><strong>Service:</strong></td><td>{record.job_type.upper()}</td></tr>
        <tr><td><strong>Location:</strong></td><td>{record.customer_location}</td></tr>
        <tr><td><strong>Urgency:</strong></td><td>{record.urgency.upper()}</td></tr>
        <tr><td><strong>Technician:</strong></td><td>{record.assigned_technician_name or "Pending assignment"}</td></tr>
    </table>
    <p>Your technician will contact you shortly.</p>
    """

    message = Mail(
        from_email=settings.from_email,
        to_emails=record.customer_email,
        subject=f"Job Dispatched - {record.job_type.upper()} - {record.job_id}",
        html_content=html_content,
    )

    if settings.app_env.value == "development":
        logger.info(
            "email_sender.dev_mode_skip",
            job_id=record.job_id,
            to=record.customer_email,
            subject=message.subject,
        )
        return

    sg = sendgrid.SendGridAPIClient(api_key=settings.sendgrid_api_key)
    response = sg.send(message)

    logger.info(
        "email_sender.sent",
        job_id=record.job_id,
        to=record.customer_email,
        status_code=response.status_code,
    )
