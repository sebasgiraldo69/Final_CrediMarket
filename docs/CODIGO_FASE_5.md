# Código de la fase 5

Copia de consulta de los archivos implementados en la fase 5 (Inventario y reservas atómicas). Para explicación y verificación ver [FASE_5.md](FASE_5.md).

## services/inventario/app/models.py

```python
from sqlalchemy import MetaData, Table, Column, String, Integer, DateTime, CheckConstraint, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID, JSONB

metadata = MetaData()

existencias = Table(
    'existencias', metadata,
    Column('producto_id', UUID(as_uuid=True), primary_key=True),
    Column('fisico', Integer, nullable=False, server_default='0'),
    Column('reservado', Integer, nullable=False, server_default='0'),
    Column('disponible', Integer, nullable=False, server_default='0'),
    Column('updated_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint('fisico >= 0', name='ck_existencias_fisico_nonneg'),
    CheckConstraint('reservado >= 0', name='ck_existencias_reservado_nonneg'),
    CheckConstraint('disponible >= 0', name='ck_existencias_disponible_nonneg'),
    CheckConstraint('fisico >= reservado', name='ck_existencias_fisico_ge_reservado'),
    CheckConstraint('disponible = fisico - reservado', name='ck_existencias_disponible_eq_calc')
)

reservas = Table(
    'reservas', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True),
    Column('prestamo_id', UUID(as_uuid=True), nullable=False, unique=True),
    Column('producto_id', UUID(as_uuid=True), nullable=True),
    Column('cantidad', Integer, nullable=True),
    Column('estado', String(32), nullable=False),
    Column('revision', Integer, nullable=False, server_default='1'),
    Column('vence_en', DateTime(timezone=True), nullable=True),
    Column('created_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column('updated_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("estado IN ('ACTIVA', 'SIN_STOCK', 'CANCELADA', 'VENCIDA', 'ENTREGADA')", name='ck_reservas_estado'),
    CheckConstraint('revision >= 1', name='ck_reservas_revision')
)

movimientos = Table(
    'movimientos', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True),
    Column('producto_id', UUID(as_uuid=True), nullable=False),
    Column('prestamo_id', UUID(as_uuid=True), nullable=True),
    Column('tipo', String(32), nullable=False),
    Column('cantidad', Integer, nullable=False),
    Column('motivo', String(250), nullable=False),
    Column('created_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("tipo IN ('ENTRADA', 'RESERVA', 'LIBERACION', 'SALIDA', 'VENCIMIENTO')", name='ck_movimientos_tipo'),
    CheckConstraint('cantidad >= 1', name='ck_movimientos_cantidad_pos')
)

idempotencia_http = Table(
    'idempotencia_http', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True),
    Column('actor', String(128), nullable=False),
    Column('operacion', String(64), nullable=False),
    Column('clave', String(128), nullable=False),
    Column('body_hash', String(64), nullable=False),
    Column('response_code', Integer, nullable=False),
    Column('response_body', JSONB, nullable=False),
    Column('created_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint('actor', 'operacion', 'clave', name='uq_idempotencia_actor_op_clave')
)
```

## services/inventario/migrations/versions/0002_inventario.py

