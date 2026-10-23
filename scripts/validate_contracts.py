"""Static phase-1 checks, JSON Schema validation and contract counterexamples.

This is not a full OpenAPI conformance validator or an integration test suite.
"""
from copy import deepcopy
import base64
import csv
import hashlib
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
checks = 0


def check(condition, message):
    global checks
    if not condition:
        raise AssertionError(message)
    checks += 1


def load(path):
    def invalid_number(value):
        raise ValueError(f"Non-finite JSON number: {value}")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=invalid_number)


def resolve(value, document):
    if isinstance(value, dict):
        if "$ref" in value:
            check(value["$ref"].startswith("#/"), "Only local refs supported by this checker")
            target = document
            for part in value["$ref"][2:].split("/"):
                target = target[part.replace("~1", "/").replace("~0", "~")]
            return resolve(target, document)
        return {k: resolve(v, document) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, document) for v in value]
    return value


def validate(schema, value):
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)


def rejects(schema, value, label):
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    check(not validator.is_valid(value), f"Invalid counterexample accepted: {label}")


docs = {}
operations = set()
covered = set()
for service in ["productos", "clientes", "prestamos", "inventario"]:
    document = load(ROOT / f"contracts/openapi/{service}.json")
    docs[service] = document
    check(document["openapi"] == "3.1.0", "Unexpected OpenAPI version")
    resolve(document, document)
    for name, schema in document["components"]["schemas"].items():
        Draft202012Validator.check_schema(resolve(schema, document))
        check(True, f"Schema {name}")
    for path, methods in document["paths"].items():
        for method, operation in methods.items():
            check(method in ["get", "post", "patch"], f"Unexpected method: {method}")
            op_id = operation["operationId"]
            check(op_id not in operations, f"Repeated operationId {op_id}")
            operations.add(op_id)
            check(bool(operation["x-roles"]), f"Missing roles: {op_id}")
            check(bool(operation["responses"]), f"Missing responses: {op_id}")
            covered.update(operation["x-acceptance-cases"])
            path_params = {p["name"] for p in operation["parameters"] if p["in"] == "path" and p.get("required")}
            check(path_params == set(re.findall(r"\{([^}]+)\}", path)), f"Path parameter mismatch {path}")
            for security in operation.get("security", document["security"]):
                check(set(security) <= set(document["components"]["securitySchemes"]), "Unknown security scheme")
            if path.startswith("/interno/"):
                check(operation["security"] == [{"ServiceBearer": []}], "Internal API permits user token")
                check(bool(operation.get("x-scope")), "Internal API lacks scope")
            for code, response in operation["responses"].items():
                check(re.fullmatch(r"[1-5][0-9]{2}", code) is not None, "Invalid response code")
                check("X-Correlation-ID" in response["headers"], "Missing correlation response header")
                check("schema" in response["content"]["application/json"], "Response without schema")

examples = load(ROOT / "contracts/openapi/examples.json")
for example in examples:
    doc = docs[example["service"]]
    validate(resolve(doc["components"]["schemas"][example["schema"]], doc), example["value"])
    check(True, "REST example")

loan_schema = resolve(docs["prestamos"]["components"]["schemas"]["PrestamoCrear"], docs["prestamos"])
loan = examples[0]["value"]
for key, value in [("precio_cop", "1.00"), ("cliente_id", loan["producto_id"]), ("incumplimiento_90d", 0)]:
    rejects(loan_schema, {**loan, key: value}, f"Untrusted field {key}")
for key, value in [("cantidad", 0), ("cantidad", 1.5), ("plazo_meses", 7), ("producto_id", "not-uuid")]:
    rejects(loan_schema, {**loan, key: value}, f"Invalid loan {key}")
features_schema = resolve(docs["prestamos"]["components"]["schemas"]["Features"], docs["prestamos"])
features = examples[1]["value"]
rejects(features_schema, {**features, "cliente_id": loan["producto_id"]}, "Predictor ID")
rejects(features_schema, {**features, "incumplimiento_90d": 1}, "Target leakage")
rejects(features_schema, {**features, "porcentaje_pago_puntual": 0}, "Missing credit history is not zero punctuality")
rejects(features_schema, {**features, "creditos_previos": 1}, "Missing punctuality with history")
rejects(features_schema, {**features, "tipo_empleo": "desconocido"}, "Unknown category")
product_schema = docs["productos"]["components"]["schemas"]["ProductoCrear"]
rejects(product_schema, {**examples[3]["value"], "precio_cop": "0.00"}, "Zero price")
loan_response = resolve(docs["prestamos"]["components"]["schemas"]["Prestamo"], docs["prestamos"])
rejects(loan_response, {**examples[5]["value"], "estado": "APROBADA"}, "Approval without a confirmed usable reservation")

