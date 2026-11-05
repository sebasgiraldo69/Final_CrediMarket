FROM python:3.12.12-slim AS builder
# uv fijo por versión y digest; las dependencias salen de infra/mlflow/uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.13.3@sha256:bee0a2a458fd956c5df7b8b4c5fed2257b0af34866e3da7b51db0be3acb375d1 /uv /bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON=/usr/local/bin/python UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy UV_NO_CACHE=1 UV_COMPILE_BYTECODE=1
COPY infra/mlflow/pyproject.toml infra/mlflow/uv.lock /tmp/uv-project/
# Servidor MLflow más el grupo `training`: el entrenamiento se ejecuta dentro de este contenedor.
RUN uv sync --project /tmp/uv-project --frozen --no-install-project --no-default-groups --group training

FROM python:3.12.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
RUN useradd --create-home --uid 10002 mlflowuser \
    && mkdir /mlartifacts && chown mlflowuser /mlartifacts
COPY infra/mlflow/start.py /app/start.py
USER mlflowuser
CMD ["python", "/app/start.py"]