```python
"""Inventario: existencias, reservas atomicas, movimientos e idempotencia HTTP."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from uuid import UUID as PyUUID, uuid4

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

INITIAL_PRODUCT_IDS = [
    PyUUID(f"10000000-0000-4000-8000-00000000000{i:x}")
    for i in range(1, 11)
]


def upgrade():
    tabla_existencias = op.create_table(
        'existencias',
        sa.Column('producto_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('fisico', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('reservado', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('disponible', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('fisico >= 0', name='ck_existencias_fisico_nonneg'),
        sa.CheckConstraint('reservado >= 0', name='ck_existencias_reservado_nonneg'),
        sa.CheckConstraint('disponible >= 0', name='ck_existencias_disponible_nonneg'),
        sa.CheckConstraint('fisico >= reservado', name='ck_existencias_fisico_ge_reservado'),
        sa.CheckConstraint('disponible = fisico - reservado', name='ck_existencias_disponible_eq_calc')
    )

    op.create_table(
        'reservas',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('prestamo_id', UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('producto_id', UUID(as_uuid=True), nullable=True),
        sa.Column('cantidad', sa.Integer(), nullable=True),
        sa.Column('estado', sa.String(32), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('vence_en', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("estado IN ('ACTIVA', 'SIN_STOCK', 'CANCELADA', 'VENCIDA', 'ENTREGADA')", name='ck_reservas_estado'),
        sa.CheckConstraint('revision >= 1', name='ck_reservas_revision')
    )

    tabla_movimientos = op.create_table(
        'movimientos',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('producto_id', UUID(as_uuid=True), nullable=False),
        sa.Column('prestamo_id', UUID(as_uuid=True), nullable=True),
        sa.Column('tipo', sa.String(32), nullable=False),
        sa.Column('cantidad', sa.Integer(), nullable=False),
        sa.Column('motivo', sa.String(250), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("tipo IN ('ENTRADA', 'RESERVA', 'LIBERACION', 'SALIDA', 'VENCIMIENTO')", name='ck_movimientos_tipo'),
        sa.CheckConstraint('cantidad >= 1', name='ck_movimientos_cantidad_pos')
    )

    op.create_table(
        'idempotencia_http',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('actor', sa.String(128), nullable=False),
        sa.Column('operacion', sa.String(64), nullable=False),
        sa.Column('clave', sa.String(128), nullable=False),
        sa.Column('body_hash', sa.String(64), nullable=False),
        sa.Column('response_code', sa.Integer(), nullable=False),
        sa.Column('response_body', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('actor', 'operacion', 'clave', name='uq_idempotencia_actor_op_clave')
    )

    existencias_seed = [
        {
            'producto_id': pid,
            'fisico': 10,
            'reservado': 0,
            'disponible': 10
        }
        for pid in INITIAL_PRODUCT_IDS
    ]
    op.bulk_insert(tabla_existencias, existencias_seed)

    movimientos_seed = [
        {
            'id': uuid4(),
            'producto_id': pid,
            'prestamo_id': None,
            'tipo': 'ENTRADA',
            'cantidad': 10,
            'motivo': 'Carga inicial de inventario'
        }
        for pid in INITIAL_PRODUCT_IDS
    ]
    op.bulk_insert(tabla_movimientos, movimientos_seed)


def downgrade():
    op.drop_table('idempotencia_http')
    op.drop_table('movimientos')
    op.drop_table('reservas')
    op.drop_table('existencias')
```

## services/inventario/app/domain.py

