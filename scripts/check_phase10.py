"""Pruebas de navegador de la fase 10 (frontend integrado) con Playwright.

Recorre la interfaz real servida en http://127.0.0.1:${FRONTEND_PORT}, sin respuestas simuladas:
- Administrador: login, crear producto, registrar entrada de stock, ver ficha del modelo y clientes.
- Cliente favorable: solicitar crédito desde el catálogo, seguir el estado por polling hasta APROBADA,
  entrega confirmada por el administrador (COMPLETADA) y cancelación de otra solicitud (CANCELADA).
- Cliente desfavorable: RECHAZADA con motivo legible.
- Idempotencia: respuesta perdida tras llegar al servidor; el reintento reutiliza la Idempotency-Key y no duplica.
- Errores: API caída y recuperación, sesión vencida, navegación por rol, persistencia tras recargar.
- Móvil: 375 px sin desplazamiento horizontal.

Requisitos: stack levantado y `python -m pip install -r requirements-e2e.txt && python -m playwright install chromium`.
"""
import json
from pathlib import Path
import secrets
import subprocess
import urllib.error
import urllib.request
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
env = dict(line.split("=", 1) for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
           if "=" in line and not line.startswith("#"))
BASE = f"http://127.0.0.1:{env.get('FRONTEND_PORT', '8080')}"
TAG = uuid4().hex[:8]
PASSWORD = secrets.token_urlsafe(18)
WAIT = 45_000  # ms: reserva y entrega pasan por Kafka


def api(path, method="GET", body=None, token=None, headers=None):
    request_headers = {**(headers or {})}
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{BASE}/api/{path}", data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


def create_admin(email):
    script = f"""
from uuid import uuid4
from sqlalchemy import create_engine
from shared.runtime import database_url
from app.models import usuarios
from app.security import hasher
with create_engine(database_url()).begin() as conn:
    conn.execute(usuarios.insert().values(id=uuid4(), email={email!r}, password_hash=hasher.hash({PASSWORD!r}), rol='administrador'))
"""
    subprocess.run(["docker", "compose", "exec", "-T", "clientes", "python", "-"], cwd=ROOT, input=script,
                   text=True, check=True, capture_output=True)


def login_api(email):
    status, data = api("clientes/auth/login", "POST", {"email": email, "password": PASSWORD})
    assert status == 200, (status, data)
    return data


def client_with_finances(name, finances, admin_token):
    email = f"{name}-{TAG}@example.com"
    status, _ = api("clientes/clientes", "POST", {"nombre": f"{name} {TAG}", "email": email, "password": PASSWORD})
    assert status == 201
    data = login_api(email)
    status, body = api(f"clientes/clientes/{data['cliente_id']}", "PATCH", {"version_esperada": 1, "finanzas": finances}, admin_token)
    assert status == 200, (status, body)
    return email, data


def ui_login(page, email):
    page.goto(f"{BASE}/acceso")
    page.get_by_label("Correo").fill(email)
    page.get_by_label("Contraseña").fill(PASSWORD)
    page.get_by_role("button", name="Ingresar", exact=True).click()
    expect(page.get_by_role("button", name="Cerrar sesión")).to_be_visible()


def go(page, section):
    page.get_by_role("navigation").get_by_role("link", name=section, exact=True).click()


def loan_row(page, product):
    return page.locator("tbody tr", has_text=product).first


FAVORABLE = {"ingresos_mensuales_cop": "6500000.00", "obligaciones_mensuales_cop": "800000.00", "tipo_empleo": "dependiente",
             "antiguedad_laboral_meses": 36, "meses_historial_crediticio": 48, "creditos_previos": 2,
             "atrasos_previos_30d": 0, "porcentaje_pago_puntual": 98.5}
UNFAVORABLE = {"ingresos_mensuales_cop": "1400000.00", "obligaciones_mensuales_cop": "1150000.00", "tipo_empleo": "independiente",
               "antiguedad_laboral_meses": 5, "meses_historial_crediticio": 12, "creditos_previos": 3,
               "atrasos_previos_30d": 3, "porcentaje_pago_puntual": 50.0}

print("Fase 10: pruebas de navegador")
admin_email = f"admin-f10-{TAG}@example.com"
create_admin(admin_email)
admin_token = login_api(admin_email)["access_token"]
client_a, session_a = client_with_finances("cliente-a", FAVORABLE, admin_token)
client_b, _ = client_with_finances("cliente-b", UNFAVORABLE, admin_token)

