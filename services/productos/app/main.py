from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4
from fastapi import Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError, OperationalError
from shared.runtime import create_app
from shared.auth import user_claims, cotizar_claims
from .models import productos
from .schemas import ProductoCrear, ProductoEditar, VersionEsperada
from .cache import get_cached_product, set_cached_product, invalidate_cached_product

app = create_app('productos')
app.version = '0.4.0'
app.description = 'Productos, catálogo, Redis cache-aside y cotización. Fase 4.'


def connection(request: Request):
    with request.app.state.engine.begin() as conn:
        yield conn


def admin_required(claims=Depends(user_claims)):
    if claims.get('role') != 'administrador':
        raise HTTPException(403, 'Se requiere rol administrador')
    return claims


def format_product(row) -> dict:
    return {
        'id': str(row['id']),
        'nombre': row['nombre'],
        'categoria': row['categoria'],
        'precio_cop': f"{Decimal(str(row['precio_cop'])):.2f}",
        'activo': bool(row['activo']),
        'version': int(row['version']),
        'created_at': row['created_at'].isoformat(),
        'updated_at': row['updated_at'].isoformat()
    }


def product_db(conn, product_id: UUID, lock: bool = False):
    query = select(productos).where(productos.c.id == product_id)
    if lock:
        query = query.with_for_update()
    row = conn.execute(query).mappings().first()
    if not row:
        raise HTTPException(404, 'Producto no encontrado')
    return dict(row)


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
            'correlation_id': request.state.correlation_id,
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


@app.get('/productos')
def list_products(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    incluir_inactivos: bool = Query(False),
    claims=Depends(user_claims),
    conn=Depends(connection)
):
    if incluir_inactivos and claims.get('role') != 'administrador':
        raise HTTPException(403, 'Solo el administrador puede incluir productos inactivos')

    query = select(productos)
    count_query = select(func.count()).select_from(productos)

    if not incluir_inactivos:
        query = query.where(productos.c.activo.is_(True))
        count_query = count_query.where(productos.c.activo.is_(True))

    query = query.order_by(productos.c.created_at, productos.c.id).limit(limit).offset(offset)

    items = [format_product(row) for row in conn.execute(query).mappings().all()]
    total = conn.execute(count_query).scalar_one()

    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}


@app.post('/productos', status_code=201)
def create_product(
    body: ProductoCrear,
    response: Response,
    claims=Depends(admin_required),
    conn=Depends(connection)
):
    product_id = uuid4()
    conn.execute(productos.insert().values(
        id=product_id,
        nombre=body.nombre,
        categoria=body.categoria,
        precio_cop=Decimal(body.precio_cop),
        activo=True,
        version=1
    ))
    row = product_db(conn, product_id)
    result = format_product(row)
    conn.commit()
    response.headers['Location'] = f'/api/productos/productos/{product_id}'
    return result


@app.get('/productos/{id}')
def get_product(
    id: UUID,
    response: Response,
    claims=Depends(user_claims),
    conn=Depends(connection)
):
    # Patrón Cache-Aside con Redis
    cached = get_cached_product(id, response=response)
    if cached:
        if not cached.get('activo', True) and claims.get('role') != 'administrador':
            raise HTTPException(404, 'Producto no encontrado')
        return cached

    # Cache miss o Redis no disponible: consultar PostgreSQL
    row = product_db(conn, id)
    if not row['activo'] and claims.get('role') != 'administrador':
        raise HTTPException(404, 'Producto no encontrado')

    formatted = format_product(row)
    # Guardar en Redis con TTL de 60s
    set_cached_product(id, formatted)
    return formatted


@app.patch('/productos/{id}')
def edit_product(
    id: UUID,
    body: ProductoEditar,
    claims=Depends(admin_required),
    conn=Depends(connection)
):
    current = product_db(conn, id, lock=True)
    if current['version'] != body.version_esperada:
        raise HTTPException(409, 'El producto cambió. Consulta la versión actual antes de guardar')

    updates = {}
    if body.nombre is not None:
        updates['nombre'] = body.nombre
    if body.categoria is not None:
        updates['categoria'] = body.categoria
    if body.precio_cop is not None:
        updates['precio_cop'] = Decimal(body.precio_cop)

    new_version = current['version'] + 1
    conn.execute(
        productos.update().where(productos.c.id == id).values(
            **updates,
            version=new_version,
            updated_at=func.now()
        )
    )

    # Invalidación tras actualizar en PostgreSQL
    invalidate_cached_product(conn, id, new_version)
    row = product_db(conn, id)
    result = format_product(row)
    conn.commit()
    return result


@app.post('/productos/{id}/desactivar')
def deactivate_product(
    id: UUID,
    body: VersionEsperada,
    claims=Depends(admin_required),
    conn=Depends(connection)
):
    current = product_db(conn, id, lock=True)
    if current['version'] != body.version_esperada:
        raise HTTPException(409, 'El producto cambió. Consulta la versión actual antes de guardar')

    new_version = current['version'] + 1
    conn.execute(
        productos.update().where(productos.c.id == id).values(
            activo=False,
            version=new_version,
            updated_at=func.now()
        )
    )

    # Invalidación tras desactivar en PostgreSQL
    invalidate_cached_product(conn, id, new_version)
    row = product_db(conn, id)
    result = format_product(row)
    conn.commit()
    return result



@app.get('/interno/productos/{id}/cotizacion')
def quote_product(
    id: UUID,
    claims=Depends(cotizar_claims),
    conn=Depends(connection)
):
    # La API interna de cotización omite Redis y consulta directamente PostgreSQL (fuente de verdad)
    row = product_db(conn, id)
    return {
        'producto_id': str(row['id']),
        'precio_unitario_cop': f"{Decimal(str(row['precio_cop'])):.2f}",
        'version_producto': int(row['version']),
        'activo': bool(row['activo']),
        'cotizado_en': datetime.now(timezone.utc).isoformat()
    }
