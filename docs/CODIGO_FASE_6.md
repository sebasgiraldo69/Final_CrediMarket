# Codigo de la fase 6

Copia de consulta de los archivos nuevos. Los originales son la fuente de verdad. Ver [guia](FASE_6.md) y [resultados](validacion-fase-6.md). La integracion de arranque esta en `shared/runtime.py`; los contratos se copian a las imagenes desde `infra/python/Dockerfile`.

## shared/messages.py

```python
"""Closed versioned event contracts. No financial or personal data."""
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from uuid import uuid4, UUID
from jsonschema import Draft202012Validator, FormatChecker
from .messaging_models import outbox

COMMANDS = 'credimarket.inventario.comandos.v1'
EVENTS = 'credimarket.inventario.eventos.v1'
COMMAND_TYPES = {'ReservaSolicitada', 'LiberacionSolicitada', 'EntregaSolicitada'}
RESULT_TYPES = {'InventarioReservado', 'InventarioInsuficiente', 'ReservaLiberada',
                'ReservaExpirada', 'EntregaConfirmada', 'EntregaRechazada', 'LiberacionRechazada'}


class PermanentMessageError(Exception):
    pass


@lru_cache
def validator(kind):
    name = 'dlq.schema.json' if kind == 'dlq' else f'schemas/{kind}.schema.json'
    schema = json.loads((Path('/app/contracts/events') / name).read_text(encoding='utf-8'))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate(body, topic, key):
    allowed = COMMAND_TYPES if topic == COMMANDS else RESULT_TYPES if topic == EVENTS else set()
    if not isinstance(body, dict) or body.get('type') not in allowed:
        raise PermanentMessageError('UNKNOWN_TYPE_OR_TOPIC')
    if not validator(body['type']).is_valid(body):
        raise PermanentMessageError('INVALID_SCHEMA')
    if key != body['prestamo_id']:
        raise PermanentMessageError('INVALID_PARTITION_KEY')
    return body


def digest(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def event(kind, prestamo_id, payload, correlation_id=None, causation_id=None):
    return {'event_id': str(uuid4()), 'type': kind, 'schema_version': 1,
            'occurred_at': datetime.now(timezone.utc).isoformat(),
            'correlation_id': correlation_id or str(uuid4()), 'causation_id': causation_id,
            'prestamo_id': str(prestamo_id), 'payload': payload}


def enqueue(conn, body, topic):
    validate(body, topic, body['prestamo_id'])
    conn.execute(outbox.insert().values(event_id=UUID(body['event_id']), topic=topic,
                 message_key=body['prestamo_id'], body=body))
```

## shared/messaging_models.py

```python
"""Messaging infrastructure tables; each service owns its own database."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

metadata = sa.MetaData()
outbox = sa.Table('outbox', metadata,
    sa.Column('sequence', sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column('event_id', UUID(as_uuid=True), nullable=False, unique=True),
    sa.Column('topic', sa.Text, nullable=False),
    sa.Column('message_key', sa.Text, nullable=False),
    sa.Column('body', JSONB, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True)),
)
inbox = sa.Table('inbox', metadata,
    sa.Column('event_id', UUID(as_uuid=True), primary_key=True),
    sa.Column('body_hash', sa.Text, nullable=False),
    sa.Column('body', JSONB, nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
)
failures = sa.Table('message_failures', metadata,
    sa.Column('topic', sa.Text, primary_key=True),
    sa.Column('partition', sa.Integer, primary_key=True),
    sa.Column('offset', sa.BigInteger, primary_key=True),
    sa.Column('attempts', sa.Integer, nullable=False),
    sa.Column('retry_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('terminal', sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column('envelope', JSONB),
)
sa.Index('ix_outbox_pending', outbox.c.sequence, postgresql_where=outbox.c.sent_at.is_(None))
```

## shared/messaging.py

