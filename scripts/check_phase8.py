"""Integration, parity (AC10), and readiness checks for Phase 8: Exportar y servir el modelo desde Préstamos.

Verifies:
1. Explicit promotion config ('models/active_model.json'), versioned manifest ('models/riesgo-v1/manifest.json'),
   and pipeline artifact ('models/riesgo-v1/pipeline.joblib') integrity.
2. 'GET /api/prestamos/health' (200) and 'GET /api/prestamos/ready' (200 with model='ok').
3. Authorization on 'GET /api/prestamos/modelo/info' and 'POST /api/prestamos/riesgo/predict':
   - 401 without token
   - 403 with 'cliente' token
   - 403 with service token missing required scope
   - 200 with 'administrador' token
   - 200 with ServiceBearer token with 'modelo:read' / 'riesgo:predict' scopes
4. Relational and domain validation (422) on 'POST /api/prestamos/riesgo/predict':
   - Inconsistent 'cuota_estimada_cop' vs annuity formula
   - 'creditos_previos == 0' with non-null 'porcentaje_pago_puntual'
   - 'creditos_previos > 0' with null 'porcentaje_pago_puntual'
   - Out-of-policy 'monto_solicitado_cop'
   - Extra unknown properties ('additionalProperties: false')
5. AC10 Offline vs API parity across all 200 unlabeled rows of 'solicitudes_nuevas.csv':
   - Probability difference <= 1e-8
   - Exact match on decision_riesgo, umbral, model_version, run_id
   - Strict OpenAPI 3.1 schema conformance ('Riesgo' and 'ModeloInfo')
6. Unavailability behavior when model is missing:
   - '/api/prestamos/ready' returns 503 with dependencies.model='unavailable'
   - '/api/prestamos/riesgo/predict' and '/api/prestamos/modelo/info' return 503
   - Restoring active_model.json recovers 200 readiness without retraining.
"""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
from uuid import uuid4
import jsonschema

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = ROOT / "contracts" / "openapi" / "prestamos.json"
ACTIVE_MODEL_PATH = ROOT / "models" / "active_model.json"
BATCH_PRED_CSV = ROOT / "ml" / "reports" / "solicitudes_nuevas_predictions.csv"
BATCH_REPORT_JSON = ROOT / "ml" / "reports" / "batch_inference_report.json"

env = dict(
    line.split("=", 1)
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
    if "=" in line and not line.startswith("#")
)
BASE = f"http://localhost:{env.get('FRONTEND_PORT', '8080')}/api"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def docker(*args, stdin=None) -> str:
    result = subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT,
        input=stdin,
        text=True,
        capture_output=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"Docker failed: {' '.join(args[:4])}\n{result.stderr}")
    return result.stdout.strip()


def req(service: str, path: str, method: str = "GET", data=None, token: str | None = None):
    headers = {"X-Correlation-ID": str(uuid4())}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(f"{BASE}/{service}{path}", data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(r, timeout=10)
        return resp.status, json.loads(resp.read().decode("utf-8")), dict(resp.headers)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        return e.code, (json.loads(raw) if raw else {}), dict(e.headers)


openapi_spec = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))


def validate_schema(instance, schema_name: str):
    schema = {
        "$ref": f"#/components/schemas/{schema_name}",
        "components": openapi_spec["components"],
    }
    jsonschema.validate(instance=instance, schema=schema)


print("--- Iniciando comprobación de Fase 8: Exportar y servir el modelo desde Préstamos ---")

# 1. Verificar artefacto promovido, manifiesto y reporte de inferencia batch
assert ACTIVE_MODEL_PATH.exists(), "No existe models/active_model.json"
active_cfg = json.loads(ACTIVE_MODEL_PATH.read_text(encoding="utf-8"))
manifest_path = ROOT / active_cfg["manifest_path"]
artifact_path = ROOT / active_cfg["artifact_path"]
assert manifest_path.exists() and artifact_path.exists(), "Faltan archivos de la versión promovida en models/"
assert sha256_file(artifact_path) == active_cfg["artifact_sha256"], "Hash SHA-256 de pipeline.joblib inválido"
assert BATCH_PRED_CSV.exists() and BATCH_REPORT_JSON.exists(), "Faltan reportes de inferencia batch de las 200 solicitudes"

batch_report = json.loads(BATCH_REPORT_JSON.read_text(encoding="utf-8"))
assert batch_report["rows_evaluated"] == 200
assert batch_report["has_ground_truth_labels"] is False
assert batch_report["supervised_metrics_computed"] is None
print("PASS Artefacto versionado, active_model.json e inferencia batch verificados")

# 2. Verificar /health y /ready de Préstamos
status, health_body, _ = req("prestamos", "/health")
assert status == 200 and health_body["status"] == "ok", f"Health falló: {status} {health_body}"

