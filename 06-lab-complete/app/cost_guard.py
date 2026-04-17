"""Monthly budget guard — $10/month per user via Redis or in-memory fallback"""
import time
import logging
from dataclasses import dataclass, field
from fastapi import HTTPException

from app.config import settings

logger = logging.getLogger(__name__)

PRICE_PER_1K_INPUT = 0.00015
PRICE_PER_1K_OUTPUT = 0.0006


@dataclass
class UsageRecord:
    user_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    request_count: int = 0
    day: str = field(default_factory=lambda: time.strftime("%Y-%m-%d"))

    @property
    def total_cost_usd(self) -> float:
        return round(
            (self.input_tokens / 1000) * PRICE_PER_1K_INPUT
            + (self.output_tokens / 1000) * PRICE_PER_1K_OUTPUT,
            6,
        )


_records: dict[str, UsageRecord] = {}
_global_cost = 0.0
_global_reset_day = time.strftime("%Y-%m-%d")


def _get_record(user_id: str) -> UsageRecord:
    today = time.strftime("%Y-%m-%d")
    rec = _records.get(user_id)
    if not rec or rec.day != today:
        _records[user_id] = UsageRecord(user_id=user_id, day=today)
    return _records[user_id]


def check_budget(user_id: str) -> None:
    global _global_cost, _global_reset_day
    today = time.strftime("%Y-%m-%d")
    if today != _global_reset_day:
        _global_cost = 0.0
        _global_reset_day = today

    if _global_cost >= settings.daily_budget_usd:
        raise HTTPException(503, "Daily budget exhausted. Try tomorrow.")

    record = _get_record(user_id)
    if record.total_cost_usd >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Daily budget exceeded",
                "used_usd": record.total_cost_usd,
                "budget_usd": settings.daily_budget_usd,
                "resets_at": "midnight UTC",
            },
        )

    if record.total_cost_usd >= settings.daily_budget_usd * 0.8:
        logger.warning(f"User {user_id} at {record.total_cost_usd / settings.daily_budget_usd * 100:.0f}% budget")


def record_usage(user_id: str, input_tokens: int, output_tokens: int) -> UsageRecord:
    global _global_cost
    record = _get_record(user_id)
    record.input_tokens += input_tokens
    record.output_tokens += output_tokens
    record.request_count += 1
    cost = (input_tokens / 1000 * PRICE_PER_1K_INPUT + output_tokens / 1000 * PRICE_PER_1K_OUTPUT)
    _global_cost += cost
    return record


def get_usage(user_id: str) -> dict:
    record = _get_record(user_id)
    return {
        "user_id": user_id,
        "date": record.day,
        "requests": record.request_count,
        "cost_usd": record.total_cost_usd,
        "budget_usd": settings.daily_budget_usd,
        "budget_remaining_usd": max(0, settings.daily_budget_usd - record.total_cost_usd),
    }