```python
"""At-least-once Kafka delivery with a transactional inbox/outbox.

Offsets are acknowledged only after database commit. Retry state survives
restarts; a paused partition cannot overtake its failed record.
"""
import base64
from datetime import datetime, timezone, timedelta
import json
import logging
import os
import threading
from uuid import UUID, uuid4
from confluent_kafka import Consumer, Producer, TopicPartition
from sqlalchemy import select, text, func
from sqlalchemy.dialects.postgresql import insert
from .messages import COMMANDS, EVENTS, PermanentMessageError, validate, digest, validator
from .messaging_models import inbox, outbox, failures

log = logging.getLogger('messaging')
DELAYS = (5, 15, 60)


def kafka_config(service):
    return {'bootstrap.servers': os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092'),
            'security.protocol': 'SASL_PLAINTEXT', 'sasl.mechanism': 'PLAIN',
            'sasl.username': service, 'sasl.password': os.environ['KAFKA_PASSWORD'],
            'log_level': 0}


def record_filter(msg):
    return ((failures.c.topic == msg.topic()) &
            (failures.c.partition == msg.partition()) & (failures.c.offset == msg.offset()))


def bounded_transaction(conn):
    conn.execute(text("SET LOCAL lock_timeout = '3s'"))
    conn.execute(text("SET LOCAL statement_timeout = '5s'"))


def process(engine, service, handler, msg):
    """Return after durable success (including duplicates), or raise."""
    try:
        body = json.loads(msg.value())
        key = msg.key().decode('utf-8') if msg.key() else None
    except (ValueError, TypeError, UnicodeDecodeError):
        raise PermanentMessageError('INVALID_JSON_OR_KEY') from None
    validate(body, msg.topic(), key)
    identity = UUID(body['event_id'])
    with engine.begin() as conn:
        bounded_transaction(conn)
        # Serializes duplicates even when an operator republishes on another partition.
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:id, 0))'),
                     {'id': str(identity)})
        previous = conn.execute(select(inbox.c.body_hash).where(inbox.c.event_id == identity)).scalar()
        if previous:
            if previous != digest(body):
                raise PermanentMessageError('EVENT_ID_COLLISION')
            return
        handler(conn, body)
        conn.execute(inbox.insert().values(event_id=identity, body_hash=digest(body), body=body))
        log.info(json.dumps({'service': service, 'event_id': str(identity),
                            'correlation_id': body['correlation_id'], 'action': 'processed'}))


def record_failure(engine, service, msg, permanent=False, code='PROCESSING_ERROR'):
    """Failure + DLQ outbox commit atomically before advancing a poison offset."""
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        bounded_transaction(conn)
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:id, 0))'),
                     {'id': f'{msg.topic()}:{msg.partition()}:{msg.offset()}'})
        previous = conn.execute(select(failures).where(record_filter(msg)).with_for_update()).mappings().first()
        if previous and previous['terminal']:
            return
        attempts = (previous['attempts'] if previous else 0) + 1
        terminal = permanent or attempts >= 4
        values = dict(topic=msg.topic(), partition=msg.partition(), offset=msg.offset(),
                      attempts=attempts, terminal=terminal,
                      retry_at=now + timedelta(seconds=0 if terminal else DELAYS[attempts - 1]))
        if terminal:
            failure_id = uuid4()
            envelope = {'failure_id': str(failure_id), 'failed_at': now.isoformat(),
                'consumer_group': f'{service}-v1', 'original_topic': msg.topic(),
                'original_partition': msg.partition(), 'original_offset': msg.offset(),
                'original_key': msg.key().decode('utf-8', errors='replace') if msg.key() else None,
                'original_value_base64': base64.b64encode(msg.value() or b'').decode(),
                'event_id': None, 'attempts': attempts, 'error_code': code,
                'error_message': 'Mensaje rechazado; revisar contrato o dependencia antes de reenviar.'}
            try:
                envelope['event_id'] = str(UUID(json.loads(msg.value())['event_id']))
            except (ValueError, TypeError, KeyError):
                pass
            validator('dlq').validate(envelope)
            values['envelope'] = envelope
            conn.execute(outbox.insert().values(event_id=failure_id, topic=msg.topic() + '.dlq',
                message_key=envelope['original_key'] or str(failure_id), body=envelope))
        statement = insert(failures).values(**values)
        conn.execute(statement.on_conflict_do_update(
            index_elements=['topic', 'partition', 'offset'], set_=values))
    log.warning(json.dumps({'service': service, 'action': 'dlq' if terminal else 'retry',
                            'partition': msg.partition(), 'offset': msg.offset(), 'attempt': attempts,
                            'code': code}))


class Workers:
    def __init__(self, engine, service, handler, sweep=None):
        self.engine, self.service, self.handler, self.sweep = engine, service, handler, sweep
        self.stop = threading.Event()
        self.threads = []

    def start(self):
        for target in (self.publish_loop, self.consume_loop):
            thread = threading.Thread(target=target, daemon=True, name=f'{self.service}-{target.__name__}')
            self.threads.append(thread)
            thread.start()
        if self.sweep:
            thread = threading.Thread(target=self.sweep_loop, daemon=True, name='reservation-expiry')
            self.threads.append(thread)
            thread.start()

    def close(self):
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=15)

    def publish_loop(self):
        producer = Producer({**kafka_config(self.service), 'enable.idempotence': True,
                             'acks': 'all', 'message.timeout.ms': 5000,
                             'max.in.flight.requests.per.connection': 1})
        while not self.stop.is_set():
            try:
                with self.engine.begin() as conn:
                    bounded_transaction(conn)
                    # One publisher per service DB, preserving committed outbox sequence.
                    if not conn.execute(text('SELECT pg_try_advisory_xact_lock(610060)')).scalar():
                        self.stop.wait(.2)
                        continue
                    row = conn.execute(select(outbox).where(outbox.c.sent_at.is_(None))
                        .order_by(outbox.c.sequence).limit(1).with_for_update()).mappings().first()
                    if row:
                        delivered = []
                        producer.produce(row['topic'], key=row['message_key'],
                            value=json.dumps(row['body']).encode(),
                            on_delivery=lambda err, msg: delivered.append(err))
                        while not delivered:
                            producer.poll(.1)
                        if delivered[0] is not None:
                            raise RuntimeError('Broker delivery not acknowledged')
                        conn.execute(outbox.update().where(outbox.c.sequence == row['sequence'])
                                     .values(sent_at=func.now()))
                self.stop.wait(.1 if row else .5)
            except Exception as exc:
                log.warning(json.dumps({'service': self.service, 'action': 'outbox_pending',
                                        'error': type(exc).__name__}))
                self.stop.wait(2)
        producer.flush(6)

    def consume_loop(self):
        # Restart a failed consumer session; never advance offsets on an unknown failure.
        while not self.stop.is_set():
            try:
                self.consume_session()
            except Exception as exc:
                log.warning(json.dumps({'service': self.service, 'action': 'consumer_restart',
                                        'error': type(exc).__name__}))
                self.stop.wait(2)

    def consume_session(self):
        consumer = Consumer({**kafka_config(self.service), 'group.id': f'{self.service}-v1',
            'enable.auto.commit': False, 'enable.auto.offset.store': False,
            'auto.offset.reset': 'earliest', 'max.poll.interval.ms': 120000,
            'session.timeout.ms': 10000})
        pending = {}
        owned = set()

        def assigned(c, partitions):
            pending.clear()
            owned.clear()
            owned.update((p.topic, p.partition) for p in partitions)

        def revoked(c, partitions):
            pending.clear()
            owned.clear()

        topic = COMMANDS if self.service == 'inventario' else EVENTS
        consumer.subscribe([topic], on_assign=assigned, on_revoke=revoked, on_lost=revoked)
        try:
            while not self.stop.is_set():
                msg = consumer.poll(.1)  # Heartbeats/rebalances continue during retry delays.
                if msg and not msg.error():
                    key = (msg.topic(), msg.partition())
                    if key in owned:
                        if key in pending:
                            # A buffered delivery must not replace an earlier uncommitted record.
                            consumer.seek(TopicPartition(*key, pending[key].offset()))
                        else:
                            pending[key] = msg
                        consumer.pause([TopicPartition(*key)])
                for key, item in list(pending.items()):
                    with self.engine.connect() as conn:
                        state = conn.execute(select(failures).where(record_filter(item))).mappings().first()
                    if state and not state['terminal'] and state['retry_at'] > datetime.now(timezone.utc):
                        continue
                    if not state or not state['terminal']:
                        try:
                            process(self.engine, self.service, self.handler, item)
                        except PermanentMessageError as exc:
                            record_failure(self.engine, self.service, item, True, str(exc))
                            continue
                        except Exception:
                            record_failure(self.engine, self.service, item)
                            continue
                    consumer.commit(message=item, asynchronous=False)
                    pending.pop(key)
                    # seek prevents skipped buffered records when resuming.
                    consumer.seek(TopicPartition(*key, item.offset() + 1))
                    consumer.resume([TopicPartition(*key)])
        finally:
            consumer.close()

    def sweep_loop(self):
        while not self.stop.is_set():
            try:
                with self.engine.begin() as conn:
                    bounded_transaction(conn)
                    self.sweep(conn)
            except Exception as exc:
                log.warning(json.dumps({'action': 'expiry_retry', 'error': type(exc).__name__}))
            self.stop.wait(2)
```

