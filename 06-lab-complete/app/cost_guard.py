"""
Cost guard (tiêu chí 8): cộng dồn chi phí theo ngày vào Redis, vượt DAILY_BUDGET_USD → 402.
"""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _day_key() -> str:
    return "cost:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    spent = float(r.get(_day_key()) or 0)
    if spent >= settings.daily_budget_usd:
        raise HTTPException(status_code=402, detail="Daily budget exceeded")


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = input_tokens / 1000 * PRICE_INPUT_PER_1K + output_tokens / 1000 * PRICE_OUTPUT_PER_1K
    pipe = r.pipeline()
    pipe.incrbyfloat(_day_key(), cost)
    pipe.expire(_day_key(), 2 * 24 * 3600)
    pipe.execute()
    return cost
