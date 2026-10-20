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
