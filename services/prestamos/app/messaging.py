"""Phase 6 integration projection. This is NOT a credit approval workflow."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, insert
from shared.messages import PermanentMessageError

metadata = sa.MetaData()
snapshots = sa.Table('inventory_snapshots', metadata,
    sa.Column('prestamo_id', UUID(as_uuid=True), primary_key=True),
    sa.Column('revision', sa.Integer, nullable=False),
    sa.Column('payload', JSONB, nullable=False),
    sa.Column('event_id', UUID(as_uuid=True), nullable=False),
)


def handle(conn, message):
    payload = message['payload']
    # Serialize even the first result, when no row exists yet.
    conn.execute(sa.text('SELECT pg_advisory_xact_lock(hashtextextended(:id, 1))'),
                 {'id': message['prestamo_id']})
    old = conn.execute(sa.select(snapshots).where(
        snapshots.c.prestamo_id == message['prestamo_id'])).mappings().first()
    if old and old['revision'] >= payload['revision_reserva']:
        if old['revision'] == payload['revision_reserva']:
            keys = ('reserva_id', 'estado_reserva', 'revision_reserva', 'vence_en')
            if any(old['payload'][k] != payload[k] for k in keys):
                raise PermanentMessageError('CONFLICTING_RESERVATION_REVISION')
        return  # An old result cannot overwrite a newer snapshot.
    stmt = insert(snapshots).values(prestamo_id=message['prestamo_id'],
        revision=payload['revision_reserva'], payload=payload, event_id=message['event_id'])
    conn.execute(stmt.on_conflict_do_update(index_elements=['prestamo_id'],
        set_={'revision': stmt.excluded.revision, 'payload': stmt.excluded.payload,
              'event_id': stmt.excluded.event_id}))
