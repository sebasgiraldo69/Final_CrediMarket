"""Generate phase-1 design contracts. Does not implement or start services."""
from copy import deepcopy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(path, value):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def obj(properties, required=None):
    return {"type": "object", "additionalProperties": False,
            "properties": properties, "required": list(properties) if required is None else required}


def ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def arr(items):
    return {"type": "array", "items": items}


def nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}


UUID = {"type": "string", "format": "uuid"}
DATE = {"type": "string", "format": "date-time"}
TEXT = {"type": "string", "minLength": 1, "maxLength": 250}
EMAIL = {"type": "string", "format": "email", "maxLength": 254}
BOOL = {"type": "boolean"}
COUNT = {"type": "integer", "minimum": 0}
POS = {"type": "integer", "minimum": 1}
MONEY = {"type": "string", "pattern": r"^(0|[1-9][0-9]{0,15})\.[0-9]{2}$",
         "description": "COP decimal exacto; reglas de positividad en la operación."}
POS_MONEY = {"type": "string", "pattern": r"^(?!0\.00$)(0|[1-9][0-9]{0,15})\.[0-9]{2}$"}
TERM = {"type": "integer", "enum": [6, 12, 18, 24, 36]}
QUANTITY = {"type": "integer", "minimum": 1, "maximum": 100}
PROB = {"type": "number", "minimum": 0, "maximum": 1}
LOAN_STATES = ["EVALUANDO", "RECHAZADA", "ERROR_TECNICO", "PENDIENTE_INVENTARIO",
               "APROBADA", "CANCELACION_PENDIENTE", "ENTREGA_PENDIENTE",
               "VERIFICACION_PENDIENTE", "CANCELADA_SIN_STOCK", "CANCELADA", "COMPLETADA"]
RESERVE_STATES = ["ACTIVA", "SIN_STOCK", "CANCELADA", "VENCIDA", "ENTREGADA"]
financial = {
    "ingresos_mensuales_cop": POS_MONEY, "obligaciones_mensuales_cop": MONEY,
    "tipo_empleo": {"enum": ["dependiente", "independiente", "temporal", None]},
    "antiguedad_laboral_meses": nullable(COUNT),
    "meses_historial_crediticio": nullable(COUNT),
    "creditos_previos": COUNT, "atrasos_previos_30d": COUNT,
    "porcentaje_pago_puntual": nullable({"type": "number", "minimum": 0, "maximum": 100}),
}

SCHEMAS = {}
SCHEMAS["Error"] = obj({"code": TEXT, "message": TEXT, "correlation_id": UUID,
                         "details": arr(obj({"field": TEXT, "message": TEXT}))})
SCHEMAS["Health"] = obj({"status": {"enum": ["ok"]}, "service": TEXT})
SCHEMAS["Ready"] = obj({"status": {"enum": ["ready", "degraded", "unavailable"]},
                         "dependencies": {"type": "object", "additionalProperties": {
                             "enum": ["ok", "degraded", "unavailable"]}}})
SCHEMAS["ProductoCrear"] = obj({"nombre": TEXT, "categoria": TEXT, "precio_cop": POS_MONEY})
SCHEMAS["ProductoEditar"] = obj({"version_esperada": POS, "nombre": TEXT,
                                  "categoria": TEXT, "precio_cop": POS_MONEY}, ["version_esperada"])
SCHEMAS["ProductoEditar"]["minProperties"] = 2
SCHEMAS["VersionEsperada"] = obj({"version_esperada": POS})
SCHEMAS["Producto"] = obj({"id": UUID, **SCHEMAS["ProductoCrear"]["properties"],
                            "activo": BOOL, "version": POS, "created_at": DATE, "updated_at": DATE})
SCHEMAS["Cotizacion"] = obj({"producto_id": UUID, "precio_unitario_cop": MONEY,
                              "version_producto": POS, "activo": BOOL, "cotizado_en": DATE})
SCHEMAS["Registro"] = obj({"nombre": TEXT, "email": EMAIL,
                            "password": {"type": "string", "minLength": 12, "maxLength": 128, "writeOnly": True}})
SCHEMAS["Login"] = obj({"email": EMAIL, "password": {"type": "string", "minLength": 1,
                                                      "maxLength": 128, "writeOnly": True}})