product_ui = f"Portátil UI {TAG}"
product_api = f"Tableta API {TAG}"
status, created = api("productos/productos", "POST", {"nombre": product_api, "categoria": "Tabletas", "precio_cop": "1800000.00"}, admin_token)
assert status == 201, created
status, _ = api("inventario/inventario/entradas", "POST", {"producto_id": created["id"], "cantidad": 3, "motivo": "Prueba fase 10"},
                admin_token, {"Idempotency-Key": f"f10-entrada-{TAG}"})
assert status == 201

with sync_playwright() as pw:
    browser = pw.chromium.launch()

    # 1. Administrador: producto, stock, modelo y clientes desde la interfaz.
    admin = browser.new_context().new_page()
    ui_login(admin, admin_email)
    expect(admin.get_by_role("navigation").get_by_role("link", name="Inventario", exact=True)).to_be_visible()
    go(admin, "Catálogo")
    admin.get_by_role("button", name="Nuevo producto").click()
    dialog = admin.get_by_role("dialog")
    dialog.get_by_label("Nombre").fill(product_ui)
    dialog.get_by_label("Categoría").fill("Portátiles")
    dialog.get_by_label("Precio (COP)").fill("2500000")
    dialog.get_by_role("button", name="Guardar").click()
    expect(admin.get_by_text(f"Producto «{product_ui}» creado.")).to_be_visible()

    go(admin, "Inventario")
    admin.get_by_role("button", name="Registrar entrada").click()
    dialog = admin.get_by_role("dialog")
    dialog.get_by_label("Producto").select_option(label=f"{product_ui} · Portátiles")
    dialog.get_by_label("Cantidad").fill("2")
    dialog.get_by_role("button", name="Registrar", exact=True).click()
    expect(admin.get_by_text(f"Entrada registrada: +2 de {product_ui}.")).to_be_visible()
    expect(admin.locator("tbody tr", has_text=product_ui)).to_contain_text("2")

    go(admin, "Modelo")
    expect(admin.get_by_text("riesgo-v1").first).to_be_visible()
    expect(admin.get_by_text("Métricas en prueba")).to_be_visible()
    mlflow_url = admin.get_by_role("link", name="Abrir MLflow").get_attribute("href")
    with urllib.request.urlopen(f"{mlflow_url.rstrip('/')}/health", timeout=5) as response:
        assert response.status == 200 and "AirTunes" not in response.headers.get("Server", ""), mlflow_url
    go(admin, "Clientes")
    expect(admin.get_by_role("heading", name="Importar clientes (CSV)")).to_be_visible()
    print("  OK administrador: producto, entrada de stock, ficha del modelo y clientes")

    # 2. Cliente favorable: solicitud hasta APROBADA por polling, sin recargar.
    client = browser.new_context().new_page()
    ui_login(client, client_a)
    nav = client.get_by_role("navigation")
    expect(nav.get_by_role("link", name="Inventario", exact=True)).to_have_count(0)
    go(client, "Catálogo")
    client.get_by_label("Buscar").fill(product_ui)
    client.get_by_role("button", name="Solicitar a crédito").click()
    dialog = client.get_by_role("dialog")
    dialog.get_by_label("Plazo").select_option("24")
    dialog.get_by_role("button", name="Enviar solicitud").click()
    expect(dialog.get_by_role("heading", name="Resultado de la solicitud")).to_be_visible()
    expect(dialog).to_contain_text("2.500.000")
    dialog.get_by_role("button", name="Ver mis solicitudes").click()
    expect(loan_row(client, product_ui).locator(".state-pill")).to_have_text("Aprobada", timeout=WAIT)
    print("  OK cliente: solicitud aprobada y visible sin recargar")

    # 3. Idempotencia: la primera respuesta se pierde después de llegar al servidor.
    keys = []
    client.on("request", lambda r: keys.append(r.headers.get("idempotency-key")) if r.method == "POST" and r.url.endswith("/api/prestamos/prestamos") else None)
    before = api("prestamos/prestamos?limit=1", token=session_a["access_token"])[1]["total"]
    lost = {"done": False}

    def lose_first_response(route):
        if route.request.method == "POST" and not lost["done"]:
            lost["done"] = True
            route.fetch()
            route.abort("connectionreset")
        else:
            route.continue_()

    client.route("**/api/prestamos/prestamos", lose_first_response)
    go(client, "Catálogo")
    client.get_by_label("Buscar").fill(product_api)
    client.get_by_role("button", name="Solicitar a crédito").click()
    dialog = client.get_by_role("dialog")
    dialog.get_by_role("button", name="Enviar solicitud").click()
    expect(dialog.get_by_role("alert")).to_contain_text("No hay conexión")
    dialog.get_by_role("button", name="Reintentar envío").click()
    expect(dialog.get_by_role("heading", name="Resultado de la solicitud")).to_be_visible()
    client.unroute("**/api/prestamos/prestamos")
    assert len(keys) == 2 and keys[0] and keys[0] == keys[1], keys
    after = api("prestamos/prestamos?limit=1", token=session_a["access_token"])[1]["total"]
    assert after == before + 1, (before, after)
    print("  OK idempotencia: reintento con la misma clave, una sola solicitud")

    # 4. Cancelación de la segunda solicitud.
    dialog.get_by_role("button", name="Ver mis solicitudes").click()
    row = loan_row(client, product_api)
    expect(row.locator(".state-pill")).to_have_text("Aprobada", timeout=WAIT)
    row.get_by_role("button", name="Cancelar").click()
    dialog = client.get_by_role("dialog")
    dialog.get_by_label("Motivo").fill("Prueba de cancelación")
    dialog.get_by_role("button", name="Confirmar cancelación").click()
    expect(row.locator(".state-pill")).to_have_text("Cancelada", timeout=WAIT)
    print("  OK cancelación confirmada por Inventario")

    # 5. Entrega por el administrador; el cliente la ve por polling.
    go(admin, "Solicitudes")
    admin_row = loan_row(admin, product_ui)
    admin_row.get_by_role("button", name="Entregar").click()
    admin.get_by_role("dialog").get_by_role("button", name="Confirmar entrega").click()
    expect(admin_row.locator(".state-pill")).to_have_text("Entregada", timeout=WAIT)
    expect(loan_row(client, product_ui).locator(".state-pill")).to_have_text("Entregada", timeout=WAIT)
    print("  OK entrega completada y visible para el cliente")

    # 6. Persistencia tras recargar y permisos por rol.
    client.reload()
    expect(loan_row(client, product_ui).locator(".state-pill")).to_have_text("Entregada")
    client.goto(f"{BASE}/inventario")
    expect(client.get_by_text("Permiso insuficiente")).to_be_visible()
    print("  OK persistencia tras recargar y bloqueo por rol")

    # 7. API caída y recuperación.
    client.route("**/api/productos/**", lambda route: route.abort("connectionrefused"))
    client.goto(f"{BASE}/catalogo")
    expect(client.get_by_role("alert")).to_contain_text("No hay conexión")
    client.unroute("**/api/productos/**")
    client.get_by_role("button", name="Actualizar").click()
    expect(client.get_by_role("button", name="Solicitar a crédito").first).to_be_visible()
    print("  OK API caída muestra error y se recupera")

    # 8. Sesión vencida: el token deja de ser válido.
    client.evaluate("""() => { const s = JSON.parse(sessionStorage.getItem('credimarket.session'));
      s.access_token = 'token.invalido.x'; sessionStorage.setItem('credimarket.session', JSON.stringify(s)); }""")
    client.goto(f"{BASE}/solicitudes")
    expect(client.get_by_text("Tu sesión venció")).to_be_visible()
    expect(client.get_by_label("Contraseña")).to_be_visible()
    print("  OK sesión vencida lleva al acceso")

    # 9. Cliente desfavorable: rechazo con motivo legible.
    rejected = browser.new_context().new_page()
    ui_login(rejected, client_b)
    go(rejected, "Catálogo")
    rejected.get_by_label("Buscar").fill(product_ui)
    rejected.get_by_role("button", name="Solicitar a crédito").click()
    dialog = rejected.get_by_role("dialog")
    dialog.get_by_role("button", name="Enviar solicitud").click()
    expect(dialog.locator(".state-pill")).to_have_text("Rechazada")
    expect(dialog).to_contain_text("modelo de riesgo")
    print("  OK rechazo por riesgo con motivo legible")

    # 10. Móvil: sin desplazamiento horizontal en las vistas con tablas.
    mobile = browser.new_context(viewport={"width": 375, "height": 812}, is_mobile=True).new_page()
    ui_login(mobile, client_a)
    for path in ("/solicitudes", "/catalogo", "/clientes"):
        mobile.goto(f"{BASE}{path}")
        mobile.wait_for_load_state("networkidle")
        overflow = mobile.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
        assert overflow <= 0, f"{path} desborda {overflow}px en móvil"
    print("  OK móvil 375 px sin desplazamiento horizontal")

    browser.close()

print("PASS: fase 10, recorrido completo desde el navegador.")
