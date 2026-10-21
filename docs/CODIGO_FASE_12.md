# Codigo de fase 12

Copia de consulta de los archivos nuevos. Ver [guia](FASE_12.md) y [resultados](validacion-fase-12.md). La correccion de DNS/reintentos esta en `services/productos/app/cache.py`; los encabezados diagnosticos en Productos y los logs de particiones en `shared/messaging.py`.

## scripts/check_phase12.py

```python
"""Run acceptance suites sequentially and retain dated evidence. Creates fixtures.

Fault suites temporarily interrupt services. No volume deletion or resets.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
TASKS = {
    'contracts': ('validate_contracts.py', [], []),
    'infrastructure': ('check_infrastructure.py', [], []),
    'clientes': ('check_phase3.py', [], ['AC12', 'AC13', 'AC16']),
    'productos': ('check_phase4.py', [], ['AC08', 'AC09']),
    'inventario': ('check_phase5.py', [], ['AC04', 'AC05', 'AC07']),
    'datos': ('check_phase7.py', [], []),
    'modelo': ('check_phase8.py', [], ['AC10', 'AC16']),
    'prestamos': ('check_phase9.py', [], ['AC01', 'AC02', 'AC03', 'AC04', 'AC05', 'AC07', 'AC09', 'AC13']),
    'frontend': ('check_phase10.py', [], ['AC14', 'AC16']),
    'mlops': ('check_phase11.py', [], ['AC11']),
    'kafka': ('check_phase6.py', ['--faults'], ['AC05', 'AC06']),
    'faults': ('check_phase12_faults.py', [], ['AC05', 'AC06', 'AC07']),
    'redis': ('measure_phase12.py', [], ['AC08']),
    'pending_ui': ('check_phase12_pending.py', [], ['AC15', 'AC16']),
    'final': ('check_infrastructure.py', [], []),
}


def write_json(path, body):
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', nargs='+', choices=list(TASKS))
    parser.add_argument('--resume', type=Path, help='Continue an evidence directory without repeating passed suites')
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    run_id = now.strftime('%Y%m%dT%H%M%S') + '-' + os.urandom(3).hex()
    output = (ROOT / args.resume).resolve() if args.resume else ROOT / 'docs/evidencias' / ('fase12-' + run_id)
    if not output.resolve().is_relative_to((ROOT / 'docs/evidencias').resolve()):
        parser.error('Evidence directory must stay inside docs/evidencias')
    output.mkdir(parents=True, exist_ok=bool(args.resume))
    child_env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1',
        CREDIMARKET_EVIDENCE_DIR=str(output), PLAYWRIGHT_BROWSERS_PATH=str(ROOT / '.local/pw-browsers'))
    child_env['PYTHONPATH'] = os.pathsep.join([str(ROOT / '.local/e2e'), str(ROOT), child_env.get('PYTHONPATH', '')])
    ledger = {'run_id': run_id, 'started_at': now.isoformat(),
        'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'fixtures_retained': True, 'results': {}}
    if args.resume:
        ledger = json.loads((output / 'results.json').read_text(encoding='utf-8'))
    selected = args.only or [name for name in TASKS if ledger['results'].get(name, {}).get('status') != 'PASS']

    def save():
        matrix = {}
        for number in range(1, 17):
            case = f'AC{number:02d}'
            required = [name for name, (_, _, cases) in TASKS.items() if case in cases]
            states = [ledger['results'].get(name, {}).get('status', 'NOT_RUN') for name in required]
            matrix[case] = {'status': 'PASS' if states and all(x == 'PASS' for x in states) else
                'FAIL' if 'FAIL' in states else 'NOT_RUN', 'required_suites': required}
        ledger['acceptance'] = matrix
        write_json(output / 'results.json', ledger)
        write_json(ROOT / 'docs/evidencias/phase12_latest.json', {'directory': output.relative_to(ROOT).as_posix(), **ledger})
    save()
    print('Evidence directory: ' + str(output.relative_to(ROOT)), flush=True)
    for name in selected:
        filename, extra, cases = TASKS[name]
        previous = ledger['results'].get(name)
        if previous and (output / (name + '.log')).exists():
            attempt = previous.get('attempt', 1)
            archived = f'{name}.attempt-{attempt}.log'
            (output / archived).write_bytes((output / (name + '.log')).read_bytes())
            ledger.setdefault('previous_attempts', []).append({**previous, 'suite': name, 'log': archived})
        else:
            attempt = 0
        source_hash = hashlib.sha256((ROOT / 'scripts' / filename).read_bytes()).hexdigest() if (ROOT / 'scripts' / filename).exists() else None
        command = [sys.executable, str(ROOT / 'scripts' / filename), *extra]
        print('START ' + name, flush=True)
        began = time.monotonic()
        try:
            result = subprocess.run(command, cwd=ROOT, env=child_env, text=True,
                encoding='utf-8', errors='replace', stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, timeout=1200)
            code, log = result.returncode, result.stdout
        except subprocess.TimeoutExpired as exc:
            code, log = -1, 'TIMEOUT\n' + str(exc.stdout or '')
        # Redact bearer credentials if a failing fixture happened to print one.
        log = re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[REDACTED_JWT]', log)
        (output / (name + '.log')).write_text(log, encoding='utf-8')
        ledger['results'][name] = {'status': 'PASS' if code == 0 else 'FAIL', 'exit_code': code,
            'duration_seconds': round(time.monotonic() - began, 2), 'cases': cases,
            'source_sha256': source_hash, 'attempt': attempt + 1,
            'log': name + '.log'}
        save()
        print(ledger['results'][name]['status'] + ' ' + name, flush=True)
        if code:
            print(log[-2200:], flush=True)
    ledger['finished_at'] = datetime.now(timezone.utc).isoformat()
    ledger['all_suites_passed'] = all(ledger['results'].get(name, {}).get('status') == 'PASS' for name in TASKS)
    save()
    print('Completed. All suites passed: ' + str(ledger['all_suites_passed']), flush=True)
    raise SystemExit(0 if all(item['status'] == 'PASS' for item in ledger['results'].values()) else 1)


if __name__ == '__main__':
    main()
```