SCHEMAS["Token"] = obj({"access_token": TEXT, "token_type": {"const": "bearer"},
                         "expires_in": {"const": 1800}, "role": {"enum": ["cliente", "administrador"]},
                         "cliente_id": nullable(UUID)})
# JWTs are usually longer than ordinary display strings.
SCHEMAS["Token"]["properties"]["access_token"] = {"type": "string", "minLength": 1}
SCHEMAS["Finanzas"] = obj(financial)
HISTORY_RULE = {"if": {"properties": {"creditos_previos": {"const": 0}}},
                "then": {"properties": {"porcentaje_pago_puntual": {"type": "null"}}},
                "else": {"properties": {"porcentaje_pago_puntual": {"type": "number"}}}}
SCHEMAS["Finanzas"]["allOf"] = [HISTORY_RULE]
SCHEMAS["Cliente"] = obj({"id": UUID, "clave_externa": nullable(TEXT), "nombre": nullable(TEXT),
                           "email": nullable(EMAIL), "activo": BOOL, "version": POS,
                           "finanzas": nullable(ref("Finanzas")), "created_at": DATE, "updated_at": DATE})
SCHEMAS["ClienteEditar"] = obj({"version_esperada": POS, "nombre": TEXT, "email": EMAIL,
                                 "activo": BOOL, "finanzas": ref("Finanzas")}, ["version_esperada"])
SCHEMAS["ClienteEditar"]["minProperties"] = 2
SCHEMAS["Importacion"] = obj({"id": UUID, "archivo_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
    "estado": {"const": "COMPLETADA"}, "total_filas": COUNT, "insertados": COUNT,
    "actualizados": COUNT, "sin_cambios": COUNT, "rechazados": COUNT,
    "errores": arr(obj({"fila": {"type": "integer", "minimum": 2}, "campo": TEXT,
                         "codigo": TEXT, "mensaje": TEXT})), "created_at": DATE})
SCHEMAS["PrestamoCrear"] = obj({"producto_id": UUID, "cantidad": QUANTITY, "plazo_meses": TERM})
features = deepcopy(financial)
features["ingresos_mensuales_cop"] = {"type": "number", "exclusiveMinimum": 0}
features["obligaciones_mensuales_cop"] = {"type": "number", "minimum": 0}
features.update({"monto_solicitado_cop": {"type": "number", "minimum": 500000, "maximum": 15000000},
                 "plazo_meses": TERM, "cuota_estimada_cop": {"type": "number", "exclusiveMinimum": 0}})
SCHEMAS["Features"] = obj(features)
SCHEMAS["Features"]["allOf"] = [HISTORY_RULE]
SCHEMAS["Riesgo"] = obj({"probabilidad_incumplimiento": PROB,
    "decision_riesgo": {"enum": ["FAVORABLE", "DESFAVORABLE"]}, "umbral": PROB,
    "model_version": TEXT, "run_id": TEXT})