```python
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4
from typing import Optional
from sqlalchemy import select, update, insert
from .models import existencias, reservas, movimientos


def format_reserva(row) -> dict:
    return {
        'reserva_id': str(row['id']),
        'prestamo_id': str(row['prestamo_id']),
        'producto_id': str(row['producto_id']) if row['producto_id'] is not None else None,
        'cantidad': row['cantidad'],
        'estado_reserva': row['estado'],
        'revision_reserva': int(row['revision']),
        'vence_en': row['vence_en'].isoformat() if row['vence_en'] is not None else None
    }


def format_movimiento(row) -> dict:
    return {
        'id': str(row['id']),
        'producto_id': str(row['producto_id']),
        'prestamo_id': str(row['prestamo_id']) if row['prestamo_id'] is not None else None,
        'tipo': row['tipo'],
        'cantidad': int(row['cantidad']),
        'motivo': row['motivo'],
        'created_at': row['created_at'].isoformat()
    }


def format_existencia(row) -> dict:
    return {
        'producto_id': str(row['producto_id']),
        'fisico': int(row['fisico']),
        'reservado': int(row['reservado']),
        'disponible': int(row['disponible'])
    }


def get_reserva_by_prestamo(conn, prestamo_id: UUID) -> Optional[dict]:
    query = select(reservas).where(reservas.c.prestamo_id == prestamo_id)
    row = conn.execute(query).mappings().first()
    if not row:
        return None
    return format_reserva(row)


def reservar(conn, prestamo_id: UUID, producto_id: UUID, cantidad: int, ttl_seconds: int = 600) -> dict:
    now = datetime.now(timezone.utc)
    
    # 1. Lock existing reservation for this prestamo_id
    res_query = select(reservas).where(reservas.c.prestamo_id == prestamo_id).with_for_update()
    res_row = conn.execute(res_query).mappings().first()
    
    if res_row:
        if res_row['producto_id'] is not None and (res_row['producto_id'] != producto_id or res_row['cantidad'] != cantidad):
            raise ValueError("Conflicto de integridad: producto o cantidad no coinciden con la reserva existente")
        
        if res_row['estado'] in ('CANCELADA', 'SIN_STOCK', 'ENTREGADA', 'VENCIDA'):
            return format_reserva(res_row)
        
        if res_row['estado'] == 'ACTIVA':
            if res_row['vence_en'] and res_row['vence_en'] < now:
                ex_query = select(existencias).where(existencias.c.producto_id == res_row['producto_id']).with_for_update()
                ex_row = conn.execute(ex_query).mappings().first()
                if ex_row:
                    conn.execute(
                        update(existencias)
                        .where(existencias.c.producto_id == res_row['producto_id'])
                        .values(
                            disponible=ex_row['disponible'] + res_row['cantidad'],
                            reservado=ex_row['reservado'] - res_row['cantidad'],
                            updated_at=now
                        )
                    )
                new_rev = res_row['revision'] + 1
                conn.execute(
                    update(reservas)
                    .where(reservas.c.id == res_row['id'])
                    .values(estado='VENCIDA', revision=new_rev, updated_at=now)
                )
                conn.execute(
                    insert(movimientos).values(
                        id=uuid4(),
                        producto_id=res_row['producto_id'],
                        prestamo_id=prestamo_id,
                        tipo='VENCIMIENTO',
                        cantidad=res_row['cantidad'],
                        motivo=f"Vencimiento automático de reserva {res_row['id']}",
                        created_at=now
                    )
                )
                updated_res = dict(res_row)
                updated_res['estado'] = 'VENCIDA'
                updated_res['revision'] = new_rev
                return format_reserva(updated_res)
            
            return format_reserva(res_row)
    
    # 2. No existing reservation (SIN_RESERVA) -> evaluate stock atomically
    ex_query = select(existencias).where(existencias.c.producto_id == producto_id).with_for_update()
    ex_row = conn.execute(ex_query).mappings().first()
    
    if not ex_row or ex_row['disponible'] < cantidad:
        res_id = uuid4()
        conn.execute(
            insert(reservas).values(
                id=res_id,
                prestamo_id=prestamo_id,
                producto_id=producto_id,
                cantidad=cantidad,
                estado='SIN_STOCK',
                revision=1,
                vence_en=None,
                created_at=now,
                updated_at=now
            )
        )
        return {
            'reserva_id': str(res_id),
            'prestamo_id': str(prestamo_id),
            'producto_id': str(producto_id),
            'cantidad': cantidad,
            'estado_reserva': 'SIN_STOCK',
            'revision_reserva': 1,
            'vence_en': None
        }
    
    conn.execute(
        update(existencias)
        .where(existencias.c.producto_id == producto_id)
        .values(
            disponible=ex_row['disponible'] - cantidad,
            reservado=ex_row['reservado'] + cantidad,
            updated_at=now
        )
    )
    
    vence_en = now + timedelta(seconds=ttl_seconds)
    res_id = uuid4()
    conn.execute(
        insert(reservas).values(
            id=res_id,
            prestamo_id=prestamo_id,
            producto_id=producto_id,
            cantidad=cantidad,
            estado='ACTIVA',
            revision=1,
            vence_en=vence_en,
            created_at=now,
            updated_at=now
        )
    )
    
    conn.execute(
        insert(movimientos).values(
            id=uuid4(),
            producto_id=producto_id,
            prestamo_id=prestamo_id,
            tipo='RESERVA',
            cantidad=cantidad,
            motivo=f"Reserva préstamo {prestamo_id}",
            created_at=now
        )
    )
    
    return {
        'reserva_id': str(res_id),
        'prestamo_id': str(prestamo_id),
        'producto_id': str(producto_id),
        'cantidad': cantidad,
        'estado_reserva': 'ACTIVA',
        'revision_reserva': 1,
        'vence_en': vence_en.isoformat()
    }


def liberar(conn, prestamo_id: UUID) -> dict:
    now = datetime.now(timezone.utc)
    res_query = select(reservas).where(reservas.c.prestamo_id == prestamo_id).with_for_update()
    res_row = conn.execute(res_query).mappings().first()
    
    if not res_row:
        res_id = uuid4()
        conn.execute(
            insert(reservas).values(
                id=res_id,
                prestamo_id=prestamo_id,
                producto_id=None,
                cantidad=None,
                estado='CANCELADA',
                revision=1,
                vence_en=None,
                created_at=now,
                updated_at=now
            )
        )
        return {
            'reserva_id': str(res_id),
            'prestamo_id': str(prestamo_id),
            'producto_id': None,
            'cantidad': None,
            'estado_reserva': 'CANCELADA',
            'revision_reserva': 1,
            'vence_en': None
        }
    
    if res_row['estado'] in ('CANCELADA', 'SIN_STOCK', 'VENCIDA'):
        return format_reserva(res_row)
    
    if res_row['estado'] == 'ENTREGADA':
        raise ValueError("YA_ENTREGADA: no es posible liberar una reserva ya entregada")
    
    if res_row['estado'] == 'ACTIVA':
        if res_row['vence_en'] and res_row['vence_en'] < now:
            ex_query = select(existencias).where(existencias.c.producto_id == res_row['producto_id']).with_for_update()
            ex_row = conn.execute(ex_query).mappings().first()
            if ex_row:
                conn.execute(
                    update(existencias)
                    .where(existencias.c.producto_id == res_row['producto_id'])
                    .values(
                        disponible=ex_row['disponible'] + res_row['cantidad'],
                        reservado=ex_row['reservado'] - res_row['cantidad'],
                        updated_at=now
                    )
                )
            new_rev = res_row['revision'] + 1
            conn.execute(
                update(reservas)
                .where(reservas.c.id == res_row['id'])
                .values(estado='VENCIDA', revision=new_rev, updated_at=now)
            )
            conn.execute(
                insert(movimientos).values(
                    id=uuid4(),
                    producto_id=res_row['producto_id'],
                    prestamo_id=prestamo_id,
                    tipo='VENCIMIENTO',
                    cantidad=res_row['cantidad'],
                    motivo=f"Vencimiento automático de reserva {res_row['id']}",
                    created_at=now
                )
            )
            updated_res = dict(res_row)
            updated_res['estado'] = 'VENCIDA'
            updated_res['revision'] = new_rev
            return format_reserva(updated_res)
        
        ex_query = select(existencias).where(existencias.c.producto_id == res_row['producto_id']).with_for_update()
        ex_row = conn.execute(ex_query).mappings().first()
        if ex_row:
            conn.execute(
                update(existencias)
                .where(existencias.c.producto_id == res_row['producto_id'])
                .values(
                    disponible=ex_row['disponible'] + res_row['cantidad'],
                    reservado=ex_row['reservado'] - res_row['cantidad'],
                    updated_at=now
                )
            )
        
        new_rev = res_row['revision'] + 1
        conn.execute(
            update(reservas)
            .where(reservas.c.id == res_row['id'])
            .values(estado='CANCELADA', revision=new_rev, updated_at=now)
        )
        conn.execute(
            insert(movimientos).values(
                id=uuid4(),
                producto_id=res_row['producto_id'],
                prestamo_id=prestamo_id,
                tipo='LIBERACION',
                cantidad=res_row['cantidad'],
                motivo=f"Liberación de reserva préstamo {prestamo_id}",
                created_at=now
            )
        )
        updated_res = dict(res_row)
        updated_res['estado'] = 'CANCELADA'
        updated_res['revision'] = new_rev
        return format_reserva(updated_res)

    raise ValueError(f"Estado de reserva desconocido: {res_row['estado']}")


def entregar(conn, prestamo_id: UUID) -> dict:
    now = datetime.now(timezone.utc)
    res_query = select(reservas).where(reservas.c.prestamo_id == prestamo_id).with_for_update()
    res_row = conn.execute(res_query).mappings().first()
    
    if not res_row:
        return {
            'reserva_id': None,
            'prestamo_id': str(prestamo_id),
            'producto_id': None,
            'cantidad': None,
            'estado_reserva': 'SIN_RESERVA',
            'revision_reserva': 0,
            'vence_en': None
        }
    
    if res_row['estado'] == 'ENTREGADA':
        return format_reserva(res_row)
    
    if res_row['estado'] in ('CANCELADA', 'SIN_STOCK', 'VENCIDA'):
        raise ValueError(f"Entrega rechazada: la reserva está en estado terminal {res_row['estado']}")
    
    if res_row['estado'] == 'ACTIVA':
        if res_row['vence_en'] and res_row['vence_en'] < now:
            ex_query = select(existencias).where(existencias.c.producto_id == res_row['producto_id']).with_for_update()
            ex_row = conn.execute(ex_query).mappings().first()
            if ex_row:
                conn.execute(
                    update(existencias)
                    .where(existencias.c.producto_id == res_row['producto_id'])
                    .values(
                        disponible=ex_row['disponible'] + res_row['cantidad'],
                        reservado=ex_row['reservado'] - res_row['cantidad'],
                        updated_at=now
                    )
                )
            new_rev = res_row['revision'] + 1
            conn.execute(
                update(reservas)
                .where(reservas.c.id == res_row['id'])
                .values(estado='VENCIDA', revision=new_rev, updated_at=now)
            )
            conn.execute(
                insert(movimientos).values(
                    id=uuid4(),
                    producto_id=res_row['producto_id'],
                    prestamo_id=prestamo_id,
                    tipo='VENCIMIENTO',
                    cantidad=res_row['cantidad'],
                    motivo=f"Vencimiento automático de reserva {res_row['id']}",
                    created_at=now
                )
            )
            raise ValueError("RESERVA_VENCIDA: la reserva expiró antes de la entrega")
        
        ex_query = select(existencias).where(existencias.c.producto_id == res_row['producto_id']).with_for_update()
        ex_row = conn.execute(ex_query).mappings().first()
        if not ex_row:
            raise ValueError("Existencias no encontradas para el producto")
        
        conn.execute(
            update(existencias)
            .where(existencias.c.producto_id == res_row['producto_id'])
            .values(
                fisico=ex_row['fisico'] - res_row['cantidad'],
                reservado=ex_row['reservado'] - res_row['cantidad'],
                updated_at=now
            )
        )
        
        new_rev = res_row['revision'] + 1
        conn.execute(
            update(reservas)
            .where(reservas.c.id == res_row['id'])
            .values(estado='ENTREGADA', revision=new_rev, updated_at=now)
        )
        conn.execute(
            insert(movimientos).values(
                id=uuid4(),
                producto_id=res_row['producto_id'],
                prestamo_id=prestamo_id,
                tipo='SALIDA',
                cantidad=res_row['cantidad'],
                motivo=f"Entrega definitiva préstamo {prestamo_id}",
                created_at=now
            )
        )
        updated_res = dict(res_row)
        updated_res['estado'] = 'ENTREGADA'
        updated_res['revision'] = new_rev
        return format_reserva(updated_res)

    raise ValueError(f"Estado de reserva desconocido: {res_row['estado']}")


def vencer(conn, prestamo_id: UUID) -> Optional[dict]:
    now = datetime.now(timezone.utc)
    res_query = select(reservas).where(reservas.c.prestamo_id == prestamo_id).with_for_update()
    res_row = conn.execute(res_query).mappings().first()
    
    if not res_row:
        return None
    
    if res_row['estado'] == 'ACTIVA' and res_row['vence_en'] and res_row['vence_en'] < now:
        ex_query = select(existencias).where(existencias.c.producto_id == res_row['producto_id']).with_for_update()
        ex_row = conn.execute(ex_query).mappings().first()
        if ex_row:
            conn.execute(
                update(existencias)
                .where(existencias.c.producto_id == res_row['producto_id'])
                .values(
                    disponible=ex_row['disponible'] + res_row['cantidad'],
                    reservado=ex_row['reservado'] - res_row['cantidad'],
                    updated_at=now
                )
            )
        new_rev = res_row['revision'] + 1
        conn.execute(
            update(reservas)
            .where(reservas.c.id == res_row['id'])
            .values(estado='VENCIDA', revision=new_rev, updated_at=now)
        )
        conn.execute(
            insert(movimientos).values(
                id=uuid4(),
                producto_id=res_row['producto_id'],
                prestamo_id=prestamo_id,
                tipo='VENCIMIENTO',
                cantidad=res_row['cantidad'],
                motivo=f"Vencimiento automático de reserva {res_row['id']}",
                created_at=now
            )
        )
        updated_res = dict(res_row)
        updated_res['estado'] = 'VENCIDA'
        updated_res['revision'] = new_rev
        return format_reserva(updated_res)
    
    return format_reserva(res_row)


def agregar_stock(conn, producto_id: UUID, cantidad: int, motivo: str) -> dict:
    now = datetime.now(timezone.utc)
    ex_query = select(existencias).where(existencias.c.producto_id == producto_id).with_for_update()
    ex_row = conn.execute(ex_query).mappings().first()
    
    if ex_row:
        conn.execute(
            update(existencias)
            .where(existencias.c.producto_id == producto_id)
            .values(
                fisico=ex_row['fisico'] + cantidad,
                disponible=ex_row['disponible'] + cantidad,
                updated_at=now
            )
        )
    else:
        conn.execute(
            insert(existencias).values(
                producto_id=producto_id,
                fisico=cantidad,
                reservado=0,
                disponible=cantidad,
                updated_at=now
            )
        )
    
    mov_id = uuid4()
    conn.execute(
        insert(movimientos).values(
            id=mov_id,
            producto_id=producto_id,
            prestamo_id=None,
            tipo='ENTRADA',
            cantidad=cantidad,
            motivo=motivo,
            created_at=now
        )
    )
    
    return {
        'id': str(mov_id),
        'producto_id': str(producto_id),
        'prestamo_id': None,
        'tipo': 'ENTRADA',
        'cantidad': cantidad,
        'motivo': motivo,
        'created_at': now.isoformat()
    }
```

