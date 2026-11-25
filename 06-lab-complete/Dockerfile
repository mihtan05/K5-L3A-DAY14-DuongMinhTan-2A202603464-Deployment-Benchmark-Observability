# ---------- Stage 1: builder — cài dependencies vào venv ----------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install -r requirements.txt

# ---------- Stage 2: runtime — chỉ copy venv + source ----------
FROM python:3.11-slim

ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8000
RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser utils/ ./utils/

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=2)" || exit 1

# exec → uvicorn là PID 1, nhận SIGTERM trực tiếp khi `docker stop`.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
