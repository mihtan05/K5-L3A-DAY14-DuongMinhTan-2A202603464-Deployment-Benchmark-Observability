"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường.
Giá trị mặc định chỉ dùng khi chạy local; secret (AGENT_API_KEY) không có mặc định.
"""
import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass
class Settings:
    port: int = field(default_factory=lambda: int(_env("PORT", "8000")))
    environment: str = field(default_factory=lambda: _env("ENVIRONMENT", "development"))
    agent_api_key: str = field(default_factory=lambda: _env("AGENT_API_KEY", ""))
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL", "redis://localhost:6379/0"))
    rate_limit_per_minute: int = field(default_factory=lambda: int(_env("RATE_LIMIT_PER_MINUTE", "10")))
    daily_budget_usd: float = field(default_factory=lambda: float(_env("DAILY_BUDGET_USD", "1.0")))


settings = Settings()
