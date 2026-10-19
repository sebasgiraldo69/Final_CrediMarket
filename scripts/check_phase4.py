"""Integration checks for phase 4: Productos y Redis.

Uses real PostgreSQL, Redis and HTTP APIs via Docker Compose.
Tests catalog, permissions, optimistic locking, internal quotation,
Redis cache-aside (hit, miss, expiry, invalidation) and Redis outage fallback.
"""
import json
from pathlib import Path
import secrets
import subprocess
import time
import urllib.request
import urllib.error
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
env = dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
FRONTEND_PORT = env.get('FRONTEND_PORT', '8080')
BASE_PRODUCTOS = f"http://127.0.0.1:{FRONTEND_PORT}/api/productos"
BASE_CLIENTES = f"http://127.0.0.1:{FRONTEND_PORT}/api/clientes"

tag = uuid4().hex[:12]
password = secrets.token_urlsafe(24)


def inside_clientes(source):
    result = subprocess.run(
        ['docker', 'compose', 'exec', '-T', 'clientes', 'python', '-'],
        cwd=ROOT, input=source, text=True, capture_output=True, encoding='utf-8', timeout=60
    )
    if result.returncode:
        raise RuntimeError(f'Clientes command failed: {result.stderr}')
    return result.stdout.strip()


def redis_cli(*args):
    redis_pass = env.get('REDIS_PASSWORD', '')
    cmd = ['docker', 'compose', 'exec', '-T', 'redis', 'redis-cli', '-a', redis_pass, *args]
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, encoding='utf-8', timeout=30)
    return result.stdout.strip()


def api(base, path, method='GET', body=None, token=None):
    headers = {}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = json.dumps(body).encode() if body is not None else None
    if data:
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


print("--- Iniciando comprobación de Fase 4: Productos y Redis ---")

# 1. Configurar usuario administrador y cliente de prueba
admin_email = f'admin-p4-{tag}@example.com'
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

client_email = f'cliente-p4-{tag}@example.com'
expect(*api(BASE_CLIENTES, '/clientes', 'POST', {'nombre': 'Cliente P4 ' + tag, 'email': client_email, 'password': password}), 201)
client_login = expect(*api(BASE_CLIENTES, '/auth/login', 'POST', {'email': client_email, 'password': password}), 200)
client_token = client_login['access_token']

# Tokens internos de servicio para cotización
service_token_valid = inside_clientes("from app.security import issue_token; print(issue_token('prestamos', scopes=['productos:cotizar']))")
service_token_wrong_scope = inside_clientes("from app.security import issue_token; print(issue_token('prestamos', scopes=['clientes:read']))")

print("PASS autenticación y tokens para pruebas de Productos")

# 2. Permisos y listado de catálogo
expect(*api(BASE_PRODUCTOS, '/productos'), 401)
expect(*api(BASE_PRODUCTOS, '/productos', token=client_token[:-6] + 'BADTOK'), 401)
catalog_client = expect(*api(BASE_PRODUCTOS, '/productos', token=client_token), 200)
assert catalog_client['total'] >= 10, f"Expected at least 10 seeded products, found {catalog_client['total']}"
assert all(p['activo'] is True for p in catalog_client['items']), "Cliente vio productos inactivos en catálogo público"

# Cliente no puede incluir inactivos ni crear/editar
expect(*api(BASE_PRODUCTOS, '/productos?incluir_inactivos=true', token=client_token), 403)
expect(*api(BASE_PRODUCTOS, '/productos', 'POST', {'nombre': 'Hacker', 'categoria': 'Test', 'precio_cop': '1000.00'}, client_token), 403)

print("PASS permisos de cliente y listado de catálogo activo")

# 3. Creación de producto por administrador
test_product_name = f'Laptop Ultrabook {tag}'
create_body = {
    'nombre': test_product_name,
    'categoria': 'Computadores',
    'precio_cop': '4500000.00'
}
created_status, created_prod, created_headers = api(BASE_PRODUCTOS, '/productos', 'POST', create_body, admin_token)
expect(created_status, created_prod, created_headers, 201)
assert created_headers.get('Location') == f"/api/productos/productos/{created_prod['id']}"
assert created_prod['nombre'] == test_product_name
assert created_prod['precio_cop'] == '4500000.00'
assert created_prod['activo'] is True
assert created_prod['version'] == 1
prod_id = created_prod['id']

print("PASS creación de producto por administrador y encabezado Location")

# 4. Redis Cache-Aside: Miss, Hit, TTL
# Asegurar que la clave no esté en Redis antes de consultar
redis_cli('del', f'producto:{prod_id}')
assert redis_cli('exists', f'producto:{prod_id}') == '0', "La clave debería estar ausente en Redis inicialmente"

# Primera lectura: Cache Miss -> consulta a PostgreSQL y puebla Redis
miss_result = expect(*api(BASE_PRODUCTOS, f'/productos/{prod_id}', token=client_token), 200)
assert miss_result['id'] == prod_id
assert redis_cli('exists', f'producto:{prod_id}') == '1', "Redis debe contener la clave tras la primera consulta (miss)"
ttl = int(redis_cli('ttl', f'producto:{prod_id}'))
assert 0 < ttl <= 60, f"TTL de Redis inválido: {ttl}s (esperado <= 60s)"

# Segunda lectura: Cache Hit desde Redis
hit_result = expect(*api(BASE_PRODUCTOS, f'/productos/{prod_id}', token=client_token), 200)
assert hit_result['precio_cop'] == '4500000.00'
assert hit_result['version'] == 1

print("PASS Redis Cache-Aside: Miss inicial, Hit subsiguiente y TTL documentado (60s)")

