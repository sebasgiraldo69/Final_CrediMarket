# Fase 8: Exportar y servir el modelo desde Préstamos

Transformación del experimento ganador de la Fase 7 (`02_logreg_c1`, `run_id = 67e5c9d9db914b4f92ce2aebb6d80a10`) en una dependencia estable del microservicio de **Préstamos**, con promoción explícita mediante `models/active_model.json`, validación criptográfica SHA-256 al arranque, endpoints protegidos `/modelo/info` y `/riesgo/predict`, inferencia batch de las 200 solicitudes nuevas sin etiqueta y verificación de paridad offline vs. API (`AC10`).

## Probar y verificar la fase

Con el stack de Docker Compose activo:

```powershell
# Promover explícitamente la versión riesgo-v1 y generar inferencia batch
python scripts/promote_model.py --version riesgo-v1

# Ejecutar todas las pruebas de integración, permisos, validación, paridad AC10 y disponibilidad (503)
python scripts/check_phase8.py

# Comprobar que toda la infraestructura reporta /ready = 200 (incluyendo model='ok' en Préstamos)
python scripts/check_infrastructure.py
```

También se puede inspeccionar la documentación interactiva OpenAPI del servicio en http://localhost:8080/api/prestamos/docs.

---

## Código y entregables

- [`models/active_model.json`](../models/active_model.json): puntero explícito a la versión activa (`riesgo-v1`), su manifiesto, ruta de artefacto, hash SHA-256 y umbral (`0.26`).
- [`models/riesgo-v1/manifest.json`](../models/riesgo-v1/manifest.json) y `models/riesgo-v1/pipeline.joblib`: paquete versionado del modelo con `model_version`, `run_id`, hashes de datasets, las 11 variables del contrato, `clase_positiva = 1`, `umbral = 0.26`, métricas de entrenamiento/validación/prueba y versiones exactas de dependencias.
- [`ml/src/export_and_promote.py`](../ml/src/export_and_promote.py) y [`scripts/promote_model.py`](../scripts/promote_model.py): exportación validada desde `ml/artifacts/candidate_v1/` hacia `models/<version>/` y actualización atómica de `models/active_model.json`.
- [`ml/src/batch_inference.py`](../ml/src/batch_inference.py): inferencia por lotes sobre las 200 filas sin etiqueta de `solicitudes_nuevas.csv`, generando [`ml/reports/solicitudes_nuevas_predictions.csv`](../ml/reports/solicitudes_nuevas_predictions.csv) y [`ml/reports/batch_inference_report.json`](../ml/reports/batch_inference_report.json).
- [`services/prestamos/app/model_service.py`](../services/prestamos/app/model_service.py): clase `ModelRegistry` que carga el modelo una única vez al iniciar Préstamos, verifica el hash SHA-256 antes de deserializar `joblib`, valida el contrato de 11 variables y la compatibilidad `major.minor` de `scikit-learn`, ejecuta un warmup de inferencia y registra eventos estructurados MLOps sin volcar montos financieros sensibles en los logs.
- [`services/prestamos/app/schemas.py`](../services/prestamos/app/schemas.py): esquemas Pydantic cerrados (`extra="forbid"`) para `Features`, `Riesgo` y `ModeloInfo`, incluyendo la regla semántica `creditos_previos == 0 <=> porcentaje_pago_puntual is null` y la validación relacional de que `cuota_estimada_cop` coincide con la fórmula de anualidad a tasa fija `0.018` dentro de `±0.01 COP`.
- [`services/prestamos/app/main.py`](../services/prestamos/app/main.py): endpoints `GET /modelo/info` y `POST /riesgo/predict` con manejo homogéneo de errores (`401`, `403`, `422`, `503`).
- [`shared/auth.py`](../shared/auth.py): dependencia `require_admin_or_service` que autoriza tanto a administradores (`aud=credimarket-api`, `role=administrador`) como a tokens internos de servicio (`aud=credimarket-internal`) con scopes `modelo:read` o `riesgo:predict`.
- [`shared/runtime.py`](../shared/runtime.py): integración de `ModelRegistry` en el ciclo de vida de `prestamos` y reporte real de `dependencies.model` (`"ok"` o `"unavailable"`) en `GET /ready`.
- [`scripts/check_phase8.py`](../scripts/check_phase8.py): verificación automatizada de extremo a extremo.

El [cuaderno de código de la fase 8](CODIGO_FASE_8.md) contiene los archivos fuente completos para estudio.

---

## Decisiones de diseño y garantías

1. **Promoción explícita sin heurísticas por fecha:**
   - El servicio nunca busca el `.joblib` más reciente. Lee exclusivamente `models/active_model.json`. Esto permite promover una nueva versión o hacer rollback en la Fase 11 cambiando únicamente la configuración activa de forma auditable.
2. **Validación de integridad y disponibilidad (`/ready`):**
   - Antes de invocar `joblib.load()`, `ModelRegistry` calcula el SHA-256 del archivo `pipeline.joblib` y verifica que coincida tanto con `manifest.json` como con `active_model.json`.
   - Si el archivo o la configuración activa no existen o están corruptos, el proceso web levanta (`/health` responde `200`), pero `/ready` responde `HTTP 503` con `dependencies.model = "unavailable"`, y cualquier llamada a `/riesgo/predict` o `/modelo/info` responde `HTTP 503`.
   - Nunca se entrena ni recalibra un modelo dentro de una petición HTTP.
3. **Validación estricta de entrada en `/riesgo/predict`:**
   - Además de los tipos y rangos del esquema OpenAPI (`monto_solicitado_cop` en `[500000, 15000000]`, `plazo_meses` en `{6, 12, 18, 24, 36}`, números finitos sin `NaN`/`Infinity`), el endpoint valida:
     - Equivalencia `creditos_previos == 0 <=> porcentaje_pago_puntual is null`.
     - Que `cuota_estimada_cop` coincida dentro de `0.01 COP` con la anualidad teórica para `monto_solicitado_cop`, `plazo_meses` y `tasa = 0.018`. Cualquier cuota arbitraria inconsistente es rechazada con `HTTP 422`.
4. **Paridad Offline vs. API (`AC10`) e inferencia batch:**
   - Las 200 filas de `solicitudes_nuevas.csv` se evalúan tanto en modo batch offline (`ml/reports/solicitudes_nuevas_predictions.csv`) como a través de llamadas HTTP reales a `POST /api/prestamos/riesgo/predict`.
   - La diferencia máxima absoluta entre las probabilidades offline y las devueltas por la API es **`0.00e+00`** (muy por debajo de la tolerancia máxima exigida de `1e-8`), produciendo exactamente **87 decisiones `FAVORABLE`** y **113 `DESFAVORABLE`** con `model_version = "riesgo-v1"` y `umbral = 0.26`.
