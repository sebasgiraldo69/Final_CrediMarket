# Código de la fase 4

Copia de consulta de los archivos implementados en la fase 4 (Productos y Redis). Para explicación y verificación ver [FASE_4.md](FASE_4.md).

## services/productos/app/models.py

```python
from sqlalchemy import MetaData, Table, Column, String, Boolean, Integer, Numeric, DateTime, CheckConstraint, func
from sqlalchemy.dialects.postgresql import UUID

metadata = MetaData()

productos = Table('productos', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True),
    Column('nombre', String(250), nullable=False),
    Column('categoria', String(250), nullable=False),
    Column('precio_cop', Numeric(18, 2), nullable=False),
    Column('activo', Boolean, nullable=False, server_default='true'),
    Column('version', Integer, nullable=False, server_default='1'),
    Column('created_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column('updated_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint('precio_cop > 0', name='ck_producto_precio'),
    CheckConstraint('version >= 1', name='ck_producto_version')
)

invalidaciones_cache = Table('invalidaciones_cache', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True),
    Column('producto_id', UUID(as_uuid=True), nullable=False),
    Column('version', Integer, nullable=False),
    Column('intentos', Integer, nullable=False, server_default='0'),
    Column('reintentar_en', DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column('procesado', Boolean, nullable=False, server_default='false'),
    Column('created_at', DateTime(timezone=True), nullable=False, server_default=func.now())
)
```

## services/productos/migrations/versions/0002_productos.py

```python
"""Productos, invalidaciones de cache y catálogo inicial."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from uuid import UUID as PyUUID

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

INITIAL_PRODUCTS = [
    {
        "id": PyUUID("10000000-0000-4000-8000-000000000001"),
        "nombre": "Lenovo ThinkPad T14 Gen 4 Core i7 16GB 512GB SSD",
        "categoria": "Portátiles",
        "precio_cop": 3800000.00,
        "activo": True,
        "version": 1
    },
    {
        "id": PyUUID("10000000-0000-4000-8000-000000000002"),
        "nombre": "Dell Inspiron 15 Core i5 16GB 1TB SSD",
        "categoria": "Portátiles",
        "precio_cop": 2750000.00,
        "activo": True,
        "version": 1
    },
    {
        "id": PyUUID("10000000-0000-4000-8000-000000000003"),
        "nombre": "Apple MacBook Air 13 M2 8GB 256GB SSD",
        "categoria": "Portátiles",
        "precio_cop": 5200000.00,
        "activo": True,
        "version": 1
    },
    {
        "id": PyUUID("10000000-0000-4000-8000-000000000004"),
        "nombre": "Samsung Galaxy S24 256GB 8GB RAM 5G",
        "categoria": "Celulares",
        "precio_cop": 3950000.00,
        "activo": True,
        "version": 1
    },
    {
        "id": PyUUID("10000000-0000-4000-8000-000000000005"),
        "nombre": "Apple iPhone 15 128GB",
        "categoria": "Celulares",
        "precio_cop": 4400000.00,
        "activo": True,
        "version": 1
    },
    {
        "id": PyUUID("10000000-0000-4000-8000-000000000006"),
        "nombre": "Xiaomi Redmi Note 13 Pro 256GB 8GB RAM",
        "categoria": "Celulares",
        "precio_cop": 1100000.00,
        "activo": True,
        "version": 1
    },
    {
        "id": PyUUID("10000000-0000-4000-8000-000000000007"),
        "nombre": "Apple iPad 10.9 10ma Gen Wi-Fi 64GB",
        "categoria": "Tablets",
        "precio_cop": 2150000.00,
        "activo": True,
        "version": 1
    },
    {
        "id": PyUUID("10000000-0000-4000-8000-000000000008"),
        "nombre": "Monitor Gamer LG UltraGear 27 IPS 144Hz 1ms",
        "categoria": "Monitores",
        "precio_cop": 1250000.00,
        "activo": True,
        "version": 1
    },
    {
        "id": PyUUID("10000000-0000-4000-8000-000000000009"),
        "nombre": "Teclado Inalámbrico Logitech MX Keys Advanced",
        "categoria": "Accesorios",
        "precio_cop": 480000.00,
        "activo": True,
        "version": 1
    },
    {
        "id": PyUUID("10000000-0000-4000-8000-000000000010"),
        "nombre": "Auriculares Sony WH-1000XM5 Noise Cancelling",
        "categoria": "Audio",
        "precio_cop": 1650000.00,
        "activo": True,
        "version": 1
    }
]


def upgrade():
    tabla_productos = op.create_table(
        'productos',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('nombre', sa.String(250), nullable=False),
        sa.Column('categoria', sa.String(250), nullable=False),
        sa.Column('precio_cop', sa.Numeric(18, 2), nullable=False),
        sa.Column('activo', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('precio_cop > 0', name='ck_producto_precio'),
        sa.CheckConstraint('version >= 1', name='ck_producto_version')
    )

    op.create_table(
        'invalidaciones_cache',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('producto_id', UUID(as_uuid=True), nullable=False),
        sa.Column('version', sa.Integer, nullable=False),
        sa.Column('intentos', sa.Integer, nullable=False, server_default='0'),
        sa.Column('reintentar_en', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('procesado', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
    )

    op.bulk_insert(tabla_productos, INITIAL_PRODUCTS)


def downgrade():
    op.drop_table('invalidaciones_cache')
    op.drop_table('productos')
```

