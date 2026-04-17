"""
Production AI Agent — Kết hợp tất cả Day 12 concepts

Checklist:
  ✅ Config từ environment (12-factor)
  ✅ Structured JSON logging
  ✅ API Key authentication
  ✅ Rate limiting
  ✅ Cost guard
  ✅ Input validation (Pydantic)
  ✅ Health check + Readiness probe
  ✅ Graceful shutdown
  ✅ Security headers
  ✅ CORS
  ✅ Error handling
  ✅ Conversation history (Redis)
  ✅ Stateless design
  ✅ OpenAI integration
"""
from __future__ import annotations

import os
import time
import uuid
import signal
import logging
import json
from datetime import datetime, timezone
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Security, Depends, Request, Response
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import uvicorn

from app.config import settings
from utils.mock_llm import ask as mock_ask

# ─────────────────────────────────────────────────────────
# LLM — OpenAI thật hoặc mock
# ─────────────────────────────────────────────────────────
_openai_client = None
if settings.openai_api_key:
    try:
        from openai import OpenAI as _OpenAI
        _openai_client = _OpenAI(api_key=settings.openai_api_key)
    except Exception as e:
        pass  # fallback to mock


def llm_ask(question: str, history: list | None = None) -> str:
    if _openai_client is not None:
        messages = []
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": question})
        resp = _openai_client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            max_tokens=512,
        )
        return resp.choices[0].message.content
    return mock_ask(question)


# ─────────────────────────────────────────────────────────
# Redis — conversation history (optional, graceful fallback)
# ─────────────────────────────────────────────────────────
_redis = None
if settings.redis_url:
    try:
        import redis as _redis_lib
        _redis = _redis_lib.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2)
        _redis.ping()
    except Exception:
        _redis = None

HISTORY_TTL = 60 * 60 * 24  # 24h
MAX_HISTORY = 20  # max messages per session


def load_history(session_id: str) -> list:
    if not _redis:
        return []
    try:
        raw = _redis.get(f"history:{session_id}")
        return json.loads(raw) if raw else []
    except Exception:
        return []


def save_history(session_id: str, history: list) -> None:
    if not _redis:
        return
    try:
        _redis.setex(f"history:{session_id}", HISTORY_TTL, json.dumps(history[-MAX_HISTORY:]))
    except Exception:
        pass


def clear_history(session_id: str) -> None:
    if not _redis:
        return
    try:
        _redis.delete(f"history:{session_id}")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────
# Logging — JSON structured
# ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format='{"ts":"%(asctime)s","lvl":"%(levelname)s","msg":"%(message)s"}',
)
logger = logging.getLogger(__name__)

START_TIME = time.time()
_is_ready = False
_request_count = 0
_error_count = 0

# ─────────────────────────────────────────────────────────
# Rate Limiter — Sliding Window
# ─────────────────────────────────────────────────────────
_rate_windows: dict[str, deque] = defaultdict(deque)


def check_rate_limit(key: str):
    now = time.time()
    window = _rate_windows[key]
    while window and window[0] < now - 60:
        window.popleft()
    if len(window) >= settings.rate_limit_per_minute:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {settings.rate_limit_per_minute} req/min",
            headers={"Retry-After": "60", "X-RateLimit-Limit": str(settings.rate_limit_per_minute)},
        )
    window.append(now)


# ─────────────────────────────────────────────────────────
# Cost Guard
# ─────────────────────────────────────────────────────────
_daily_cost = 0.0
_cost_reset_day = time.strftime("%Y-%m-%d")


def check_and_record_cost(input_tokens: int, output_tokens: int):
    global _daily_cost, _cost_reset_day
    today = time.strftime("%Y-%m-%d")
    if today != _cost_reset_day:
        _daily_cost = 0.0
        _cost_reset_day = today
    if _daily_cost >= settings.daily_budget_usd:
        raise HTTPException(503, "Daily budget exhausted. Try tomorrow.")
    cost = (input_tokens / 1000) * 0.00015 + (output_tokens / 1000) * 0.0006
    _daily_cost += cost


# ─────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    if not api_key or api_key != settings.agent_api_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Include header: X-API-Key: <key>",
        )
    return api_key


# ─────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _is_ready
    logger.info(json.dumps({
        "event": "startup",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "llm": "openai" if _openai_client else "mock",
        "redis": "connected" if _redis else "unavailable",
    }))
    time.sleep(0.1)
    _is_ready = True
    logger.info(json.dumps({"event": "ready"}))

    yield

    _is_ready = False
    logger.info(json.dumps({"event": "shutdown"}))


