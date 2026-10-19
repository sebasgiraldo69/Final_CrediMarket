"""Clientes, usuarios y reportes de importación."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('clientes',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('clave_externa', sa.String(250), unique=True),
        sa.Column('nombre', sa.String(250)), sa.Column('email', sa.String(254)),
        sa.Column('activo', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('finanzas', JSONB),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('version >= 1', name='ck_cliente_version'))
    op.create_table('usuarios',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('cliente_id', UUID(as_uuid=True), sa.ForeignKey('clientes.id'), unique=True),
        sa.Column('email', sa.String(254), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(512), nullable=False),
        sa.Column('rol', sa.String(20), nullable=False),
        sa.Column('activo', sa.Boolean, nullable=False, server_default='true'),
        sa.CheckConstraint("rol IN ('cliente','administrador')", name='ck_usuario_rol'),
        sa.CheckConstraint("rol != 'cliente' OR cliente_id IS NOT NULL", name='ck_usuario_cliente'))
    op.create_table('importaciones', sa.Column('id', UUID(as_uuid=True), primary_key=True),
                    sa.Column('reporte', JSONB, nullable=False))


def downgrade():
    op.drop_table('importaciones')
    op.drop_table('usuarios')
    op.drop_table('clientes')
