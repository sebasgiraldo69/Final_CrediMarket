"""Integration checks for phase 3. Uses real PostgreSQL and HTTP APIs.

Creates uniquely named synthetic test accounts and durable import reports.
No deletes, volume resets or production credentials.
"""
from concurrent.futures import ThreadPoolExecutor
import io
import csv
import json
from pathlib import Path
import secrets
import subprocess
import urllib.request
import urllib.error
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
env = dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
BASE = f"http://127.0.0.1:{env.get('FRONTEND_PORT', '8080')}/api/clientes"
tag = uuid4().hex[:12]
password = secrets.token_urlsafe(24)


def inside(source):
    result = subprocess.run(['docker', 'compose', 'exec', '-T', 'clientes', 'python', '-'],
        cwd=ROOT, input=source, text=True, capture_output=True, encoding='utf-8', timeout=60)
    if result.returncode:
        raise RuntimeError('Fixture setup failed inside Clientes (output suppressed to protect credentials)')
    return result.stdout.strip()


def api(path, method='GET', body=None, token=None, file=None):
    headers = {}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if file is not None:
        boundary = 'Boundary' + uuid4().hex
        data = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="test.csv"\r\nContent-Type: text/csv\r\n\r\n'.encode()
                + file + f'\r\n--{boundary}--\r\n'.encode())
        headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
    else:
        data = json.dumps(body).encode() if body is not None else None
        if data:
            headers['Content-Type'] = 'application/json'
    try:
        response = urllib.request.urlopen(urllib.request.Request(BASE + path, data=data, headers=headers, method=method), timeout=120)
    except urllib.error.HTTPError as exc:
        response = exc
    content = response.read()
    try:
        result = json.loads(content)
    except ValueError:
        raise AssertionError(f'Non-JSON response: HTTP {response.status} {path}')
    return response.status, result


def expect(status, result, code):
    assert status == code, (status, code, result.get('message', result.get('code', 'Unexpected response')))
    return result


admin_email = f'admin-{tag}@example.com'
inside('''
from uuid import uuid4
from sqlalchemy import create_engine
from shared.runtime import database_url
from app.models import usuarios
from app.security import hasher
with create_engine(database_url()).begin() as conn:
    conn.execute(usuarios.insert().values(id=uuid4(), email=EMAIL, password_hash=hasher.hash(PASSWORD), rol='administrador'))
'''.replace('EMAIL', repr(admin_email)).replace('PASSWORD', repr(password)))
admin = expect(*api('/auth/login', 'POST', {'email': admin_email, 'password': password}), 200)['access_token']
clients = []
for name in ['a', 'b']:
    email = f'{name}-{tag}@example.com'
    row = expect(*api('/clientes', 'POST', {'nombre': 'Prueba ' + name, 'email': email, 'password': password}), 201)
    login = expect(*api('/auth/login', 'POST', {'email': email.upper(), 'password': password}), 200)
    assert login['role'] == 'cliente' and login['cliente_id'] == row['id']
    clients.append((row, login['access_token'], email))
a, a_token, a_email = clients[0]
b, b_token, _ = clients[1]
assert a['finanzas'] is None
expect(*api('/clientes', 'POST', {'nombre': 'Ataque', 'email': f'bad-{tag}@example.com', 'password': password, 'role': 'administrador'}), 422)
expect(*api('/auth/login', 'POST', {'email': a_email, 'password': 'incorrecta'}), 401)
before = expect(*api('/clientes', token=admin), 200)['total']
expect(*api('/clientes', 'POST', {'nombre': 'Duplicado', 'email': a_email, 'password': password}), 409)
assert expect(*api('/clientes', token=admin), 200)['total'] == before
expect(*api('/clientes'), 401)
expect(*api('/clientes', token=a_token), 403)
expect(*api('/clientes/' + b['id'], token=a_token), 404)
expect(*api('/clientes/' + a['id'], 'PATCH', {'version_esperada': 1, 'activo': False}, a_token), 403)
expect(*api('/clientes/importaciones', 'POST', token=a_token, file=b'cliente_id\n'), 403)
expect(*api('/interno/clientes/' + a['id'], token=admin), 401)
expect(*api('/clientes/' + a['id'], token=a_token[:-8] + 'AAAAAAAA'), 401)
expired = inside('''
import jwt, time
from app.security import private_key
claims=jwt.decode(TOKEN, options={'verify_signature': False})
claims['iat']=int(time.time())-3600
claims['exp']=int(time.time())-60
print(jwt.encode(claims, private_key(), algorithm='RS256'))
'''.replace('TOKEN', repr(a_token)))
expect(*api('/clientes/' + a['id'], token=expired), 401)
service_token = inside("from app.security import issue_token; print(issue_token('prestamos', scopes=['clientes:read']))")
expect(*api('/interno/clientes/' + a['id'], token=service_token), 200)
expect(*api('/clientes/' + a['id'], token=service_token), 401)
print('PASS register, password login, duplicate rollback, owner/role, expired/forged token and service scope')

