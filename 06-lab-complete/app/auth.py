"""
API Key authentication (tiêu chí 6): header X-API-Key phải trùng AGENT_API_KEY, thiếu/sai → 401.
"""
import hmac

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Dependency cho FastAPI — dùng trong /ask: Depends(verify_api_key)."""
    expected = settings.agent_api_key
    # Server chưa cấu hình key → từ chối tất cả thay vì mở cửa.
    if not api_key or not expected or not hmac.compare_digest(api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key",
                            headers={"WWW-Authenticate": "ApiKey"})
    return api_key
