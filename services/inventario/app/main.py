import hashlib
from uuid import UUID, uuid4
from fastapi import Depends, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, func, insert
from sqlalchemy.exc import IntegrityError, OperationalError
from shared.runtime import create_app
from shared.auth import user_claims, reservas_read_claims
from .models import existencias, reservas, movimientos, idempotencia_http
from .schemas import Entrada, Existencias, Movimientos, Reservas
from .domain import (
    format_existencia,
    format_reserva,
    format_movimiento,
    get_reserva_by_prestamo,
    agregar_stock,
    vencer
)

app = create_app('inventario')
app.version = '0.5.0'
app.description = 'Inventario, existencias, reservas atómicas, movimientos e idempotencia. Fase 5.'


def connection(request: Request):
    with request.app.state.engine.begin() as conn:
        yield conn


def admin_required(claims=Depends(user_claims)):
    if claims.get('role') != 'administrador':
        raise HTTPException(403, 'Se requiere rol administrador')
    return claims


def error_response(request, status, message, details=None, headers=None):
    codes = {
        401: 'UNAUTHORIZED',
        403: 'FORBIDDEN',
        404: 'NOT_FOUND',
        409: 'CONFLICT',
        422: 'INVALID_INPUT',
        503: 'UNAVAILABLE'
    }
    return JSONResponse(
        status_code=status,
        headers=headers,
        content={
            'code': codes.get(status, 'ERROR'),
            'message': message,
            'correlation_id': getattr(request.state, 'correlation_id', str(uuid4())),
            'details': details or []
        }
    )


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return error_response(request, exc.status_code, str(exc.detail), headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    details = [{'field': '.'.join(map(str, item['loc'])), 'message': item['msg']} for item in exc.errors()]
    return error_response(request, 422, 'Entrada inválida', details)


@app.exception_handler(IntegrityError)
async def integrity_error(request, exc):
    return error_response(request, 409, 'Conflicto de integridad de datos')


@app.exception_handler(OperationalError)
async def unavailable(request, exc):
    return error_response(request, 503, 'Base de datos no disponible')


@app.get('/inventario', response_model=Existencias)
def listar_existencias(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _admin=Depends(admin_required),
    conn=Depends(connection)
):
    total = conn.execute(select(func.count()).select_from(existencias)).scalar() or 0
    query = (
        select(existencias)
        .order_by(existencias.c.producto_id.asc())
        .limit(limit)
        .offset(offset)
    )
    rows = conn.execute(query).mappings().all()
    items = [format_existencia(row) for row in rows]
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}


@app.post('/inventario/entradas', status_code=201)
def registrar_entrada(
    payload: Entrada,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128),
    claims=Depends(admin_required),
    conn=Depends(connection)
):
    actor = claims.get('sub', 'admin')
    operacion = 'POST /inventario/entradas'
    raw_body = payload.model_dump_json(by_alias=True)
    body_hash = hashlib.sha256(raw_body.encode('utf-8')).hexdigest()

    # Lock idempotency record if present
    idemp_query = (
        select(idempotencia_http)
        .where(
            idempotencia_http.c.actor == actor,
            idempotencia_http.c.operacion == operacion,
            idempotencia_http.c.clave == idempotency_key
        )
        .with_for_update()
    )
    idemp_row = conn.execute(idemp_query).mappings().first()

    if idemp_row:
        if idemp_row['body_hash'] == body_hash:
            # Replay identical response
            return JSONResponse(
                status_code=idemp_row['response_code'],
                headers={'Location': '/api/inventario/movimientos'},
                content=idemp_row['response_body']
            )
        else:
            raise HTTPException(409, 'Clave de idempotencia ya utilizada con otro contenido')

    # Execute stock addition
    mov_dict = agregar_stock(conn, payload.producto_id, payload.cantidad, payload.motivo)

    # Record idempotency
    conn.execute(
        insert(idempotencia_http).values(
            id=uuid4(),
            actor=actor,
            operacion=operacion,
            clave=idempotency_key,
            body_hash=body_hash,
            response_code=201,
            response_body=mov_dict
        )
    )

    return JSONResponse(
        status_code=201,
        headers={'Location': '/api/inventario/movimientos'},
        content=mov_dict
    )


@app.get('/inventario/reservas', response_model=Reservas)
def listar_reservas(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _admin=Depends(admin_required),
    conn=Depends(connection)
):
    total = conn.execute(select(func.count()).select_from(reservas)).scalar() or 0
    query = (
        select(reservas)
        .order_by(reservas.c.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = conn.execute(query).mappings().all()
    items = [format_reserva(row) for row in rows]
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}


@app.get('/inventario/movimientos', response_model=Movimientos)
def listar_movimientos(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _admin=Depends(admin_required),
    conn=Depends(connection)
):
    total = conn.execute(select(func.count()).select_from(movimientos)).scalar() or 0
    query = (
        select(movimientos)
        .order_by(movimientos.c.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = conn.execute(query).mappings().all()
    items = [format_movimiento(row) for row in rows]
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}


@app.get('/interno/reservas/por-prestamo/{prestamo_id}')
def consultar_reserva_interna(
    prestamo_id: UUID,
    _auth=Depends(reservas_read_claims),
    conn=Depends(connection)
):
    # If active and expired, vencer will update and release stock atomically
    reserva_actual = vencer(conn, prestamo_id)
    if not reserva_actual:
        raise HTTPException(404, 'Reserva no encontrada')
    return reserva_actual
