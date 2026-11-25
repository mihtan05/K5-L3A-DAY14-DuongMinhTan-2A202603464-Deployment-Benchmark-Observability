"""
Production AI Agent — Part 6 Final Project.
Chạy: uvicorn app.main:app --workers 2   ·   Kiểm tra: python check_production_ready.py
"""
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "lvl": record.levelname,
                 "event": record.getMessage()}
        entry.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


_handler = logging.StreamHandler()
_handler.setFormatter(JsonFormatter())
logger = logging.getLogger("agent")
logger.handlers = [_handler]
logger.setLevel(logging.INFO)
logger.propagate = False


def log(event: str, **fields) -> None:
    logger.info(event, extra={"extra_fields": fields})


@asynccontextmanager
async def lifespan(app: FastAPI):
    log("startup", environment=settings.environment, port=settings.port)
    yield
    # uvicorn đã ngừng nhận request mới và chờ request đang chạy xong trước khi tới đây (SIGTERM).
    log("shutdown")


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    log("request", method=request.method, path=request.url.path, status=response.status_code,
        ms=round((time.perf_counter() - start) * 1000, 1))
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"error": "Invalid request body",
                                                  "detail": [e["msg"] for e in exc.errors()]})


@app.exception_handler(redis.RedisError)
async def redis_error(request: Request, exc: redis.RedisError):
    log("redis_error", path=request.url.path, error=type(exc).__name__)
    return JSONResponse(status_code=503, content={"error": "Service temporarily unavailable"})


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    logger.exception("unhandled_error", extra={"extra_fields": {"path": request.url.path}})
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    if not redis_healthy():
        return JSONResponse(status_code=503, content={"status": "not ready", "redis": "down"})
    return {"status": "ready"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()
    answer = llm_ask(body.question)
    # shortcut: token ước lượng theo số từ (mock LLM không trả usage), dùng tokenizer thật khi có LLM thật.
    cost = record_cost(len(body.question.split()) * 2, len(answer.split()) * 2)
    return {"question": body.question, "answer": answer, "cost_usd": round(cost, 8)}
