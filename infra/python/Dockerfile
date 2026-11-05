FROM python:3.12.12-slim AS builder
# uv fijo por versión y digest; las dependencias salen de uv.lock (grupos de pyproject.toml).
COPY --from=ghcr.io/astral-sh/uv:0.13.3@sha256:bee0a2a458fd956c5df7b8b4c5fed2257b0af34866e3da7b51db0be3acb375d1 /uv /bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON=/usr/local/bin/python UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy UV_NO_CACHE=1 UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock /tmp/uv-project/
ARG SERVICE
# Todos los servicios instalan `backend`; solo Préstamos suma `inference` (scikit-learn, pandas, numpy, joblib).
RUN if [ "$SERVICE" = "prestamos" ]; then groups="--group backend --group inference"; else groups="--group backend"; fi \
    && uv sync --project /tmp/uv-project --frozen --no-install-project --no-default-groups $groups

FROM python:3.12.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
RUN useradd --create-home --uid 10001 appuser
ARG SERVICE
COPY shared /app/shared
COPY contracts/events /app/contracts/events
COPY models /app/models
COPY services/${SERVICE}/ /app/
USER appuser
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log"]
