# Fase 12: aceptación, fallos y mediciones

Esta fase ejecuta el sistema real contra los 16 casos definidos en fase 1, conserva evidencias por ejecución y mide el comportamiento local de Redis. No crea funcionalidades nuevas de compra ni sustituye pruebas por respuestas simuladas.

## Preparación y ejecución

Desde la raíz con Docker Desktop activo:

```powershell
docker compose up -d --build --wait --wait-timeout 300
python -m pip install --target .local/e2e -r requirements-acceptance.txt
$env:PYTHONPATH = (Join-Path (Get-Location) '.local/e2e')
$env:PLAYWRIGHT_BROWSERS_PATH = (Join-Path (Get-Location) '.local/pw-browsers')
python -m playwright install chromium
python scripts/check_phase12.py
```

La suite es extensa: compara 200 predicciones, ejecuta Chromium, interrumpe servicios, demuestra rollback y espera la expiración real del TTL. Usa datos sintéticos nuevos y conserva sus registros. No elimina bases, volúmenes ni cuentas anteriores. Durante los ensayos puede haber indisponibilidad temporal de Redis, Inventario, Préstamos, Productos y Kafka.

Cada ejecución crea `docs/evidencias/fase12-<fecha>-<id>/` con logs y `results.json`. `docs/evidencias/phase12_latest.json` señala la ejecución más reciente y contiene el estado de cada caso. Un caso solo aparece PASS cuando todas sus suites requeridas terminaron con código 0; los casos no ejecutados quedan NOT_RUN y los fallidos permanecen FAIL.

Para continuar una ejecución después de corregir un fallo:

```powershell
python scripts/check_phase12.py --resume docs/evidencias/fase12-IDENTIFICADOR
```

Se vuelven a ejecutar las suites fallidas o pendientes. Si una corrección afecta suites previamente aprobadas, pueden repetirse explícitamente:

```powershell
python scripts/check_phase12.py --resume docs/evidencias/fase12-IDENTIFICADOR --only productos redis final
```

## Cobertura y evidencia

- Suites de Clientes, Productos, Inventario, datos/modelo, Préstamos, frontend, Kafka y MLOps: `check_phase3.py` a `check_phase11.py`.
- `check_phase12_faults.py`: procesos aislados ejecutan los trabajadores reales. Uno termina abruptamente después del ACK de Kafka y antes de confirmar `sent_at`; otro después del commit de Inventario y antes de confirmar offsets. Al recuperar los servicios se verifican inbox, outbox y un solo movimiento de reserva. No se agregan interruptores de fallo a las APIs de producción.
- El mismo ensayo repite una reserva con un event_id nuevo y compite entrega contra vencimiento en transacciones distintas.
- `check_phase12_pending.py`: detiene Inventario, muestra una solicitud pendiente real en Chromium y comprueba que cambie a aprobada por polling tras recuperarlo. También prueba formulario inválido sin envío, JWT realmente vencido y caída real de Productos. Guarda capturas de esas pantallas con datos de prueba.
- Los callbacks de asignación y revocación del consumidor registran grupo y particiones, sin datos financieros.

## Redis y recursos

`measure_phase12.py` usa 60 consultas idénticas por escenario: miss forzado, caché caliente y Redis detenido. El tiempo se mide desde HTTP loopback dentro de Productos, excluyendo la preparación de cada muestra. `X-Cache` identifica HIT, MISS o BYPASS; no se infieren aciertos a partir del tiempo de respuesta.

El ensayo observa la expiración real del TTL configurado de 60 segundos sin acortarlo, comprueba invalidación al cambiar precio y una escritura durante caída de Redis con registro durable de invalidación pendiente. Al recuperar Redis comprueba el precio vigente. La tabla de invalidaciones pendientes conserva evidencia; no se presenta como un trabajador automático de reintentos ya implementado.

La medición detectó demoras por DNS y reintentos internos de Redis. Se resolvió el nombre de forma asíncrona conservando la última IP conocida, con espera inicial acotada, y se configuró cero reintentos internos para pasar a PostgreSQL. La prueba exige p95 menor de 2 segundos durante esta carga local como guardia contra regresión de las esperas; no es un SLA de producción. Referencia de la política por defecto del cliente: [redis-py 6.4, Retry Helpers](https://redis.readthedocs.io/en/v6.4.0/retry.html).

`redis_metrics.json` conserva p50, p95, aciertos, expiración e invalidación. `resources.json` contiene muestras de `docker stats` durante el ensayo y la asignación de CPU/memoria a la VM Docker. Son mediciones diagnósticas locales y secuenciales; no representan capacidad máxima, alta concurrencia, un SLA ni necesariamente el hardware físico completo del equipo. No se exige que Redis gane una comparación: se publican los valores observados.

## Reproducibilidad de MLflow al cambiar de equipo

Git contiene artefactos y reportes, pero no copia el volumen PostgreSQL de MLflow. Si el historial v1 falta en otro equipo, puede reproducirse sin reemplazar el modelo publicado:

```powershell
docker run --rm --network credimarket_backend --mount "type=bind,source=$((Get-Location).Path),target=/workspace" -w /workspace -e MLFLOW_TRACKING_URI=http://mlflow:5000 -e GIT_PYTHON_REFRESH=quiet credimarket-mlflow python -m ml.src.restore_tracking
```

Este comando vuelve a ajustar los siete modelos sobre entrenamiento y comprueba sus métricas en validación. No lee test para elegir o ajustar nada. Las métricas de prueba previas se importan del reporte congelado con el prefijo `imported_test_` y la etiqueta de procedencia `original_frozen_report`.

`ml/manifests/mlflow_reproduction.json` enlaza IDs originales con nuevas ejecuciones locales y conserva hashes del reporte y artefacto. La ficha del modelo y los préstamos mantienen el run original; para localizar su reproducción en MLflow se consulta ese mapa o la etiqueta `source_run_id`. Una reproducción no se presenta como la ejecución histórica original.

## Resultados y límites

Consultar `docs/validacion-fase-12.md` y la matriz generada en `docs/evidencias/phase12_latest.json` para los resultados realmente ejecutados. No basta con que este documento o un script existan para considerar un caso aprobado.

El entorno sigue usando un solo broker Kafka, sin alta disponibilidad. Los fallos inyectados no cubren todas las particiones de red ni fallos posibles de sistema operativo. La preparación de una entrega desde un clon limpio y el ensayo de sustentación corresponden a la fase 13.