## shared/messaging_cli.py

```python
"""Local operator tools. No public endpoint can publish arbitrary commands."""
import argparse
import json
import os
import sys
from uuid import UUID
from sqlalchemy import create_engine, select, func
from .runtime import database_url
from .messages import event, validate, enqueue, COMMANDS, EVENTS, digest, PermanentMessageError
from .messaging_models import outbox, inbox, failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('status')
    sub.add_parser('replay', help='Validate a JSON event from stdin without business effects')
    sub.add_parser('enqueue', help='Operator: publish a validated JSON event from stdin')
    sub.add_parser('requeue', help='Operator: retry same event from stdin after fixing its cause')
    reserve = sub.add_parser('reserve', help='Phase 6 integration command; NOT a loan approval')
    reserve.add_argument('--prestamo-id', required=True, type=UUID)
    reserve.add_argument('--producto-id', required=True, type=UUID)
    reserve.add_argument('--cantidad', type=int, default=1)
    args = parser.parse_args()
    engine = create_engine(database_url(), hide_parameters=True)
    service = os.environ['DB_NAME'].removesuffix('_db')
    if args.action == 'status':
        with engine.connect() as conn:
            report = {'service': service}
            for name, table, predicate in (
                ('outbox_pending', outbox, outbox.c.sent_at.is_(None)),
                ('inbox_processed', inbox, True),
                ('failures', failures, True)):
                report[name] = conn.execute(select(func.count()).select_from(table).where(predicate)).scalar()
            report['recent_failures'] = [dict(r) for r in conn.execute(
                select(failures).order_by(failures.c.retry_at.desc()).limit(20)).mappings()]
        print(json.dumps(report, default=str))
        return
    if args.action == 'reserve':
        if service != 'prestamos':
            parser.error('Los comandos se originan en Préstamos')
        body = event('ReservaSolicitada', args.prestamo_id,
                     {'producto_id': str(args.producto_id), 'cantidad': args.cantidad})
    else:
        body = json.load(sys.stdin)
    topic = COMMANDS if body.get('type') in ('ReservaSolicitada', 'EntregaSolicitada', 'LiberacionSolicitada') else EVENTS
    validate(body, topic, body.get('prestamo_id'))
    if args.action == 'replay':
        print(json.dumps({'valid': True, 'event_id': body['event_id'], 'business_effects': False}))
        return
    if (topic == COMMANDS) != (service == 'prestamos'):
        parser.error('Este servicio no es productor del topic solicitado')
    with engine.begin() as conn:
        old = conn.execute(select(outbox).where(outbox.c.event_id == body['event_id']).with_for_update()).mappings().first()
        if old:
            if digest(old['body']) != digest(body):
                raise PermanentMessageError('EVENT_ID_COLLISION')
            if args.action == 'requeue':
                conn.execute(outbox.update().where(outbox.c.event_id == body['event_id']).values(sent_at=None))
        else:
            enqueue(conn, body, topic)
    print(json.dumps({'event_id': body['event_id'], 'prestamo_id': body['prestamo_id'], 'queued': True}))


if __name__ == '__main__':
    main()
```

