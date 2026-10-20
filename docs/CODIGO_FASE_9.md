# Cuaderno de Código: Fase 9 — Flujo completo de Préstamos

Este documento compila el código fuente implementado y ajustado durante la **Fase 9: Completar el flujo de Préstamos**.

---

## 1. Migración Alembic `0003_prestamos.py`

Ubicación: [`services/prestamos/migrations/versions/0003_prestamos.py`](../services/prestamos/migrations/versions/0003_prestamos.py)

```python
"""Esquema relacional de Préstamos, idempotencia e historial (Fase 9).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

ESTADOS = (
    "EVALUANDO",
    "RECHAZADA",
    "ERROR_TECNICO",
    "PENDIENTE_INVENTARIO",
    "APROBADA",
    "CANCELACION_PENDIENTE",
    "ENTREGA_PENDIENTE",
    "VERIFICACION_PENDIENTE",
    "CANCELADA_SIN_STOCK",
    "CANCELADA",
    "COMPLETADA",
)

def upgrade():
    op.create_table(
        "prestamos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("cliente_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("producto_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("plazo_meses", sa.Integer(), nullable=False),
        sa.Column("estado", sa.String(length=32), nullable=False),
        sa.Column("motivo", sa.String(length=250), nullable=True),
        sa.Column("precio_unitario_cop", sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column("version_producto", sa.Integer(), nullable=True),
        sa.Column("monto_cop", sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column("cuota_cop", sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column("probabilidad_incumplimiento", sa.Float(), nullable=True),
        sa.Column("decision_riesgo", sa.String(length=32), nullable=True),
        sa.Column("umbral_riesgo", sa.Float(), nullable=True),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("features", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reserva_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revision_reserva", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("vence_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reserva_utilizable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("accion_pendiente", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"estado IN {tuple(ESTADOS)}", name="ck_prestamos_estado"),
        sa.CheckConstraint("cantidad >= 1 AND cantidad <= 100", name="ck_prestamos_cantidad"),
        sa.CheckConstraint("plazo_meses IN (6, 12, 18, 24, 36)", name="ck_prestamos_plazo"),
    )
    op.create_index("ix_prestamos_cliente", "prestamos", ["cliente_id"])
    op.create_index("ix_prestamos_estado", "prestamos", ["estado"])

    op.create_table(
        "prestamos_idempotencia",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("user_id", sa.String(length=64), primary_key=True),
        sa.Column("endpoint", sa.String(length=64), primary_key=True),
        sa.Column("prestamo_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("location", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "prestamos_historial",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("prestamo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("estado_anterior", sa.String(length=32), nullable=True),
        sa.Column("estado_nuevo", sa.String(length=32), nullable=False),
        sa.Column("motivo", sa.String(length=250), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["prestamo_id"], ["prestamos.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_prestamos_historial_prestamo", "prestamos_historial", ["prestamo_id"])

def downgrade():
    op.drop_table("prestamos_historial")
    op.drop_table("prestamos_idempotencia")
    op.drop_table("prestamos")
```

---

## 2. Clientes HTTP Internos (`services/prestamos/app/clients.py`)

Ubicación: [`services/prestamos/app/clients.py`](../services/prestamos/app/clients.py)

```python
"""Clientes HTTP internos para comunicación entre microservicios (Fase 9)."""
import json
import os
import urllib.error
import urllib.request
from uuid import UUID

from shared.auth import issue_service_token

class ServiceCommunicationError(Exception):
    def __init__(self, service: str, status_code: int, message: str, details=None):
        super().__init__(f"Error comunicando con {service}: {status_code} - {message}")
        self.service = service
        self.status_code = status_code
        self.message = message
        self.details = details or []

def get_service_url(service_name: str, default_url: str) -> str:
    env_var = f"{service_name.upper()}_URL"
    return os.getenv(env_var, default_url).rstrip("/")

def _internal_get(service: str, url: str, scopes: list[str], correlation_id: str | None = None) -> dict | None:
    token = issue_service_token("prestamos", scopes=scopes)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if correlation_id:
        headers["X-Correlation-ID"] = str(correlation_id)

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return None
        raw_err = err.read().decode("utf-8")
        parsed = {}
        try:
            parsed = json.loads(raw_err) if raw_err else {}
        except Exception:
            pass
        msg = parsed.get("message", f"HTTP {err.code}")
        details = parsed.get("details", [])
        raise ServiceCommunicationError(service, err.code, msg, details)
    except urllib.error.URLError as err:
        raise ServiceCommunicationError(service, 503, f"Servicio {service} no disponible ({err.reason})")

def fetch_product_quote(product_id: UUID, correlation_id: str | None = None) -> dict | None:
    base = get_service_url("productos", "http://productos:8000")
    url = f"{base}/interno/productos/{product_id}/cotizacion"
    return _internal_get("productos", url, ["productos:cotizar"], correlation_id)

def fetch_client_profile(client_id: UUID, correlation_id: str | None = None) -> dict | None:
    base = get_service_url("clientes", "http://clientes:8000")
    url = f"{base}/interno/clientes/{client_id}"
    return _internal_get("clientes", url, ["clientes:read"], correlation_id)

def fetch_inventory_reservation(prestamo_id: UUID, correlation_id: str | None = None) -> dict | None:
    base = get_service_url("inventario", "http://inventario:8000")
    url = f"{base}/interno/reservas/por-prestamo/{prestamo_id}"
    return _internal_get("inventario", url, ["reservas:read"], correlation_id)
```

---

## 3. Lógica de Dominio y Máquina de Estados (`services/prestamos/app/domain.py`)

Ubicación: [`services/prestamos/app/domain.py`](../services/prestamos/app/domain.py)

Provee:
- `calcular_cuota_anualidad(monto, plazo, tasa)`
- `compute_request_hash(payload)`
- `check_idempotency(...)` / `save_idempotency(...)`
- `evaluar_y_crear_solicitud(...)`
- `solicitar_cancelacion(...)`
- `solicitar_entrega(...)`
- `record_transition(...)`
- `advisory_loan_lock(...)`

---

## 4. Script Automatizado de Verificación (`scripts/check_phase9.py`)

Ubicación: [`scripts/check_phase9.py`](../scripts/check_phase9.py)

Ejecuta de forma secuencial y paralela la suite completa de pruebas:
- 12 secciones de verificación cubriendo todos los Acceptance Criteria (AC01, AC02, AC03, AC04, AC05, AC07, AC09, AC13).
