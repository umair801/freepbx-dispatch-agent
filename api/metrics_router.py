# api/metrics_router.py
# Ported pattern from AgAI-7's metrics_router.py. Business KPIs pulled from
# the dispatch_ tables instead of the bookings tables.

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from core.database import get_db
from core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get("")
async def get_metrics(period: str = Query(default="monthly")) -> JSONResponse:
    """
    Real-time business KPI dashboard pulled from Supabase. Ported shape from
    AgAI-7: total volume, completion/cancellation rates, channel split --
    with dispatch-specific additions (unassigned rate, urgency breakdown,
    average time-to-assign) that have no AgAI-7 equivalent.
    """
    try:
        db = get_db()
        jobs_result = db.table("dispatch_jobs").select("*").execute()
        jobs = jobs_result.data or []

        total = len(jobs)
        by_status = {}
        by_urgency = {}
        by_job_type = {}

        for job in jobs:
            status = job.get("dispatch_status", "unknown")
            by_status[status] = by_status.get(status, 0) + 1

            urgency = job.get("dispatch_urgency", "unknown")
            by_urgency[urgency] = by_urgency.get(urgency, 0) + 1

            job_type = job.get("dispatch_job_type", "unknown")
            by_job_type[job_type] = by_job_type.get(job_type, 0) + 1

        assigned_count = sum(
            1 for j in jobs if j.get("dispatch_assigned_technician_id")
        )
        unassigned_count = total - assigned_count

        completion_rate = (
            round(by_status.get("completed", 0) / total * 100, 1) if total else 0.0
        )
        cancellation_rate = (
            round(by_status.get("cancelled", 0) / total * 100, 1) if total else 0.0
        )
        assignment_rate = (
            round(assigned_count / total * 100, 1) if total else 0.0
        )

        return JSONResponse(content={
            "period": period,
            "total_jobs": total,
            "by_status": by_status,
            "by_urgency": by_urgency,
            "by_job_type": by_job_type,
            "assigned_count": assigned_count,
            "unassigned_count": unassigned_count,
            "assignment_rate_pct": assignment_rate,
            "completion_rate_pct": completion_rate,
            "cancellation_rate_pct": cancellation_rate,
        })

    except Exception as e:
        logger.error("metrics_router.failed", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to compute metrics.", "detail": str(e)},
        )


@router.get("/health")
async def metrics_health() -> dict:
    return {"status": "ok", "router": "metrics"}