## services/inventario/app/messaging.py

```python
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
```

## services/prestamos/app/messaging.py

```python
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
```

## services/inventario/migrations/versions/0003_messaging.py

```python
"""Durable inbox, outbox and failure/retry state."""
from alembic import op
from shared.messaging_models import metadata

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind(), checkfirst=False)


def downgrade():
    metadata.drop_all(op.get_bind(), checkfirst=False)
```

## services/prestamos/migrations/versions/0002_messaging.py

```python
"""Messaging transport and inventory projection, no credit decisions."""
from alembic import op
from shared.messaging_models import metadata
from app.messaging import metadata as projection

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind(), checkfirst=False)
    projection.create_all(op.get_bind(), checkfirst=False)


def downgrade():
    projection.drop_all(op.get_bind(), checkfirst=False)
    metadata.drop_all(op.get_bind(), checkfirst=False)
```

## scripts/kafka_ops.py

```python
"""Operator-only inspection and DLQ replay. Uses each service's own credentials."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def docker(*args, stdin=None):
    result = subprocess.run(['docker', 'compose', *args], cwd=ROOT, input=stdin,
        text=True, encoding='utf-8', capture_output=True, timeout=60)
    if result.returncode:
        raise SystemExit('Operation failed: ' + result.stderr[-1000:])
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['status', 'lag', 'replay', 'requeue'])
    parser.add_argument('--service', choices=['prestamos', 'inventario'], default='inventario')
    parser.add_argument('--failure-id', type=str)
    parser.add_argument('--replacement', type=Path,
                        help='Corrected event JSON with a NEW event_id, if original bytes were invalid')
    args = parser.parse_args()
    if args.action == 'lag':
        print(docker('exec', '-T', 'kafka', '/opt/kafka/bin/kafka-consumer-groups.sh',
            '--bootstrap-server', 'kafka:9092', '--command-config', '/run/secrets/kafka_admin.properties',
            '--describe', '--group', args.service + '-v1'))
        return
    if args.action == 'status':
        print(docker('exec', '-T', args.service, 'python', '-m', 'shared.messaging_cli', 'status'))
        return
    if not args.failure_id:
        parser.error('--failure-id is required')
    from uuid import UUID
    failure_id = str(UUID(args.failure_id))
    source = '''
import json
from sqlalchemy import create_engine, select
from shared.runtime import database_url
from shared.messaging_models import failures
with create_engine(database_url()).connect() as c:
    body=c.execute(select(failures.c.envelope).where(failures.c.envelope['failure_id'].astext == FAILURE_ID)).scalar_one()
print(json.dumps(body))
'''.replace('FAILURE_ID', repr(failure_id))
    envelope = json.loads(docker('exec', '-T', args.service, 'python', '-', stdin=source))
    body = json.loads(args.replacement.read_text(encoding='utf-8')) if args.replacement else json.loads(
        base64.b64decode(envelope['original_value_base64']))
    if args.replacement and body['event_id'] == envelope['event_id']:
        parser.error('Corrections require a new event_id; retain correlation_id for traceability')
    owner = 'prestamos' if envelope['original_topic'].endswith('comandos.v1') else 'inventario'
    print(docker('exec', '-T', owner, 'python', '-m', 'shared.messaging_cli',
                 args.action, stdin=json.dumps(body)))


if __name__ == '__main__':
    main()
```

