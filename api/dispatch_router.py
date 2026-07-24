# api/dispatch_router.py
# Ported from AgAI-7's chat_router.py -- SMS/WhatsApp still runs through
# Twilio in AgAI-33 (only inbound voice moved to Asterisk, see ari_router.py),
# so this router is largely unchanged in shape. Renamed to reflect the
# dispatch domain and to house the manual/API dispatch-request endpoint
# that a client's existing dashboard could call directly (see README
# "Integration into an existing AI engine").

import uuid
from typing import Optional

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import JSONResponse
from twilio.twiml.messaging_response import MessagingResponse

from core.normalizer import normalize_chat_input
from core.orchestrator import run_agent
from core.session_manager import close_session, save_session_state
from core.models import Channel
from core.database import get_db
from core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/dispatch", tags=["Dispatch"])


# ── Twilio SMS / WhatsApp Webhook (ported, unchanged in shape) ────────────────

@router.post("/webhook/twilio")
async def twilio_dispatch_webhook(
    request: Request,
    From: Optional[str] = Form(None),
    Body: Optional[str] = Form(None),
    MessageSid: Optional[str] = Form(None),
) -> Response:
    """
    Twilio webhook for inbound WhatsApp and SMS messages. Voice moved to
    Asterisk in AgAI-33 (see api/ari_router.py) -- this endpoint keeps
    handling text channels, since a customer texting "my job is done" or
    "cancel my dispatch" doesn't touch the PBX at all.
    """
    caller = From or "unknown"
    message_text = Body or ""
    message_sid = MessageSid or f"msg-{uuid.uuid4().hex[:8]}"

    channel = Channel.WHATSAPP if caller.startswith("whatsapp:") else Channel.SMS

    logger.info(
        "dispatch_router.twilio_received",
        channel=channel.value,
        from_=caller,
        message_sid=message_sid,
        text_preview=message_text[:60],
    )

    if not message_text.strip():
        reply = "Hello! I can dispatch a technician, check job status, or cancel a job. How can I help?"
        return _twilio_reply(reply)

    try:
        normalized = normalize_chat_input(
            raw_text=message_text,
            channel=channel,
            customer_phone=caller,
        )

        result = await run_agent(normalized)
        agent_reply: str = result.get("response_text", "")

        if not agent_reply:
            agent_reply = "I am sorry, I could not process that. Please try again."

        await save_session_state(normalized.session_id, normalized, result)

        logger.info("dispatch_router.twilio_reply_sent", reply_preview=agent_reply[:80])
        return _twilio_reply(agent_reply)

    except Exception as exc:
        logger.error("dispatch_router.twilio_error", error=str(exc), exc_info=True)
        return _twilio_reply("I am sorry, something went wrong. Please try again in a moment.")


# ── Web Widget / Direct API (ported, unchanged in shape) ──────────────────────

