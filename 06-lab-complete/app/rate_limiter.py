"""
Rate limiting (tiêu chí 7): sliding window 60s trong Redis sorted set,
dùng chung giữa các worker/instance và còn nguyên sau khi restart agent.
"""
import hashlib
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    # Hash key để không lưu API key thô trong Redis.
    bucket = "rl:" + hashlib.sha256(key.encode()).hexdigest()[:16]
    now = time.time()
    pipe = r.pipeline()
    pipe.zremrangebyscore(bucket, 0, now - WINDOW_SECONDS)
    pipe.zcard(bucket)
    pipe.zrange(bucket, 0, 0, withscores=True)
    _, count, oldest = pipe.execute()

    if count >= settings.rate_limit_per_minute:
        retry_after = int(oldest[0][1] + WINDOW_SECONDS - now) + 1 if oldest else WINDOW_SECONDS
        raise HTTPException(status_code=429, detail="Rate limit exceeded",
                            headers={"Retry-After": str(max(retry_after, 1))})

    pipe = r.pipeline()
    pipe.zadd(bucket, {f"{now}-{uuid.uuid4().hex[:8]}": now})
    pipe.expire(bucket, WINDOW_SECONDS)
    pipe.execute()
