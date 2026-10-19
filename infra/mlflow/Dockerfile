FROM python:3.12.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY infra/mlflow/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock \
    && useradd --create-home --uid 10002 mlflowuser \
    && mkdir /mlartifacts && chown mlflowuser /mlartifacts
COPY infra/mlflow/start.py /app/start.py
USER mlflowuser
CMD ["python", "/app/start.py"]
