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
