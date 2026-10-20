"""Inventory commands and expiration: stock, inbox and result outbox share a commit."""
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select, text
from shared.messages import event, enqueue, EVENTS, PermanentMessageError
from .models import reservas
from .domain import reservar, liberar, entregar, vencer, get_reserva_by_prestamo


def loan_lock(conn, loan_id):
    conn.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:id, 1))'),
                 {'id': str(loan_id)})


def emit(conn, kind, snapshot, command=None):
    payload = {key: snapshot[key] for key in
               ('reserva_id', 'estado_reserva', 'revision_reserva', 'vence_en')}
    payload['motivo'] = 'YA_ENTREGADA' if kind == 'LiberacionRechazada' else snapshot['estado_reserva']
    enqueue(conn, event(kind, snapshot['prestamo_id'], payload,
        command['correlation_id'] if command else None,
        command['event_id'] if command else None), EVENTS)


def expire(conn, loan_id):
    """Also used by the internal HTTP lookup, so no transition loses its event."""
    loan_lock(conn, loan_id)
    before = get_reserva_by_prestamo(conn, loan_id)
    after = vencer(conn, loan_id)
    if before and after and before['revision_reserva'] != after['revision_reserva']:
        emit(conn, 'ReservaExpirada', after)
    return after


def handle(conn, command):
    loan_id = UUID(command['prestamo_id'])
    loan_lock(conn, loan_id)
    kind, payload = command['type'], command['payload']
    current = get_reserva_by_prestamo(conn, loan_id)
    if kind == 'EntregaSolicitada' and current and current['reserva_id'] != payload['reserva_id']:
        raise PermanentMessageError('RESERVATION_ID_MISMATCH')
    # Persist expiry and its event even when delivery must subsequently be rejected.
    current = expire(conn, loan_id)
    try:
        if kind == 'ReservaSolicitada':
            snapshot = reservar(conn, loan_id, UUID(payload['producto_id']), payload['cantidad'])
            result = {'ACTIVA': 'InventarioReservado', 'SIN_STOCK': 'InventarioInsuficiente',
                      'CANCELADA': 'ReservaLiberada', 'VENCIDA': 'ReservaExpirada',
                      'ENTREGADA': 'EntregaConfirmada'}[snapshot['estado_reserva']]
        elif kind == 'LiberacionSolicitada':
            if current and current['estado_reserva'] == 'ENTREGADA':
                snapshot, result = current, 'LiberacionRechazada'
            else:
                snapshot = liberar(conn, loan_id)
                result = 'ReservaExpirada' if snapshot['estado_reserva'] == 'VENCIDA' else 'ReservaLiberada'
        else:
            if current and current['estado_reserva'] not in ('ACTIVA', 'ENTREGADA'):
                snapshot, result = current, 'EntregaRechazada'
            else:
                snapshot = entregar(conn, loan_id)
                result = 'EntregaConfirmada' if snapshot['estado_reserva'] == 'ENTREGADA' else 'EntregaRechazada'
    except ValueError:
        # Delivery can expire between the preceding check and the domain call.
        snapshot = get_reserva_by_prestamo(conn, loan_id)
        if kind == 'EntregaSolicitada' and snapshot and snapshot['estado_reserva'] == 'VENCIDA':
            emit(conn, 'ReservaExpirada', snapshot)
            result = 'EntregaRechazada'
        else:
            raise PermanentMessageError('DOMAIN_CONFLICT') from None
    emit(conn, result, snapshot, command)


def sweep(conn):
    ids = conn.execute(select(reservas.c.prestamo_id).where(
        reservas.c.estado == 'ACTIVA', reservas.c.vence_en <= datetime.now(timezone.utc))
        .order_by(reservas.c.vence_en).limit(50)).scalars().all()
    for loan_id in ids:
        expire(conn, loan_id)
