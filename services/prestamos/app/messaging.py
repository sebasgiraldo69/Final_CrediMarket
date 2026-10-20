"""Messaging transport, inventory projection, and loan state machine events (Fase 9)."""
from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB, insert

from shared.messages import PermanentMessageError, event, enqueue, COMMANDS
from .models import prestamos, prestamos_historial
from .domain import TERMINAL_STATES, record_transition, advisory_loan_lock

metadata = sa.MetaData()
snapshots = sa.Table(
    "inventory_snapshots",
    metadata,
    sa.Column("prestamo_id", PG_UUID(as_uuid=True), primary_key=True),
    sa.Column("revision", sa.Integer, nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    sa.Column("event_id", PG_UUID(as_uuid=True), nullable=False),
)


def handle(conn, message):
    loan_id = UUID(message["prestamo_id"])
    payload = message["payload"]
    event_type = message["type"]
    correlation_id = message.get("correlation_id")

    # Serialize even the first result, when no row exists yet.
    advisory_loan_lock(conn, loan_id)

    # 1. Mantener proyección de snapshots de inventario (Fase 6)
    old = conn.execute(
        sa.select(snapshots).where(snapshots.c.prestamo_id == loan_id)
    ).mappings().first()

    revision_reserva = payload.get("revision_reserva", 0)
    if old and old["revision"] >= revision_reserva:
        if old["revision"] == revision_reserva:
            keys = ("reserva_id", "estado_reserva", "revision_reserva", "vence_en")
            if any(old["payload"].get(k) != payload.get(k) for k in keys):
                raise PermanentMessageError("CONFLICTING_RESERVATION_REVISION")
    else:
        stmt = insert(snapshots).values(
            prestamo_id=loan_id,
            revision=revision_reserva,
            payload=payload,
            event_id=UUID(message["event_id"]),
        )
        conn.execute(
            stmt.on_conflict_do_update(
                index_elements=["prestamo_id"],
                set_={
                    "revision": stmt.excluded.revision,
                    "payload": stmt.excluded.payload,
                    "event_id": stmt.excluded.event_id,
                },
            )
        )

    # 2. Transición normativa del ciclo de vida del préstamo en prestamos (Fase 9)
    loan_query = sa.select(prestamos).where(prestamos.c.id == loan_id).with_for_update()
    loan = conn.execute(loan_query).mappings().first()
    if not loan:
        # Si aún no existe el préstamo en esta base (p. ej. pruebas aisladas de fase 6), no fallar
        return

    current_state = loan["estado"]

    # Invariante 5 (docs/estados.md): no reactivar préstamos terminales
    if current_state in TERMINAL_STATES:
        return

    now_utc = datetime.now(timezone.utc)

    if event_type == "InventarioReservado":
        reserva_id = UUID(payload["reserva_id"]) if payload.get("reserva_id") else None
        vence_en_str = payload.get("vence_en")
        vence_en_dt = datetime.fromisoformat(vence_en_str) if vence_en_str else None

        if current_state == "PENDIENTE_INVENTARIO":
            if vence_en_dt and vence_en_dt <= now_utc:
                # Llegó ya vencido
                new_state = "VERIFICACION_PENDIENTE"
                utilizable = False
            else:
                new_state = "APROBADA"
                utilizable = True

            conn.execute(
                prestamos.update()
                .where(prestamos.c.id == loan_id)
                .values(
                    estado=new_state,
                    reserva_id=reserva_id,
                    revision_reserva=revision_reserva,
                    vence_en=vence_en_dt,
                    reserva_utilizable=utilizable,
                    updated_at=sa.func.now(),
                )
            )
            record_transition(conn, loan_id, current_state, new_state, None, correlation_id)

        elif current_state == "CANCELACION_PENDIENTE":
            # InventarioReservado tardío mientras se cancelaba: asegurar comando de liberación, nunca aprobar
            conn.execute(
                prestamos.update()
                .where(prestamos.c.id == loan_id)
                .values(
                    reserva_id=reserva_id,
                    revision_reserva=revision_reserva,
                    vence_en=vence_en_dt,
                    reserva_utilizable=False,
                    updated_at=sa.func.now(),
                )
            )
            lib_cmd = event(
                "LiberacionSolicitada",
                loan_id,
                {"motivo": loan.get("motivo") or "CANCELACION_TARDA"},
                correlation_id=correlation_id,
            )
            enqueue(conn, lib_cmd, COMMANDS)

    elif event_type == "InventarioInsuficiente":
        if current_state == "PENDIENTE_INVENTARIO":
            conn.execute(
                prestamos.update()
                .where(prestamos.c.id == loan_id)
                .values(
                    estado="CANCELADA_SIN_STOCK",
                    motivo="STOCK_INSUFICIENTE",
                    reserva_utilizable=False,
                    updated_at=sa.func.now(),
                )
            )
            record_transition(conn, loan_id, current_state, "CANCELADA_SIN_STOCK", "STOCK_INSUFICIENTE", correlation_id)

        elif current_state == "CANCELACION_PENDIENTE":
            conn.execute(
                prestamos.update()
                .where(prestamos.c.id == loan_id)
                .values(
                    estado="CANCELADA",
                    motivo=loan.get("motivo") or "STOCK_INSUFICIENTE",
                    reserva_utilizable=False,
                    updated_at=sa.func.now(),
                )
            )
            record_transition(conn, loan_id, current_state, "CANCELADA", "STOCK_INSUFICIENTE", correlation_id)

    elif event_type == "ReservaLiberada":
        if current_state in ("CANCELACION_PENDIENTE", "PENDIENTE_INVENTARIO", "APROBADA", "VERIFICACION_PENDIENTE"):
            conn.execute(
                prestamos.update()
                .where(prestamos.c.id == loan_id)
                .values(
                    estado="CANCELADA",
                    motivo=loan.get("motivo") or "RESERVA_LIBERADA",
                    reserva_utilizable=False,
                    updated_at=sa.func.now(),
                )
            )
            record_transition(conn, loan_id, current_state, "CANCELADA", loan.get("motivo") or "RESERVA_LIBERADA", correlation_id)

    elif event_type == "ReservaExpirada":
        if current_state in ("PENDIENTE_INVENTARIO", "APROBADA", "ENTREGA_PENDIENTE", "VERIFICACION_PENDIENTE", "CANCELACION_PENDIENTE"):
            conn.execute(
                prestamos.update()
                .where(prestamos.c.id == loan_id)
                .values(
                    estado="CANCELADA",
                    motivo="RESERVA_VENCIDA",
                    reserva_utilizable=False,
                    updated_at=sa.func.now(),
                )
            )
            record_transition(conn, loan_id, current_state, "CANCELADA", "RESERVA_VENCIDA", correlation_id)

    elif event_type == "EntregaConfirmada":
        if current_state in ("ENTREGA_PENDIENTE", "VERIFICACION_PENDIENTE", "APROBADA"):
            conn.execute(
                prestamos.update()
                .where(prestamos.c.id == loan_id)
                .values(
                    estado="COMPLETADA",
                    reserva_utilizable=False,
                    updated_at=sa.func.now(),
                )
            )
            record_transition(conn, loan_id, current_state, "COMPLETADA", None, correlation_id)

    elif event_type == "EntregaRechazada":
        estado_reserva = payload.get("estado_reserva")
        if estado_reserva in ("VENCIDA", "CANCELADA", "SIN_STOCK"):
            conn.execute(
                prestamos.update()
                .where(prestamos.c.id == loan_id)
                .values(
                    estado="CANCELADA",
                    motivo=payload.get("motivo") or estado_reserva,
                    reserva_utilizable=False,
                    updated_at=sa.func.now(),
                )
            )
            record_transition(conn, loan_id, current_state, "CANCELADA", payload.get("motivo") or estado_reserva, correlation_id)
        elif estado_reserva == "SIN_RESERVA":
            conn.execute(
                prestamos.update()
                .where(prestamos.c.id == loan_id)
                .values(
                    estado="VERIFICACION_PENDIENTE",
                    motivo="ENTREGA_RECHAZADA_SIN_RESERVA",
                    reserva_utilizable=False,
                    updated_at=sa.func.now(),
                )
            )
            record_transition(conn, loan_id, current_state, "VERIFICACION_PENDIENTE", "ENTREGA_RECHAZADA_SIN_RESERVA", correlation_id)

    elif event_type == "LiberacionRechazada":
        if payload.get("motivo") == "YA_ENTREGADA":
            conn.execute(
                prestamos.update()
                .where(prestamos.c.id == loan_id)
                .values(
                    estado="COMPLETADA",
                    reserva_utilizable=False,
                    updated_at=sa.func.now(),
                )
            )
            record_transition(conn, loan_id, current_state, "COMPLETADA", "YA_ENTREGADA", correlation_id)


def sweep(conn):
    """Barrido periódico en segundo plano para marcar vencimientos."""
    now_utc = datetime.now(timezone.utc)
    expired_loans = conn.execute(
        sa.select(prestamos.c.id)
        .where(
            prestamos.c.estado.in_(["APROBADA", "ENTREGA_PENDIENTE"]),
            prestamos.c.vence_en <= now_utc,
        )
        .limit(50)
    ).scalars().all()

    for lid in expired_loans:
        advisory_loan_lock(conn, lid)
        row = conn.execute(
            sa.select(prestamos.c.estado, prestamos.c.vence_en)
            .where(prestamos.c.id == lid)
            .with_for_update()
        ).mappings().first()
        if row and row["estado"] in ("APROBADA", "ENTREGA_PENDIENTE") and row["vence_en"] and row["vence_en"] <= now_utc:
            conn.execute(
                prestamos.update()
                .where(prestamos.c.id == lid)
                .values(estado="VERIFICACION_PENDIENTE", reserva_utilizable=False, updated_at=sa.func.now())
            )
            record_transition(conn, lid, row["estado"], "VERIFICACION_PENDIENTE", "RESERVA_VENCIDA", None)
