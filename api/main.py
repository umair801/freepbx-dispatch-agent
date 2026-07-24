# api/main.py

import time
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import settings
from core.logger import get_logger
from api.dispatch_router import router as dispatch_router
from api.ari_router import router as ari_router, start_ari_listener
from api.metrics_router import router as metrics_router

logger = get_logger(__name__)

_ari_task: asyncio.Task | None = None


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs once on startup and once on shutdown. Ported shape from AgAI-7 --
    extended to also start the ARI event listener as a background task, since
    unlike Twilio's webhook model, ARI requires an always-on WebSocket
    connection to receive call events.
    """
    global _ari_task

    logger.info(
        "app.startup",
        env=settings.app_env.value,
        host=settings.app_host,
        port=settings.app_port,
    )

    _ari_task = asyncio.create_task(start_ari_listener())
    logger.info("app.ari_listener_started")

    yield

    if _ari_task:
        _ari_task.cancel()
        try:
            await _ari_task
        except asyncio.CancelledError:
            pass

    logger.info("app.shutdown")


# ── App Factory ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="AgAI-33 FreePBX Dispatch Agent",
    description=(
        "Gemini-powered AI dispatch agent for field service businesses running "
        "self-hosted Asterisk/FreePBX. Takes inbound calls via Asterisk ARI, "
        "matches jobs to technicians by skill, proximity, and urgency, and "
        "notifies both customer and technician. Ported architecture from "
        "AgAI-7's voice/chat scheduling agent."
    ),
    version="0.1.0",
    contact={
        "name": "Muhammad Umair | Datawebify",
        "url": "https://datawebify.com",
    },
    lifespan=lifespan,
)


# ── Middleware ────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Log every request with method, path, status code, and duration. Ported unchanged."""
    start = time.time()
    try:
        response = await call_next(request)
        duration_ms = round((time.time() - start) * 1000, 2)
        print(f"[{response.status_code}] {request.method} {request.url.path} {duration_ms}ms")
        return response
    except Exception as exc:
        duration_ms = round((time.time() - start) * 1000, 2)
        print(f"[500] {request.method} {request.url.path} {duration_ms}ms ERROR: {exc}")
        raise


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(dispatch_router)
app.include_router(ari_router)
app.include_router(metrics_router)


# ── Root and Health Endpoints ─────────────────────────────────────────────────

@app.get("/", tags=["Root"])
async def root() -> dict:
    return {
        "project": "AgAI-33 FreePBX Dispatch Agent",
        "brand": "Datawebify",
        "version": "0.1.0",
        "status": "online",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", tags=["Root"])
async def health_check() -> dict:
    return {
        "status": "healthy",
        "env": settings.app_env.value,
        "routers": ["dispatch", "ari", "metrics"],
    }


# ── Global Exception Handler ──────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        error=str(exc),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "An unexpected error occurred.",
            "detail": str(exc),
        },
    )