## scripts/phase12_support.py

```python
"""Local acceptance fixtures and operator helpers; credentials are never printed."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import urllib.request
import urllib.error
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
ENV = dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines()
           if '=' in line and not line.startswith('#'))
BASE = f"http://127.0.0.1:{ENV.get('FRONTEND_PORT', '8080')}"


def evidence(name, value):
    folder = Path(os.getenv('CREDIMARKET_EVIDENCE_DIR', ROOT / '.local/phase12-manual'))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    return folder


def docker(*args, stdin=None, timeout=120):
    result = subprocess.run(['docker', 'compose', *args], cwd=ROOT, input=stdin,
        text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Docker operation failed: ' + ' '.join(args[:4]) + '\n' + result.stderr[-1200:])
    return result.stdout.strip()


PREFIX = '''
import json
from uuid import UUID, uuid4
from sqlalchemy import create_engine, select, text, func
from shared.runtime import database_url
engine = create_engine(database_url(), hide_parameters=True)
'''


def inside(service, source, oneoff=False):
    args = ('run', '--rm', '--no-deps', '-T', '--entrypoint', 'python', service, '-') if oneoff else (
        'exec', '-T', service, 'python', '-')
    return docker(*args, stdin=PREFIX + source)


def api(path, method='GET', body=None, token=None, key=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if key:
        headers['Idempotency-Key'] = key
    request = urllib.request.Request(BASE + '/api/' + path, method=method,
        data=json.dumps(body).encode() if body is not None else None, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=20)
    except urllib.error.HTTPError as exc:
        response = exc
    data = response.read()
    return response.status, json.loads(data) if data else {}


def wait_for(check, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(.4)
    raise AssertionError('Timed out waiting for acceptance condition')


def fixtures(stock=10):
    tag = uuid4().hex[:10]
    password = secrets.token_urlsafe(20)
    account, profile, admin_id = str(uuid4()), str(uuid4()), str(uuid4())
    emails = {'client': f'ac12-client-{tag}@example.com', 'admin': f'ac12-admin-{tag}@example.com'}
    source = '''
from app.models import clientes, usuarios
from app.security import hasher, issue_token
with engine.begin() as c:
    c.execute(clientes.insert().values(id=UUID(PROFILE), nombre='Aceptacion '+TAG, email=CLIENT_EMAIL,
        finanzas={'ingresos_mensuales_cop': '6500000.00', 'obligaciones_mensuales_cop': '800000.00',
        'tipo_empleo':'dependiente','antiguedad_laboral_meses':36,'meses_historial_crediticio':48,
        'creditos_previos':2,'atrasos_previos_30d':0,'porcentaje_pago_puntual':98.5}))
    c.execute(usuarios.insert().values(id=UUID(ACCOUNT), cliente_id=UUID(PROFILE), email=CLIENT_EMAIL,
        password_hash=hasher.hash(PASSWORD), rol='cliente'))
    c.execute(usuarios.insert().values(id=UUID(ADMIN), email=ADMIN_EMAIL,
        password_hash=hasher.hash(PASSWORD), rol='administrador'))
print(json.dumps({'client':issue_token(ACCOUNT,role='cliente',cliente_id=PROFILE),
                  'admin':issue_token(ADMIN,role='administrador')}))
'''
    for key, value in {'PROFILE': profile, 'ACCOUNT': account, 'ADMIN_EMAIL': emails['admin'],
        'ADMIN': admin_id, 'CLIENT_EMAIL': emails['client'], 'PASSWORD': password, 'TAG': tag}.items():
        source = source.replace(key, repr(value))
    tokens = json.loads(inside('clientes', source))
    status, product = api('productos/productos', 'POST', {'nombre': 'Aceptacion '+tag,
        'categoria': 'Portátiles', 'precio_cop': '2500000.00'}, tokens['admin'])
    assert status == 201
    if stock:
        status, _ = api('inventario/inventario/entradas', 'POST', {'producto_id': product['id'],
            'cantidad': stock, 'motivo': 'Fixture fase 12'}, tokens['admin'], str(uuid4()))
        assert status == 201
    return {'tag': tag, 'tokens': tokens, 'emails': emails, 'password': password,
            'profile': profile, 'product': product}
```

