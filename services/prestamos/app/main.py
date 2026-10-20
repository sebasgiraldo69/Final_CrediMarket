"""API del microservicio Préstamos (Fase 8: Servicio del modelo de riesgo e información de versión activa)."""
from uuid import uuid4
from fastapi import Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError

from shared.auth import modelo_read_claims, riesgo_predict_claims
from shared.runtime import create_app
from .model_service import ModelRegistry, ModelUnavailableError
from .schemas import Features, ModeloInfo, Riesgo

app = create_app("prestamos")
app.version = "0.8.0"
app.description = "Transporte Kafka, proyección de Inventario y servicio del modelo de riesgo activo (Fase 8)."


def error_response(request: Request, status: int, message: str, details=None, headers=None) -> JSONResponse:
    codes = {
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "INVALID_INPUT",
        503: "UNAVAILABLE",
    }
    return JSONResponse(
        status_code=status,
        headers=headers,
        content={
            "code": codes.get(status, "ERROR"),
            "message": message,
            "correlation_id": getattr(request.state, "correlation_id", str(uuid4())),
            "details": details or [],
        },
    )


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return error_response(request, exc.status_code, str(exc.detail), headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    details = [
        {"field": ".".join(map(str, item["loc"])) or "body", "message": item["msg"][:250]}
        for item in exc.errors()
    ]
    return error_response(request, 422, "Entrada inválida", details)


@app.exception_handler(ModelUnavailableError)
async def model_unavailable_error(request: Request, exc: ModelUnavailableError):
    return error_response(
        request,
        503,
        "Modelo de riesgo no disponible",
        details=[{"field": "model", "message": "El artefacto o manifiesto del modelo activo no está disponible"}],
    )


@app.exception_handler(IntegrityError)
async def integrity_error(request: Request, exc: IntegrityError):
    return error_response(request, 409, "Conflicto de integridad de datos")


@app.exception_handler(OperationalError)
async def unavailable(request: Request, exc: OperationalError):
    return error_response(request, 503, "Base de datos no disponible")


def get_registry(request: Request) -> ModelRegistry:
    registry = getattr(request.app.state, "model_registry", None)
    if registry is None:
        raise ModelUnavailableError("Registro de modelo no inicializado")
    return registry


@app.get("/modelo/info", response_model=ModeloInfo)
def informacion_modelo(
    _claims=Depends(modelo_read_claims),
    registry: ModelRegistry = Depends(get_registry),
):
    return registry.get_model_info()


@app.post("/riesgo/predict", response_model=Riesgo)
def predecir_riesgo(
    payload: Features,
    request: Request,
    _claims=Depends(riesgo_predict_claims),
    registry: ModelRegistry = Depends(get_registry),
):
    correlation_id = getattr(request.state, "correlation_id", None)
    return registry.predict_one(payload.model_dump(), correlation_id=correlation_id)