SCHEMAS["ModeloInfo"] = obj({"model_version": TEXT, "run_id": TEXT, "variables": arr(TEXT),
    "clase_positiva": {"const": 1}, "umbral": PROB,
    "artifact_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}})
snapshot = {"reserva_id": UUID, "prestamo_id": UUID,
            "producto_id": nullable(UUID), "cantidad": nullable(QUANTITY),
            "estado_reserva": {"enum": RESERVE_STATES}, "revision_reserva": POS,
            "vence_en": nullable(DATE)}
SCHEMAS["Reserva"] = obj(snapshot)
SCHEMAS["Reserva"]["allOf"] = [
    {"if": {"properties": {"estado_reserva": {"enum": ["ACTIVA", "VENCIDA", "ENTREGADA"]}}},
     "then": {"properties": {"producto_id": UUID, "cantidad": QUANTITY, "vence_en": DATE}}},
    {"if": {"properties": {"estado_reserva": {"const": "SIN_STOCK"}}},
     "then": {"properties": {"producto_id": UUID, "cantidad": QUANTITY, "vence_en": {"type": "null"}}}},
]
SCHEMAS["Prestamo"] = obj({"id": UUID, "cliente_id": UUID,
    **SCHEMAS["PrestamoCrear"]["properties"], "estado": {"enum": LOAN_STATES},
    "motivo": nullable(TEXT), "precio_unitario_cop": nullable(MONEY),
    "version_producto": nullable(POS), "monto_cop": nullable(MONEY),
    "cuota_cop": nullable(MONEY), "riesgo": nullable(ref("Riesgo")),
    "reserva_id": nullable(UUID), "vence_en": nullable(DATE), "reserva_utilizable": BOOL,
    "created_at": DATE, "updated_at": DATE})
SCHEMAS["Prestamo"]["allOf"] = [
    {"if": {"properties": {"estado": {"const": "APROBADA"}}},
     "then": {"properties": {"reserva_id": UUID, "vence_en": DATE, "riesgo": ref("Riesgo"),
                              "reserva_utilizable": {"const": True}}},
     "else": {"properties": {"reserva_utilizable": {"const": False}}}},
    {"if": {"properties": {"estado": {"enum": ["PENDIENTE_INVENTARIO", "APROBADA", "ENTREGA_PENDIENTE", "COMPLETADA"]}}},
     "then": {"properties": {"riesgo": ref("Riesgo"), "precio_unitario_cop": POS_MONEY,
                              "version_producto": POS, "monto_cop": POS_MONEY, "cuota_cop": POS_MONEY}}},
]
SCHEMAS["Cancelacion"] = obj({"motivo": {"type": "string", "minLength": 1, "maxLength": 250}})
SCHEMAS["Entrada"] = obj({"producto_id": UUID, "cantidad": POS, "motivo": TEXT})
SCHEMAS["Existencia"] = obj({"producto_id": UUID, "fisico": COUNT,
                              "reservado": COUNT, "disponible": COUNT})
SCHEMAS["Movimiento"] = obj({"id": UUID, "producto_id": UUID, "prestamo_id": nullable(UUID),
    "tipo": {"enum": ["ENTRADA", "RESERVA", "LIBERACION", "SALIDA", "VENCIMIENTO"]},
    "cantidad": POS, "motivo": TEXT, "created_at": DATE})
for singular, plural in [("Producto", "Productos"), ("Cliente", "Clientes"), ("Prestamo", "Prestamos"),
                          ("Reserva", "Reservas"), ("Existencia", "Existencias"), ("Movimiento", "Movimientos")]:
    SCHEMAS[plural] = obj({"items": arr(ref(singular)), "total": COUNT,
                          "limit": {"type": "integer", "minimum": 1, "maximum": 100}, "offset": COUNT})

CORRELATION = {"description": "UUID de correlación generado o propagado.", "schema": UUID}
IDEMPOTENCY = {"name": "Idempotency-Key", "in": "header", "required": True,
               "schema": {"type": "string", "minLength": 8, "maxLength": 128}}
PAGING = [{"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}},
          {"name": "offset", "in": "query", "schema": {"type": "integer", "minimum": 0, "default": 0}}]


def response(schema, description, location=False):
    headers = {"X-Correlation-ID": CORRELATION}
    if location:
        headers["Location"] = {"description": "URL relativa de consulta del recurso", "schema": {"type": "string"}}
    return {"description": description, "headers": headers,
            "content": {"application/json": {"schema": ref(schema)}}}


def spec(service):
    return {"openapi": "3.1.0", "info": {"title": f"CrediMarket - {service}", "version": "1.0.0",
             "description": "Contrato de diseño de fase 1. Ver docs/api-y-seguridad.md y docs/estados.md."},
            "servers": [{"url": f"/api/{service}"}], "security": [{"UserBearer": []}], "paths": {},
            "components": {"securitySchemes": {
                "UserBearer": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT",
                               "description": "aud=credimarket-api; rol y propietario validados por backend"},
                "ServiceBearer": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT",
                                  "description": "aud=credimarket-internal; identidad de servicio y scopes"}},
                           "schemas": deepcopy(SCHEMAS)}}


def operation(doc, path, method, name, summary, roles, outputs, body=None, *, internal=False,
              scope=None, owner=False, paging=False, idem=False, errors=None, cases=None):
    params = [{"name": "X-Correlation-ID", "in": "header", "schema": UUID}]
    import re
    for variable in re.findall(r"\{([^}]+)\}", path):
        params.append({"name": variable, "in": "path", "required": True, "schema": UUID})
    if paging:
        params += deepcopy(PAGING)
    if idem:
        params.append(deepcopy(IDEMPOTENCY))
    entry = {"operationId": name, "summary": summary, "x-roles": roles,
             "x-acceptance-cases": cases or [], "parameters": params, "responses": {}}
    if roles == ["publico"]:
        entry["security"] = []
    elif internal:
        entry["security"] = [{"ServiceBearer": []}]
    elif "servicio" in roles:
        entry["security"] = [{"UserBearer": []}, {"ServiceBearer": []}]
    if scope:
        entry["x-scope"] = scope
    if owner:
        entry["x-owner"] = "Cliente solo recurso propio; administrador todos; ajeno devuelve 404."
    if body:
        if body == "CSV":
            content = {"multipart/form-data": {"schema": obj({"file": {"type": "string", "format": "binary"}})}}
        else:
            content = {"application/json": {"schema": ref(body)}}
        entry["requestBody"] = {"required": True, "content": content}
    for code, schema in outputs.items():
        entry["responses"][str(code)] = response(schema, summary, code in (201, 202))
    codes = set([401, 403, 404, 409, 422, 503] if errors is None else errors)
    for code in sorted(codes):
        if str(code) not in entry["responses"]:
            entry["responses"][str(code)] = response("Error", {
                401: "Credencial ausente o inválida", 403: "Permiso insuficiente", 404: "Recurso no visible o inexistente",
                409: "Conflicto de estado, versión o idempotencia", 413: "Archivo excede límite",
                422: "Entrada inválida", 503: "Dependencia no disponible"}[code])
    doc["paths"].setdefault(path, {})[method] = entry
    return entry


docs = {s: spec(s) for s in ["productos", "clientes", "prestamos", "inventario"]}
p, c, l, i = (docs[s] for s in ["productos", "clientes", "prestamos", "inventario"])
users = ["cliente", "administrador"]
admin = ["administrador"]
operation(p, "/productos", "get", "listarProductos", "Listar catálogo activo; admin puede incluir inactivos", users, {200: "Productos"}, paging=True, cases=[8, 9, 14])
p["paths"]["/productos"]["get"]["parameters"].append({"name": "incluir_inactivos", "in": "query", "schema": {"type": "boolean", "default": False}, "description": "Solo administrador; cliente con true recibe 403."})
operation(p, "/productos", "post", "crearProducto", "Crear producto con precio positivo", admin, {201: "Producto"}, "ProductoCrear", cases=[14])
operation(p, "/productos/{id}", "get", "consultarProducto", "Consultar producto usando cache-aside", users, {200: "Producto"}, cases=[8, 14])
operation(p, "/productos/{id}", "patch", "editarProducto", "Editar con versión esperada e invalidar caché", admin, {200: "Producto"}, "ProductoEditar", cases=[9, 14])
operation(p, "/productos/{id}/desactivar", "post", "desactivarProducto", "Desactivar e invalidar caché", admin, {200: "Producto"}, "VersionEsperada", cases=[9, 14])
operation(p, "/interno/productos/{id}/cotizacion", "get", "cotizarProducto", "Cotizar desde PostgreSQL, incluyendo indicador activo", ["servicio"], {200: "Cotizacion"}, internal=True, scope="productos:cotizar", cases=[1, 9])

operation(c, "/auth/login", "post", "login", "Iniciar sesión por email y contraseña", ["publico"], {200: "Token"}, "Login", errors=[401, 422, 503], cases=[13, 16])
operation(c, "/clientes", "post", "registrarCliente", "Crear usuario cliente y perfil incompleto", ["publico"], {201: "Cliente"}, "Registro", errors=[409, 422, 503], cases=[14])
operation(c, "/clientes", "get", "listarClientes", "Listar clientes paginados", admin, {200: "Clientes"}, paging=True, cases=[14])
operation(c, "/clientes/{id}", "get", "consultarCliente", "Consultar perfil propio o administrado", users, {200: "Cliente"}, owner=True, cases=[13, 14])
op = operation(c, "/clientes/{id}", "patch", "editarCliente", "Editar contacto; finanzas/activo solo admin", users, {200: "Cliente"}, "ClienteEditar", owner=True, cases=[13, 14])
op["x-field-policy"] = {"cliente": ["version_esperada", "nombre", "email"], "administrador": ["version_esperada", "nombre", "email", "finanzas", "activo"]}
operation(c, "/interno/clientes/{id}", "get", "leerClienteInterno", "Leer perfil para evaluación de crédito", ["servicio"], {200: "Cliente"}, internal=True, scope="clientes:read", cases=[1, 2])
operation(c, "/clientes/importaciones", "post", "importarClientes", "Importar CSV de clientes y devolver informe por fila", admin, {201: "Importacion"}, "CSV", errors=[401, 403, 413, 422, 503], cases=[12, 14])
operation(c, "/clientes/importaciones/{id}", "get", "consultarImportacion", "Consultar informe durable", admin, {200: "Importacion"}, cases=[12, 14])

operation(l, "/prestamos", "post", "crearPrestamo", "Evaluar solicitud; 201 rechazo o 202 pendiente/evaluando", ["cliente"], {201: "Prestamo", 202: "Prestamo"}, "PrestamoCrear", idem=True, cases=[1, 2, 3, 5, 9, 15])
operation(l, "/prestamos", "get", "listarPrestamos", "Listar propios; admin puede consultar todos", users, {200: "Prestamos"}, owner=True, paging=True, cases=[13, 14])
operation(l, "/prestamos/{id}", "get", "consultarPrestamo", "Consultar estado y decisión autorizados", users, {200: "Prestamo"}, owner=True, cases=[1, 2, 3, 13, 15])
operation(l, "/prestamos/{id}/cancelacion", "post", "cancelarPrestamo", "Solicitar liberación; no declarar cancelada antes de confirmar", users, {200: "Prestamo", 202: "Prestamo"}, "Cancelacion", idem=True, owner=True, cases=[7, 13, 14])
operation(l, "/prestamos/{id}/entrega", "post", "entregarPrestamo", "Solicitar salida de inventario autorizada", admin, {200: "Prestamo", 202: "Prestamo"}, idem=True, cases=[1, 7, 14])
operation(l, "/riesgo/predict", "post", "predecirRiesgo", "Evaluar features sin reservar inventario", ["administrador", "servicio"], {200: "Riesgo"}, "Features", scope="riesgo:predict", cases=[10])
operation(l, "/modelo/info", "get", "informacionModelo", "Consultar versión y umbral activos", ["administrador", "servicio"], {200: "ModeloInfo"}, scope="modelo:read", cases=[10, 11, 14])

operation(i, "/inventario", "get", "listarExistencias", "Consultar stock físico, reservado y disponible", admin, {200: "Existencias"}, paging=True, cases=[3, 4, 14])
operation(i, "/inventario/entradas", "post", "registrarEntrada", "Agregar existencias de un producto validado por API", admin, {201: "Movimiento"}, "Entrada", idem=True, cases=[5, 14])
operation(i, "/inventario/reservas", "get", "listarReservas", "Consultar reservas y marcas terminales", admin, {200: "Reservas"}, paging=True, cases=[1, 7, 14])
operation(i, "/inventario/movimientos", "get", "listarMovimientos", "Consultar movimientos de stock", admin, {200: "Movimientos"}, paging=True, cases=[1, 4, 5, 14])
operation(i, "/interno/reservas/por-prestamo/{prestamo_id}", "get", "consultarReservaInterna", "Obtener snapshot autoritativo; 404 si no hay fila", ["servicio"], {200: "Reserva"}, internal=True, scope="reservas:read", cases=[6, 7])
for service, doc in docs.items():
    operation(doc, "/health", "get", f"{service}Health", "Comprobar proceso vivo", ["publico"], {200: "Health"}, errors=[], cases=[6, 16])
    # Health never needs generic business errors.
    doc["paths"]["/health"]["get"]["responses"] = {"200": response("Health", "Proceso vivo")}
    operation(doc, "/ready", "get", f"{service}Ready", "Comprobar dependencias críticas", ["publico"], {200: "Ready", 503: "Ready"}, errors=[], cases=[6, 10, 16])
    doc["paths"]["/ready"]["get"]["responses"] = {"200": response("Ready", "Listo o degradado tolerable"), "503": response("Ready", "No disponible")}
    # Keep each service contract limited to schemas actually reachable from its operations.
    needed = set()

    def collect(value):
        if isinstance(value, dict):
            if "$ref" in value:
                name = value["$ref"].rsplit("/", 1)[1]
                if name not in needed:
                    needed.add(name)
                    collect(SCHEMAS[name])
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(doc["paths"])
    doc["components"]["schemas"] = {name: deepcopy(SCHEMAS[name]) for name in sorted(needed)}
    write(f"contracts/openapi/{service}.json", doc)

U = "11111111-1111-4111-8111-111111111111"
PRODUCT = "22222222-2222-4222-8222-222222222222"
RESERVE = "33333333-3333-4333-8333-333333333333"
CORR = "44444444-4444-4444-8444-444444444444"
NOW = "2026-10-18T15:00:00Z"
EXPIRY = "2026-10-18T15:10:00Z"
COMMAND_TOPIC = "credimarket.inventario.comandos.v1"
EVENT_TOPIC = "credimarket.inventario.eventos.v1"
event_types = {
    "ReservaSolicitada": (obj({"producto_id": UUID, "cantidad": QUANTITY}), {"producto_id": PRODUCT, "cantidad": 1}),
    "LiberacionSolicitada": (obj({"motivo": TEXT}), {"motivo": "CANCELACION_USUARIO"}),
    "EntregaSolicitada": (obj({"reserva_id": UUID}), {"reserva_id": RESERVE}),
}
result_states = {
    "InventarioReservado": ["ACTIVA"], "InventarioInsuficiente": ["SIN_STOCK"],
    "ReservaLiberada": ["CANCELADA", "SIN_STOCK"], "ReservaExpirada": ["VENCIDA"],
    "EntregaConfirmada": ["ENTREGADA"],
    "EntregaRechazada": ["VENCIDA", "CANCELADA", "SIN_STOCK", "SIN_RESERVA"],
    "LiberacionRechazada": ["ENTREGADA"],
}
for event_type, states in result_states.items():
    props = {"reserva_id": nullable(UUID), "estado_reserva": {"enum": states},
             "revision_reserva": COUNT, "vence_en": nullable(DATE), "motivo": TEXT}
    payload = obj(props)
    payload["allOf"] = [
        {"if": {"properties": {"estado_reserva": {"const": "SIN_RESERVA"}}},
         "then": {"properties": {"reserva_id": {"type": "null"}, "revision_reserva": {"const": 0}, "vence_en": {"type": "null"}}},
         "else": {"properties": {"reserva_id": UUID, "revision_reserva": POS}}},
        {"if": {"properties": {"estado_reserva": {"enum": ["ACTIVA", "VENCIDA", "ENTREGADA"]}}},
         "then": {"properties": {"vence_en": DATE}}},
    ]
    state = states[0]
    example = {"reserva_id": RESERVE, "estado_reserva": state,
               "revision_reserva": 1 if state in ["ACTIVA", "SIN_STOCK"] else 2,
               "vence_en": EXPIRY if state in ["ACTIVA", "VENCIDA", "ENTREGADA"] else None,
               "motivo": "YA_ENTREGADA" if event_type == "LiberacionRechazada" else state}
    event_types[event_type] = payload, example
catalog = {"schema_version": 1, "key": "prestamo_id", "messages": []}
for index, (event_type, (payload, example_payload)) in enumerate(event_types.items(), start=1):
    command = event_type in ["ReservaSolicitada", "LiberacionSolicitada", "EntregaSolicitada"]
    schema = obj({"event_id": UUID, "type": {"const": event_type}, "schema_version": {"const": 1},
                  "occurred_at": DATE, "correlation_id": UUID, "causation_id": nullable(UUID),
                  "prestamo_id": UUID, "payload": payload})
    schema.update({"$schema": "https://json-schema.org/draft/2020-12/schema", "title": event_type})
    example = {"event_id": f"55555555-5555-4555-8555-{index:012d}", "type": event_type,
               "schema_version": 1, "occurred_at": NOW if command or event_type not in ["ReservaExpirada", "EntregaRechazada"] else "2026-10-18T15:11:00Z",
               "correlation_id": CORR, "causation_id": None if command or event_type == "ReservaExpirada" else (
                   "55555555-5555-4555-8555-000000000003" if event_type in ["EntregaConfirmada", "EntregaRechazada"] else
                   "55555555-5555-4555-8555-000000000002" if event_type in ["ReservaLiberada", "LiberacionRechazada"] else
                   "55555555-5555-4555-8555-000000000001"),
               "prestamo_id": U, "payload": example_payload}
    schema_path = f"schemas/{event_type}.schema.json"
    example_path = f"examples/{event_type}.json"
    write(f"contracts/events/{schema_path}", schema)
    write(f"contracts/events/{example_path}", example)
    catalog["messages"].append({"type": event_type, "topic": COMMAND_TOPIC if command else EVENT_TOPIC,
        "producer": "prestamos" if command else "inventario",
        "consumer_group": "inventario-v1" if command else "prestamos-v1",
        "schema": schema_path, "example": example_path})
write("contracts/events/catalog.json", catalog)
dlq = obj({"failure_id": UUID, "failed_at": DATE, "consumer_group": TEXT,
           "original_topic": {"enum": [COMMAND_TOPIC, EVENT_TOPIC]}, "original_partition": COUNT,
           "original_offset": COUNT, "original_key": nullable({"type": "string"}),
           "original_value_base64": {"type": "string", "contentEncoding": "base64"},
           "event_id": nullable(UUID), "attempts": {"type": "integer", "minimum": 1, "maximum": 4},
           "error_code": TEXT, "error_message": TEXT})
dlq["$schema"] = "https://json-schema.org/draft/2020-12/schema"
write("contracts/events/dlq.schema.json", dlq)
write("contracts/events/examples/dlq.json", {"failure_id": U, "failed_at": NOW, "consumer_group": "inventario-v1",
      "original_topic": COMMAND_TOPIC, "original_partition": 0, "original_offset": 10,
      "original_key": U, "original_value_base64": "bm90LWpzb24=", "event_id": None,
      "attempts": 1, "error_code": "INVALID_JSON", "error_message": "No se puede decodificar el mensaje"})

# REST examples with explicit schema references for repeatable validation.
feature_example = {"ingresos_mensuales_cop": 2757000, "obligaciones_mensuales_cop": 1059000,
    "tipo_empleo": "dependiente", "antiguedad_laboral_meses": 6, "meses_historial_crediticio": 54,
    "creditos_previos": 0, "atrasos_previos_30d": 0, "porcentaje_pago_puntual": None,
    "monto_solicitado_cop": 7464000, "plazo_meses": 6, "cuota_estimada_cop": 1323536.90}
write("contracts/openapi/examples.json", [
    {"service": "prestamos", "schema": "PrestamoCrear", "value": {"producto_id": PRODUCT, "cantidad": 1, "plazo_meses": 12}},
    {"service": "prestamos", "schema": "Features", "value": feature_example},
    {"service": "prestamos", "schema": "Riesgo", "value": {"probabilidad_incumplimiento": 0.2,
       "decision_riesgo": "FAVORABLE", "umbral": 0.4, "model_version": "ejemplo-no-entrenado", "run_id": "ejemplo"}},
    {"service": "productos", "schema": "ProductoCrear", "value": {"nombre": "Portátil demo", "categoria": "computadores", "precio_cop": "2500000.00"}},
    {"service": "inventario", "schema": "Entrada", "value": {"producto_id": PRODUCT, "cantidad": 1, "motivo": "Carga inicial"}},
    {"service": "prestamos", "schema": "Prestamo", "value": {
        "id": U, "cliente_id": CORR, "producto_id": PRODUCT, "cantidad": 1, "plazo_meses": 12,
        "estado": "PENDIENTE_INVENTARIO", "motivo": None, "precio_unitario_cop": "2500000.00",
        "version_producto": 1, "monto_cop": "2500000.00", "cuota_cop": "233504.94",
        "riesgo": {"probabilidad_incumplimiento": 0.2, "decision_riesgo": "FAVORABLE", "umbral": 0.4,
                   "model_version": "ejemplo-no-entrenado", "run_id": "ejemplo"},
        "reserva_id": None, "vence_en": None, "reserva_utilizable": False,
        "created_at": NOW, "updated_at": NOW}},
])
print(f"Generated {len(docs)} OpenAPI contracts, {len(event_types)} message schemas and DLQ.")
