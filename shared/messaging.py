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
            log.info(json.dumps({'service': self.service, 'action': 'partitions_assigned',
                'group': self.service+'-v1', 'partitions': [p.partition for p in partitions]}))

        def revoked(c, partitions):
            log.info(json.dumps({'service': self.service, 'action': 'partitions_revoked',
                'group': self.service+'-v1', 'partitions': [p.partition for p in partitions]}))
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
