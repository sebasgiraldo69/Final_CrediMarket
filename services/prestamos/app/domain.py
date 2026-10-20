"""Lógica de dominio, máquina de estados, idempotencia y formato para Préstamos (Fase 9)."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, func, text
from sqlalchemy.dialects.postgresql import insert

from shared.messages import event, enqueue, COMMANDS
from .models import prestamos, prestamos_idempotencia, prestamos_historial
from .schemas import calcular_cuota_anualidad, PrestamoCrear, Cancelacion
from .clients import fetch_product_quote, fetch_client_profile, ServiceCommunicationError

TERMINAL_STATES = {
    "RECHAZADA",
    "ERROR_TECNICO",
    "CANCELADA_SIN_STOCK",
    "CANCELADA",
    "COMPLETADA",
}


def advisory_loan_lock(conn, loan_id: UUID | str):
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:id, 1))"),
        {"id": str(loan_id)},
    )


def compute_request_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def check_idempotency(conn, key: str, actor_id: str, endpoint: str, request_hash: str) -> dict | None:
    stmt = select(prestamos_idempotencia).where(
        prestamos_idempotencia.c.idempotency_key == key,
        prestamos_idempotencia.c.actor_id == str(actor_id),
        prestamos_idempotencia.c.endpoint == endpoint,
    )
    row = conn.execute(stmt).mappings().first()
    if not row:
        return None
    if row["request_hash"] != request_hash:
        raise HTTPException(409, "La misma clave de idempotencia se usó con otro cuerpo de solicitud")
    return {
        "status_code": row["status_code"],
        "body": row["response_body"],
        "location": row["location_header"],
    }


def save_idempotency(
    conn,
    key: str,
    actor_id: str,
    endpoint: str,
    resource_id: UUID | None,
    request_hash: str,
    status_code: int,
    response_body: dict,
    location_header: str | None,
):
    stmt = insert(prestamos_idempotencia).values(
        idempotency_key=key,
        actor_id=str(actor_id),
        endpoint=endpoint,
        resource_id=resource_id,
        request_hash=request_hash,
        status_code=status_code,
        response_body=response_body,
        location_header=location_header,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["idempotency_key", "actor_id", "endpoint"],
        set_={
            "status_code": stmt.excluded.status_code,
            "response_body": stmt.excluded.response_body,
            "location_header": stmt.excluded.location_header,
        },
    )
    conn.execute(stmt)


def record_transition(
    conn,
    prestamo_id: UUID,
    estado_anterior: str | None,
    estado_nuevo: str,
    motivo: str | None,
    correlation_id: str | None,
):
    conn.execute(
        prestamos_historial.insert().values(
            id=uuid4(),
            prestamo_id=prestamo_id,
            estado_anterior=estado_anterior,
            estado_nuevo=estado_nuevo,
            motivo=motivo,
            correlation_id=str(correlation_id) if correlation_id else None,
        )
    )


def format_prestamo(row: dict) -> dict:
    estado = row["estado"]
    vence_en_dt = row.get("vence_en")
    now_utc = datetime.now(timezone.utc)

    # Expiración dinámica para lecturas: si está en APROBADA pero el tiempo venció,
    # el contrato y la especificación exigen presentar VERIFICACION_PENDIENTE y reserva_utilizable=false
    if estado == "APROBADA" and vence_en_dt is not None:
        if isinstance(vence_en_dt, str):
            try:
                vence_en_dt_parsed = datetime.fromisoformat(vence_en_dt)
            except Exception:
                vence_en_dt_parsed = None
        else:
            vence_en_dt_parsed = vence_en_dt

        if vence_en_dt_parsed and vence_en_dt_parsed <= now_utc:
            estado = "VERIFICACION_PENDIENTE"

    reserva_utilizable = (estado == "APROBADA")

    riesgo_obj = None
    if row.get("probabilidad_incumplimiento") is not None:
        riesgo_obj = {
            "probabilidad_incumplimiento": float(row["probabilidad_incumplimiento"]),
            "decision_riesgo": row["decision_riesgo"],
            "umbral": float(row["umbral_riesgo"]),
            "model_version": row["model_version"],
            "run_id": row["run_id"],
        }

    def _fmt_money(val) -> str | None:
        if val is None:
            return None
        return f"{Decimal(str(val)):.2f}"

    def _fmt_dt(val) -> str | None:
        if val is None:
            return None
        if isinstance(val, str):
            return val
        return val.isoformat()

    return {
        "id": str(row["id"]),
        "cliente_id": str(row["cliente_id"]),
        "producto_id": str(row["producto_id"]),
        "cantidad": int(row["cantidad"]),
        "plazo_meses": int(row["plazo_meses"]),
        "estado": estado,
        "motivo": row.get("motivo"),
        "precio_unitario_cop": _fmt_money(row.get("precio_unitario_cop")),
        "version_producto": int(row["version_producto"]) if row.get("version_producto") is not None else None,
        "monto_cop": _fmt_money(row.get("monto_cop")),
        "cuota_cop": _fmt_money(row.get("cuota_cop")),
        "riesgo": riesgo_obj,
        "reserva_id": str(row["reserva_id"]) if row.get("reserva_id") else None,
        "vence_en": _fmt_dt(row.get("vence_en")),
        "reserva_utilizable": reserva_utilizable,
        "created_at": _fmt_dt(row["created_at"]),
        "updated_at": _fmt_dt(row["updated_at"]),
    }


def evaluar_y_crear_solicitud(
    conn,
    cliente_id: UUID,
    body: PrestamoCrear,
    registry,
    correlation_id: str | None,
) -> tuple[int, dict, str]:
    """Evalúa la solicitud de crédito; devuelve (status_code, prestamo_dict, location_header)."""
    producto_id = UUID(body.producto_id)
    cantidad = body.cantidad
    plazo_meses = body.plazo_meses
    prestamo_id = uuid4()
    location = f"/api/prestamos/prestamos/{prestamo_id}"

    # 1. Obtener cotización de Productos
    try:
        quote = fetch_product_quote(producto_id, correlation_id)
    except ServiceCommunicationError as err:
        raise HTTPException(err.status_code, err.message)

    if quote is None:
        raise HTTPException(404, "Producto no encontrado")

    precio_unitario_cop = Decimal(str(quote["precio_unitario_cop"]))
    version_producto = int(quote["version_producto"])
    producto_activo = bool(quote["activo"])

    # 2. Si el producto está inactivo, rechazar
    if not producto_activo:
        monto_cop = precio_unitario_cop * cantidad
        cuota_cop = calcular_cuota_anualidad(monto_cop, plazo_meses)
        rechazo_data = {
            "id": prestamo_id,
            "cliente_id": cliente_id,
            "producto_id": producto_id,
            "cantidad": cantidad,
            "plazo_meses": plazo_meses,
            "estado": "RECHAZADA",
            "motivo": "PRODUCTO_INACTIVO",
            "precio_unitario_cop": precio_unitario_cop,
            "version_producto": version_producto,
            "monto_cop": monto_cop,
            "cuota_cop": cuota_cop,
            "probabilidad_incumplimiento": None,
            "decision_riesgo": None,
            "umbral_riesgo": None,
            "model_version": None,
            "run_id": None,
            "features": None,
            "reserva_id": None,
            "revision_reserva": 0,
            "vence_en": None,
            "reserva_utilizable": False,
            "accion_pendiente": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        conn.execute(prestamos.insert().values(**rechazo_data))
        record_transition(conn, prestamo_id, None, "RECHAZADA", "PRODUCTO_INACTIVO", correlation_id)
        return 201, format_prestamo(rechazo_data), location

    # 3. Obtener perfil de Clientes
    try:
        client_profile = fetch_client_profile(cliente_id, correlation_id)
    except ServiceCommunicationError as err:
        raise HTTPException(err.status_code, err.message)

    if client_profile is None:
        raise HTTPException(404, "Cliente no encontrado")

    if not client_profile.get("activo", True):
        monto_cop = precio_unitario_cop * cantidad
        cuota_cop = calcular_cuota_anualidad(monto_cop, plazo_meses)
        rechazo_data = {
            "id": prestamo_id,
            "cliente_id": cliente_id,
            "producto_id": producto_id,
            "cantidad": cantidad,
            "plazo_meses": plazo_meses,
            "estado": "RECHAZADA",
            "motivo": "CLIENTE_INACTIVO",
            "precio_unitario_cop": precio_unitario_cop,
            "version_producto": version_producto,
            "monto_cop": monto_cop,
            "cuota_cop": cuota_cop,
            "probabilidad_incumplimiento": None,
            "decision_riesgo": None,
            "umbral_riesgo": None,
            "model_version": None,
            "run_id": None,
            "features": None,
            "reserva_id": None,
            "revision_reserva": 0,
            "vence_en": None,
            "reserva_utilizable": False,
            "accion_pendiente": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        conn.execute(prestamos.insert().values(**rechazo_data))
        record_transition(conn, prestamo_id, None, "RECHAZADA", "CLIENTE_INACTIVO", correlation_id)
        return 201, format_prestamo(rechazo_data), location

    finanzas = client_profile.get("finanzas")
    if not finanzas:
        monto_cop = precio_unitario_cop * cantidad
        cuota_cop = calcular_cuota_anualidad(monto_cop, plazo_meses)
        rechazo_data = {
            "id": prestamo_id,
            "cliente_id": cliente_id,
            "producto_id": producto_id,
            "cantidad": cantidad,
            "plazo_meses": plazo_meses,
            "estado": "RECHAZADA",
            "motivo": "INFORMACION_INCOMPLETA",
            "precio_unitario_cop": precio_unitario_cop,
            "version_producto": version_producto,
            "monto_cop": monto_cop,
            "cuota_cop": cuota_cop,
            "probabilidad_incumplimiento": None,
            "decision_riesgo": None,
            "umbral_riesgo": None,
            "model_version": None,
            "run_id": None,
            "features": None,
            "reserva_id": None,
            "revision_reserva": 0,
            "vence_en": None,
            "reserva_utilizable": False,
            "accion_pendiente": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        conn.execute(prestamos.insert().values(**rechazo_data))
        record_transition(conn, prestamo_id, None, "RECHAZADA", "INFORMACION_INCOMPLETA", correlation_id)
        return 201, format_prestamo(rechazo_data), location

    # 4. Calcular importes y validar política de monto [500000, 15000000] COP
    monto_cop = precio_unitario_cop * cantidad
    if monto_cop < Decimal("500000.00") or monto_cop > Decimal("15000000.00"):
        cuota_cop = calcular_cuota_anualidad(monto_cop, plazo_meses)
        rechazo_data = {
            "id": prestamo_id,
            "cliente_id": cliente_id,
            "producto_id": producto_id,
            "cantidad": cantidad,
            "plazo_meses": plazo_meses,
            "estado": "RECHAZADA",
            "motivo": "MONTO_FUERA_DE_POLITICA",
            "precio_unitario_cop": precio_unitario_cop,
            "version_producto": version_producto,
            "monto_cop": monto_cop,
            "cuota_cop": cuota_cop,
            "probabilidad_incumplimiento": None,
            "decision_riesgo": None,
            "umbral_riesgo": None,
            "model_version": None,
            "run_id": None,
            "features": None,
            "reserva_id": None,
            "revision_reserva": 0,
            "vence_en": None,
            "reserva_utilizable": False,
            "accion_pendiente": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        conn.execute(prestamos.insert().values(**rechazo_data))
        record_transition(conn, prestamo_id, None, "RECHAZADA", "MONTO_FUERA_DE_POLITICA", correlation_id)
        return 201, format_prestamo(rechazo_data), location

    cuota_cop = calcular_cuota_anualidad(monto_cop, plazo_meses)

    # 5. Predecir riesgo con el modelo activo
    features_payload = {
        "ingresos_mensuales_cop": float(finanzas["ingresos_mensuales_cop"]),
        "obligaciones_mensuales_cop": float(finanzas["obligaciones_mensuales_cop"]),
        "tipo_empleo": finanzas["tipo_empleo"],
        "antiguedad_laboral_meses": finanzas["antiguedad_laboral_meses"],
        "meses_historial_crediticio": finanzas["meses_historial_crediticio"],
        "creditos_previos": finanzas["creditos_previos"],
        "atrasos_previos_30d": finanzas["atrasos_previos_30d"],
        "porcentaje_pago_puntual": finanzas["porcentaje_pago_puntual"],
        "monto_solicitado_cop": float(monto_cop),
        "plazo_meses": plazo_meses,
        "cuota_estimada_cop": float(cuota_cop),
    }

    riesgo_res = registry.predict_one(features_payload, correlation_id=correlation_id)

    # 6. Si el riesgo es DESFAVORABLE, rechazar sin solicitar inventario
    if riesgo_res["decision_riesgo"] == "DESFAVORABLE":
        rechazo_data = {
            "id": prestamo_id,
            "cliente_id": cliente_id,
            "producto_id": producto_id,
            "cantidad": cantidad,
            "plazo_meses": plazo_meses,
            "estado": "RECHAZADA",
            "motivo": "RIESGO_DESFAVORABLE",
            "precio_unitario_cop": precio_unitario_cop,
            "version_producto": version_producto,
            "monto_cop": monto_cop,
            "cuota_cop": cuota_cop,
            "probabilidad_incumplimiento": riesgo_res["probabilidad_incumplimiento"],
            "decision_riesgo": riesgo_res["decision_riesgo"],
            "umbral_riesgo": riesgo_res["umbral"],
            "model_version": riesgo_res["model_version"],
            "run_id": riesgo_res["run_id"],
            "features": features_payload,
            "reserva_id": None,
            "revision_reserva": 0,
            "vence_en": None,
            "reserva_utilizable": False,
            "accion_pendiente": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        conn.execute(prestamos.insert().values(**rechazo_data))
        record_transition(conn, prestamo_id, None, "RECHAZADA", "RIESGO_DESFAVORABLE", correlation_id)
        return 201, format_prestamo(rechazo_data), location

    # 7. Riesgo FAVORABLE: guardar PENDIENTE_INVENTARIO y encolar ReservaSolicitada en outbox
    prestamo_data = {
        "id": prestamo_id,
        "cliente_id": cliente_id,
        "producto_id": producto_id,
        "cantidad": cantidad,
        "plazo_meses": plazo_meses,
        "estado": "PENDIENTE_INVENTARIO",
        "motivo": None,
        "precio_unitario_cop": precio_unitario_cop,
        "version_producto": version_producto,
        "monto_cop": monto_cop,
        "cuota_cop": cuota_cop,
        "probabilidad_incumplimiento": riesgo_res["probabilidad_incumplimiento"],
        "decision_riesgo": riesgo_res["decision_riesgo"],
        "umbral_riesgo": riesgo_res["umbral"],
        "model_version": riesgo_res["model_version"],
        "run_id": riesgo_res["run_id"],
        "features": features_payload,
        "reserva_id": None,
        "revision_reserva": 0,
        "vence_en": None,
        "reserva_utilizable": False,
        "accion_pendiente": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    conn.execute(prestamos.insert().values(**prestamo_data))
    record_transition(conn, prestamo_id, None, "PENDIENTE_INVENTARIO", None, correlation_id)

    # Encolar comando Kafka ReservaSolicitada hacia Inventario en la misma transacción PostgreSQL
    cmd_body = event(
        "ReservaSolicitada",
        prestamo_id,
        {"producto_id": str(producto_id), "cantidad": cantidad},
        correlation_id=correlation_id,
    )
    enqueue(conn, cmd_body, COMMANDS)

    return 202, format_prestamo(prestamo_data), location


def solicitar_cancelacion(
    conn,
    prestamo_id: UUID,
    actor_role: str,
    actor_client_id: UUID | None,
    body: Cancelacion,
    correlation_id: str | None,
) -> tuple[int, dict, str]:
    """Solicita la cancelación del préstamo según las reglas de estados de Fase 1 y 9."""
    advisory_loan_lock(conn, prestamo_id)
    location = f"/api/prestamos/prestamos/{prestamo_id}"

    query = select(prestamos).where(prestamos.c.id == prestamo_id).with_for_update()
    row = conn.execute(query).mappings().first()
    if not row:
        raise HTTPException(404, "Préstamo no encontrado")

    if actor_role != "administrador" and row["cliente_id"] != actor_client_id:
        raise HTTPException(404, "Préstamo no encontrado")

    current_state = row["estado"]

    # Reglas normativas de cancelación (docs/estados.md):
    if current_state == "EVALUANDO":
        raise HTTPException(409, "La solicitud está en evaluación y no puede cancelarse aún")

    if current_state == "CANCELADA":
        # No-op idempotente: ya está cancelada
        return 200, format_prestamo(row), location

    if current_state == "CANCELACION_PENDIENTE":
        # Ya fue aceptada la cancelación
        return 202, format_prestamo(row), location

    if current_state in ("ENTREGA_PENDIENTE", "COMPLETADA"):
        raise HTTPException(409, f"No se puede cancelar un préstamo en estado {current_state}")

    if current_state in ("RECHAZADA", "ERROR_TECNICO", "CANCELADA_SIN_STOCK"):
        raise HTTPException(409, f"No se puede cancelar un préstamo en estado terminal {current_state}")

    # Estados cancelables: PENDIENTE_INVENTARIO, APROBADA, VERIFICACION_PENDIENTE (sin entrega aceptada)
    if current_state in ("PENDIENTE_INVENTARIO", "APROBADA", "VERIFICACION_PENDIENTE"):
        if row.get("accion_pendiente") == "entrega":
            raise HTTPException(409, "Una entrega ya aceptada bloquea la cancelación")

        new_values = {
            "estado": "CANCELACION_PENDIENTE",
            "motivo": body.motivo,
            "reserva_utilizable": False,
            "accion_pendiente": "cancelacion",
            "updated_at": func.now(),
        }
        conn.execute(prestamos.update().where(prestamos.c.id == prestamo_id).values(**new_values))
        record_transition(conn, prestamo_id, current_state, "CANCELACION_PENDIENTE", body.motivo, correlation_id)

        # Encolar comando LiberacionSolicitada en outbox
        cmd_body = event(
            "LiberacionSolicitada",
            prestamo_id,
            {"motivo": body.motivo},
            correlation_id=correlation_id,
        )
        enqueue(conn, cmd_body, COMMANDS)

        updated_row = conn.execute(select(prestamos).where(prestamos.c.id == prestamo_id)).mappings().first()
        return 202, format_prestamo(updated_row), location

    raise HTTPException(409, f"Operación no permitida en estado {current_state}")


def solicitar_entrega(
    conn,
    prestamo_id: UUID,
    correlation_id: str | None,
) -> tuple[int, dict, str]:
    """Solicita la entrega física del producto para un préstamo aprobado."""
    advisory_loan_lock(conn, prestamo_id)
    location = f"/api/prestamos/prestamos/{prestamo_id}"

    query = select(prestamos).where(prestamos.c.id == prestamo_id).with_for_update()
    row = conn.execute(query).mappings().first()
    if not row:
        raise HTTPException(404, "Préstamo no encontrado")

    current_state = row["estado"]

    if current_state == "COMPLETADA":
        # No-op idempotente: ya entregado
        return 200, format_prestamo(row), location

    if current_state == "ENTREGA_PENDIENTE":
        # Ya en entrega
        return 202, format_prestamo(row), location

    if current_state in ("CANCELACION_PENDIENTE", "CANCELADA"):
        raise HTTPException(409, "Cancelación ya aceptada bloquea entrega")

    if current_state in ("EVALUANDO", "RECHAZADA", "ERROR_TECNICO", "CANCELADA_SIN_STOCK", "PENDIENTE_INVENTARIO"):
        raise HTTPException(409, f"No se puede solicitar entrega en estado {current_state}")

    if current_state == "APROBADA":
        vence_en_dt = row.get("vence_en")
        now_utc = datetime.now(timezone.utc)
        if vence_en_dt is not None:
            if isinstance(vence_en_dt, str):
                vence_en_dt = datetime.fromisoformat(vence_en_dt)
            if vence_en_dt <= now_utc:
                # La reserva venció antes de la entrega: pasar a VERIFICACION_PENDIENTE
                conn.execute(
                    prestamos.update()
                    .where(prestamos.c.id == prestamo_id)
                    .values(estado="VERIFICACION_PENDIENTE", reserva_utilizable=False, updated_at=func.now())
                )
                record_transition(conn, prestamo_id, "APROBADA", "VERIFICACION_PENDIENTE", "RESERVA_VENCIDA", correlation_id)
                raise HTTPException(409, "La reserva de inventario ha vencido")

        if not row.get("reserva_id"):
            raise HTTPException(409, "El préstamo aprobado no tiene reserva de inventario asociada")

        new_values = {
            "estado": "ENTREGA_PENDIENTE",
            "accion_pendiente": "entrega",
            "reserva_utilizable": False,
            "updated_at": func.now(),
        }
        conn.execute(prestamos.update().where(prestamos.c.id == prestamo_id).values(**new_values))
        record_transition(conn, prestamo_id, current_state, "ENTREGA_PENDIENTE", None, correlation_id)

        # Encolar EntregaSolicitada en outbox
        cmd_body = event(
            "EntregaSolicitada",
            prestamo_id,
            {"reserva_id": str(row["reserva_id"])},
            correlation_id=correlation_id,
        )
        enqueue(conn, cmd_body, COMMANDS)

        updated_row = conn.execute(select(prestamos).where(prestamos.c.id == prestamo_id)).mappings().first()
        return 202, format_prestamo(updated_row), location

    raise HTTPException(409, f"Operación de entrega no permitida en estado {current_state}")
