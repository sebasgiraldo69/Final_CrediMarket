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
