# Fase 11: monitoreo, v2 y rollback

Esta fase permite observar cómo se utiliza el modelo y cambiar de versión de forma explícita. El modelo original se conserva y los préstamos guardan la versión con la que fueron evaluados.

## Qué se agregó

- Registros de inferencia con fecha, versión, score, decisión, latencia y campos faltantes. Los errores de inferencia registran su tipo, sin copiar datos financieros ni contraseñas.
- Reporte agregado de los logs retenidos en Docker: cantidades por versión, histograma de scores, faltantes, latencias p50/p95 y errores HTTP separados de los errores de inferencia.
- Comparación de distribuciones mediante PSI. La referencia es el split de entrenamiento; se comparan las 200 solicitudes sin etiqueta y una variante explícitamente simulada.
- `riesgo-v2`: regresión logística con `C=0.5`, frente al `C=1.0` de v1. Se mantiene la preparación de datos y se ajusta el umbral con validación. No se lee el conjunto de prueba para entrenar o seleccionar v2.
- Registro de v2 en el experimento MLflow `credimarket-riesgo-v2`, exportación versionada y protección contra sobrescribir una versión existente con otro modelo.
- Escritura atómica de `active_model.json`, auditoría de solicitudes de activación y verificación por API después de reiniciar Préstamos.

## Ejecutar y observar

Con el entorno encendido:

```powershell
docker compose up -d --build --wait --wait-timeout 300
```

Generar el monitoreo de las últimas 24 horas de logs disponibles:

```powershell
python scripts/run_phase11.py monitor
```

El resultado aparece en terminal y en `ml/reports/monitoring_report.json`. Incluye las inferencias hechas mediante el endpoint de riesgo y durante solicitudes de crédito. Los errores HTTP de validación o autorización se cuentan aparte: no son fallos del clasificador. La ventana depende de los logs retenidos del contenedor actual; recrearlo puede perder la parte anterior del historial. Es un reporte manual, no un sistema externo de métricas persistentes ni alertas automáticas.

Generar el estudio de drift:

```powershell
python scripts/run_phase11.py drift
```

`ml/reports/drift_report.json` contiene estadísticas agregadas. La simulación multiplica los ingresos por 0.45 y las obligaciones por 1.5, y elimina el dato de empleo en una de cada tres filas de una copia en memoria. Los CSV originales no se modifican ni se guardan filas financieras completas en el reporte.

PSI usa intervalos de deciles calculados sobre la referencia, una categoría de faltantes y suavizado aditivo de 0.5 por intervalo. Un PSI mayor indica mayor diferencia para esa comparación; este proyecto no aplica un umbral estadístico universal ni cambia automáticamente el modelo por drift. Sin etiquetas nuevas no se puede concluir que haya disminuido la precisión.

## Modelo v2 y comparación

```powershell
python scripts/run_phase11.py train-v2
```

La primera ejecución entrena, registra en MLflow y exporta el paquete `models/riesgo-v2/`. Las siguientes verifican el paquete existente y lo conservan. Para otro experimento debe utilizarse una nueva versión, en vez de sobrescribirlo.

Ver `ml/reports/v2_comparison.json`: contiene las métricas comparables de v1 y v2 en validación. No se copian las métricas de prueba de v1 a v2. La existencia de una segunda versión no implica que sea mejor; su promoción en esta fase demuestra el procedimiento de operación.

## Promoción y rollback

Activar v2:

```powershell
python scripts/run_phase11.py promote --version riesgo-v2
```

El comando valida el artefacto, registra la solicitud de activación en `models/promotions/`, cambia atómicamente el puntero, reinicia únicamente Préstamos y consulta `/modelo/info` hasta confirmar la versión servida. Hay un breve periodo de indisponibilidad del servicio durante el reinicio. No promueve automáticamente un artefacto distinto si el solicitado falta.

Restaurar v1:

```powershell
python scripts/run_phase11.py rollback --version riesgo-v1
```

No se reentrena: se carga el mismo archivo de v1. Su hash y sus predicciones deben coincidir con los anteriores. Los préstamos históricos conservan `model_version`, `run_id`, probabilidad y umbral originales.

En localhost, entrar como administrador a **Modelo** y actualizar la página permite observar la versión activa. Las solicitudes nuevas utilizan esa versión; el detalle de una solicitud anterior mantiene la que utilizó originalmente. El monitoreo y el estudio de drift se consultan mediante los comandos y reportes anteriores.

La auditoría en `models/promotions/` registra una **solicitud validada**, no una garantía de que un proceso haya arrancado. La observación por API y el evento `model_loaded` confirman la activación. Si la API no confirma el cambio, el comando informa el fallo; el operador puede ejecutar el rollback explícito.

## Verificación

```powershell
python scripts/check_phase11.py
```

La prueba hace v1 → v2 → v1, consulta y predice por HTTP, crea préstamos de prueba, comprueba que la metadata histórica no cambie y que un artefacto corrupto no cambie el puntero activo. También verifica monitoreo y la simulación. Conserva fixtures y restaura la versión que estaba activa al comenzar.

Los resultados ejecutados se registran en `ml/reports/phase11_validation.json` y `docs/validacion-fase-11.md`.

## Fuentes técnicas

Preparación aprendida exclusivamente sobre entrenamiento: [prácticas de scikit-learn para evitar fuga de datos](https://scikit-learn.org/stable/common_pitfalls.html). Registro de parámetros, métricas y artefactos: [API de tracking de MLflow](https://mlflow.org/docs/latest/api_reference/python_api/mlflow.html).
