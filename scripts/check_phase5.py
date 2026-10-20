"""Integration checks for phase 5: Inventario y reservas atómicas.

Tests real PostgreSQL, HTTP APIs, authorization, Idempotency-Key,
concurrency race for the last unit, idempotent liberar/entregar,
pre-cancellation marks, automatic expiration, and OpenAPI contracts.
"""
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import time
import urllib.request
import urllib.error
from uuid import uuid4
import jsonschema

ROOT = Path(__file__).resolve().parents[1]
env = dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
FRONTEND_PORT = env.get('FRONTEND_PORT', '8080')
BASE_INVENTARIO = f"http://127.0.0.1:{FRONTEND_PORT}/api/inventario"
BASE_CLIENTES = f"http://127.0.0.1:{FRONTEND_PORT}/api/clientes"

tag = uuid4().hex[:12]
password = secrets.token_urlsafe(24)

# Load OpenAPI specification
openapi_path = ROOT / 'contracts' / 'openapi' / 'inventario.json'
openapi_spec = json.loads(openapi_path.read_text(encoding='utf-8'))
schema_resolver = jsonschema.RefResolver.from_schema(openapi_spec)


def validate_schema(instance, schema_name):
    schema = openapi_spec['components']['schemas'][schema_name]
    jsonschema.validate(instance=instance, schema=schema, resolver=schema_resolver)


def inside_clientes(source):
    result = subprocess.run(
        ['docker', 'compose', 'exec', '-T', 'clientes', 'python', '-'],
        cwd=ROOT, input=source, text=True, capture_output=True, encoding='utf-8', timeout=60
    )
    if result.returncode:
        raise RuntimeError(f'Clientes command failed: {result.stderr}')
    return result.stdout.strip()


def inside_inventario(source):
    result = subprocess.run(
        ['docker', 'compose', 'exec', '-T', 'inventario', 'python', '-'],
        cwd=ROOT, input=source, text=True, capture_output=True, encoding='utf-8', timeout=60
    )
    if result.returncode:
        raise RuntimeError(f'Inventario command failed: {result.stderr}\nOutput: {result.stdout}')
    return result.stdout.strip()


def api(base, path, method='GET', body=None, token=None, headers_extra=None):
    headers = {}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if headers_extra:
        headers.update(headers_extra)
    data = json.dumps(body).encode() if body is not None else None
    if data and 'Content-Type' not in headers:
        headers['Content-Type'] = 'application/json'
    try:
        req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
        response = urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as exc:
        response = exc
    content = response.read()
    try:
        result = json.loads(content)
    except ValueError:
        raise AssertionError(f'Non-JSON response: HTTP {response.status} {path}: {content.decode()[:200]}')
    return response.status, result, response.headers


def expect(status, result, headers, expected_code):
    assert status == expected_code, (status, expected_code, result.get('message', result.get('code', 'Unexpected response')))
    return result


print("--- Iniciando comprobación de Fase 5: Inventario y reservas atómicas ---")

# 1. Configurar usuario administrador y cliente
admin_email = f'admin-p5-{tag}@example.com'
inside_clientes(f'''
from uuid import uuid4
from sqlalchemy import create_engine
from shared.runtime import database_url
from app.models import usuarios
from app.security import hasher
with create_engine(database_url()).begin() as conn:
    conn.execute(usuarios.insert().values(id=uuid4(), email={repr(admin_email)}, password_hash=hasher.hash({repr(password)}), rol='administrador'))
''')
admin_login = expect(*api(BASE_CLIENTES, '/auth/login', 'POST', {'email': admin_email, 'password': password}), 200)
admin_token = admin_login['access_token']

client_email = f'cliente-p5-{tag}@example.com'
expect(*api(BASE_CLIENTES, '/clientes', 'POST', {'nombre': 'Cliente P5 ' + tag, 'email': client_email, 'password': password}), 201)
client_login = expect(*api(BASE_CLIENTES, '/auth/login', 'POST', {'email': client_email, 'password': password}), 200)
client_token = client_login['access_token']

# Tokens de servicio internos para reservas
service_token_valid = inside_clientes("from app.security import issue_token; print(issue_token('prestamos', scopes=['reservas:read']))")
service_token_wrong_scope = inside_clientes("from app.security import issue_token; print(issue_token('prestamos', scopes=['productos:cotizar']))")

