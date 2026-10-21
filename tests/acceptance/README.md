# Pruebas de aceptación de negocio

La ejecución integral es `python scripts/check_phase12.py`. Consultar `docs/FASE_12.md` para instalar Chromium y las dependencias, y para los efectos de las pruebas de fallos.

Cada ejecución guarda logs y resultados por suite en `docs/evidencias/fase12-<id>/`. `docs/evidencias/phase12_latest.json` contiene la matriz AC01–AC16: PASS exige que todas las suites requeridas hayan terminado correctamente; FAIL y NOT_RUN permanecen explícitos.

Las suites de fases previas se complementan con `check_phase12_faults.py` (caídas en fronteras de commit), `measure_phase12.py` (Redis y recursos) y `check_phase12_pending.py` (pendiente real en navegador y recuperación). Los datos sintéticos se conservan y los servicios se restauran después de las interrupciones.