## scripts/check_phase12_faults.py

```python
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
```

## scripts/check_phase12_pending.py

```python
"""AC15: pending UI with real consumer interruption; AC16 invalid form and expired JWT."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from phase12_support import BASE, fixtures, docker, inside, evidence, wait_for, api


def main():
    fixture = fixtures()
    folder = evidence('pending_ui.json', {'status': 'STARTED'})
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(BASE + '/acceso')
            requests = []
            page.on('request', lambda r: requests.append(r.url) if r.method == 'POST' else None)
            page.get_by_role('button', name='Ingresar', exact=True).click()
            assert page.locator('input:invalid').count() > 0
            assert not requests, 'Invalid form submitted a request'
            page.get_by_label('Correo').fill(fixture['emails']['client'])
            page.get_by_label('Contraseña').fill(fixture['password'])
            page.get_by_role('button', name='Ingresar', exact=True).click()
            expect(page.get_by_role('button', name='Cerrar sesión')).to_be_visible()
            try:
                docker('stop', 'inventario')
                page.get_by_role('navigation').get_by_role('link', name='Catálogo', exact=True).click()
                page.get_by_label('Buscar').fill(fixture['product']['nombre'])
                page.get_by_role('button', name='Solicitar a crédito').click()
                dialog = page.get_by_role('dialog')
                dialog.get_by_label('Plazo').select_option('24')
                dialog.get_by_role('button', name='Enviar solicitud').click()
                expect(dialog.get_by_role('heading', name='Resultado de la solicitud')).to_be_visible()
                dialog.get_by_role('button', name='Ver mis solicitudes').click()
                row = page.locator('tbody tr', has_text=fixture['product']['nombre']).first
                expect(row.locator('.state-pill')).to_have_text('Reservando producto', timeout=15000)
                page.screenshot(path=str(folder / 'AC15-pending.png'), full_page=True)
                # Observe two poll intervals: no fabricated approval while Inventory is down.
                page.wait_for_timeout(4500)
                expect(row.locator('.state-pill')).to_have_text('Reservando producto')
            finally:
                docker('restart', '--no-deps', 'inventario')
            expect(row.locator('.state-pill')).to_have_text('Aprobada', timeout=90000)
            page.screenshot(path=str(folder / 'AC15-recovered.png'), full_page=True)
            try:
                docker('stop', 'productos')
                page.goto(BASE + '/catalogo')
                expect(page.get_by_role('alert')).to_contain_text('no responde', timeout=15000)
                page.screenshot(path=str(folder / 'AC16-api-down.png'), full_page=True)
            finally:
                docker('restart', '--no-deps', 'productos')
            def products_ready():
                try:
                    return api('productos/health')[0] == 200
                except (OSError, ValueError):
                    return False
            wait_for(products_ready)
            page.get_by_role('button', name='Actualizar', exact=True).click()
            expect(page.get_by_role('button', name='Solicitar a crédito').first).to_be_visible(timeout=30000)
            expired = inside('clientes', '''
import time, jwt
from app.security import private_key
token=TOKEN
claims=jwt.decode(token,options={'verify_signature':False})
claims['iat']=int(time.time())-3600; claims['exp']=int(time.time())-60
print(jwt.encode(claims,private_key(),algorithm='RS256'))
'''.replace('TOKEN', repr(fixture['tokens']['client'])))
            page.evaluate('''token => {const s=JSON.parse(sessionStorage.getItem('credimarket.session'));
                s.access_token=token; sessionStorage.setItem('credimarket.session',JSON.stringify(s));}''', expired)
            page.goto(BASE + '/solicitudes')
            expect(page.get_by_text('Tu sesión venció')).to_be_visible()
            expect(page.get_by_label('Contraseña')).to_be_visible()
            evidence('pending_ui.json', {'status': 'PASS', 'real_consumer_interruption': True,
                'pending_observed': True, 'approved_by_polling_after_restart': True,
                'invalid_form_did_not_submit': True, 'genuinely_expired_jwt': True,
                'real_productos_api_outage_recovered': True,
                'product_id': fixture['product']['id']})
        finally:
            browser.close()
    print('PASS AC15 real pending/recovery UI and AC16 invalid form/expired session', flush=True)


if __name__ == '__main__':
    main()
```