print("PASS Autenticación, roles y tokens de servicio")

# 2. Health & Ready del servicio Inventario
health_res = expect(*api(BASE_INVENTARIO, '/health'), 200)
assert health_res['status'] == 'ok'
validate_schema(health_res, 'Health')

ready_res = expect(*api(BASE_INVENTARIO, '/ready'), 200)
assert ready_res['status'] in ('ready', 'degraded')
assert ready_res['dependencies']['database'] == 'ok'
validate_schema(ready_res, 'Ready')

print("PASS Health y Ready (/health, /ready)")

# 3. Autorización y permisos en endpoints HTTP
expect(*api(BASE_INVENTARIO, '/inventario'), 401)
expect(*api(BASE_INVENTARIO, '/inventario', token=client_token), 403)
existencias_data = expect(*api(BASE_INVENTARIO, '/inventario', token=admin_token), 200)
validate_schema(existencias_data, 'Existencias')
assert existencias_data['total'] >= 10, f"Se esperaban al menos 10 productos con inventario, se hallaron {existencias_data['total']}"
for item in existencias_data['items']:
    validate_schema(item, 'Existencia')
    assert item['fisico'] >= item['reservado']
    assert item['disponible'] == item['fisico'] - item['reservado']

expect(*api(BASE_INVENTARIO, '/inventario/movimientos'), 401)
expect(*api(BASE_INVENTARIO, '/inventario/movimientos', token=client_token), 403)
movimientos_data = expect(*api(BASE_INVENTARIO, '/inventario/movimientos', token=admin_token), 200)
validate_schema(movimientos_data, 'Movimientos')
assert movimientos_data['total'] >= 10

expect(*api(BASE_INVENTARIO, '/inventario/reservas'), 401)
expect(*api(BASE_INVENTARIO, '/inventario/reservas', token=client_token), 403)
reservas_data = expect(*api(BASE_INVENTARIO, '/inventario/reservas', token=admin_token), 200)
validate_schema(reservas_data, 'Reservas')

print("PASS Autorización de roles y esquemas en existencias, movimientos y reservas")

# 4. Idempotencia en POST /inventario/entradas con Idempotency-Key
test_product_id = "10000000-0000-4000-8000-000000000001"
test_key = f"key-idemp-{tag}-001"
entrada_body = {
    "producto_id": test_product_id,
    "cantidad": 5,
    "motivo": f"Entrada test idempotencia {tag}"
}

# Falta cabecera Idempotency-Key -> 422
expect(*api(BASE_INVENTARIO, '/inventario/entradas', 'POST', entrada_body, token=admin_token), 422)

# Primera llamada -> 201 Created
status1, res1, headers1 = api(BASE_INVENTARIO, '/inventario/entradas', 'POST', entrada_body, token=admin_token, headers_extra={'Idempotency-Key': test_key})
assert status1 == 201
validate_schema(res1, 'Movimiento')
assert headers1.get('Location') == '/api/inventario/movimientos'
assert res1['tipo'] == 'ENTRADA'
assert res1['cantidad'] == 5
first_mov_id = res1['id']

# Reintento con la misma clave y mismo body -> 201 Replay idéntico
status2, res2, headers2 = api(BASE_INVENTARIO, '/inventario/entradas', 'POST', entrada_body, token=admin_token, headers_extra={'Idempotency-Key': test_key})
assert status2 == 201
assert res2['id'] == first_mov_id, "El reintento no devolvió el mismo movimiento registrado"
assert headers2.get('Location') == '/api/inventario/movimientos'

# Intento con la misma clave pero contenido diferente -> 409 Conflict
diff_body = {
    "producto_id": test_product_id,
    "cantidad": 12,
    "motivo": "Contenido diferente con misma clave"
}
expect(*api(BASE_INVENTARIO, '/inventario/entradas', 'POST', diff_body, token=admin_token, headers_extra={'Idempotency-Key': test_key}), 409)

print("PASS Idempotencia HTTP en POST /inventario/entradas (201 replay y 409 en conflicto)")

