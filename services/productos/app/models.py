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