## services/productos/app/schemas.py

```python
from decimal import Decimal
from typing import Annotated, Optional, List
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Text = Annotated[str, Field(min_length=1, max_length=250)]
Money = Annotated[str, Field(pattern=r'^(0|[1-9][0-9]{0,15})\.[0-9]{2}$')]


class Closed(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ProductoCrear(Closed):
    nombre: Text
    categoria: Text
    precio_cop: Money

    @field_validator('precio_cop')
    @classmethod
    def positive_price(cls, v: str) -> str:
        if Decimal(v) <= 0:
            raise ValueError('El precio debe ser estrictamente positivo (mayor a 0.00)')
        return v


class ProductoEditar(Closed):
    version_esperada: Annotated[int, Field(ge=1, strict=True)]
    nombre: Optional[Text] = None
    categoria: Optional[Text] = None
    precio_cop: Optional[Money] = None

    @field_validator('precio_cop')
    @classmethod
    def positive_price(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and Decimal(v) <= 0:
            raise ValueError('El precio debe ser estrictamente positivo (mayor a 0.00)')
        return v

    @model_validator(mode='after')
    def check_at_least_one_field(self):
        fields = self.model_fields_set - {'version_esperada'}
        if not fields or any(getattr(self, f) is None for f in fields):
            raise ValueError('Debes proporcionar al menos un campo no nulo para actualizar (nombre, categoria o precio_cop)')
        return self


class VersionEsperada(Closed):
    version_esperada: Annotated[int, Field(ge=1, strict=True)]


class Producto(Closed):
    id: str
    nombre: str
    categoria: str
    precio_cop: str
    activo: bool
    version: int
    created_at: str
    updated_at: str


class Productos(Closed):
    items: List[Producto]
    total: int
    limit: int
    offset: int


class Cotizacion(Closed):
    producto_id: str
    precio_unitario_cop: Money
    version_producto: int
    activo: bool
    cotizado_en: str
```

## services/productos/app/cache.py

```python
import os
import json
import logging
from uuid import UUID, uuid4
from typing import Optional, Dict, Any
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import func
from .models import invalidaciones_cache

logger = logging.getLogger("productos.cache")

PRODUCTO_TTL_SECONDS = 60
CACHE_KEY_PREFIX = "producto"


def _cache_key(product_id: UUID | str) -> str:
    return f"{CACHE_KEY_PREFIX}:{product_id}"


def get_redis_client() -> Redis:
    return Redis(
        host=os.environ.get("REDIS_HOST", "redis"),
        port=int(os.environ.get("REDIS_PORT", 6379)),
        password=os.environ.get("REDIS_PASSWORD"),
        socket_connect_timeout=0.2,
        socket_timeout=0.2,
        decode_responses=True
    )


def get_cached_product(product_id: UUID | str) -> Optional[Dict[str, Any]]:
    try:
        with get_redis_client() as client:
            raw = client.get(_cache_key(product_id))
            if raw:
                return json.loads(raw)
            return None
    except (RedisError, OSError) as exc:
        logger.warning(f"Error consultando Redis para producto {product_id} (fallback a PostgreSQL): {exc}")
        return None


def set_cached_product(product_id: UUID | str, product_data: Dict[str, Any], ttl: int = PRODUCTO_TTL_SECONDS) -> None:
    try:
        with get_redis_client() as client:
            client.set(_cache_key(product_id), json.dumps(product_data), ex=ttl)
    except (RedisError, OSError) as exc:
        logger.warning(f"Error guardando en Redis para producto {product_id}: {exc}")


def invalidate_cached_product(conn, product_id: UUID | str, version: int) -> bool:
    key = _cache_key(product_id)
    try:
        with get_redis_client() as client:
            client.delete(key)
        return True
    except (RedisError, OSError) as exc:
        logger.warning(f"Fallo al invalidar Redis para {product_id}. Registrando en PostgreSQL para reintento: {exc}")
        try:
            conn.execute(invalidaciones_cache.insert().values(
                id=uuid4(),
                producto_id=UUID(str(product_id)),
                version=version,
                intentos=1,
                reintentar_en=func.now(),
                procesado=False
            ))
        except Exception as db_exc:
            logger.error(f"Error registrando invalidación fallida en base de datos: {db_exc}")
        return False
```

## services/productos/app/main.py

```python
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
    claims=Depends(user_claims),
    conn=Depends(connection)
):
    cached = get_cached_product(id)
    if cached:
        if not cached.get('activo', True) and claims.get('role') != 'administrador':
            raise HTTPException(404, 'Producto no encontrado')
        return cached

    row = product_db(conn, id)
    if not row['activo'] and claims.get('role') != 'administrador':
        raise HTTPException(404, 'Producto no encontrado')

    formatted = format_product(row)
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
    row = product_db(conn, id)
    return {
        'producto_id': str(row['id']),
        'precio_unitario_cop': f"{Decimal(str(row['precio_cop'])):.2f}",
        'version_producto': int(row['version']),
        'activo': bool(row['activo']),
        'cotizado_en': datetime.now(timezone.utc).isoformat()
    }
```
