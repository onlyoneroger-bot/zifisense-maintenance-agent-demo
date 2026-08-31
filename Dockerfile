FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY fixtures ./fixtures

RUN pip install --no-cache-dir uv==0.12.6 \
    && uv sync --frozen --no-dev --no-editable


FROM python:3.11-slim AS runtime

ARG APP_VERSION=1.0.0

LABEL org.opencontainers.image.title="ZiFiSense Maintenance Agent" \
      org.opencontainers.image.version="${APP_VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH \
    APP_VERSION=${APP_VERSION} \
    DATABASE_URL=sqlite:////app/data/agent.db

WORKDIR /app

RUN groupadd --system agent \
    && useradd --system --gid agent --home-dir /app agent \
    && mkdir -p /app/data \
    && chown agent:agent /app/data

COPY --from=builder --chown=agent:agent /app/.venv /app/.venv
COPY --from=builder --chown=agent:agent /app/fixtures /app/fixtures

USER agent

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"]

STOPSIGNAL SIGTERM

CMD ["uvicorn", "zifisense_agent_api.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-server-header"]