## scripts/measure_phase12.py

```python
"""Controlled local cache microbenchmark and Docker resource samples (not a capacity test)."""
from datetime import datetime, timezone
import json
import subprocess
import threading
import time
from phase12_support import ROOT, api, docker, inside, fixtures, evidence, wait_for


def main():
    fixture = fixtures()
    product = fixture['product']['id']
    token = fixture['tokens']['admin']
    resource_samples = []
    stop = threading.Event()

    def resources():
        while not stop.is_set():
            result = subprocess.run(['docker', 'stats', '--no-stream', '--format', '{{json .}}'],
                cwd=ROOT, text=True, capture_output=True, timeout=30)
            if result.returncode == 0:
                resource_samples.append({'at': datetime.now(timezone.utc).isoformat(),
                    'containers': [json.loads(line) for line in result.stdout.splitlines() if line.strip()]})
            stop.wait(2)

    thread = threading.Thread(target=resources, daemon=True)
    thread.start()
    source = '''
import time, urllib.request
from app.cache import get_redis_client
mode=MODE
url='http://127.0.0.1:8000/productos/'+PRODUCT
token=TOKEN
times=[]; cache_counts={}
cache=get_redis_client() if mode!='offline' else None
if mode=='warm':
    with urllib.request.urlopen(urllib.request.Request(url,headers={'Authorization':'Bearer '+token})) as r: r.read()
for index in range(60):
    if mode=='cold': cache.delete('producto:'+PRODUCT)
    began=time.perf_counter()
    with urllib.request.urlopen(urllib.request.Request(url,headers={'Authorization':'Bearer '+token})) as r:
        body=json.loads(r.read()); outcome=r.headers['X-Cache']
    times.append((time.perf_counter()-began)*1000)
    assert body['id']==PRODUCT
    cache_counts[outcome]=cache_counts.get(outcome,0)+1
values=sorted(times)
def percentile(p):
    x=(len(values)-1)*p; lo=int(x)
    return round(values[lo]+(values[min(lo+1,len(values)-1)]-values[lo])*(x-lo),3)
print(json.dumps({'samples':len(times),'p50_ms':percentile(.5),'p95_ms':percentile(.95),
    'cache_outcomes':cache_counts,'hit_rate':cache_counts.get('HIT',0)/len(times),
    'measurement':'HTTP loopback inside Productos; preparation excluded; serial identical product requests'}))
'''.replace('PRODUCT', repr(product)).replace('TOKEN', repr(token))

    def bench(mode):
        return json.loads(inside('productos', source.replace('MODE', repr(mode))))

    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'product_id': product,
        'limits': 'Local sequential diagnostic workload (60 requests per mode); not production SLA or maximum capacity'}
    try:
        report['initial_dns_bound'] = json.loads(inside('productos', '''
import time
from unittest.mock import patch
from app import cache
def slow_dns(host):
    time.sleep(2)
    raise OSError('simulated DNS outage')
with patch.object(cache.socket,'gethostbyname',slow_dns):
    began=time.perf_counter()
    try: cache.redis_address()
    except cache.RedisError: pass
    else: raise AssertionError('Expected unavailable DNS')
    elapsed=time.perf_counter()-began
    assert elapsed < .5
    print(json.dumps({'simulated_blocked_dns':True,'caller_wait_seconds':round(elapsed,3)}))
'''))
        report['cold'] = bench('cold')
        report['warm'] = bench('warm')
        assert report['cold']['cache_outcomes'] == {'MISS': 60}
        assert report['warm']['cache_outcomes'] == {'HIT': 60}
        ttl = json.loads(inside('productos', '''
import time
from app.cache import get_redis_client
with get_redis_client() as cache:
    key='producto:'+PRODUCT
    initial=cache.ttl(key)
    assert 0 < initial <= 60
    began=time.monotonic()
    while cache.exists(key):
        assert time.monotonic()-began < 66
        time.sleep(.2)
    print(json.dumps({'initial_ttl_seconds': initial, 'observed_wait_seconds': round(time.monotonic()-began,2),
                     'expired_without_forcing_ttl': True}))
'''.replace('PRODUCT', repr(product))))
        report['expiration'] = ttl
        status, _ = api('productos/productos/'+product, token=token)
        assert status == 200
        status, updated = api('productos/productos/'+product, 'PATCH',
            {'version_esperada': 1, 'precio_cop': '2600000.00'}, token)
        assert status == 200 and updated['version'] == 2
        exists = inside('productos', "from app.cache import get_redis_client; print(get_redis_client().exists('producto:'+"+repr(product)+"))")
        assert exists == '0'
        status, fresh = api('productos/productos/'+product, token=token)
        assert status == 200 and fresh['precio_cop'] == '2600000.00'
        report['invalidation'] = {'key_removed_after_update': True, 'new_price_read': True}
        try:
            docker('stop', 'redis')
            status, changed = api('productos/productos/'+product, 'PATCH',
                {'version_esperada': 2, 'precio_cop': '2700000.00'}, token)
            assert status == 200 and changed['version'] == 3
            pending = inside('productos', '''
from app.models import invalidaciones_cache
with engine.connect() as c:
    print(c.execute(select(func.count()).select_from(invalidaciones_cache).where(
        invalidaciones_cache.c.producto_id == PRODUCT, invalidaciones_cache.c.procesado == False)).scalar())
'''.replace('PRODUCT', repr(product)))
            assert int(pending) >= 1
            report['invalidation_during_outage'] = {'write_committed': True, 'pending_record_durable': True}
            report['fallback'] = bench('offline')
            assert report['fallback']['cache_outcomes'] == {'BYPASS': 60}
            assert report['fallback']['p95_ms'] < 2000, 'Unexpected hidden retry/backoff during cache outage'
            status, ready = api('productos/ready')
            assert status == 200 and ready['dependencies']['redis'] == 'degraded'
        finally:
            docker('restart', '--no-deps', 'redis')
        wait_for(lambda: api('productos/ready')[1]['dependencies']['redis'] == 'ok')
        status, recovered = api('productos/productos/'+product, token=token)
        assert status == 200 and recovered['precio_cop'] == '2700000.00'
        report['p50_warm_to_cold_ratio'] = report['warm']['p50_ms'] / report['cold']['p50_ms']
        evidence('redis_metrics.json', report)
        print(json.dumps(report), flush=True)
    finally:
        stop.set()
        thread.join(timeout=35)
        info = subprocess.run(['docker', 'info', '--format',
            '{"cpus":{{.NCPU}},"memory_bytes":{{.MemTotal}},"server_version":"{{.ServerVersion}}"}'],
            cwd=ROOT, text=True, capture_output=True, timeout=20)
        assert resource_samples and info.returncode == 0, 'Docker resource samples missing'
        peaks = {}
        for sample in resource_samples:
            for container in sample['containers']:
                name = container.get('Name', container.get('Container'))
                row = peaks.setdefault(name, {'max_observed_cpu_percent': 0, 'max_observed_memory_percent': 0})
                row['max_observed_cpu_percent'] = max(row['max_observed_cpu_percent'], float(container['CPUPerc'].rstrip('%')))
                row['max_observed_memory_percent'] = max(row['max_observed_memory_percent'], float(container['MemPerc'].rstrip('%')))
        evidence('resources.json', {'docker_vm': json.loads(info.stdout), 'sample_count': len(resource_samples),
            'sampled_peaks': peaks,
            'samples': resource_samples, 'scope': 'Docker VM allocation and samples during this microbenchmark; not physical host totals'})
    print('PASS measured hit/miss, actual TTL expiration, invalidation, fallback and resource samples', flush=True)


if __name__ == '__main__':
    main()
```

