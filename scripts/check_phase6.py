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
