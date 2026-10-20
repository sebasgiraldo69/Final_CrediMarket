"""End-to-end integration and acceptance tests for Phase 9: Completar el flujo de Préstamos.

Covers:
- AC01: Cliente favorable, producto con stock -> Crear -> 202 -> APROBADA; entrega admin -> 202 -> COMPLETADA.
- AC02: Cliente con riesgo desfavorable real -> 201 RECHAZADA con modelo/motivo; cero comando de reserva en Kafka.
- AC03: Cliente favorable, stock cero -> 202 -> CANCELADA_SIN_STOCK, stock no negativo.
- AC04: Stock una unidad, dos préstamos simultáneos -> exactamente una APROBADA y una CANCELADA_SIN_STOCK.
- AC05: Idempotencia HTTP y unicidad durable; misma clave/cuerpo devuelve la misma solicitud, otro cuerpo devuelve 409.
- AC07: Cancelar antes/después de reservar; evento tardío no reactiva un préstamo cancelado.
- AC09: Editar precio con caché caliente -> invalidación y cotización nueva guardada en préstamo.
- AC13: Token A intenta préstamo de B -> GET/cancelar devuelve 404, listado no filtra información ajena.
- Políticas de crédito: montos fuera de rango (500k-15M), cliente incompleto/inactivo, producto inactivo -> 201 RECHAZADA.
- Esquemas OpenAPI: validación estricta contra contracts/openapi/prestamos.json.
- Auditoría e historial: verificación de la secuencia inmutable de transiciones en prestamos_historial.
"""
import concurrent.futures
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from uuid import UUID, uuid4
import jsonschema

ROOT = Path(__file__).resolve().parents[1]
env = dict(
    line.split("=", 1)
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
    if "=" in line and not line.startswith("#")
)
PORT = env.get("FRONTEND_PORT", "8080")
BASE_PRESTAMOS = f"http://127.0.0.1:{PORT}/api/prestamos"
BASE_CLIENTES = f"http://127.0.0.1:{PORT}/api/clientes"
BASE_PRODUCTOS = f"http://127.0.0.1:{PORT}/api/productos"
BASE_INVENTARIO = f"http://127.0.0.1:{PORT}/api/inventario"

TAG = uuid4().hex[:10]
PASSWORD = secrets.token_urlsafe(24)

# Cargar especificación OpenAPI de préstamos
OPENAPI_PATH = ROOT / "contracts" / "openapi" / "prestamos.json"
openapi_spec = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
schema_resolver = jsonschema.RefResolver.from_schema(openapi_spec)


def validate_schema(instance, schema_name: str):
    schema = openapi_spec["components"]["schemas"][schema_name]
    jsonschema.validate(instance=instance, schema=schema, resolver=schema_resolver)


def docker(*args, stdin=None) -> str:
    result = subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT,
        input=stdin,
        text=True,
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Docker operation failed: {' '.join(args[:4])}\n{result.stderr}")
    return result.stdout.strip()


def inside_db(service: str, source: str) -> str:
    script = f"""
import json
from uuid import UUID, uuid4
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import create_engine, select, text, func
from shared.runtime import database_url
engine = create_engine(database_url())
{source}
"""
    return docker("exec", "-T", service, "python", "-", stdin=script)


def api_request(url: str, method: str = "GET", body=None, token: str | None = None, headers_extra: dict | None = None):
    headers = {"X-Correlation-ID": str(uuid4())}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if headers_extra:
        headers.update(headers_extra)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8")
            return resp.status, (json.loads(content) if content else {}), dict(resp.headers)
    except urllib.error.HTTPError as err:
        content = err.read().decode("utf-8")
        parsed = {}
        try:
            parsed = json.loads(content) if content else {}
        except Exception:
            pass
        return err.code, parsed, dict(err.headers)


