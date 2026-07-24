from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional
from datetime import datetime


# ── Enums ────────────────────────────────────────────────────────────────────

class Channel(str, Enum):
    VOICE = "voice"           # kept for chat/SMS parity; Asterisk calls use ASTERISK_VOICE
    ASTERISK_VOICE = "asterisk_voice"   # NEW in AgAI-33 -- calls arriving via Asterisk AMI/ARI
    CHAT = "chat"
    SMS = "sms"
    WHATSAPP = "whatsapp"


class Intent(str, Enum):
    DISPATCH_REQUEST = "dispatch_request"    # NEW in AgAI-33 -- replaces BOOK
    CHECK_STATUS = "check_status"
    CANCEL = "cancel"
    GENERAL_INQUIRY = "general_inquiry"
    UNKNOWN = "unknown"


class DispatchStatus(str, Enum):
    """NEW in AgAI-33 -- replaces BookingStatus."""
    PENDING = "pending"
    ASSIGNED = "assigned"
    EN_ROUTE = "en_route"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    UNASSIGNED = "unassigned"   # no technician match found


class Urgency(str, Enum):
    """NEW in AgAI-33 -- drives dispatch ranking, has no equivalent in AgAI-7."""
    EMERGENCY = "emergency"
    URGENT = "urgent"
    ROUTINE = "routine"


class TechnicianStatus(str, Enum):
    """NEW in AgAI-33."""
    AVAILABLE = "available"
    ON_JOB = "on_job"
    OFF_SHIFT = "off_shift"
    UNAVAILABLE = "unavailable"


class ServiceType(str, Enum):
    HVAC = "hvac"
    PLUMBING = "plumbing"
    ELECTRICAL = "electrical"
    CLEANING = "cleaning"
    PEST_CONTROL = "pest_control"
    LANDSCAPING = "landscaping"
    SECURITY_ALARM = "security_alarm"   # NEW in AgAI-33 -- target industry addition
    GENERAL = "general"


# ── Core Message Object (ported unchanged from AgAI-7) ────────────────────────

class NormalizedMessage(BaseModel):
    """Unified message object passed through the entire agent pipeline."""
    session_id: str
    channel: Channel
    raw_text: str
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    customer_name: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


# ── Intent Extraction (ported, entities extended for dispatch) ────────────────

class ExtractedEntities(BaseModel):
    """Entities extracted from customer message by the Intent Parser."""
    service_type: Optional[ServiceType] = None
    location: Optional[str] = None              # customer address / service location
    urgency: Optional[Urgency] = None            # NEW in AgAI-33
    notes: Optional[str] = None
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None


class ParsedIntent(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    entities: ExtractedEntities
    raw_response: str = ""


# ── Technician Registry (NEW in AgAI-33, no AgAI-7 equivalent) ────────────────

class Technician(BaseModel):
    technician_id: str
    name: str
    phone: str
    skills: list[ServiceType]
    status: TechnicianStatus = TechnicianStatus.AVAILABLE
    current_lat: Optional[float] = None
    current_lng: Optional[float] = None
    current_queue_depth: int = 0
    shift_start: Optional[str] = None    # "08:00"
    shift_end: Optional[str] = None      # "17:00"


class TechnicianMatch(BaseModel):
    """A ranked candidate technician for a given dispatch job."""
    technician: Technician
    distance_km: Optional[float] = None
    rank_score: float = 0.0
    skill_match: bool = True


class DispatchMatchResult(BaseModel):
    """Result of the Dispatch Agent's ranking pass -- replaces AvailabilityResult."""
    candidates: list[TechnicianMatch]
    has_match: bool
    job_type: str
    urgency: Urgency


# ── Dispatch Job (NEW in AgAI-33 -- replaces BookingRequest/BookingRecord) ────

class DispatchRequest(BaseModel):
    session_id: str
    customer_name: str
    customer_phone: str
    customer_email: Optional[str] = None
    job_type: ServiceType
    customer_location: str
    urgency: Urgency = Urgency.ROUTINE
    notes: Optional[str] = None


class DispatchRecord(BaseModel):
    job_id: str
    session_id: str
    customer_name: str
    customer_phone: str
    customer_email: Optional[str] = None
    job_type: str
    customer_location: str
    urgency: str
    assigned_technician_id: Optional[str] = None
    assigned_technician_name: Optional[str] = None
    assigned_technician_phone: Optional[str] = None
    status: DispatchStatus = DispatchStatus.PENDING
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Agent State (LangGraph) -- ported shape, dispatch fields swapped in ───────

class AgentState(BaseModel):
    """Shared state object that flows through every node in the LangGraph."""
    message: Optional[NormalizedMessage] = None
    parsed_intent: Optional[ParsedIntent] = None
    dispatch_match: Optional[DispatchMatchResult] = None
    selected_technician: Optional[Technician] = None
    dispatch: Optional[DispatchRecord] = None
    response_text: str = ""
    error: Optional[str] = None
    turn_count: int = 0
    conversation_history: list[dict] = Field(default_factory=list)