# 5. Edición, bloqueo optimista (versión) e Invalidación de Caché
# Conflicto de versión esperada incorrecta -> 409
expect(*api(BASE_PRODUCTOS, f'/productos/{prod_id}', 'PATCH', {'version_esperada': 99, 'precio_cop': '4800000.00'}, admin_token), 409)

# Edición válida con versión_esperada=1 -> pasa a versión 2
updated_prod = expect(*api(BASE_PRODUCTOS, f'/productos/{prod_id}', 'PATCH', {'version_esperada': 1, 'precio_cop': '4800000.00'}, admin_token), 200)
assert updated_prod['version'] == 2
assert updated_prod['precio_cop'] == '4800000.00'

# La clave en Redis debió ser invalidada (eliminada)
assert redis_cli('exists', f'producto:{prod_id}') == '0', "La clave en Redis debió eliminarse tras la actualización de precio"

# Nueva lectura puebla Redis con la versión 2
refreshed = expect(*api(BASE_PRODUCTOS, f'/productos/{prod_id}', token=client_token), 200)
assert refreshed['version'] == 2
assert refreshed['precio_cop'] == '4800000.00'
assert redis_cli('exists', f'producto:{prod_id}') == '1'

print("PASS control de versiones optimista (409) e invalidación de caché en actualización de precio")

# 6. Desactivación e invalidación
expect(*api(BASE_PRODUCTOS, f'/productos/{prod_id}/desactivar', 'POST', {'version_esperada': 1}, admin_token), 409)
deactivated = expect(*api(BASE_PRODUCTOS, f'/productos/{prod_id}/desactivar', 'POST', {'version_esperada': 2}, admin_token), 200)
assert deactivated['activo'] is False
assert deactivated['version'] == 3

# Invalidada en Redis
assert redis_cli('exists', f'producto:{prod_id}') == '0', "La clave en Redis debió eliminarse tras desactivar"

# Cliente recibe 404 al consultar producto inactivo
expect(*api(BASE_PRODUCTOS, f'/productos/{prod_id}', token=client_token), 404)

# Administrador puede consultar producto inactivo directamente
admin_view = expect(*api(BASE_PRODUCTOS, f'/productos/{prod_id}', token=admin_token), 200)
assert admin_view['activo'] is False

print("PASS desactivación de producto, ocultamiento a clientes (404) e invalidación")

# 7. Endpoint interno de cotización para Préstamos
# No admite acceso público ni tokens de usuario normal
expect(*api(BASE_PRODUCTOS, f'/interno/productos/{prod_id}/cotizacion'), 401)
expect(*api(BASE_PRODUCTOS, f'/interno/productos/{prod_id}/cotizacion', token=client_token), 401)
expect(*api(BASE_PRODUCTOS, f'/interno/productos/{prod_id}/cotizacion', token=admin_token), 401)
expect(*api(BASE_PRODUCTOS, f'/interno/productos/{prod_id}/cotizacion', token=service_token_wrong_scope), 403)

# Con token interno y alcance productos:cotizar
quote = expect(*api(BASE_PRODUCTOS, f'/interno/productos/{prod_id}/cotizacion', token=service_token_valid), 200)
assert quote['producto_id'] == prod_id
assert quote['precio_unitario_cop'] == '4800000.00'
assert quote['version_producto'] == 3
assert quote['activo'] is False
assert 'cotizado_en' in quote

print("PASS cotización interna segura para Préstamos con scope productos:cotizar")

# 8. Tolerancia y resiliencia ante caída de Redis (Fallback a PostgreSQL)
print("Simulando caída temporal de Redis...")
subprocess.run(['docker', 'compose', 'stop', 'redis'], cwd=ROOT, check=True)
time.sleep(1)

try:
    # Health sigue 200
    health_code, health_body, _ = api(BASE_PRODUCTOS, '/health')
    assert health_code == 200

    # Ready devuelve 200 con status "degraded"
    ready_code, ready_body, _ = api(BASE_PRODUCTOS, '/ready')
    assert ready_code == 200
    assert ready_body['status'] == 'degraded'
    assert ready_body['dependencies']['redis'] == 'degraded'
    assert ready_body['dependencies']['database'] == 'ok'

    # Las consultas de producto siguen funcionando transparentemente desde PostgreSQL
    fallback_client = expect(*api(BASE_PRODUCTOS, '/productos', token=client_token), 200)
    assert fallback_client['total'] >= 10

    fallback_single = expect(*api(BASE_PRODUCTOS, f'/productos/{prod_id}', token=admin_token), 200)
    assert fallback_single['id'] == prod_id
    assert fallback_single['precio_cop'] == '4800000.00'
finally:
    print("Restaurando contenedor Redis...")
    subprocess.run(['docker', 'compose', 'start', 'redis'], cwd=ROOT, check=True)
    time.sleep(3)

# Comprobar que tras reiniciar Redis, el servicio vuelve a estado ready
ready_restored_code, ready_restored_body, _ = api(BASE_PRODUCTOS, '/ready')
assert ready_restored_code == 200
assert ready_restored_body['dependencies']['redis'] == 'ok'

print("PASS resiliencia ante caída de Redis y recuperación automática")

# 9. Validación estática contra OpenAPI con jsonschema
from jsonschema import Draft202012Validator, FormatChecker
contract = json.loads((ROOT / 'contracts/openapi/productos.json').read_text(encoding='utf-8'))
for schema_name, value in [('Producto', refreshed), ('Productos', catalog_client), ('Cotizacion', quote)]:
    schema = {'$ref': '#/components/schemas/' + schema_name, 'components': contract['components']}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)

print("PASS conformidad estructural con contrato OpenAPI de Productos")
print("=== FASE 4 COMPLETADA Y VALIDADA CON ÉXITO ===")