@router.post("/webhook/web")
async def web_dispatch_webhook(request: Request) -> JSONResponse:
    """
    Web widget and direct API dispatch endpoint. Same request/response
    contract as AgAI-7's web_chat_webhook -- a client's existing dashboard
    can POST here directly instead of going through a phone call at all,
    which is the "integration into an existing AI engine" adapter pattern
    called out in the project README.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body."})

    message_text: str = body.get("message", "").strip()
    session_id: Optional[str] = body.get("session_id")
    customer_phone: Optional[str] = body.get("customer_phone")
    customer_email: Optional[str] = body.get("customer_email")
    customer_name: Optional[str] = body.get("customer_name")

    if not message_text:
        return JSONResponse(
            status_code=400,
            content={"error": "message field is required and cannot be empty."},
        )

    logger.info("dispatch_router.web_received", session_id=session_id, text_preview=message_text[:60])

    try:
        normalized = normalize_chat_input(
            raw_text=message_text,
            channel=Channel.CHAT,
            customer_phone=customer_phone,
            customer_email=customer_email,
            customer_name=customer_name,
            session_id=session_id,
        )

        result = await run_agent(normalized)
        agent_reply: str = result.get("response_text", "")

        if not agent_reply:
            agent_reply = "I am sorry, I could not process that. Please try again."

        await save_session_state(normalized.session_id, normalized, result)

        logger.info(
            "dispatch_router.web_reply_sent",
            session_id=normalized.session_id,
            reply_preview=agent_reply[:80],
        )

        return JSONResponse(content={
            "reply": agent_reply,
            "session_id": normalized.session_id,
            "channel": Channel.CHAT.value,
            "dispatch": result.get("dispatch"),
        })

    except Exception as exc:
        logger.error("dispatch_router.web_error", error=str(exc), exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error. Please try again.",
                "reply": "I am sorry, something went wrong on my end.",
            },
        )


# ── Session Close (ported unchanged) ───────────────────────────────────────────

@router.post("/session/close")
async def close_dispatch_session(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        session_id: str = body.get("session_id", "")

        if not session_id:
            return JSONResponse(status_code=400, content={"error": "session_id is required."})

        await close_session(session_id)
        logger.info("dispatch_router.session_closed", session_id=session_id)

        return JSONResponse(content={"status": "closed", "session_id": session_id})

    except Exception as exc:
        logger.error("dispatch_router.session_close_error", error=str(exc))
        return JSONResponse(status_code=500, content={"error": "Failed to close session."})


# ── Jobs and Technicians List (NEW -- for the future dispatch.datawebify.com
# frontend's live dispatch board and technician roster views, see README
# "Frontend Dashboard") ─────────────────────────────────────────────────

@router.get("/jobs")
async def list_dispatch_jobs(status: Optional[str] = None, limit: int = 50) -> JSONResponse:
    """
    List dispatch jobs, optionally filtered by status (pending/assigned/
    en_route/in_progress/completed/cancelled/unassigned). This is the read
    endpoint a dashboard would poll for the live dispatch board -- distinct
    from /metrics, which returns aggregate counts, not individual job rows.
    """
    try:
        db = get_db()
        query = db.table("dispatch_jobs").select("*").order("dispatch_created_at", desc=True).limit(limit)
        if status:
            query = query.eq("dispatch_status", status)
        result = query.execute()

        jobs = [_from_db_job(row) for row in (result.data or [])]

        return JSONResponse(content={"jobs": jobs, "count": len(jobs)})

    except Exception as exc:
        logger.error("dispatch_router.list_jobs_failed", error=str(exc))
        return JSONResponse(status_code=500, content={"error": "Failed to retrieve jobs."})


@router.get("/technicians")
async def list_technicians(status: Optional[str] = None) -> JSONResponse:
    """
    List technicians, optionally filtered by status. Backs the future
    dashboard's technician roster view -- lets a non-technical viewer see
    who's available, their skills, and current queue depth, which is what
    actually explains a dispatch decision rather than a black-box assignment.
    """
    try:
        db = get_db()
        query = db.table("dispatch_technicians").select("*")
        if status:
            query = query.eq("dispatch_technician_status", status)
        result = query.execute()

        technicians = [_from_db_technician(row) for row in (result.data or [])]

        return JSONResponse(content={"technicians": technicians, "count": len(technicians)})

    except Exception as exc:
        logger.error("dispatch_router.list_technicians_failed", error=str(exc))
        return JSONResponse(status_code=500, content={"error": "Failed to retrieve technicians."})


# ── Health Check ──────────────────────────────────────────────────────────────

@router.get("/test")
async def dispatch_test_endpoint() -> dict:
    return {
        "status": "ok",
        "router": "dispatch",
        "endpoints": [
            "POST /dispatch/webhook/twilio  -- SMS/WhatsApp via Twilio",
            "POST /dispatch/webhook/web     -- Web widget / existing-dashboard adapter",
            "POST /dispatch/session/close   -- Close a session explicitly",
            "GET  /dispatch/jobs            -- List dispatch jobs (for dashboard)",
            "GET  /dispatch/technicians     -- List technicians (for dashboard)",
        ],
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _twilio_reply(message: str) -> Response:
    resp = MessagingResponse()
    resp.message(message)
    return Response(content=str(resp), media_type="application/xml")


def _from_db_job(row: dict) -> dict:
    """Translate a raw dispatch_jobs row (dispatch_-prefixed columns) into a
    clean dict for the /dispatch/jobs list response."""
    return {
        "job_id": row.get("dispatch_job_id"),
        "session_id": row.get("dispatch_session_id"),
        "customer_name": row.get("dispatch_customer_name"),
        "customer_phone": row.get("dispatch_customer_phone"),
        "job_type": row.get("dispatch_job_type"),
        "customer_location": row.get("dispatch_customer_location"),
        "urgency": row.get("dispatch_urgency"),
        "assigned_technician_id": row.get("dispatch_assigned_technician_id"),
        "assigned_technician_name": row.get("dispatch_assigned_technician_name"),
        "status": row.get("dispatch_status"),
        "notes": row.get("dispatch_notes"),
        "created_at": row.get("dispatch_created_at"),
    }


def _from_db_technician(row: dict) -> dict:
    """Translate a raw dispatch_technicians row into a clean dict for the
    /dispatch/technicians list response."""
    return {
        "technician_id": row.get("dispatch_technician_id"),
        "name": row.get("dispatch_technician_name"),
        "phone": row.get("dispatch_technician_phone"),
        "skills": row.get("dispatch_technician_skills"),
        "status": row.get("dispatch_technician_status"),
        "current_lat": row.get("dispatch_technician_current_lat"),
        "current_lng": row.get("dispatch_technician_current_lng"),
        "current_queue_depth": row.get("dispatch_technician_current_queue_depth"),
        "shift_start": row.get("dispatch_technician_shift_start"),
        "shift_end": row.get("dispatch_technician_shift_end"),
    }