## scripts/report_phase12.py

```python
"""Render the acceptance report only from a fully passed evidence ledger."""
import json
from pathlib import Path
import shutil
import hashlib
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    latest = json.loads((ROOT / 'docs/evidencias/phase12_latest.json').read_text(encoding='utf-8'))
    assert latest.get('all_suites_passed'), 'Acceptance is incomplete; retain FAIL/NOT_RUN statuses'
    assert all(row['status'] == 'PASS' for row in latest['acceptance'].values())
    folder = ROOT / latest['directory'].replace('\\', '/')
    redis = json.loads((folder / 'redis_metrics.json').read_text(encoding='utf-8'))
    resources = json.loads((folder / 'resources.json').read_text(encoding='utf-8'))
    base = folder.relative_to(ROOT / 'docs').as_posix()
    sources = subprocess.check_output(['rg', '--files', 'services', 'shared', 'scripts', 'ml/src',
        'frontend/src', 'infra', 'contracts'], cwd=ROOT, text=True).splitlines()
    sources += ['compose.yaml', 'requirements-acceptance.txt', 'requirements-contracts.txt',
        'requirements-e2e.txt', 'models/active_model.json', 'models/riesgo-v1/manifest.json',
        'models/riesgo-v1/pipeline.joblib', 'models/riesgo-v2/manifest.json', 'models/riesgo-v2/pipeline.joblib',
        'prestamos_entrenamiento.csv', 'solicitudes_nuevas.csv']
    hashes = {name.replace('\\','/'): hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
              for name in sources}
    (folder / 'workspace_hashes.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
    for source in ['ml/reports/phase11_validation.json', 'ml/manifests/mlflow_reproduction.json']:
        shutil.copyfile(ROOT / source, folder / Path(source).name)
    lines = ['# Verificación de fase 12', '',
        'Estado: **16 casos de aceptación aprobados** y todas las suites requeridas terminadas con código 0.', '',
        f"Ejecución: `{latest['run_id']}`. Finalizada: `{latest['finished_at']}`. Commit base: `{latest['commit']}`.", '',
        'Se probó el código de trabajo del repositorio, incluidas las correcciones locales; los logs conservan el hash del script ejecutado. Los datos sintéticos se conservan y los servicios se restauraron.', '',
        f'[Resultados estructurados]({base}/results.json) y [huellas del código, contratos, modelos y fuentes al cierre]({base}/workspace_hashes.json). Cada caso exige todas las suites enlazadas:', '',
        '| Caso | Resultado | Evidencia |', '|---|---|---|']
    for case, value in latest['acceptance'].items():
        links = ', '.join(f'[{name}]({base}/{name}.log)' for name in value['required_suites'])
        lines.append(f"| {case} | {value['status']} | {links} |")
    lines += ['', '## Redis: medición observada', '',
        '60 consultas HTTP secuenciales por escenario, por loopback dentro de Productos. La preparación de caché se excluye del tiempo. Los encabezados X-Cache identifican el origen.', '',
        '| Escenario | p50 (ms) | p95 (ms) | HIT | MISS | BYPASS |', '|---|---:|---:|---:|---:|---:|']
    for key, label in [('cold','Miss forzado'),('warm','Caché caliente'),('fallback','Redis detenido')]:
        row = redis[key]
        outcomes = row['cache_outcomes']
        lines.append(f"| {label} | {row['p50_ms']} | {row['p95_ms']} | {outcomes.get('HIT',0)} | {outcomes.get('MISS',0)} | {outcomes.get('BYPASS',0)} |")
    lines += ['', f"TTL inicial observado: {redis['expiration']['initial_ttl_seconds']} s; espera hasta expiración: {redis['expiration']['observed_wait_seconds']} s, sin forzar ni reducir TTL.", '',
        'En esta carga local pequeña la caché caliente no resultó más rápida que el miss. No se demuestra una mejora de latencia con este ensayo; no se oculta ese resultado ni se extrapola a otras cargas.', '',
        'Se verificaron invalidación al editar precio, escritura con Redis detenido y registro durable de invalidación pendiente. Tras recuperarlo se leyó el precio nuevo.', '',
        f'[Mediciones completas]({base}/redis_metrics.json). No se extrapolan a capacidad máxima, concurrencia de producción ni SLA.', '',
        '## Recursos del entorno', '',
        f"VM Docker: {resources['docker_vm']['cpus']} CPU, {resources['docker_vm']['memory_bytes']} bytes de memoria asignada, Docker {resources['docker_vm']['server_version']}. Muestras: {resources['sample_count']}.", '',
        '| Contenedor | Máximo CPU observado (%) | Máximo memoria observado (%) |', '|---|---:|---:|']
    for name, row in sorted(resources['sampled_peaks'].items()):
        lines.append(f"| {name} | {row['max_observed_cpu_percent']} | {row['max_observed_memory_percent']} |")
    lines += ['', f'[Muestras originales]({base}/resources.json). Son máximos de muestras durante el microbenchmark, no máximos continuos ni memoria física total del equipo.', '',
        '## Fallos y navegador', '',
        f'[Caídas en fronteras de commit]({base}/crash_boundaries.json): trabajadores aislados terminaron después del ACK de Kafka y antes de confirmar outbox, y después del commit de Inventario y antes de confirmar offset. Se comprobó recuperación y un solo movimiento de reserva.', '',
        f'[Pendiente y recuperación reales]({base}/pending_ui.json): Inventario detenido, aprobación por polling al recuperarlo, formulario inválido sin envío, JWT vencido y Productos realmente detenido.', '',
        f'![Solicitud pendiente]({base}/AC15-pending.png)', '',
        f'![Solicitud recuperada]({base}/AC15-recovered.png)', '',
        f'![Error por API detenida]({base}/AC16-api-down.png)', '',
        '## Correcciones y procedencia de MLflow', '',
        'Se detectó que el volumen local de MLflow no contenía las ejecuciones v1 incorporadas por Git en otro equipo. Se reprodujeron los siete modelos sobre train/validación y se verificó coincidencia con el reporte original. El conjunto test no se reevaluó; sus métricas se importaron con procedencia explícita y prefijo imported_test_.', '',
        f'[Mapa de ejecuciones originales a reproducciones locales]({base}/mlflow_reproduction.json). Se mantuvieron el artefacto, run de origen y evaluación histórica de los préstamos.', '',
        'Se añadieron X-Cache para medir HIT/MISS/BYPASS y logs de asignación/revocación de particiones. No se agregaron interruptores de fallo a producción.', '',
        'El primer ensayo Redis detectó bloqueo por DNS; el segundo confirmó esperas adicionales por los tres reintentos internos del cliente. Se corrigieron resolución asíncrona y política de cero reintentos para la caché opcional. Se repitieron Productos y Redis antes del cierre; los intentos fallidos se conservan como logs de intentos en la misma carpeta.', '',
        '## Límites', '',
        'Kafka es un broker único sin alta disponibilidad. El benchmark es local y secuencial; los fallos no cubren todas las particiones de red o condiciones del sistema operativo. Las invalidaciones fallidas se registran, pero no hay un trabajador automático de reintentos de esa tabla. Las cotizaciones internas usan PostgreSQL. La entrega desde un clon limpio y la sustentación corresponden a fase 13.', '']
    (ROOT / 'docs/validacion-fase-12.md').write_text('\n'.join(lines), encoding='utf-8')
    print('Generated docs/validacion-fase-12.md from passed execution ' + latest['run_id'])


if __name__ == '__main__':
    main()
```

