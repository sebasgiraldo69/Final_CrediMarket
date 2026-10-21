# Verificación de fase 11

Ejecución local del 21 de octubre de 2026 con Docker, MLflow, PostgreSQL, Kafka y APIs reales.

## Resultados ejecutados

- Entrenamiento de `riesgo-v2`: ejecución MLflow `54683d2c2f444d1ab0fd438a77cf502f`, experimento `credimarket-riesgo-v2`.
- Variación prefijada: regresión logística `C=0.5`, preparación ajustada solo sobre las 7.200 filas de entrenamiento y comparación en las 2.400 de validación.
- Average Precision en validación: v1 `0.504484`, v2 `0.504425`. Ambas usan umbral operativo `0.26`. La versión 2 es una variación demostrativa; no se presenta como una mejora de calidad.
- El entrenamiento v2 no consultó el conjunto de prueba; su manifiesto no contiene métricas de test heredadas de v1.
- Reporte de drift generado con las 200 solicitudes sin etiqueta y una copia explícitamente simulada. PSI de scores simulado: `1.3151707255284713`. Es evidencia de cambio de distribución; no permite concluir pérdida de precisión.
- `python scripts/check_phase11.py` terminó con código 0: API v1 → v2 → v1; predicciones y préstamos nuevos identificados con su versión, run y hash; predicción de v1 idéntica después del rollback.
- Los dos préstamos que ya existían conservaron versión, run, score y umbral. Los tres préstamos de la prueba también conservaron la versión con la que se crearon.
- Un paquete corrupto fue rechazado antes de activar el modelo y el puntero activo no cambió.
- Monitoreo agregado con ambas versiones, histogramas, faltantes, latencias y errores HTTP de prueba 401/422.
- Prueba focalizada de error de inferencia: se registra tipo/versión/latencia, sin datos financieros ni texto sensible de la excepción.
- `python scripts/validate_contracts.py`: 74.338 comprobaciones estáticas aprobadas.
- `python scripts/check_infrastructure.py` terminó con código 0: servicios, modelo, migraciones, aislamiento de bases, Kafka y MLflow disponibles.
- Compilación de módulos Python y comprobación de diferencias de Git sin errores.

La evidencia estructurada está en `ml/reports/phase11_validation.json`. Otros entregables son `v2_comparison.json`, `drift_report.json`, `monitoring_report.json`, el paquete `models/riesgo-v2/` y las solicitudes de activación en `models/promotions/`.

## Incidencias corregidas

El primer ensayo detectó que `mkstemp` generaba el nuevo puntero con permisos 0600, impidiendo su lectura por el usuario sin privilegios de Préstamos. La publicación atómica establece 0644 antes de reemplazar el archivo. Se restauró v1 y la secuencia completa se ejecutó nuevamente con éxito.

Se corrigió además la decodificación de errores del proceso Python hijo en Windows: la captura tolera la salida de la consola sin ocultar un fallo de promoción.

## Límites y estado final

Quedó activa `riesgo-v1`; su artefacto original no se modificó. Las pruebas conservaron cuentas, producto, stock y préstamos sintéticos propios. Los CSV originales y los préstamos previos se conservaron.

El monitoreo es una agregación manual de los logs retenidos del contenedor actual, no una plataforma de telemetría externa. La simulación ocurre en memoria y no sustituye etiquetas de resultados reales. No se hizo una nueva evaluación sobre test ni una nueva prueba visual del navegador en esta fase. En localhost se puede observar la versión activa en la ficha Modelo y la versión de evaluación en cada solicitud.