# 5. Endpoint interno /interno/reservas/por-prestamo/{prestamo_id}
dummy_prestamo_id = str(uuid4())
expect(*api(BASE_INVENTARIO, f'/interno/reservas/por-prestamo/{dummy_prestamo_id}'), 401)
expect(*api(BASE_INVENTARIO, f'/interno/reservas/por-prestamo/{dummy_prestamo_id}', token=admin_token), 401)
expect(*api(BASE_INVENTARIO, f'/interno/reservas/por-prestamo/{dummy_prestamo_id}', token=service_token_wrong_scope), 403)
expect(*api(BASE_INVENTARIO, f'/interno/reservas/por-prestamo/{dummy_prestamo_id}', token=service_token_valid), 404)

print("PASS Autorización estricta en GET /interno/reservas/por-prestamo (ServiceBearer y scope)")

# 6. Pruebas de dominio transaccional y concurrencia dentro del contenedor inventario
print("Ejecutando suite de concurrencia y máquina de estados dentro del contenedor...")
domain_test_script = f'''
import threading
from uuid import uuid4, UUID
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import create_engine, select
from shared.runtime import database_url
from app.models import existencias, reservas, movimientos
from app.domain import reservar, liberar, entregar, vencer

engine = create_engine(database_url())

# 1. Competencia por la última unidad
comp_prod_id = uuid4()
with engine.begin() as conn:
    conn.execute(existencias.insert().values(
        producto_id=comp_prod_id,
        fisico=1,
        reservado=0,
        disponible=1
    ))

p_id_1 = uuid4()
p_id_2 = uuid4()
results = {{}}

def attempt_reserve(p_id):
    with engine.begin() as conn:
        res = reservar(conn, p_id, comp_prod_id, cantidad=1)
        results[p_id] = res

t1 = threading.Thread(target=attempt_reserve, args=(p_id_1,))
t2 = threading.Thread(target=attempt_reserve, args=(p_id_2,))
t1.start()
t2.start()
t1.join()
t2.join()

states = [results[p_id_1]['estado_reserva'], results[p_id_2]['estado_reserva']]
assert sorted(states) == ['ACTIVA', 'SIN_STOCK'], f"Concurrencia fallida: {{states}}"

winner_id = p_id_1 if results[p_id_1]['estado_reserva'] == 'ACTIVA' else p_id_2
loser_id = p_id_2 if winner_id == p_id_1 else p_id_1

with engine.begin() as conn:
    row = conn.execute(select(existencias).where(existencias.c.producto_id == comp_prod_id)).mappings().one()
    assert row['fisico'] == 1
    assert row['reservado'] == 1
    assert row['disponible'] == 0
    assert row['fisico'] >= row['reservado']
    assert row['disponible'] >= 0

# 2. Doble liberar no altera el stock dos veces
with engine.begin() as conn:
    lib1 = liberar(conn, winner_id)
    assert lib1['estado_reserva'] == 'CANCELADA'
    assert lib1['revision_reserva'] == 2

with engine.begin() as conn:
    lib2 = liberar(conn, winner_id)
    assert lib2['estado_reserva'] == 'CANCELADA'
    # Stock se restableció a 1 una sola vez
    row = conn.execute(select(existencias).where(existencias.c.producto_id == comp_prod_id)).mappings().one()
    assert row['fisico'] == 1
    assert row['reservado'] == 0
    assert row['disponible'] == 1

# 3. Marca durable de pre-cancelación (liberar antes de reservar)
pre_cancel_id = uuid4()
with engine.begin() as conn:
    marca = liberar(conn, pre_cancel_id)
    assert marca['estado_reserva'] == 'CANCELADA'
    assert marca['revision_reserva'] == 1
    assert marca['producto_id'] is None

with engine.begin() as conn:
    intento_tardio = reservar(conn, pre_cancel_id, comp_prod_id, cantidad=1)
    assert intento_tardio['estado_reserva'] == 'CANCELADA'
    # Stock intacto
    row = conn.execute(select(existencias).where(existencias.c.producto_id == comp_prod_id)).mappings().one()
    assert row['disponible'] == 1
    assert row['reservado'] == 0

# 4. Entrega e idempotencia de doble entrega
entrega_prod_id = uuid4()
with engine.begin() as conn:
    conn.execute(existencias.insert().values(
        producto_id=entrega_prod_id,
        fisico=2,
        reservado=0,
        disponible=2
    ))

prestamo_entregar = uuid4()
with engine.begin() as conn:
    res = reservar(conn, prestamo_entregar, entrega_prod_id, cantidad=2)
    assert res['estado_reserva'] == 'ACTIVA'

with engine.begin() as conn:
    ent1 = entregar(conn, prestamo_entregar)
    assert ent1['estado_reserva'] == 'ENTREGADA'
    row = conn.execute(select(existencias).where(existencias.c.producto_id == entrega_prod_id)).mappings().one()
    assert row['fisico'] == 0
    assert row['reservado'] == 0
    assert row['disponible'] == 0

# Segunda entrega es un no-op idempotente: no crea segunda salida ni altera existencias
with engine.begin() as conn:
    ent2 = entregar(conn, prestamo_entregar)
    assert ent2['estado_reserva'] == 'ENTREGADA'
    salidas = conn.execute(
        select(movimientos)
        .where(movimientos.c.prestamo_id == prestamo_entregar, movimientos.c.tipo == 'SALIDA')
    ).mappings().all()
    assert len(salidas) == 1, f"Se esperaba 1 salida, se encontraron {{len(salidas)}}"

# Liberar un producto ya entregado es rechazado (YA_ENTREGADA)
try:
    with engine.begin() as conn:
        liberar(conn, prestamo_entregar)
    assert False, "Debio fallar liberar sobre reserva ENTREGADA"
except ValueError as e:
    assert "YA_ENTREGADA" in str(e)

# 5. Vencimiento de reserva restaura stock disponible
exp_prod_id = uuid4()
prestamo_exp = uuid4()
with engine.begin() as conn:
    conn.execute(existencias.insert().values(
        producto_id=exp_prod_id,
        fisico=3,
        reservado=0,
        disponible=3
    ))
    res_exp = reservar(conn, prestamo_exp, exp_prod_id, cantidad=2, ttl_seconds=-10)
    assert res_exp['estado_reserva'] == 'ACTIVA'

with engine.begin() as conn:
    # Vencer detecta la expiración y retorna stock
    vencida = vencer(conn, prestamo_exp)
    assert vencida['estado_reserva'] == 'VENCIDA'
    row = conn.execute(select(existencias).where(existencias.c.producto_id == exp_prod_id)).mappings().one()
    assert row['disponible'] == 3
    assert row['reservado'] == 0
    assert row['fisico'] == 3

print("SUCCESS_DOMAIN")
'''
output_domain = inside_inventario(domain_test_script)
assert "SUCCESS_DOMAIN" in output_domain, f"Fallo en pruebas de dominio: {output_domain}"

