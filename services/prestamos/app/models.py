"""Tablas de base de datos para el microservicio de Préstamos (Fase 9)."""
from sqlalchemy import (
    MetaData,
    Table,
    Column,
    String,
    Boolean,
    Integer,
    Numeric,
    DateTime,
    ForeignKey,
    func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB

metadata = MetaData()

prestamos = Table(
    "prestamos",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("cliente_id", UUID(as_uuid=True), nullable=False, index=True),
    Column("producto_id", UUID(as_uuid=True), nullable=False),
    Column("cantidad", Integer, nullable=False),
    Column("plazo_meses", Integer, nullable=False),
    Column("estado", String(30), nullable=False, index=True),
    Column("motivo", String(250), nullable=True),
    Column("precio_unitario_cop", Numeric(18, 2), nullable=True),
    Column("version_producto", Integer, nullable=True),
    Column("monto_cop", Numeric(18, 2), nullable=True),
    Column("cuota_cop", Numeric(18, 2), nullable=True),
    Column("probabilidad_incumplimiento", Numeric(12, 10), nullable=True),
    Column("decision_riesgo", String(30), nullable=True),
    Column("umbral_riesgo", Numeric(10, 4), nullable=True),
    Column("model_version", String(50), nullable=True),
    Column("run_id", String(64), nullable=True),
    Column("features", JSONB, nullable=True),
    Column("reserva_id", UUID(as_uuid=True), nullable=True),
    Column("revision_reserva", Integer, nullable=False, server_default="0"),
    Column("vence_en", DateTime(timezone=True), nullable=True),
    Column("reserva_utilizable", Boolean, nullable=False, server_default="false"),
    Column("accion_pendiente", String(50), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

prestamos_idempotencia = Table(
    "prestamos_idempotencia",
    metadata,
    Column("idempotency_key", String(128), primary_key=True),
    Column("actor_id", String(64), primary_key=True),
    Column("endpoint", String(100), primary_key=True),
    Column("resource_id", UUID(as_uuid=True), nullable=True),
    Column("request_hash", String(64), nullable=False),
    Column("status_code", Integer, nullable=False),
    Column("response_body", JSONB, nullable=False),
    Column("location_header", String(255), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

prestamos_historial = Table(
    "prestamos_historial",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("prestamo_id", UUID(as_uuid=True), ForeignKey("prestamos.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("estado_anterior", String(30), nullable=True),
    Column("estado_nuevo", String(30), nullable=False),
    Column("motivo", String(250), nullable=True),
    Column("correlation_id", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