with ThreadPoolExecutor(max_workers=2) as executor:
    results = list(executor.map(lambda name: api('/clientes/' + a['id'], 'PATCH', {'version_esperada': 1, 'nombre': name}, a_token), ['Edición uno', 'Edición dos']))
assert sorted(code for code, _ in results) == [200, 409]
financial = {'ingresos_mensuales_cop': '2500000.00', 'obligaciones_mensuales_cop': '300000.00',
    'tipo_empleo': 'dependiente', 'antiguedad_laboral_meses': 12, 'meses_historial_crediticio': None,
    'creditos_previos': 0, 'atrasos_previos_30d': 0, 'porcentaje_pago_puntual': None}
updated = expect(*api('/clientes/' + a['id'], 'PATCH', {'version_esperada': 2, 'finanzas': financial}, admin), 200)
assert updated['finanzas'] == financial and updated['version'] == 3
expect(*api('/clientes/' + a['id'], 'PATCH', {'version_esperada': 3, 'finanzas': {**financial, 'creditos_previos': 1}}, admin), 422)
print('PASS concurrent version check and validated admin financial update')

raw = (ROOT / 'prestamos_entrenamiento.csv').read_bytes()
first = expect(*api('/clientes/importaciones', 'POST', token=admin, file=raw), 201)
assert first['total_filas'] == 12000 and first['rechazados'] == 0
second = expect(*api('/clientes/importaciones', 'POST', token=admin, file=raw), 201)
assert second['insertados'] == second['actualizados'] == second['rechazados'] == 0 and second['sin_cambios'] == 12000
assert expect(*api('/clientes/importaciones/' + second['id'], token=admin), 200) == second

sample = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))[:3]
for index, row in enumerate(sample):
    row['cliente_id'] = f'TEST-{tag}-{index}'
sample[1]['cliente_id'] = sample[0]['cliente_id']
sample[2]['ingresos_mensuales_cop'] = '-1'
out = io.StringIO(); writer = csv.DictWriter(out, fieldnames=sample[0].keys()); writer.writeheader(); writer.writerows(sample)
mixed = expect(*api('/clientes/importaciones', 'POST', token=admin, file=out.getvalue().encode()), 201)
assert mixed['insertados'] == 1 and mixed['rechazados'] == 2 and len(mixed['errores']) == 2
assert 'repetido' in mixed['errores'][0]['mensaje']
assert mixed['errores'][1]['campo'] == 'ingresos_mensuales_cop'
expect(*api('/clientes/importaciones', 'POST', token=admin, file=b'cliente_id,unknown\nx,y\n'), 422)
expect(*api('/clientes/importaciones', 'POST', token=admin, file=b'x' * (10 * 1024 * 1024 + 1)), 413)
print('PASS 12,000-row import twice, durable report, duplicate/invalid rows and upload limits')

# Validate representative real responses against the phase-1 design contracts.
from jsonschema import Draft202012Validator, FormatChecker
contract = json.loads((ROOT / 'contracts/openapi/clientes.json').read_text(encoding='utf-8'))
for schema_name, value in [('Cliente', updated), ('Importacion', first)]:
    schema = {'$ref': '#/components/schemas/' + schema_name, 'components': contract['components']}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
print('PASS response contracts. Phase 3 API checks completed; synthetic test accounts retained.')