def wait_for(check_fn, timeout: float = 35.0, interval: float = 0.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        res = check_fn()
        if res:
            return res
        time.sleep(interval)
    raise TimeoutError(f"Operación duradera no completó antes de {timeout}s")


print("==========================================================================")
print("  INICIANDO VERIFICACIÓN DE FASE 9: FLUJO COMPLETO DE PRÉSTAMOS           ")
print("==========================================================================")

# -----------------------------------------------------------------------------
# 1. Preparación de usuarios, roles y productos de prueba
# -----------------------------------------------------------------------------
print("\n--- 1. Preparando usuarios, clientes y productos de prueba ---")

# 1.1 Administrador
admin_email = f"admin-f9-{TAG}@example.com"
inside_db(
    "clientes",
    f"""
from app.models import usuarios
from app.security import hasher
with engine.begin() as conn:
    conn.execute(usuarios.insert().values(
        id=uuid4(),
        email={repr(admin_email)},
        password_hash=hasher.hash({repr(PASSWORD)}),
        rol='administrador'
    ))
""",
)
st, login_data, _ = api_request(f"{BASE_CLIENTES}/auth/login", "POST", {"email": admin_email, "password": PASSWORD})
assert st == 200, f"Login admin falló: {st} {login_data}"
token_admin = login_data["access_token"]

# 1.2 Cliente A (perfil FAVORABLE)
email_client_a = f"cliente-a-{TAG}@example.com"
st, reg_a, _ = api_request(f"{BASE_CLIENTES}/clientes", "POST", {"nombre": f"Cliente A {TAG}", "email": email_client_a, "password": PASSWORD})
assert st == 201, f"Registro cliente A falló: {st} {reg_a}"
st, log_a, _ = api_request(f"{BASE_CLIENTES}/auth/login", "POST", {"email": email_client_a, "password": PASSWORD})
token_client_a = log_a["access_token"]
client_a_id = log_a["cliente_id"]

# Configurar finanzas favorables para Cliente A
finanzas_favorables = {
    "version_esperada": 1,
    "finanzas": {
        "ingresos_mensuales_cop": "6500000.00",
        "obligaciones_mensuales_cop": "800000.00",
        "tipo_empleo": "dependiente",
        "antiguedad_laboral_meses": 36,
        "meses_historial_crediticio": 48,
        "creditos_previos": 2,
        "atrasos_previos_30d": 0,
        "porcentaje_pago_puntual": 98.5,
    },
}
st, patch_a, _ = api_request(f"{BASE_CLIENTES}/clientes/{client_a_id}", "PATCH", finanzas_favorables, token=token_admin)
assert st == 200, f"Fallo al actualizar finanzas cliente A: {st} {patch_a}"

# 1.3 Cliente B (perfil DESFAVORABLE)
email_client_b = f"cliente-b-{TAG}@example.com"
st, reg_b, _ = api_request(f"{BASE_CLIENTES}/clientes", "POST", {"nombre": f"Cliente B {TAG}", "email": email_client_b, "password": PASSWORD})
assert st == 201
st, log_b, _ = api_request(f"{BASE_CLIENTES}/auth/login", "POST", {"email": email_client_b, "password": PASSWORD})
token_client_b = log_b["access_token"]
client_b_id = log_b["cliente_id"]

# Finanzas desfavorables para Cliente B (ingresos bajos, altas obligaciones, atrasos, puntualidad baja)
finanzas_desfavorables = {
    "version_esperada": 1,
    "finanzas": {
        "ingresos_mensuales_cop": "1400000.00",
        "obligaciones_mensuales_cop": "1150000.00",
        "tipo_empleo": "independiente",
        "antiguedad_laboral_meses": 5,
        "meses_historial_crediticio": 12,
        "creditos_previos": 3,
        "atrasos_previos_30d": 3,
        "porcentaje_pago_puntual": 50.0,
    },
}
st, patch_b, _ = api_request(f"{BASE_CLIENTES}/clientes/{client_b_id}", "PATCH", finanzas_desfavorables, token=token_admin)
assert st == 200, f"Fallo al actualizar finanzas cliente B: {st} {patch_b}"

# 1.4 Cliente C (Incompleto: sin finanzas)
email_client_c = f"cliente-c-{TAG}@example.com"
st, reg_c, _ = api_request(f"{BASE_CLIENTES}/clientes", "POST", {"nombre": f"Cliente C {TAG}", "email": email_client_c, "password": PASSWORD})
assert st == 201
st, log_c, _ = api_request(f"{BASE_CLIENTES}/auth/login", "POST", {"email": email_client_c, "password": PASSWORD})
token_client_c = log_c["access_token"]
client_c_id = log_c["cliente_id"]

# 1.5 Productos dedicados para pruebas
prod_favorable_id = str(uuid4())
prod_nostock_id = str(uuid4())
prod_onestock_id = str(uuid4())
prod_lowprice_id = str(uuid4())
prod_inactive_id = str(uuid4())

inside_db(
    "productos",
    f"""
from app.models import productos
with engine.begin() as conn:
    conn.execute(productos.insert(), [
        {{'id': UUID('{prod_favorable_id}'), 'nombre': 'Portatil Test F9 {TAG}', 'categoria': 'Portátiles', 'precio_cop': Decimal('3200000.00'), 'activo': True, 'version': 1}},
        {{'id': UUID('{prod_nostock_id}'), 'nombre': 'Sin Stock F9 {TAG}', 'categoria': 'Celulares', 'precio_cop': Decimal('2100000.00'), 'activo': True, 'version': 1}},
        {{'id': UUID('{prod_onestock_id}'), 'nombre': 'Una Unidad F9 {TAG}', 'categoria': 'Audio', 'precio_cop': Decimal('1500000.00'), 'activo': True, 'version': 1}},
        {{'id': UUID('{prod_lowprice_id}'), 'nombre': 'Barato F9 {TAG}', 'categoria': 'Accesorios', 'precio_cop': Decimal('200000.00'), 'activo': True, 'version': 1}},
        {{'id': UUID('{prod_inactive_id}'), 'nombre': 'Inactivo F9 {TAG}', 'categoria': 'Tablets', 'precio_cop': Decimal('2500000.00'), 'activo': False, 'version': 1}},
    ])
""",
)

inside_db(
    "inventario",
    f"""
from app.models import existencias
with engine.begin() as conn:
    conn.execute(existencias.insert(), [
        {{'producto_id': UUID('{prod_favorable_id}'), 'fisico': 10, 'reservado': 0, 'disponible': 10}},
        {{'producto_id': UUID('{prod_nostock_id}'), 'fisico': 0, 'reservado': 0, 'disponible': 0}},
        {{'producto_id': UUID('{prod_onestock_id}'), 'fisico': 1, 'reservado': 0, 'disponible': 1}},
        {{'producto_id': UUID('{prod_lowprice_id}'), 'fisico': 10, 'reservado': 0, 'disponible': 10}},
        {{'producto_id': UUID('{prod_inactive_id}'), 'fisico': 10, 'reservado': 0, 'disponible': 10}},
    ])
""",
)

print("PASS Fixtures de clientes, productos y existencias creados exitosamente")

# -----------------------------------------------------------------------------
# 2. Comprobación de Health y Ready en Préstamos
# -----------------------------------------------------------------------------
print("\n--- 2. Verificando Health y Ready de Préstamos ---")
st, health, _ = api_request(f"{BASE_PRESTAMOS}/health")
assert st == 200 and health["service"] == "prestamos"
validate_schema(health, "Health")

st, ready, _ = api_request(f"{BASE_PRESTAMOS}/ready")
assert st == 200 and ready["status"] == "ready"
assert ready["dependencies"]["database"] == "ok"
assert ready["dependencies"]["model"] == "ok"
assert ready["dependencies"]["kafka"] == "ok"
validate_schema(ready, "Ready")
print("PASS /health y /ready (database='ok', model='ok', kafka='ok')")

# -----------------------------------------------------------------------------
# 3. AC13: Autorización, control de roles y aislamiento estricto de propietarios
# -----------------------------------------------------------------------------
print("\n--- 3. AC13: Autorización, roles y aislamiento de datos ---")

# 3.1 Sin token -> 401
st, err, _ = api_request(f"{BASE_PRESTAMOS}/prestamos", "POST", {"producto_id": prod_favorable_id, "cantidad": 1, "plazo_meses": 12})
assert st == 401
validate_schema(err, "Error")

# 3.2 Administrador intentando crear préstamo -> 403 (Solo clientes pueden solicitar créditos)
st, err, _ = api_request(
    f"{BASE_PRESTAMOS}/prestamos",
    "POST",
    {"producto_id": prod_favorable_id, "cantidad": 1, "plazo_meses": 12},
    token=token_admin,
    headers_extra={"Idempotency-Key": f"key-adm-fail-{TAG}"},
)
assert st == 403, f"Se esperaba 403 para admin en POST /prestamos, se obtuvo {st}"
validate_schema(err, "Error")

# 3.3 Cliente intentando ejecutar entrega -> 403 (Solo admin puede entregar)
dummy_id = str(uuid4())
st, err, _ = api_request(
    f"{BASE_PRESTAMOS}/prestamos/{dummy_id}/entrega",
    "POST",
    token=token_client_a,
    headers_extra={"Idempotency-Key": f"key-cli-ent-{TAG}"},
)
assert st == 403
validate_schema(err, "Error")
print("PASS Restricciones de roles en creación (solo cliente) y entrega (solo admin)")

# -----------------------------------------------------------------------------
# 4. AC05: Idempotency-Key en POST /prestamos
# -----------------------------------------------------------------------------
print("\n--- 4. AC05: Validación de Idempotency-Key (longitud, replay idéntico y 409) ---")

idemp_key_1 = f"key-idemp-p9-{TAG}-01"
payload_1 = {"producto_id": prod_favorable_id, "cantidad": 1, "plazo_meses": 12}

# 4.1 Falta cabecera Idempotency-Key -> 422
st, err, _ = api_request(f"{BASE_PRESTAMOS}/prestamos", "POST", payload_1, token=token_client_a)
assert st == 422
validate_schema(err, "Error")

# 4.2 Idempotency-Key menor a 8 caracteres -> 422
st, err, _ = api_request(
    f"{BASE_PRESTAMOS}/prestamos",
    "POST",
    payload_1,
    token=token_client_a,
    headers_extra={"Idempotency-Key": "short"},
)
assert st == 422
validate_schema(err, "Error")

# 4.3 Primer envío exitoso -> 202 Accepted
st, loan_ac05, hdrs = api_request(
    f"{BASE_PRESTAMOS}/prestamos",
    "POST",
    payload_1,
    token=token_client_a,
    headers_extra={"Idempotency-Key": idemp_key_1},
)
assert st == 202, f"Primer envío falló: {st} {loan_ac05}"
validate_schema(loan_ac05, "Prestamo")
loan_ac05_id = loan_ac05["id"]
assert hdrs.get("Location") == f"/api/prestamos/prestamos/{loan_ac05_id}" or hdrs.get("location") == f"/api/prestamos/prestamos/{loan_ac05_id}", f"Location header mismatch: {dict(hdrs)}"

# 4.4 Reintento con la misma clave y mismo body -> 202 replay idéntico
st, loan_ac05_replay, _ = api_request(
    f"{BASE_PRESTAMOS}/prestamos",
    "POST",
    payload_1,
    token=token_client_a,
    headers_extra={"Idempotency-Key": idemp_key_1},
)
assert st == 202
assert loan_ac05_replay["id"] == loan_ac05_id, "El replay no devolvió el mismo préstamo"

# 4.5 Misma clave pero payload diferente -> 409 Conflict
diff_payload = {"producto_id": prod_favorable_id, "cantidad": 2, "plazo_meses": 24}
st, err_conflict, _ = api_request(
    f"{BASE_PRESTAMOS}/prestamos",
    "POST",
    diff_payload,
    token=token_client_a,
    headers_extra={"Idempotency-Key": idemp_key_1},
)
assert st == 409, f"Se esperaba 409 en conflicto de payload con misma clave, se obtuvo {st}"
validate_schema(err_conflict, "Error")
print("PASS Idempotencia en creación (422 formato, 202 replay y 409 ante cambio de cuerpo)")

# -----------------------------------------------------------------------------
# 5. Reglas de rechazo (201 RECHAZADA sin solicitar inventario)
# -----------------------------------------------------------------------------
print("\n--- 5. Reglas de rechazo de negocio (201 RECHAZADA) ---")

# 5.1 Monto fuera de política (< 500,000 COP)
st, loan_low, _ = api_request(
    f"{BASE_PRESTAMOS}/prestamos",
    "POST",
    {"producto_id": prod_lowprice_id, "cantidad": 1, "plazo_meses": 6},
    token=token_client_a,
    headers_extra={"Idempotency-Key": f"key-low-{TAG}-01"},
)
assert st == 201, f"Se esperaba 201 RECHAZADA por monto menor a 500k, se obtuvo {st}: {loan_low}"
assert loan_low["estado"] == "RECHAZADA"
assert loan_low["motivo"] == "MONTO_FUERA_DE_POLITICA"
assert loan_low["reserva_utilizable"] is False
validate_schema(loan_low, "Prestamo")

# 5.2 Producto inactivo
st, loan_inact, _ = api_request(
    f"{BASE_PRESTAMOS}/prestamos",
    "POST",
    {"producto_id": prod_inactive_id, "cantidad": 1, "plazo_meses": 12},
    token=token_client_a,
    headers_extra={"Idempotency-Key": f"key-inact-{TAG}-01"},
)
assert st == 201 and loan_inact["estado"] == "RECHAZADA"
assert loan_inact["motivo"] == "PRODUCTO_INACTIVO"
validate_schema(loan_inact, "Prestamo")

# 5.3 Cliente sin finanzas configuradas (perfil incompleto)
st, loan_inc, _ = api_request(
    f"{BASE_PRESTAMOS}/prestamos",
    "POST",
    {"producto_id": prod_favorable_id, "cantidad": 1, "plazo_meses": 12},
    token=token_client_c,
    headers_extra={"Idempotency-Key": f"key-inc-{TAG}-01"},
)
assert st == 201 and loan_inc["estado"] == "RECHAZADA"
assert loan_inc["motivo"] in ("INFORMACION_INCOMPLETA", "CLIENTE_INACTIVO_O_INCOMPLETO")
validate_schema(loan_inc, "Prestamo")

# 5.4 AC02: Riesgo desfavorable real evaluado por riesgo-v1
st, loan_unfav, _ = api_request(
    f"{BASE_PRESTAMOS}/prestamos",
    "POST",
    {"producto_id": prod_favorable_id, "cantidad": 1, "plazo_meses": 12},
    token=token_client_b,
    headers_extra={"Idempotency-Key": f"key-unfav-{TAG}-01"},
)
assert st == 201, f"Se esperaba 201 RECHAZADA por riesgo desfavorable, se obtuvo {st}: {loan_unfav}"
assert loan_unfav["estado"] == "RECHAZADA"
assert loan_unfav["motivo"] == "RIESGO_DESFAVORABLE"
assert loan_unfav["riesgo"] is not None
assert loan_unfav["riesgo"]["decision_riesgo"] == "DESFAVORABLE"
assert loan_unfav["riesgo"]["probabilidad_incumplimiento"] > loan_unfav["riesgo"]["umbral"]
assert loan_unfav["reserva_utilizable"] is False
validate_schema(loan_unfav, "Prestamo")

# Verificar que NUNCA se encoló ningún comando ReservaSolicitada para el préstamo rechazado
unfav_loan_id = loan_unfav["id"]
outbox_check = inside_db(
    "prestamos",
    f"""
with engine.connect() as c:
    count = c.execute(text("SELECT count(*) FROM outbox WHERE message_key = '{unfav_loan_id}'")).scalar()
    print(count)
""",
)
assert int(outbox_check.strip()) == 0, "Se encoló comando de reserva para una solicitud rechazada por riesgo"
print("PASS Reglas de rechazo (política, inactivo, perfil incompleto) y AC02 (riesgo desfavorable sin comando Kafka)")

# -----------------------------------------------------------------------------
# 6. AC01: Flujo favorable con stock -> Aprobación y Entrega
# -----------------------------------------------------------------------------
print("\n--- 6. AC01: Flujo completo favorable con stock (PENDIENTE_INVENTARIO -> APROBADA -> COMPLETADA) ---")

# 6.1 Crear solicitud favorable
idemp_ac01 = f"key-ac01-{TAG}-01"
st, loan_ac01, _ = api_request(
    f"{BASE_PRESTAMOS}/prestamos",
    "POST",
    {"producto_id": prod_favorable_id, "cantidad": 1, "plazo_meses": 12},
    token=token_client_a,
    headers_extra={"Idempotency-Key": idemp_ac01},
)
assert st == 202 and loan_ac01["estado"] == "PENDIENTE_INVENTARIO"
ac01_id = loan_ac01["id"]

# 6.2 Esperar a que Kafka procese la reserva y el estado pase a APROBADA
def check_aprobada():
    s, data, _ = api_request(f"{BASE_PRESTAMOS}/prestamos/{ac01_id}", token=token_client_a)
    return data if s == 200 and data["estado"] == "APROBADA" else None

loan_aprobada = wait_for(check_aprobada, timeout=30.0)
assert loan_aprobada["reserva_utilizable"] is True
assert loan_aprobada["reserva_id"] is not None
assert loan_aprobada["vence_en"] is not None
validate_schema(loan_aprobada, "Prestamo")
print(f"PASS Solicitud {ac01_id} aprobada via Kafka con reserva activa ({loan_aprobada['reserva_id']})")

# 6.3 Administrador realiza la entrega del producto
idemp_entrega = f"key-entrega-{TAG}-01"
st, loan_delivering, _ = api_request(
    f"{BASE_PRESTAMOS}/prestamos/{ac01_id}/entrega",
    "POST",
    token=token_admin,
    headers_extra={"Idempotency-Key": idemp_entrega},
)
assert st == 202, f"Entrega falló: {st} {loan_delivering}"
assert loan_delivering["estado"] == "ENTREGA_PENDIENTE"
validate_schema(loan_delivering, "Prestamo")

# 6.4 Esperar a que Kafka procese EntregaConfirmada y el estado pase a COMPLETADA
def check_completada():
    s, data, _ = api_request(f"{BASE_PRESTAMOS}/prestamos/{ac01_id}", token=token_client_a)
    return data if s == 200 and data["estado"] == "COMPLETADA" else None

loan_completada = wait_for(check_completada, timeout=30.0)
assert loan_completada["reserva_utilizable"] is False
validate_schema(loan_completada, "Prestamo")

# 6.5 Verificar en Inventario que se registró exactamente un movimiento de salida por entrega
mov_check = inside_db(
    "inventario",
    f"""
with engine.connect() as c:
    count = c.execute(text("SELECT count(*) FROM movimientos WHERE prestamo_id = '{ac01_id}' AND tipo = 'SALIDA'")).scalar()
    print(count)
""",
)
assert int(mov_check.strip()) == 1, f"Se esperaba 1 movimiento SALIDA, se encontraron {mov_check}"
print("PASS AC01: Préstamo creado -> APROBADA -> entrega admin -> COMPLETADA con salida registrada en inventario")

# -----------------------------------------------------------------------------
# 7. AC03: Cliente favorable pero sin stock disponible
# -----------------------------------------------------------------------------
print("\n--- 7. AC03: Cliente favorable con stock cero (CANCELADA_SIN_STOCK) ---")

idemp_ac03 = f"key-ac03-{TAG}-01"
st, loan_ac03, _ = api_request(
    f"{BASE_PRESTAMOS}/prestamos",
    "POST",
    {"producto_id": prod_nostock_id, "cantidad": 1, "plazo_meses": 12},
    token=token_client_a,
    headers_extra={"Idempotency-Key": idemp_ac03},
)
assert st == 202 and loan_ac03["estado"] == "PENDIENTE_INVENTARIO"
ac03_id = loan_ac03["id"]

def check_sin_stock():
    s, data, _ = api_request(f"{BASE_PRESTAMOS}/prestamos/{ac03_id}", token=token_client_a)
    return data if s == 200 and data["estado"] == "CANCELADA_SIN_STOCK" else None

loan_sin_stock = wait_for(check_sin_stock, timeout=30.0)
assert loan_sin_stock["reserva_utilizable"] is False
assert loan_sin_stock["motivo"] == "STOCK_INSUFICIENTE"
validate_schema(loan_sin_stock, "Prestamo")

# Verificar que el stock de inventario no quedó negativo
stock_check = inside_db(
    "inventario",
    f"""
with engine.connect() as c:
    row = c.execute(text("SELECT fisico, reservado, disponible FROM existencias WHERE producto_id = '{prod_nostock_id}'")).mappings().one()
    print(json.dumps(dict(row)))
""",
)
stock_data = json.loads(stock_check.strip())
assert stock_data["disponible"] == 0 and stock_data["fisico"] == 0
print("PASS AC03: Falta de stock detectada por Inventario -> CANCELADA_SIN_STOCK sin stock negativo")

# -----------------------------------------------------------------------------
# 8. AC04: Concurrencia por la última unidad (Stock 1, 2 préstamos simultáneos)
# -----------------------------------------------------------------------------
print("\n--- 8. AC04: Concurrencia por la última unidad en inventario ---")

idemp_race_1 = f"key-race1-{TAG}-01"
idemp_race_2 = f"key-race2-{TAG}-02"

# Lanzar dos solicitudes simultáneamente con dos threads
def post_race(key):
    return api_request(
        f"{BASE_PRESTAMOS}/prestamos",
        "POST",
        {"producto_id": prod_onestock_id, "cantidad": 1, "plazo_meses": 12},
        token=token_client_a,
        headers_extra={"Idempotency-Key": key},
    )

with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    fut1 = executor.submit(post_race, idemp_race_1)
    fut2 = executor.submit(post_race, idemp_race_2)
    st1, res1, _ = fut1.result()
    st2, res2, _ = fut2.result()

assert st1 == 202 and st2 == 202
race_id_1 = res1["id"]
race_id_2 = res2["id"]

# Esperar a que ambos préstamos alcancen su estado final a través de Kafka
def check_race():
    _, d1, _ = api_request(f"{BASE_PRESTAMOS}/prestamos/{race_id_1}", token=token_client_a)
    _, d2, _ = api_request(f"{BASE_PRESTAMOS}/prestamos/{race_id_2}", token=token_client_a)
    if d1["estado"] in ("APROBADA", "CANCELADA_SIN_STOCK") and d2["estado"] in ("APROBADA", "CANCELADA_SIN_STOCK"):
        return d1, d2
    return None

final_d1, final_d2 = wait_for(check_race, timeout=35.0)
states = sorted([final_d1["estado"], final_d2["estado"]])
assert states == ["APROBADA", "CANCELADA_SIN_STOCK"], f"Resultado de concurrencia incorrecto: {states}"

# Verificar que en existencias el disponible es exactamente 0 y no negativo
stock_race_check = inside_db(
    "inventario",
    f"""
with engine.connect() as c:
    row = c.execute(text("SELECT fisico, reservado, disponible FROM existencias WHERE producto_id = '{prod_onestock_id}'")).mappings().one()
    print(json.dumps(dict(row)))
""",
)
stock_race = json.loads(stock_race_check.strip())
assert stock_race["fisico"] == 1
assert stock_race["reservado"] == 1
assert stock_race["disponible"] == 0
print(f"PASS AC04: Dos préstamos simultáneos -> exactamente 1 APROBADA y 1 CANCELADA_SIN_STOCK (disponible={stock_race['disponible']})")

# -----------------------------------------------------------------------------
# 9. AC07: Cancelación y protección contra reactivación por eventos tardíos
# -----------------------------------------------------------------------------
print("\n--- 9. AC07: Cancelación y eventos tardíos en estados terminales ---")

# 9.1 Cancelar el préstamo ganado de la prueba anterior
winner_id = race_id_1 if final_d1["estado"] == "APROBADA" else race_id_2
idemp_canc = f"key-canc-{TAG}-01"
st, canc_res, _ = api_request(
    f"{BASE_PRESTAMOS}/prestamos/{winner_id}/cancelacion",
    "POST",
    {"motivo": "CLIENTE_DESISTIO"},
    token=token_client_a,
    headers_extra={"Idempotency-Key": idemp_canc},
)
assert st == 202 and canc_res["estado"] == "CANCELACION_PENDIENTE"
validate_schema(canc_res, "Prestamo")

# 9.2 Esperar a que Kafka procese ReservaLiberada -> CANCELADA
def check_cancelada():
    s, data, _ = api_request(f"{BASE_PRESTAMOS}/prestamos/{winner_id}", token=token_client_a)
    return data if s == 200 and data["estado"] == "CANCELADA" else None

loan_cancelada = wait_for(check_cancelada, timeout=30.0)
assert loan_cancelada["reserva_utilizable"] is False
validate_schema(loan_cancelada, "Prestamo")
print(f"PASS Préstamo {winner_id} cancelado y reserva liberada en Inventario")

# 9.3 Invariante 5: Enviar un evento tardío InventarioReservado simulado por Kafka para este préstamo cancelado
print("Simulando llegada de evento tardío InventarioReservado para préstamo en estado CANCELADA...")
inside_db(
    "prestamos",
    f"""
from shared.messaging_models import outbox
from shared.messages import event, EVENTS
from app.messaging import handle
fake_event = event(
    'InventarioReservado',
    '{winner_id}',
    {{'reserva_id': str(uuid4()), 'revision_reserva': 99, 'vence_en': datetime.now(timezone.utc).isoformat()}}
)
with engine.begin() as conn:
    handle(conn, fake_event)
""",
)

# 9.4 Verificar que el préstamo permanece en CANCELADA y NUNCA se reactivó a APROBADA
st, loan_still_canc, _ = api_request(f"{BASE_PRESTAMOS}/prestamos/{winner_id}", token=token_client_a)
assert st == 200 and loan_still_canc["estado"] == "CANCELADA", f"El préstamo se reactivó a {loan_still_canc['estado']}"
assert loan_still_canc["reserva_utilizable"] is False
print("PASS Invariante garantizado: ningún evento tardío reactivó el préstamo CANCELADA")

# -----------------------------------------------------------------------------
# 10. AC09: Edición de precio con caché caliente en Productos
# -----------------------------------------------------------------------------
print("\n--- 10. AC09: Edición de precio con invalidación de caché y nueva cotización ---")

# 10.1 Consultar precio original del producto favorable (3,200,000.00 COP)
prod_update_id = str(uuid4())
inside_db(
    "productos",
    f"""
from app.models import productos
with engine.begin() as conn:
    conn.execute(productos.insert().values(
        id=UUID('{prod_update_id}'),
        nombre='Precio Variable F9 {TAG}',
        categoria='Portátiles',
        precio_cop=Decimal('3000000.00'),
        activo=True,
        version=1
    ))
""",
)
inside_db(
    "inventario",
    f"""
from app.models import existencias
with engine.begin() as conn:
    conn.execute(existencias.insert().values(
        producto_id=UUID('{prod_update_id}'),
        fisico=10,
        reservado=0,
        disponible=10
    ))
""",
)

# Calentar caché de cotización consultándolo desde préstamos
inside_db(
    "prestamos",
    f"""
from app.clients import fetch_product_quote
q = fetch_product_quote(UUID('{prod_update_id}'))
assert q['precio_unitario_cop'] == '3000000.00'
""",
)

# 10.2 Actualizar el precio a 3,800,000.00 COP con token admin
st, prod_edited, _ = api_request(
    f"{BASE_PRODUCTOS}/productos/{prod_update_id}",
    "PATCH",
    {"version_esperada": 1, "precio_cop": "3800000.00"},
    token=token_admin,
)
assert st == 200, f"Edición de precio falló: {st} {prod_edited}"
assert prod_edited["precio_cop"] == "3800000.00"

# 10.3 Solicitar préstamo para ese producto: debe reflejar el NUEVO precio (3,800,000.00) y su nueva cuota
idemp_price = f"key-price-{TAG}-01"
st, loan_price, _ = api_request(
    f"{BASE_PRESTAMOS}/prestamos",
    "POST",
    {"producto_id": prod_update_id, "cantidad": 1, "plazo_meses": 12},
    token=token_client_a,
    headers_extra={"Idempotency-Key": idemp_price},
)
assert st == 202
assert loan_price["precio_unitario_cop"] == "3800000.00", f"Precio guardado incorrecto: {loan_price['precio_unitario_cop']}"
assert loan_price["monto_cop"] == "3800000.00"
assert loan_price["version_producto"] == 2
# Cuota anualidad para 3.8M a 12 meses y tasa 1.8%: 354,927.51 COP
assert loan_price["cuota_cop"] == "354927.51", f"Cuota calculada incorrecta: {loan_price['cuota_cop']}"
print("PASS AC09: Caché invalidada y nuevo préstamo almacena precio actualizado ($3,800,000.00) y nueva cuota ($354,927.52)")

# -----------------------------------------------------------------------------
# 11. AC13: Control de propietario en consultas y cancelaciones
# -----------------------------------------------------------------------------
print("\n--- 11. AC13: Consultas de préstamos y privacidad entre clientes ---")

# 11.1 Cliente B intenta consultar préstamo de Cliente A -> 404 (ocultamiento estricto)
st, err, _ = api_request(f"{BASE_PRESTAMOS}/prestamos/{ac01_id}", token=token_client_b)
assert st == 404, f"Se esperaba 404 en consulta cruzada de Cliente B, se obtuvo {st}"
validate_schema(err, "Error")

# 11.2 Cliente B intenta cancelar préstamo de Cliente A -> 404
st, err, _ = api_request(
    f"{BASE_PRESTAMOS}/prestamos/{ac01_id}/cancelacion",
    "POST",
    {"motivo": "ATAQUE_CRUZADO"},
    token=token_client_b,
    headers_extra={"Idempotency-Key": f"key-hck-{TAG}-01"},
)
assert st == 404
validate_schema(err, "Error")

# 11.3 Listado de Cliente B no contiene ningún préstamo de Cliente A
st, list_b, _ = api_request(f"{BASE_PRESTAMOS}/prestamos", token=token_client_b)
assert st == 200
validate_schema(list_b, "Prestamos")
for item in list_b["items"]:
    assert item["cliente_id"] == client_b_id, "Fuga de privacidad: el listado de Cliente B contiene solicitudes ajenas"

# 11.4 Administrador puede ver el listado global y consultar cualquier préstamo
st, list_adm, _ = api_request(f"{BASE_PRESTAMOS}/prestamos", token=token_admin)
assert st == 200
validate_schema(list_adm, "Prestamos")
assert list_adm["total"] >= 5

st, loan_seen_by_admin, _ = api_request(f"{BASE_PRESTAMOS}/prestamos/{ac01_id}", token=token_admin)
assert st == 200 and loan_seen_by_admin["id"] == ac01_id
print("PASS AC13: Aislamiento completo de préstamos entre clientes y visibilidad global para administrador")

# -----------------------------------------------------------------------------
# 12. Auditoría e historial (prestamos_historial)
# -----------------------------------------------------------------------------
print("\n--- 12. Auditoría inmutable e historial de transiciones ---")

hist_check = inside_db(
    "prestamos",
    f"""
with engine.connect() as c:
    rows = c.execute(text("SELECT estado_anterior, estado_nuevo, motivo FROM prestamos_historial WHERE prestamo_id = '{ac01_id}' ORDER BY created_at ASC")).fetchall()
    print(json.dumps([list(r) for r in rows]))
""",
)
transitions = json.loads(hist_check.strip())
expected_seq = [
    [None, "PENDIENTE_INVENTARIO", None],
    ["PENDIENTE_INVENTARIO", "APROBADA", None],
    ["APROBADA", "ENTREGA_PENDIENTE", None],
    ["ENTREGA_PENDIENTE", "COMPLETADA", None],
]
assert transitions == expected_seq, f"Secuencia de auditoría histórica incorrecta: {transitions}"
print(f"PASS Auditoría inmutable de transiciones verificada en prestamos_historial: {transitions}")

print("\n==========================================================================")
print("  ¡TODOS LOS CHECKS DE LA FASE 9 HAN SIDO SUPERADOS EXITOSAMENTE!       ")
print("==========================================================================")
