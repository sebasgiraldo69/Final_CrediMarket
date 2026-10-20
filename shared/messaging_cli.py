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