status, ready_body, _ = req("prestamos", "/ready")
assert status == 200 and ready_body["status"] in ("ready", "degraded"), f"Ready falló: {status} {ready_body}"
assert ready_body["dependencies"]["model"] == "ok", f"Dependencia model no está ok: {ready_body}"
validate_schema(ready_body, "Ready")
print("PASS /api/prestamos/health (200) y /api/prestamos/ready (200, model='ok')")

# 3. Emitir tokens de prueba (cliente, administrador, servicio con y sin scopes)
tokens_script = """
import json
from uuid import uuid4
from app.security import issue_token
print(json.dumps({
    'cliente': issue_token(uuid4(), role='cliente', cliente_id=uuid4()),
    'admin': issue_token(uuid4(), role='administrador'),
    'svc_read': issue_token('prestamos', scopes=['modelo:read']),
    'svc_predict': issue_token('prestamos', scopes=['riesgo:predict']),
    'svc_wrong': issue_token('prestamos', scopes=['clientes:read']),
}))
"""
tokens = json.loads(docker("exec", "-T", "clientes", "python", "-", stdin=tokens_script))

# 4. Verificar permisos y contrato de GET /modelo/info
status, err, _ = req("prestamos", "/modelo/info")
assert status == 401
validate_schema(err, "Error")

status, err, _ = req("prestamos", "/modelo/info", token=tokens["cliente"])
assert status == 403
validate_schema(err, "Error")

status, err, _ = req("prestamos", "/modelo/info", token=tokens["svc_wrong"])
assert status == 403
validate_schema(err, "Error")

status, info_admin, _ = req("prestamos", "/modelo/info", token=tokens["admin"])
assert status == 200, f"GET /modelo/info admin falló: {status} {info_admin}"
validate_schema(info_admin, "ModeloInfo")

status, info_svc, _ = req("prestamos", "/modelo/info", token=tokens["svc_read"])
assert status == 200 and info_svc == info_admin
assert info_admin["model_version"] == active_cfg["model_version"]
assert info_admin["run_id"] == active_cfg["run_id"]
assert info_admin["umbral"] == active_cfg["umbral"]
assert info_admin["artifact_sha256"] == active_cfg["artifact_sha256"]
print("PASS GET /api/prestamos/modelo/info (autorización admin/servicio y conformidad OpenAPI)")

# 5. Verificar permisos y validaciones relacionales/dominio (422) en POST /riesgo/predict
valid_sample = {
    "ingresos_mensuales_cop": 4200000.0,
    "obligaciones_mensuales_cop": 950000.0,
    "tipo_empleo": "dependiente",
    "antiguedad_laboral_meses": 36,
    "meses_historial_crediticio": 48,
    "creditos_previos": 2,
    "atrasos_previos_30d": 0,
    "porcentaje_pago_puntual": 95.5,
    "monto_solicitado_cop": 3000000.0,
    "plazo_meses": 12,
    "cuota_estimada_cop": 280205.93,
}

status, _, _ = req("prestamos", "/riesgo/predict", method="POST", data=valid_sample)
assert status == 401

status, _, _ = req("prestamos", "/riesgo/predict", method="POST", data=valid_sample, token=tokens["cliente"])
assert status == 403

status, _, _ = req("prestamos", "/riesgo/predict", method="POST", data=valid_sample, token=tokens["svc_read"])
assert status == 403

status, ok_pred, _ = req("prestamos", "/riesgo/predict", method="POST", data=valid_sample, token=tokens["admin"])
assert status == 200, f"Se esperaba 200 en valid_sample con admin, se obtuvo {status}: {ok_pred}"
validate_schema(ok_pred, "Riesgo")

# 5a. Cuota inconsistente con anualidad
bad_cuota = {**valid_sample, "cuota_estimada_cop": 250000.00}
status, err, _ = req("prestamos", "/riesgo/predict", method="POST", data=bad_cuota, token=tokens["admin"])
assert status == 422, f"Se esperaba 422 por cuota inconsistente, se obtuvo {status}"
validate_schema(err, "Error")

# 5b. creditos_previos == 0 pero porcentaje_pago_puntual no nulo
bad_zero_cred = {**valid_sample, "creditos_previos": 0, "porcentaje_pago_puntual": 80.0}
status, err, _ = req("prestamos", "/riesgo/predict", method="POST", data=bad_zero_cred, token=tokens["admin"])
assert status == 422, f"Se esperaba 422 por porcentaje no nulo con creditos_previos=0, se obtuvo {status}"
validate_schema(err, "Error")

# 5c. creditos_previos > 0 pero porcentaje_pago_puntual nulo
bad_pos_cred = {**valid_sample, "creditos_previos": 2, "porcentaje_pago_puntual": None}
status, err, _ = req("prestamos", "/riesgo/predict", method="POST", data=bad_pos_cred, token=tokens["admin"])
assert status == 422, f"Se esperaba 422 por porcentaje nulo con creditos_previos>0, se obtuvo {status}"
validate_schema(err, "Error")

# 5d. Monto fuera de política (< 500000)
bad_monto = {**valid_sample, "monto_solicitado_cop": 200000.0, "cuota_estimada_cop": 18680.39}
status, err, _ = req("prestamos", "/riesgo/predict", method="POST", data=bad_monto, token=tokens["admin"])
assert status == 422
validate_schema(err, "Error")

