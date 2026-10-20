"""API del microservicio Préstamos (Fase 9: Flujo completo de crédito, estados, idempotencia y Kafka)."""
from uuid import UUID, uuid4
from fastapi import Depends, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError, OperationalError

from shared.auth import user_claims, modelo_read_claims, riesgo_predict_claims
from shared.runtime import create_app
from .model_service import ModelRegistry, ModelUnavailableError
from .models import prestamos
from .schemas import (
    Features,
    ModeloInfo,
    Riesgo,
    Prestamo,
    PrestamoCrear,
    Cancelacion,
    Prestamos,
)
from .domain import (
    compute_request_hash,
    check_idempotency,
    save_idempotency,
    format_prestamo,
    evaluar_y_crear_solicitud,
    solicitar_cancelacion,
    solicitar_entrega,
)

app = create_app("prestamos")
app.version = "0.9.0"
app.description = "Flujo completo de créditos, integración con Clientes, Productos, Inventario y servicio del modelo (Fase 9)."


def connection(request: Request):
    with request.app.state.engine.begin() as conn:
        yield conn


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


@app.post("/prestamos", response_model=Prestamo)
def crear_prestamo(
    body: PrestamoCrear,
    request: Request,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128),
    claims=Depends(user_claims),
    registry: ModelRegistry = Depends(get_registry),
    conn=Depends(connection),
):
    if claims.get("role") != "cliente":
        raise HTTPException(403, "Se requiere rol cliente para solicitar crédito")
    cliente_id_raw = claims.get("cliente_id")
    if not cliente_id_raw:
        raise HTTPException(403, "El token no tiene un perfil de cliente asociado")
    cliente_id = UUID(str(cliente_id_raw))

    req_hash = compute_request_hash(body.model_dump(mode="json"))
    cached = check_idempotency(conn, idempotency_key, str(cliente_id), "POST /prestamos", req_hash)
    if cached:
        response.status_code = cached["status_code"]
        if cached.get("location"):
            response.headers["Location"] = cached["location"]
        return cached["body"]

    correlation_id = getattr(request.state, "correlation_id", str(uuid4()))
    status_code, prestamo_dict, location = evaluar_y_crear_solicitud(
        conn, cliente_id, body, registry, correlation_id
    )

    save_idempotency(
        conn,
        idempotency_key,
        str(cliente_id),
        "POST /prestamos",
        UUID(prestamo_dict["id"]),
        req_hash,
        status_code,
        prestamo_dict,
        location,
    )

    response.status_code = status_code
    response.headers["Location"] = location
    return prestamo_dict


@app.get("/prestamos", response_model=Prestamos)
def listar_prestamos(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    claims=Depends(user_claims),
    conn=Depends(connection),
):
    role = claims.get("role")
    query = select(prestamos)
    count_query = select(func.count()).select_from(prestamos)

    if role == "cliente":
        cliente_id = UUID(str(claims["cliente_id"]))
        query = query.where(prestamos.c.cliente_id == cliente_id)
        count_query = count_query.where(prestamos.c.cliente_id == cliente_id)

    total = conn.execute(count_query).scalar_one()
    rows = conn.execute(
        query.order_by(prestamos.c.created_at.desc(), prestamos.c.id.desc()).limit(limit).offset(offset)
    ).mappings().all()

    items = [format_prestamo(row) for row in rows]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.get("/prestamos/{id}", response_model=Prestamo)
def consultar_prestamo(
    id: UUID,
    claims=Depends(user_claims),
    conn=Depends(connection),
):
    row = conn.execute(select(prestamos).where(prestamos.c.id == id)).mappings().first()
    if not row:
        raise HTTPException(404, "Préstamo no encontrado")

    role = claims.get("role")
    if role == "cliente" and row["cliente_id"] != UUID(str(claims["cliente_id"])):
        raise HTTPException(404, "Préstamo no encontrado")

    return format_prestamo(row)


@app.post("/prestamos/{id}/cancelacion", response_model=Prestamo)
def cancelar_prestamo_endpoint(
    id: UUID,
    body: Cancelacion,
    request: Request,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128),
    claims=Depends(user_claims),
    conn=Depends(connection),
):
    role = claims.get("role")
    client_id = UUID(str(claims["cliente_id"])) if claims.get("cliente_id") else None
    actor_id = str(client_id) if role == "cliente" else str(claims.get("sub", "admin"))

    req_hash = compute_request_hash(body.model_dump(mode="json"))
    cached = check_idempotency(conn, idempotency_key, actor_id, f"POST /prestamos/{id}/cancelacion", req_hash)
    if cached:
        response.status_code = cached["status_code"]
        if cached.get("location"):
            response.headers["Location"] = cached["location"]
        return cached["body"]

    correlation_id = getattr(request.state, "correlation_id", str(uuid4()))
    status_code, prestamo_dict, location = solicitar_cancelacion(
        conn, id, role, client_id, body, correlation_id
    )

    save_idempotency(
        conn,
        idempotency_key,
        actor_id,
        f"POST /prestamos/{id}/cancelacion",
        id,
        req_hash,
        status_code,
        prestamo_dict,
        location,
    )

    response.status_code = status_code
    response.headers["Location"] = location
    return prestamo_dict


@app.post("/prestamos/{id}/entrega", response_model=Prestamo)
def entregar_prestamo_endpoint(
    id: UUID,
    request: Request,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128),
    claims=Depends(user_claims),
    conn=Depends(connection),
):
    if claims.get("role") != "administrador":
        raise HTTPException(403, "Se requiere rol administrador")
    actor_id = str(claims.get("sub", "admin"))

    req_hash = compute_request_hash({})
    cached = check_idempotency(conn, idempotency_key, actor_id, f"POST /prestamos/{id}/entrega", req_hash)
    if cached:
        response.status_code = cached["status_code"]
        if cached.get("location"):
            response.headers["Location"] = cached["location"]
        return cached["body"]

    correlation_id = getattr(request.state, "correlation_id", str(uuid4()))
    status_code, prestamo_dict, location = solicitar_entrega(conn, id, correlation_id)

    save_idempotency(
        conn,
        idempotency_key,
        actor_id,
        f"POST /prestamos/{id}/entrega",
        id,
        req_hash,
        status_code,
        prestamo_dict,
        location,
    )

    response.status_code = status_code
    response.headers["Location"] = location
    return prestamo_dict


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