# Check dataset-to-feature adaptation against the same schema used by the API.
# This validates input compatibility, without training or evaluating a model.
feature_validator = Draft202012Validator(features_schema, format_checker=FormatChecker())
data_rows = 0
for name in ["prestamos_entrenamiento.csv", "solicitudes_nuevas.csv"]:
    with (ROOT / name).open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            value = {}
            for field in features_schema["properties"]:
                raw = row[field]
                if not raw:
                    value[field] = None
                elif field == "tipo_empleo":
                    value[field] = raw
                elif field in ["antiguedad_laboral_meses", "meses_historial_crediticio", "creditos_previos", "atrasos_previos_30d", "plazo_meses"]:
                    number = float(raw)
                    check(number.is_integer(), f"Fractional month/count: {row['solicitud_id']}")
                    value[field] = int(number)
                else:
                    value[field] = float(raw)
            feature_validator.validate(value)
            calculated = value["monto_solicitado_cop"] * 0.018 / (1 - 1.018 ** -value["plazo_meses"])
            check(abs(calculated - value["cuota_estimada_cop"]) <= 0.01, "Inconsistent installment in source data")
            data_rows += 1
check(data_rows == 12200, "Unexpected number of dataset rows")

catalog = load(ROOT / "contracts/events/catalog.json")
check(catalog["key"] == "prestamo_id", "Wrong partition key")
check(len(catalog["messages"]) == 10, "Missing message contracts")
types = set()
for entry in catalog["messages"]:
    check(entry["type"] not in types, "Duplicate message type")
    types.add(entry["type"])
    schema = load(ROOT / "contracts/events" / entry["schema"])
    example = load(ROOT / "contracts/events" / entry["example"])
    validate(schema, example)
    check(example["type"] == entry["type"], "Message type mismatch")
    check((entry["producer"], entry["consumer_group"]) in [
        ("prestamos", "inventario-v1"), ("inventario", "prestamos-v1")], "Wrong route")
    check(entry["topic"].endswith("comandos.v1" if entry["producer"] == "prestamos" else "eventos.v1"), "Wrong topic")
    broken = deepcopy(example)
    broken.pop("event_id")
    rejects(schema, broken, "Missing event ID")
    rejects(schema, {**example, "schema_version": 2}, "Unknown schema version")
    broken = deepcopy(example)
    broken["payload"]["ingresos_mensuales_cop"] = 1000000
    rejects(schema, broken, "Financial data sent to inventory")
    if entry["type"] == "InventarioReservado":
        broken = deepcopy(example)
        broken["payload"]["vence_en"] = None
        rejects(schema, broken, "Active reservation without expiration")
        broken = deepcopy(example)
        broken["payload"]["estado_reserva"] = "ENTREGADA"
        rejects(schema, broken, "Wrong state for event type")
    if entry["type"] == "EntregaRechazada":
        variant = deepcopy(example)
        variant["payload"].update(estado_reserva="SIN_RESERVA", reserva_id=None, revision_reserva=0, vence_en=None)
        validate(schema, variant)
        variant["payload"]["revision_reserva"] = 1
        rejects(schema, variant, "Absent reservation with nonzero revision")

dlq = load(ROOT / "contracts/events/examples/dlq.json")
validate(load(ROOT / "contracts/events/dlq.schema.json"), dlq)
base64.b64decode(dlq["original_value_base64"], validate=True)
check(True, "DLQ original bytes")

# Acceptance coverage is a traceability check, not proof of passing the cases.
check(covered == set(range(1, 17)), "Missing acceptance references in operations")
matrix = (ROOT / "docs/aceptacion-y-backlog.md").read_text(encoding="utf-8")
for n in range(1, 17):
    check(f"| AC{n:02d} |" in matrix, f"Missing acceptance case {n}")
for document in [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]:
    text = document.read_text(encoding="utf-8")
    check(text.count("```") % 2 == 0, f"Unbalanced code fences in {document}")
    prose = re.sub(r"```[\s\S]*?```", "", text)
    for target in re.findall(r"\]\(([^)]+)\)", prose):
        if "://" not in target and not target.startswith("#"):
            check((document.parent / target.split("#")[0]).exists(), f"Broken link {target}")
for name, digest in {
    "prestamos_entrenamiento.csv": "c6cdc437c3aecc9116bc8b978df421d5a7600634c1ad7d6f82e58222a2446ecd",
    "solicitudes_nuevas.csv": "1430d7b34e924d5e4170c4fb9d9a412c1000af17c062af513ef15e44a1a7f1f7",
}.items():
    check(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, f"Original dataset changed: {name}")
print(f"PASS: {len(docs)} OpenAPI documents, {len(operations)} operations, 10 event examples + DLQ, "
      f"{len(examples)} REST examples, negative cases, {data_rows} source rows, 16 acceptance references, {checks} static checks.")
print("Runtime acceptance tests remain pending. OpenAPI checks are structural, not full specification certification.")