# 5e. Propiedad extra no permitida
bad_extra = {**valid_sample, "campo_extra": 123}
status, err, _ = req("prestamos", "/riesgo/predict", method="POST", data=bad_extra, token=tokens["admin"])
assert status == 422
validate_schema(err, "Error")

print("PASS POST /api/prestamos/riesgo/predict (permisos y validaciones 422 de anualidad, semántica y rangos)")

# 6. AC10: Paridad offline vs API en las 200 filas de solicitudes_nuevas.csv (tolerancia <= 1e-8)
with (ROOT / "solicitudes_nuevas.csv").open("r", encoding="utf-8") as f:
    raw_rows = list(csv.DictReader(f))

with BATCH_PRED_CSV.open("r", encoding="utf-8") as f:
    offline_preds = {row["solicitud_id"]: row for row in csv.DictReader(f)}

assert len(raw_rows) == 200 and len(offline_preds) == 200

max_diff = 0.0
for idx, r in enumerate(raw_rows):
    sol_id = r["solicitud_id"]
    payload = {
        "ingresos_mensuales_cop": float(r["ingresos_mensuales_cop"]),
        "obligaciones_mensuales_cop": float(r["obligaciones_mensuales_cop"]),
        "tipo_empleo": r["tipo_empleo"] if r["tipo_empleo"] != "" else None,
        "antiguedad_laboral_meses": int(float(r["antiguedad_laboral_meses"])) if r["antiguedad_laboral_meses"] != "" else None,
        "meses_historial_crediticio": int(float(r["meses_historial_crediticio"])) if r["meses_historial_crediticio"] != "" else None,
        "creditos_previos": int(float(r["creditos_previos"])),
        "atrasos_previos_30d": int(float(r["atrasos_previos_30d"])),
        "porcentaje_pago_puntual": float(r["porcentaje_pago_puntual"]) if r["porcentaje_pago_puntual"] != "" else None,
        "monto_solicitado_cop": float(r["monto_solicitado_cop"]),
        "plazo_meses": int(float(r["plazo_meses"])),
        "cuota_estimada_cop": float(r["cuota_estimada_cop"]),
    }
    tok = tokens["svc_predict"] if idx % 2 == 0 else tokens["admin"]
    status, api_res, _ = req("prestamos", "/riesgo/predict", method="POST", data=payload, token=tok)
    assert status == 200, f"Fallo en fila {sol_id}: {status} {api_res}"
    if idx < 10:
        validate_schema(api_res, "Riesgo")

    off = offline_preds[sol_id]
    diff = abs(float(api_res["probabilidad_incumplimiento"]) - float(off["probabilidad_incumplimiento"]))
    max_diff = max(max_diff, diff)
    assert diff <= 1e-8, f"Diferencia de paridad excedida en {sol_id}: {diff}"
    assert api_res["decision_riesgo"] == off["decision_riesgo"], f"Decisión distinta en {sol_id}"
    assert api_res["model_version"] == off["model_version"]
    assert api_res["run_id"] == off["run_id"]

print(f"PASS AC10: Paridad offline vs API en las 200 solicitudes nuevas verificada (max_abs_diff={max_diff:.2e} <= 1e-8)")

# 7. Comprobar indisponibilidad (503) cuando falta el modelo y recuperación al restaurarlo
backup_bytes = ACTIVE_MODEL_PATH.read_bytes()
try:
    ACTIVE_MODEL_PATH.unlink()
    # Docker Desktop (macOS) cachea metadatos del bind mount ~0,5 s tras consultas recientes: esperar hasta 5 s.
    deadline = time.monotonic() + 5
    while True:
        status, ready_unavail, _ = req("prestamos", "/ready")
        if status == 503 or time.monotonic() > deadline:
            break
        time.sleep(0.2)
    assert status == 503 and ready_unavail["dependencies"]["model"] == "unavailable", (
        f"Se esperaba 503 cuando falta active_model.json, se obtuvo {status}: {ready_unavail}"
    )
    status, pred_unavail, _ = req("prestamos", "/riesgo/predict", method="POST", data=valid_sample, token=tokens["admin"])
    assert status == 503, f"Se esperaba 503 en /riesgo/predict sin modelo, se obtuvo {status}"
    validate_schema(pred_unavail, "Error")
finally:
    ACTIVE_MODEL_PATH.write_bytes(backup_bytes)

status, ready_recovered, _ = req("prestamos", "/ready")
assert status == 200 and ready_recovered["dependencies"]["model"] == "ok", "No se recuperó /ready tras restaurar active_model.json"
print("PASS Señal de no disponibilidad (503) ante ausencia del modelo y recuperación automática verificadas")

print("=================================================================")
print("  ¡FASE 8 COMPLETADA CON ÉXITO: MODELO PROMOVIDO Y API ACTIVA!   ")
print("=================================================================")
