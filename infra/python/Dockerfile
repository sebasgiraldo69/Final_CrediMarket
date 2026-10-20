FROM python:3.12.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app
COPY infra/python/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock \
    && useradd --create-home --uid 10001 appuser
ARG SERVICE
COPY infra/python/requirements-ml.lock /tmp/requirements-ml.lock
RUN if [ "$SERVICE" = "prestamos" ]; then pip install --no-cache-dir --require-hashes -r /tmp/requirements-ml.lock; fi
COPY shared /app/shared
COPY contracts/events /app/contracts/events
COPY models /app/models
COPY services/${SERVICE}/ /app/
USER appuser
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log"]