## services/inventario/app/schemas.py

```python
from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SchemaBase(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Entrada(SchemaBase):
    producto_id: UUID
    cantidad: int = Field(..., ge=1)
    motivo: str = Field(..., min_length=1, max_length=250)


class Existencia(SchemaBase):
    producto_id: UUID
    fisico: int = Field(..., ge=0)
    reservado: int = Field(..., ge=0)
    disponible: int = Field(..., ge=0)


class Existencias(SchemaBase):
    items: List[Existencia]
    total: int = Field(..., ge=0)
    limit: int = Field(..., ge=1, le=100)
    offset: int = Field(..., ge=0)


class Movimiento(SchemaBase):
    id: UUID
    producto_id: UUID
    prestamo_id: Optional[UUID] = None
    tipo: Literal['ENTRADA', 'RESERVA', 'LIBERACION', 'SALIDA', 'VENCIMIENTO']
    cantidad: int = Field(..., ge=1)
    motivo: str = Field(..., min_length=1, max_length=250)
    created_at: datetime


class Movimientos(SchemaBase):
    items: List[Movimiento]
    total: int = Field(..., ge=0)
    limit: int = Field(..., ge=1, le=100)
    offset: int = Field(..., ge=0)


class Reserva(SchemaBase):
    reserva_id: UUID
    prestamo_id: UUID
    producto_id: Optional[UUID] = None
    cantidad: Optional[int] = Field(None, ge=1, le=100)
    estado_reserva: Literal['ACTIVA', 'SIN_STOCK', 'CANCELADA', 'VENCIDA', 'ENTREGADA']
    revision_reserva: int = Field(..., ge=1)
    vence_en: Optional[datetime] = None

    @model_validator(mode='after')
    def validate_reserva_state(self):
        if self.estado_reserva in ('ACTIVA', 'VENCIDA', 'ENTREGADA'):
            if self.producto_id is None:
                raise ValueError(f"producto_id es obligatorio cuando estado_reserva es {self.estado_reserva}")
            if self.cantidad is None:
                raise ValueError(f"cantidad es obligatoria cuando estado_reserva es {self.estado_reserva}")
            if self.vence_en is None:
                raise ValueError(f"vence_en es obligatorio cuando estado_reserva es {self.estado_reserva}")
        elif self.estado_reserva == 'SIN_STOCK':
            if self.producto_id is None:
                raise ValueError("producto_id es obligatorio cuando estado_reserva es SIN_STOCK")
            if self.cantidad is None:
                raise ValueError("cantidad es obligatoria cuando estado_reserva es SIN_STOCK")
            if self.vence_en is not None:
                raise ValueError("vence_en debe ser null cuando estado_reserva es SIN_STOCK")
        return self


class Reservas(SchemaBase):
    items: List[Reserva]
    total: int = Field(..., ge=0)
    limit: int = Field(..., ge=1, le=100)
    offset: int = Field(..., ge=0)
```

## services/inventario/app/main.py

```python
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
            return JSONResponse(
                status_code=idemp_row['response_code'],
                headers={'Location': '/api/inventario/movimientos'},
                content=idemp_row['response_body']
            )
        else:
            raise HTTPException(409, 'Clave de idempotencia ya utilizada con otro contenido')

    mov_dict = agregar_stock(conn, payload.producto_id, payload.cantidad, payload.motivo)

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
    reserva_actual = vencer(conn, prestamo_id)
    if not reserva_actual:
        raise HTTPException(404, 'Reserva no encontrada')
    return reserva_actual
```
