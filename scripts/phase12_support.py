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