## ml/src/restore_tracking.py

```python
"""Reproduce train/validation runs in a fresh local MLflow, preserving frozen v1.

Original test metrics are imported with explicit provenance, never reevaluated.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import joblib
import mlflow
import numpy as np
from .contract import FEATURES, TARGET_COLUMN, get_candidate_specifications, build_candidate_pipeline, normalize_features_df, sha256_file
from .phase11 import split
from .train_and_select import compute_classification_metrics, compute_calibration_data, optimize_threshold_on_validation
from .export_and_promote import atomic_json, validate_model_package

ROOT = Path(__file__).resolve().parents[2]


def main():
    source_path = ROOT / 'ml/reports/model_selection_report.json'
    original = json.loads(source_path.read_text())
    candidate = json.loads((ROOT / 'ml/manifests/candidate_v1.json').read_text())
    artifact = ROOT / candidate['artifact_path']
    validate_model_package(candidate, artifact)
    train, val = split('train'), split('val')
    x_train, x_val = normalize_features_df(train, FEATURES), normalize_features_df(val, FEATURES)
    y_train, y_val = train[TARGET_COLUMN].to_numpy(), val[TARGET_COLUMN].to_numpy()
    mlflow.set_tracking_uri(os.getenv('MLFLOW_TRACKING_URI', 'http://mlflow:5000'))
    mlflow.set_experiment('credimarket-riesgo-v1')
    mapping = {'created_at': datetime.now(timezone.utc).isoformat(), 'source_report_sha256': sha256_file(source_path),
        'frozen_artifact_sha256': sha256_file(artifact), 'runs': {},
        'scope': 'Actual train/validation reproduction; test metrics imported from original report, not recomputed'}
    prior = {row['run_name']: row for row in original['runs']}
    for spec in get_candidate_specifications():
        old = prior[spec['run_name']]
        pipe = build_candidate_pipeline(spec)
        with mlflow.start_run(run_name='reproduced_' + spec['run_name']) as run:
            selected = old['run_id'] == candidate['run_id']
            mlflow.set_tags({'source_run_id': old['run_id'], 'phase': '12', 'reproduction': 'true',
                'selected_candidate': str(selected).lower(), 'test_metrics_origin': 'original_frozen_report'})
            mlflow.log_params({'algorithm': spec['algorithm'], 'source_run_id': old['run_id'],
                               'test_set_read': False, **spec['params']})
            pipe.fit(x_train, y_train)
            train_probs, val_probs = pipe.predict_proba(x_train)[:, 1], pipe.predict_proba(x_val)[:, 1]
            metrics = {}
            for name, labels, probs in [('train', y_train, train_probs), ('val', y_val, val_probs)]:
                actual = compute_classification_metrics(labels, probs)
                for metric in ('average_precision', 'roc_auc', 'brier_score'):
                    assert abs(actual[metric] - old[name + '_metrics'][metric]) <= 1e-6
                metrics.update({name + '_' + k: v for k, v in actual.items() if isinstance(v, (int, float))})
            mlflow.log_metrics(metrics)
            mlflow.log_dict(compute_classification_metrics(y_val, val_probs)['confusion_matrix'], 'confusion_matrix_val.json')
            mlflow.log_dict(compute_calibration_data(y_val, val_probs), 'calibration_curve_val.json')
            with tempfile.TemporaryDirectory() as temporary:
                saved = Path(temporary) / 'reproduced_pipeline.joblib'
                joblib.dump(pipe, saved)
                mlflow.log_artifact(str(saved))
            if selected:
                frozen = joblib.load(artifact)
                assert np.max(np.abs(frozen.predict_proba(x_val)[:, 1] - val_probs)) <= 1e-12
                mlflow.log_artifact(str(artifact))
                mlflow.log_dict(optimize_threshold_on_validation(y_val, val_probs), 'threshold_cost_curve.json')
                mlflow.log_dict({'origin': 'Original frozen evaluation; no test reevaluation in phase 12',
                    'source_report_sha256': mapping['source_report_sha256'],
                    'evaluation': original['final_test_evaluation']}, 'test_evaluation.json')
                mlflow.log_metrics({'imported_test_' + key: value for key, value in
                    original['final_test_evaluation']['metrics_at_optimal_threshold'].items()
                    if isinstance(value, (int, float))})
            mapping['runs'][old['run_id']] = run.info.run_id
    atomic_json(ROOT / 'ml/manifests/mlflow_reproduction.json', mapping)
    print(json.dumps(mapping))


if __name__ == '__main__':
    main()
```
