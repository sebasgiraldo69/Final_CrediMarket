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

    # Initial stock seed
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