print("PASS Pruebas de concurrencia, doble liberación/entrega, marca de cancelación y expiración")

# 7. Verificación del endpoint interno /interno/reservas/por-prestamo/{prestamo_id} con caso real
# Creamos una reserva activa mediante inside_inventario y la consultamos vía HTTP
prestamo_query_id = str(uuid4())
setup_reserva_script = f'''
from uuid import UUID
from sqlalchemy import create_engine
from shared.runtime import database_url
from app.domain import reservar

engine = create_engine(database_url())
with engine.begin() as conn:
    reservar(conn, UUID("{prestamo_query_id}"), UUID("{test_product_id}"), cantidad=1)
'''
inside_inventario(setup_reserva_script)

# Consulta vía API interna con token autorizado
reserva_http = expect(*api(BASE_INVENTARIO, f'/interno/reservas/por-prestamo/{prestamo_query_id}', token=service_token_valid), 200)
validate_schema(reserva_http, 'Reserva')
assert reserva_http['prestamo_id'] == prestamo_query_id
assert reserva_http['producto_id'] == test_product_id
assert reserva_http['estado_reserva'] == 'ACTIVA'
assert reserva_http['revision_reserva'] == 1

print("PASS Consulta autorizada de snapshot en GET /interno/reservas/por-prestamo/{prestamo_id}")

print("=========================================================")
print("  ¡FASE 5 COMPLETADA CON ÉXITO: INVENTARIO Y RESERVAS!  ")
print("=========================================================")
