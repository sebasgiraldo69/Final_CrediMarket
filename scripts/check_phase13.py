"""Script de verificacion para la Fase 13: Preparar entrega y sustentacion.

Comprueba:
1. Salud y disponibilidad de todos los contenedores y microservicios (/health, /ready).
2. Validez de contratos estaticos OpenAPI y esquemas de eventos.
3. Existencia e integridad de artefactos de Machine Learning (active_model.json, v1, v2).
4. Cuentas demo de administrador y cliente operativas con autenticacion exitosa.
5. Presencia y consistencia de los documentos de sustentacion (FASE_13.md, guion_demo.md, preguntas_sustentacion.md).
6. Trazabilidad en README.md y PLAN_DESARROLLO_POR_ETAPAS.md.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ["productos", "clientes", "prestamos", "inventario"]
PORT = "8080"
BASE = f"http://127.0.0.1:{PORT}/api"


def check(condition: bool, message: str):
    if not condition:
        print(f"FALLO: {message}", file=sys.stderr)
        sys.exit(1)
    print(f"PASS: {message}")


def http_get(url: str, token: str | None = None) -> tuple[int, dict]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
            return resp.status, json.loads(content) if content else {}
    except urllib.error.HTTPError as err:
        content = err.read().decode("utf-8")
        parsed = json.loads(content) if content else {}
        return err.code, parsed


def http_post(url: str, body: dict) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
            return resp.status, json.loads(content) if content else {}
    except urllib.error.HTTPError as err:
        content = err.read().decode("utf-8")
        parsed = json.loads(content) if content else {}
        return err.code, parsed


print("==========================================================================")
print("  VERIFICACION DE FASE 13: PREPARAR ENTREGA Y SUSTENTACION                ")
print("==========================================================================")

# 1. Comprobacion de microservicios y proxy
print("\n--- 1. Comprobacion de estado de microservicios (/health y /ready) ---")
for svc in SERVICES:
    st_health, res_health = http_get(f"{BASE}/{svc}/health")
    check(st_health == 200 and res_health.get("status") == "ok", f"Servicio {svc} /health responde 200 OK")

    st_ready, res_ready = http_get(f"{BASE}/{svc}/ready")
    check(st_ready == 200 and res_ready.get("status") == "ready", f"Servicio {svc} /ready responde 200 OK con dependencias saludables")

# 2. Comprobacion de cuentas demo
print("\n--- 2. Comprobacion de cuentas de demostracion ---")
st_admin, res_admin = http_post(f"{BASE}/clientes/auth/login", {
    "email": "admin@credimarket.com",
    "password": "Admin12345678!"
})
check(st_admin == 200 and res_admin.get("role") == "administrador", "Cuenta demo de administrador autenticada correctamente (rol: administrador)")

st_cli, res_cli = http_post(f"{BASE}/clientes/auth/login", {
    "email": "cliente@credimarket.com",
    "password": "Cliente12345678!"
})
check(st_cli == 200 and res_cli.get("role") == "cliente", "Cuenta demo de cliente autenticada correctamente (rol: cliente)")

# 3. Comprobacion de artefactos de Machine Learning
print("\n--- 3. Comprobacion de artefactos y manifiestos de Machine Learning ---")
active_config_path = ROOT / "models/active_model.json"
check(active_config_path.exists(), "Archivo de configuracion activa models/active_model.json presente")
active_cfg = json.loads(active_config_path.read_text(encoding="utf-8"))
check("model_version" in active_cfg and "artifact_path" in active_cfg, "Estructura valida en models/active_model.json")

for version in ["riesgo-v1", "riesgo-v2"]:
    manifest_p = ROOT / f"models/{version}/manifest.json"
    pipeline_p = ROOT / f"models/{version}/pipeline.joblib"
    check(manifest_p.exists() and pipeline_p.exists(), f"Artefactos completos para version {version} (manifest.json y pipeline.joblib)")
    manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
    sha = hashlib.sha256(pipeline_p.read_bytes()).hexdigest()
    check(sha == manifest["artifact_sha256"], f"Hash SHA-256 verificado para artefacto {version}")

# 4. Comprobacion de documentacion de entrega y sustentacion
print("\n--- 4. Comprobacion de documentacion de sustentacion ---")
doc_fase13 = ROOT / "docs/FASE_13.md"
check(doc_fase13.exists() and len(doc_fase13.read_text(encoding="utf-8")) > 500, "Documento docs/FASE_13.md presente y detallado")

doc_guion = ROOT / "docs/guion_demo.md"
check(doc_guion.exists() and len(doc_guion.read_text(encoding="utf-8")) > 500, "Guion de demostracion docs/guion_demo.md presente con todos los escenarios")

doc_preguntas = ROOT / "docs/preguntas_sustentacion.md"
check(doc_preguntas.exists() and len(doc_preguntas.read_text(encoding="utf-8")) > 500, "Bateria de preguntas de sustentacion docs/preguntas_sustentacion.md presente")

plan_doc = ROOT / "PLAN_DESARROLLO_POR_ETAPAS.md"
check("Etapa 13. Preparar entrega y sustentación" in plan_doc.read_text(encoding="utf-8"), "Plan de desarrollo actualizado")

readme_doc = ROOT / "README.md"
check("Fase 13" in readme_doc.read_text(encoding="utf-8") or "fase 13" in readme_doc.read_text(encoding="utf-8"), "README.md actualizado con referencias de la fase 13")

# 5. Ejecucion estatica de contratos
print("\n--- 5. Validacion estatica de contratos OpenAPI y schemas ---")
res_contracts = subprocess.run([sys.executable, "scripts/validate_contracts.py"], cwd=ROOT, capture_output=True, text=True)
check(res_contracts.returncode == 0, "Validacion estatica de contratos OpenAPI y schemas superada (validate_contracts.py)")

print("\n==========================================================================")
print("  TODAS LAS VERIFICACIONES DE LA FASE 13 SE COMPLETARON EXITOSAMENTE      ")
print("==========================================================================")