# ─────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    global _request_count, _error_count
    start = time.time()
    _request_count += 1
    try:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if "server" in response.headers:
            del response.headers["server"]
        duration = round((time.time() - start) * 1000, 1)
        logger.info(json.dumps({
            "event": "request",
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": duration,
        }))
        return response
    except Exception:
        _error_count += 1
        raise


# ─────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = Field(None, description="Session ID for conversation history")


class AskResponse(BaseModel):
    question: str
    answer: str
    model: str
    session_id: str
    timestamp: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = Field(None, description="Omit to start new conversation")


class ChatResponse(BaseModel):
    message: str
    session_id: str
    model: str
    timestamp: str
    history_length: int


# ─────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────

@app.get("/", tags=["Info"])
def root():
    index = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.isfile(index):
        return FileResponse(index)
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "endpoints": {
            "ask": "POST /ask (single question, requires X-API-Key)",
            "chat": "POST /chat (conversation with history, requires X-API-Key)",
            "health": "GET /health",
            "ready": "GET /ready",
            "metrics": "GET /metrics (requires X-API-Key)",
        },
    }


@app.post("/ask", response_model=AskResponse, tags=["Agent"])
async def ask_agent(
    body: AskRequest,
    request: Request,
    _key: str = Depends(verify_api_key),
):
    """Single question — no conversation history."""
    check_rate_limit(_key[:8])

    input_tokens = len(body.question.split()) * 2
    check_and_record_cost(input_tokens, 0)

    session_id = body.session_id or str(uuid.uuid4())

    logger.info(json.dumps({
        "event": "agent_call",
        "q_len": len(body.question),
        "session": session_id,
        "client": str(request.client.host) if request.client else "unknown",
    }))

    answer = llm_ask(body.question)

    output_tokens = len(answer.split()) * 2
    check_and_record_cost(0, output_tokens)

    return AskResponse(
        question=body.question,
        answer=answer,
        model=settings.llm_model,
        session_id=session_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.post("/chat", response_model=ChatResponse, tags=["Agent"])
async def chat_agent(
    body: ChatRequest,
    request: Request,
    _key: str = Depends(verify_api_key),
):
    """
    Conversation with history stored in Redis.
    Pass the same `session_id` to continue a conversation.
    Omit `session_id` to start a new one.
    """
    check_rate_limit(_key[:8])

    input_tokens = len(body.message.split()) * 2
    check_and_record_cost(input_tokens, 0)

    session_id = body.session_id or str(uuid.uuid4())
    history = load_history(session_id)

    logger.info(json.dumps({
        "event": "chat_call",
        "session": session_id,
        "history_len": len(history),
        "client": str(request.client.host) if request.client else "unknown",
    }))

    answer = llm_ask(body.message, history=history)

    history.append({"role": "user", "content": body.message})
    history.append({"role": "assistant", "content": answer})
    save_history(session_id, history)

    output_tokens = len(answer.split()) * 2
    check_and_record_cost(0, output_tokens)

    return ChatResponse(
        message=answer,
        session_id=session_id,
        model=settings.llm_model,
        timestamp=datetime.now(timezone.utc).isoformat(),
        history_length=len(history),
    )


@app.delete("/chat/{session_id}", tags=["Agent"])
async def clear_chat(
    session_id: str,
    _key: str = Depends(verify_api_key),
):
    """Clear conversation history for a session."""
    clear_history(session_id)
    return {"cleared": True, "session_id": session_id}


@app.get("/health", tags=["Operations"])
def health():
    """Liveness probe."""
    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": _request_count,
        "checks": {
            "llm": "openai" if _openai_client else "mock",
            "redis": "connected" if _redis else "unavailable",
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready", tags=["Operations"])
def ready():
    """Readiness probe."""
    if not _is_ready:
        raise HTTPException(503, "Not ready")
    return {"ready": True}


@app.get("/metrics", tags=["Operations"])
def metrics(_key: str = Depends(verify_api_key)):
    """Basic metrics (protected)."""
    return {
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": _request_count,
        "error_count": _error_count,
        "daily_cost_usd": round(_daily_cost, 4),
        "daily_budget_usd": settings.daily_budget_usd,
        "budget_used_pct": round(_daily_cost / settings.daily_budget_usd * 100, 1),
        "redis": "connected" if _redis else "unavailable",
        "llm": "openai" if _openai_client else "mock",
    }


# ─────────────────────────────────────────────────────────
# Graceful Shutdown
# ─────────────────────────────────────────────────────────
def _handle_signal(signum, _frame):
    logger.info(json.dumps({"event": "signal", "signum": signum}))


signal.signal(signal.SIGTERM, _handle_signal)


if __name__ == "__main__":
    logger.info(f"Starting {settings.app_name} on {settings.host}:{settings.port}")
    logger.info(f"API Key: {settings.agent_api_key[:4]}****")
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        timeout_graceful_shutdown=30,
    )
