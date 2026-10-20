# Modelos Exportados y Promoción Explícita (`models/`)

Este directorio almacena las versiones de modelos de riesgo exportadas desde el flujo de entrenamiento en MLflow (`ml/`) y la configuración de promoción explícita consumida por el microservicio de **Préstamos**.

## Estructura

```text
models/
├── active_model.json           # Configuración explícita de la versión activa
└── riesgo-v1/
    ├── manifest.json           # Metadatos, hashes, variables, umbral, métricas y dependencias
    └── pipeline.joblib         # Pipeline completo (ColumnTransformer + estimador)
```

## Reglas de promoción y carga

1. **Promoción explícita (`active_model.json`):**
   - El servicio de Préstamos **nunca** selecciona un modelo buscando el archivo más reciente por fecha.
   - Siempre lee `models/active_model.json`, verifica el hash SHA-256 del artefacto `pipeline.joblib` contra el manifiesto antes de cargarlo en memoria y comprueba la compatibilidad de variables y versión de `scikit-learn`.
2. **Carga única al inicio:**
   - El pipeline se carga una sola vez durante el arranque (`lifespan`) de Préstamos.
   - Si falta `active_model.json`, falta el artefacto o el hash no coincide, `/api/prestamos/ready` devuelve `HTTP 503` con `dependencies.model = "unavailable"` y `/api/prestamos/riesgo/predict` rechaza inferencias con `503`.

## Comandos

```powershell
# Exportar y promover una versión (y ejecutar inferencia batch sobre solicitudes_nuevas.csv)
python scripts/promote_model.py --version riesgo-v1 --restart

# Verificar el servicio del modelo y la paridad offline/API (AC10)
python scripts/check_phase8.py
```
