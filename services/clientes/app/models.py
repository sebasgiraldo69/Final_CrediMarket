from sqlalchemy import MetaData, Table, Column, String, Boolean, Integer, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB

metadata = MetaData()
clientes = Table('clientes', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True),
    Column('clave_externa', String(250), unique=True),
    Column('nombre', String(250)), Column('email', String(254)),
    Column('activo', Boolean, nullable=False, server_default='true'),
    Column('version', Integer, nullable=False, server_default='1'),
    Column('finanzas', JSONB),
    Column('created_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column('updated_at', DateTime(timezone=True), nullable=False, server_default=func.now()))
usuarios = Table('usuarios', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True),
    Column('cliente_id', UUID(as_uuid=True), ForeignKey('clientes.id'), unique=True),
    Column('email', String(254), unique=True, nullable=False),
    Column('password_hash', String(512), nullable=False),
    Column('rol', String(20), nullable=False),
    Column('activo', Boolean, nullable=False, server_default='true'))
importaciones = Table('importaciones', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True),
    Column('reporte', JSONB, nullable=False))