## scripts/check_phase6.py

```python
"""Real Kafka/DB integration checks. Synthetic records are retained.

--faults also restarts consumers and interrupts Kafka temporarily.
No volume deletion or resets. All fixtures use each service's own database.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = 'credimarket.inventario.comandos.v1'


def docker(*args, stdin=None):
    result = subprocess.run(['docker', 'compose', *args], cwd=ROOT, input=stdin,
        text=True, encoding='utf-8', capture_output=True, timeout=150)
    if result.returncode:
        raise RuntimeError(result.stderr[-1800:])
    return result.stdout.strip()


def inside(service, source):
    prefix = '''
import json
from uuid import UUID, uuid4
from sqlalchemy import create_engine, select, func, text
from shared.runtime import database_url
from shared.messaging_models import inbox, outbox, failures
engine = create_engine(database_url(), hide_parameters=True)
'''
    return docker('exec', '-T', service, 'python', '-', stdin=prefix + source)


def command(kind, loan, payload):
    return dict(event_id=str(uuid4()), type=kind, schema_version=1,
        occurred_at=datetime.now(timezone.utc).isoformat(), correlation_id=str(uuid4()),
        causation_id=None, prestamo_id=loan, payload=payload)


def send(body, direct=False, raw=None):
    if not direct:
        return docker('exec', '-T', 'prestamos', 'python', '-m', 'shared.messaging_cli',
                      'enqueue', stdin=json.dumps(body))
    return inside('prestamos', '''
from confluent_kafka import Producer
from shared.messaging import kafka_config
p=Producer({**kafka_config('prestamos'), 'enable.idempotence': True, 'acks': 'all'})
result=[]
p.produce(TOPIC, key=KEY, value=VALUE, on_delivery=lambda e,m: result.append(e))
assert p.flush(15)==0 and result == [None], 'No broker acknowledgement'
'''.replace('TOPIC', repr(COMMANDS)).replace('KEY', repr(body['prestamo_id']))
        .replace('VALUE', repr(raw if raw is not None else json.dumps(body))))


def snapshot(loan):
    return json.loads(inside('prestamos', '''
from app.messaging import snapshots
with engine.connect() as c:
    value=c.execute(select(snapshots.c.payload).where(snapshots.c.prestamo_id == LOAN)).scalar()
print(json.dumps(value))
'''.replace('LOAN', repr(loan))))


def wait_for(check, timeout=70):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(.5)
    raise AssertionError('Timed out waiting for durable result')


def state(loan, expected):
    def check():
        value = snapshot(loan)
        return value if value and value['estado_reserva'] == expected else None
    return wait_for(check)


def movement_count(loan, kind):
    return int(inside('inventario', '''
from app.models import movimientos
with engine.connect() as c:
    print(c.execute(select(func.count()).select_from(movimientos).where(
        movimientos.c.prestamo_id == LOAN, movimientos.c.tipo == KIND)).scalar())
'''.replace('LOAN', repr(loan)).replace('KIND', repr(kind))))


def failure_for(body):
    return json.loads(inside('inventario', '''
with engine.connect() as c:
    row=c.execute(select(failures.c.envelope).where(failures.c.envelope['event_id'].astext == EVENT)).scalar()
print(json.dumps(row))
'''.replace('EVENT', repr(body['event_id']))))


def run(faults):
    product = str(uuid4())
    inside('inventario', '''
from app.domain import agregar_stock
with engine.begin() as c:
    agregar_stock(c, UUID(PRODUCT), 10, 'Phase 6 integration fixture')
'''.replace('PRODUCT', repr(product)))
    loan = str(uuid4())
    reserve = command('ReservaSolicitada', loan, {'producto_id': product, 'cantidad': 1})
    send(reserve)
    active = state(loan, 'ACTIVA')
    send(reserve, direct=True)
    # A later command is a barrier on the same Kafka key/partition.
    release = command('LiberacionSolicitada', loan, {'motivo': 'CANCELACION_USUARIO'})
    send(release)
    state(loan, 'CANCELADA')
    send(release, direct=True)
    assert movement_count(loan, 'RESERVA') == movement_count(loan, 'LIBERACION') == 1
    print('PASS real Kafka round trip and duplicate command / stock effects', flush=True)

    # Cancellation before reservation cannot resurrect stock.
    cancelled = str(uuid4())
    send(command('LiberacionSolicitada', cancelled, {'motivo': 'CANCELACION_USUARIO'}))
    state(cancelled, 'CANCELADA')
    late = command('ReservaSolicitada', cancelled, {'producto_id': product, 'cantidad': 1})
    send(late)
    wait_for(lambda: processed('inventario', late['event_id']))
    assert snapshot(cancelled)['estado_reserva'] == 'CANCELADA'
    assert movement_count(cancelled, 'RESERVA') == 0

    delivery_loan = str(uuid4())
    send(command('ReservaSolicitada', delivery_loan, {'producto_id': product, 'cantidad': 1}))
    active = state(delivery_loan, 'ACTIVA')
    delivery = command('EntregaSolicitada', delivery_loan, {'reserva_id': active['reserva_id']})
    send(delivery)
    state(delivery_loan, 'ENTREGADA')
    send(delivery, direct=True)
    rejection = command('LiberacionSolicitada', delivery_loan, {'motivo': 'CANCELACION_USUARIO'})
    send(rejection)
    wait_for(lambda: processed('inventario', rejection['event_id']))
    assert movement_count(delivery_loan, 'SALIDA') == 1
    assert snapshot(delivery_loan)['estado_reserva'] == 'ENTREGADA'
    print('PASS pre-cancellation, delivery and terminal operation idempotency', flush=True)

    # Invalid message goes to durable DLQ; next record on the same partition succeeds.
    poison_loan = str(uuid4())
    poison = command('ReservaSolicitada', poison_loan, {'producto_id': product, 'cantidad': -1})
    send(poison, direct=True)
    envelope = wait_for(lambda: failure_for(poison))
    assert envelope['error_code'] == 'INVALID_SCHEMA' and envelope['attempts'] == 1
    valid = command('ReservaSolicitada', poison_loan, {'producto_id': product, 'cantidad': 1})
    send(valid)
    state(poison_loan, 'ACTIVA')
    wait_for(lambda: sent('inventario', envelope['failure_id']))
    # Reuse an ID with altered content must never silently execute another effect.
    altered = dict(valid, payload={'producto_id': product, 'cantidad': 2})
    send(altered, direct=True)
    collision = wait_for(lambda: failure_for(altered))
    assert collision['error_code'] == 'EVENT_ID_COLLISION'

    expiring = str(uuid4())
    send(command('ReservaSolicitada', expiring, {'producto_id': product, 'cantidad': 1}))
    state(expiring, 'ACTIVA')
    inside('inventario', '''
from app.models import reservas
with engine.begin() as c:
    c.execute(reservas.update().where(reservas.c.prestamo_id == LOAN)
        .values(vence_en=func.now() - text("interval '1 second'")))
'''.replace('LOAN', repr(expiring)))
    state(expiring, 'VENCIDA')
    assert movement_count(expiring, 'VENCIMIENTO') == 1
    print('PASS DLQ, continued partition processing, event collision and expiry event', flush=True)

    # Wrong delivery ID must not consume stock; no-stock is a business result, not DLQ.
    wrong = command('EntregaSolicitada', poison_loan, {'reserva_id': str(uuid4())})
    send(wrong)
    assert wait_for(lambda: failure_for(wrong))['error_code'] == 'RESERVATION_ID_MISMATCH'
    assert snapshot(poison_loan)['estado_reserva'] == 'ACTIVA'
    empty_loan = str(uuid4())
    send(command('ReservaSolicitada', empty_loan, {'producto_id': str(uuid4()), 'cantidad': 1}))
    state(empty_loan, 'SIN_STOCK')
    malformed_loan = str(uuid4())
    malformed = command('LiberacionSolicitada', malformed_loan, {'motivo': 'CANCELACION_USUARIO'})
    send(malformed, direct=True, raw='{broken-json')
    send(malformed)
    state(malformed_loan, 'CANCELADA')
    print('PASS mismatched reservation, insufficient stock and malformed JSON recovery', flush=True)

    # Exercise transaction rollback and persistent retry policy without runtime fault hooks.
    retry_fixture = inside('inventario', '''
from datetime import datetime, timezone
from shared.messaging import process, record_failure
from shared.messages import event, COMMANDS
body=event('LiberacionSolicitada', uuid4(), {'motivo': 'CANCELACION_USUARIO'})
class Message:
    def topic(self): return COMMANDS
    def partition(self): return 0
    def offset(self): return OFFSET
    def key(self): return body['prestamo_id'].encode()
    def value(self): return json.dumps(body).encode()
msg=Message()
def fail(c,b):
    from app.domain import liberar
    liberar(c, UUID(b['prestamo_id']))
    raise RuntimeError('Injected transaction failure')
for attempt, delay in enumerate([5,15,60,0], start=1):
    try: process(engine, 'inventario', fail, msg)
    except RuntimeError: pass
    else: raise AssertionError('Expected injected failure')
    record_failure(engine, 'inventario', msg)
    with engine.connect() as c:
        from app.models import reservas
        assert c.execute(select(reservas.c.id).where(reservas.c.prestamo_id == body['prestamo_id'])).first() is None
        row=c.execute(select(failures).where(failures.c.offset == msg.offset())).mappings().one()
        assert row['attempts']==attempt and row['terminal']==(attempt==4)
        remaining=(row['retry_at']-datetime.now(timezone.utc)).total_seconds()
        assert delay-3 <= remaining <= delay
print(json.dumps({'failure_id': row['envelope']['failure_id'], 'prestamo_id': body['prestamo_id']}))
'''.replace('OFFSET', str(8_000_000_000_000 + int(uuid4().hex[:10], 16))))
    print('PASS atomic rollback, persisted retry delays and retry exhaustion', flush=True)
    fixture = json.loads(retry_fixture)
    for action in ('replay', 'requeue'):
        check = subprocess.run([sys.executable, str(ROOT / 'scripts/kafka_ops.py'), action,
            '--service', 'inventario', '--failure-id', fixture['failure_id']],
            cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=60)
        assert check.returncode == 0, check.stderr
        if action == 'replay':
            assert json.loads(check.stdout)['business_effects'] is False
            assert snapshot(fixture['prestamo_id']) is None
    state(fixture['prestamo_id'], 'CANCELADA')
    print('PASS diagnostic replay without effects and operator DLQ requeue', flush=True)

    if faults:
        print('Testing consumer restart and broker outage; services restored in finally.', flush=True)
        restart_loan = str(uuid4())
        queued = command('ReservaSolicitada', restart_loan, {'producto_id': product, 'cantidad': 1})
        try:
            docker('stop', 'inventario')
            send(queued)
            wait_for(lambda: sent('prestamos', queued['event_id']))
        finally:
            docker('restart', '--no-deps', 'inventario')
        state(restart_loan, 'ACTIVA')
        docker('restart', '--no-deps', 'inventario')
        send(queued, direct=True)
        marker = command('LiberacionSolicitada', restart_loan, {'motivo': 'CANCELACION_USUARIO'})
        send(marker)
        state(restart_loan, 'CANCELADA')
        assert movement_count(restart_loan, 'RESERVA') == 1

        # Force a genuine transient lock timeout, then restart during its durable delay.
        retry_loan = str(uuid4())
        retry_command = command('ReservaSolicitada', retry_loan, {'producto_id': product, 'cantidad': 1})
        lock_source = '''
from sqlalchemy import create_engine, text
from shared.runtime import database_url
with create_engine(database_url(), hide_parameters=True).begin() as c:
    c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:id, 0))'), {'id': EVENT_ID})
    print('LOCKED', flush=True)
    c.execute(text('SELECT pg_sleep(20)'))
'''.replace('EVENT_ID', repr(retry_command['event_id']))
        blocker = subprocess.Popen(['docker', 'compose', 'exec', '-T', 'inventario', 'python', '-'],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8')
        try:
            blocker.stdin.write(lock_source)
            blocker.stdin.close()
            assert blocker.stdout.readline().strip() == 'LOCKED'
            send(retry_command)
            def retry_pending():
                return inside('inventario', '''
with engine.connect() as c:
    print(c.execute(select(func.count()).select_from(failures).where(
        failures.c.terminal == False, failures.c.retry_at > func.now())).scalar() > 0)
''') == 'True'
            wait_for(retry_pending, timeout=15)
            docker('restart', '--no-deps', 'inventario')
            state(retry_loan, 'ACTIVA')
            assert movement_count(retry_loan, 'RESERVA') == 1
        finally:
            blocker.wait(timeout=30)
            blocker.stdout.close()
            blocker.stderr.close()
        print('PASS real transient failure and restart during retry backoff', flush=True)

        offline_loan = str(uuid4())
        offline = command('ReservaSolicitada', offline_loan, {'producto_id': product, 'cantidad': 1})
        try:
            docker('stop', 'kafka')
            send(offline)
            assert not sent('prestamos', offline['event_id'])
            docker('restart', '--no-deps', 'prestamos')  # Outbox survives publisher restart.
        finally:
            docker('restart', '--no-deps', 'kafka')
        state(offline_loan, 'ACTIVA')
        print('PASS stopped/restarted consumer, broker outage and persistent publisher outbox', flush=True)
    print('Phase 6 checks completed. Synthetic fixtures retained; no credit approvals created.', flush=True)


def processed(service, identity):
    return inside(service, '''
with engine.connect() as c:
    print(bool(c.execute(select(inbox.c.event_id).where(inbox.c.event_id == ID)).first()))
'''.replace('ID', repr(identity))) == 'True'


def sent(service, identity):
    return inside(service, '''
with engine.connect() as c:
    print(c.execute(select(outbox.c.sent_at).where(outbox.c.event_id == ID)).scalar() is not None)
'''.replace('ID', repr(identity))) == 'True'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--faults', action='store_true')
    run(parser.parse_args().faults)
```
