"""Crash isolated real workers at commit boundaries. No production failure hooks."""
import json
import subprocess
from uuid import uuid4
from phase12_support import ROOT, PREFIX, docker, inside, fixtures, evidence, wait_for
from check_phase6 import command, send, state, movement_count


def crash_worker(service, source, expected):
    name = 'credimarket-ac12-' + uuid4().hex[:12]
    try:
        result = subprocess.run(['docker', 'compose', 'run', '--name', name, '--rm', '--no-deps', '-T',
            '--entrypoint', 'python', service, '-'], cwd=ROOT, input=PREFIX + source,
            text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=100)
    finally:
        # Only this test-owned ephemeral worker, never volumes or application services.
        subprocess.run(['docker', 'rm', '-f', name], cwd=ROOT, capture_output=True, timeout=30)
    assert result.returncode == expected, ('Worker did not reach crash checkpoint', result.stderr[-1000:])
    markers = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    assert markers and markers[-1]['checkpoint']
    return markers[-1]


def local_counts(service, identity, oneoff=False):
    return json.loads(inside(service, '''
from shared.messaging_models import inbox, outbox
with engine.connect() as c:
    processed=c.execute(select(func.count()).select_from(inbox).where(inbox.c.event_id == EVENT)).scalar()
    sent=c.execute(select(outbox.c.sent_at).where(outbox.c.event_id == EVENT)).scalar()
    pending=c.execute(select(func.count()).select_from(outbox).where(outbox.c.sent_at.is_(None))).scalar()
print(json.dumps({'inbox_count':processed,'event_sent':sent is not None,'pending_outbox':pending}))
'''.replace('EVENT', repr(identity)), oneoff=oneoff))


def main():
    fixture = fixtures(stock=10)
    report = {}
    # Crash after Kafka acknowledges the command, before publisher commits sent_at.
    loan = str(uuid4())
    message = command('ReservaSolicitada', loan, {'producto_id': fixture['product']['id'], 'cantidad': 1})
    try:
        docker('stop', 'prestamos')
        inside('prestamos', '''
from shared.messages import enqueue, COMMANDS
with engine.begin() as c: enqueue(c, BODY, COMMANDS)
'''.replace('BODY', repr(message)), oneoff=True)
        marker = crash_worker('prestamos', '''
import os
import shared.messaging as messaging
RealProducer=messaging.Producer
class CrashAfterAck:
    def __init__(self,config): self.inner=RealProducer(config)
    def __getattr__(self,name): return getattr(self.inner,name)
    def produce(self,*args,**kwargs):
        original=kwargs['on_delivery']
        body=json.loads(kwargs['value'])
        def delivered(error,msg):
            if error is None and body['event_id']==EVENT:
                print(json.dumps({'checkpoint':'broker_ack_before_sent_commit','event_id':EVENT}),flush=True)
                os._exit(82)
            original(error,msg)
        kwargs['on_delivery']=delivered
        self.inner.produce(*args,**kwargs)
messaging.Producer=CrashAfterAck
messaging.Workers(engine,'prestamos',None).publish_loop()
'''.replace('EVENT', repr(message['event_id'])), 82)
        counts = local_counts('prestamos', message['event_id'], oneoff=True)
        assert not counts['event_sent'] and counts['pending_outbox'] >= 1
        report['publisher'] = {**marker, 'pending_after_crash': True}
    finally:
        docker('restart', '--no-deps', 'prestamos')
    state(loan, 'ACTIVA')
    wait_for(lambda: local_counts('prestamos', message['event_id'])['event_sent'])
    assert movement_count(loan, 'RESERVA') == 1
    assert local_counts('inventario', message['event_id'])['inbox_count'] == 1
    print('PASS actual worker crash after broker ACK; outbox recovered; one stock effect', flush=True)

    # Crash after the inventory transaction commits, before the consumer commits offsets.
    loan = str(uuid4())
    message = command('ReservaSolicitada', loan, {'producto_id': fixture['product']['id'], 'cantidad': 1})
    try:
        docker('stop', 'inventario')
        send(message)
        marker = crash_worker('inventario', '''
import os
import shared.messaging as messaging
from app.messaging import handle
real_process=messaging.process
def crash_after_commit(engine,service,handler,msg):
    real_process(engine,service,handler,msg)
    if json.loads(msg.value())['event_id']==EVENT:
        print(json.dumps({'checkpoint':'db_commit_before_offset_commit','event_id':EVENT,
            'topic':msg.topic(),'partition':msg.partition(),'offset':msg.offset()}),flush=True)
        os._exit(83)
messaging.process=crash_after_commit
messaging.Workers(engine,'inventario',handle).consume_session()
'''.replace('EVENT', repr(message['event_id'])), 83)
        assert local_counts('inventario', message['event_id'], oneoff=True)['inbox_count'] == 1
        report['consumer'] = {**marker, 'inbox_durable_before_offset_ack': True}
    finally:
        docker('restart', '--no-deps', 'inventario')
    state(loan, 'ACTIVA')
    assert movement_count(loan, 'RESERVA') == 1
    assert local_counts('inventario', message['event_id'])['inbox_count'] == 1
    print('PASS actual consumer crash after DB commit; reassignment and inbox recovery', flush=True)

    # Duplicate business operation with a new event ID must also be idempotent.
    duplicate = command('ReservaSolicitada', loan, {'producto_id': fixture['product']['id'], 'cantidad': 1})
    send(duplicate)
    wait_for(lambda: local_counts('inventario', duplicate['event_id'])['inbox_count'] == 1)
    assert movement_count(loan, 'RESERVA') == 1
    report['new_event_same_operation'] = {'event_id': duplicate['event_id'], 'single_reservation': True}

    # Race delivery vs expiry in two DB transactions against fixture-owned stock.
    outcome = inside('inventario', '''
from concurrent.futures import ThreadPoolExecutor
from app.domain import reservar, entregar, vencer
from app.messaging import loan_lock
from app.models import reservas, existencias, movimientos
loan_id=uuid4()
with engine.begin() as c:
    reservar(c,loan_id,UUID(PRODUCT),1,ttl_seconds=-1)
def operation(name):
    try:
        with engine.begin() as c:
            loan_lock(c,loan_id)
            return (entregar if name=='deliver' else vencer)(c,loan_id)
    except ValueError: return 'expired_delivery_rejected'
with ThreadPoolExecutor(max_workers=2) as executor:
    list(executor.map(operation,['deliver','expire']))
with engine.begin() as c:
    loan_lock(c,loan_id)
    final=vencer(c,loan_id)
    assert final['estado_reserva']=='VENCIDA'
    outs=c.execute(select(func.count()).select_from(movimientos).where(movimientos.c.prestamo_id==loan_id,movimientos.c.tipo=='SALIDA')).scalar()
    expirations=c.execute(select(func.count()).select_from(movimientos).where(movimientos.c.prestamo_id==loan_id,movimientos.c.tipo=='VENCIMIENTO')).scalar()
    assert outs==0 and expirations==1
print(json.dumps({'terminal':'VENCIDA','physical_outputs':outs,'expiration_movements':expirations}))
'''.replace('PRODUCT', repr(fixture['product']['id'])))
    report['delivery_expiry_race'] = json.loads(outcome)
    evidence('crash_boundaries.json', report)
    print('PASS business duplicate with new event ID and delivery/expiry race', flush=True)


if __name__ == '__main__':
    main()
