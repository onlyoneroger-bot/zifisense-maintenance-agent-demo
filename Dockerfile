FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////app/data/agent.db \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app

RUN groupadd --system agent && useradd --system --gid agent --home-dir /app agent

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY fixtures ./fixtures

RUN pip install --no-cache-dir uv==0.12.6 \
    && uv sync --frozen --no-dev --no-editable \
    && mkdir -p /app/data \
    && chown -R agent:agent /app

USER agent
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"]

CMD ["uvicorn", "zifisense_agent_api.main:app", "--host", "0.0.0.0", "--port", "8080"]
