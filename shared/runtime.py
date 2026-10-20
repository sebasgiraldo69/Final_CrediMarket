"""Infrastructure only. No domain models or cross-service database access."""
from contextlib import asynccontextmanager
import json
import logging
import os
import time
from uuid import UUID, uuid4

from confluent_kafka.admin import AdminClient
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import URL, create_engine, text


def database_url():
    return URL.create("postgresql+psycopg", username=os.environ["DB_USER"],
                      password=os.environ["DB_PASSWORD"], host=os.environ.get("DB_HOST", "postgres"),
                      port=5432, database=os.environ["DB_NAME"])


def create_app(service):
    logger = logging.getLogger(service)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    @asynccontextmanager
    async def lifespan(app):
        app.state.engine = create_engine(database_url(), pool_pre_ping=True, pool_size=3,
                                         max_overflow=2, connect_args={"connect_timeout": 2},
                                         hide_parameters=True)
        workers = None
        if service in ('prestamos', 'inventario'):
            from shared.messaging import Workers
            from app import messaging
            workers = Workers(app.state.engine, service, messaging.handle, getattr(messaging, 'sweep', None))
            workers.start()
            app.state.messaging_workers = workers
        try:
            yield
        finally:
            if workers:
                workers.close()
        app.state.engine.dispose()

    app = FastAPI(title=f"CrediMarket - {service}", version="0.2.0", lifespan=lifespan,
                  description="Fase 2: infraestructura. Operaciones de negocio pendientes.",
                  root_path=f"/api/{service}")
    app.add_middleware(CORSMiddleware,
                       allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:8080").split(","),
                       allow_methods=["GET", "POST", "PATCH"],
                       allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Correlation-ID"],
                       expose_headers=["X-Correlation-ID", "Location"])

    @app.middleware("http")
    async def correlation(request: Request, call_next):
        try:
            request_id = str(UUID(request.headers.get("X-Correlation-ID", "")))
        except ValueError:
            request_id = str(uuid4())
        request.state.correlation_id = request_id
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            # No exception text: it might contain credentials or query parameters.
            response = JSONResponse(status_code=500, content={"code": "INTERNAL_ERROR",
                "message": "Error interno", "correlation_id": request_id, "details": []})
        response.headers["X-Correlation-ID"] = request_id
        logger.info(json.dumps({"service": service, "method": request.method,
                                "path": request.url.path, "status": response.status_code,
                                "correlation_id": request_id,
                                "duration_ms": round((time.monotonic() - started) * 1000, 2)}))
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "service": service}

    @app.get("/ready")
    def ready(request: Request):
        dependencies = {}
        try:
            with request.app.state.engine.connect() as connection:
                connection.execute(text("SELECT 1 FROM infrastructure_metadata LIMIT 1"))
            dependencies["database"] = "ok"
        except Exception:
            dependencies["database"] = "unavailable"
        if service == "productos":
            try:
                with Redis(host="redis", password=os.environ["REDIS_PASSWORD"],
                           socket_connect_timeout=0.1, socket_timeout=0.1) as cache:
                    cache.ping()
                dependencies["redis"] = "ok"
            except Exception:
                dependencies["redis"] = "degraded"
        if service in ["prestamos", "inventario"]:
            workers = getattr(app.state, 'messaging_workers', None)
            dependencies["messaging"] = "ok" if workers and all(
                thread.is_alive() for thread in workers.threads) else "unavailable"
            try:
                client = AdminClient({"bootstrap.servers": "kafka:9092", "security.protocol": "SASL_PLAINTEXT",
                    "sasl.mechanism": "PLAIN", "sasl.username": service,
                    "sasl.password": os.environ["KAFKA_PASSWORD"], "log_level": 0})
                metadata = client.list_topics(timeout=2)
                if not metadata.brokers:
                    raise RuntimeError("Broker unavailable")
                dependencies["kafka"] = "ok"
            except Exception:
                dependencies["kafka"] = "degraded"
        if service == "prestamos":
            # Do not claim inference readiness until the real pipeline is integrated in phase 8.
            dependencies["model"] = "unavailable"
        status = "unavailable" if "unavailable" in dependencies.values() else (
            "degraded" if "degraded" in dependencies.values() else "ready")
        return JSONResponse(status_code=503 if status == "unavailable" else 200,
                            content={"status": status, "dependencies": dependencies})

    return app
