# Aceptación y backlog

Los 16 casos se ejecutaron en fase 12 y terminaron aprobados en el entorno local. Consultar la [matriz ejecutada, logs, mediciones y límites](validacion-fase-12.md) y `docs/evidencias/phase12_latest.json`. La tabla siguiente conserva la definición y preparación de los casos. A/B/C/D son frentes sugeridos (README), no nombres ni asignaciones personales confirmadas.

| ID | Caso y preparación | Acción / resultado observable | Responsable | Backlog |
|---|---|---|---|---|
| AC01 | Cliente favorable, producto con stock | Crear → 202 → APROBADA; entrega admin → COMPLETADA, una salida | C + A | CM-07,08,09 |
| AC02 | Cliente con riesgo desfavorable real | 201 RECHAZADA con modelo/motivo; cero comando de reserva | C + D | CM-06,07 |
| AC03 | Cliente favorable, stock cero | 202 → CANCELADA_SIN_STOCK, stock no negativo | A + C | CM-04,07 |
| AC04 | Stock uno, dos préstamos simultáneos | Solo una reserva/APROBADA y una falta de stock | A | CM-04,12 |
| AC05 | Misma clave HTTP y mensaje repetidos | Un préstamo/movimiento; clave con otro cuerpo → 409; operación con otro event_id tampoco duplica | C + A | CM-05,07,12 |
| AC06 | Pendiente aceptado, caída en puntos críticos | Reinicio recupera outbox/inbox, sin pérdida ni doble efecto | C | CM-05,12 |
| AC07 | Cancelar antes/después de reservar; retrasar evento | Sin reactivación, reserva liberada; vencimiento/entrega concurrentes coherentes | A + C | CM-08,12 |
| AC08 | Redis vacío, TTL agotado y servicio detenido | Miss/hit/expiración/fallback; medir p50/p95 y aciertos | A | CM-03,12 |
| AC09 | Editar precio con caché caliente | Invalidación y cotización nueva guardada en préstamo | A + C | CM-03,07 |
| AC10 | Mismo lote offline/API | Predicciones equivalentes dentro de 1e-8 y versión identificable | D | CM-06,12 |
| AC11 | Dos versiones propias | v1→v2→v1, manifiestos/run IDs; histórico inmutable | D | CM-11 |
| AC12 | CSV válido y filas inválidas, repetir archivo | Mismo número de clientes, resumen coherente y errores por fila | B | CM-02 |
| AC13 | Token A intenta préstamo de B | GET/cancelar devuelve 404, listado no filtra información ajena | B + C | CM-02,07 |
| AC14 | Usuario y admin desde navegador | Catálogo/clientes/préstamo/inventario reales con persistencia | B | CM-09,10 |
| AC15 | Consumidor pausado | UI muestra pendiente y luego actualiza al reanudar | B + C | CM-09,10 |
| AC16 | Formulario inválido, token vencido, API detenida | Error claro; reintento conserva clave; no éxito ficticio | B | CM-10,12 |

## Backlog por dependencia

| ID | Trabajo | Depende de | Criterio de cierre | Fase |
|---|---|---|---|---|
| CM-01 | Compose, bases/usuarios, Kafka KRaft, Redis, MLflow, migraciones y esqueletos | Fase 1 | Arranque documentado, persistencia y aislamiento verificados | 2 |
| CM-02 | Clientes, identidad, permisos e importación | CM-01 | AC12; permisos y perfil incompleto probados | 3 |
| CM-03 | Productos/cotización/Redis | CM-01 | AC08/09 a nivel servicio | 4 |
| CM-04 | Stock, reservas atómicas y estados | CM-01 | AC03/04 a nivel dominio, no doble salida | 5 |
| CM-05 | Kafka/outbox/inbox/reintentos/DLQ | CM-04 | AC05/06 con mensajes reales y reinicios | 6 |
| CM-06 | EDA, entrenamiento, MLflow, exportación/API | CM-01 | 7 ejecuciones mínimas, manifiesto, AC10 | 7–8 |
| CM-07 | Crear/consultar préstamos, riesgo e idempotencia | CM-02,03,05,06 | AC01/02/03/05/09/13 del backend | 9 |
| CM-08 | Cancelar/entregar/vencer/reconciliar | CM-07 | AC07 y entrega AC01, guardas exhaustivos | 9 |
| CM-09 | Primera compra completa desde navegador | CM-07 | AC01/15 con API real; estructura UI comienza en CM-01 | 9 |
| CM-10 | Módulos admin, errores y responsive | CM-02,03,08,09 | AC14/15/16 | 10 |
| CM-11 | Monitoreo/drift/v2/rollback | CM-06,07 | AC11, drift identificado como simulado | 11 |
| CM-12 | Aceptación, fallos, recursos y evidencias | CM-08,10,11 | Los 16 casos ejecutados y documentados | 12 |
| CM-13 | Reproducción, README, guía y ensayo | CM-12 | Arranque limpio y demo por integrantes distintos | 13 |

Pruebas adicionales de consistencia: inbox con event_id repetido y cuerpo distinto; revocación de partición antes del commit de offset; caída tras commit PostgreSQL y antes de Kafka; DLQ con bytes inválidos; lectura APROBADA con reserva vencida; cancelar antes del primer comando de reserva; entrega frente a vencimiento; fallo de Redis durante invalidación.

## Cobertura de evaluación

Negocio (15 %): CM-04/07/08. Broker (15 %): CM-05. Redis (10 %): CM-03/12. Datos/experimentos (15 %): CM-06. Exportación/API/versiones (15 %): CM-06/11. Seguridad/consistencia (15 %): CM-02/04/05/07/08. Frontend (10 %): CM-09/10. Documentación (5 %): CM-13 y documentación incremental.

No se bloquea el comienzo de la fase 2 por nombres aún no asignados. Toda prueba de esta matriz debe cambiar de pendiente a aprobada solo con ejecución y evidencia, no por existir su contrato.
