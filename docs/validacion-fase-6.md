# Verificación de fase 6

Ejecución local: 20 de octubre de 2026, con PostgreSQL y Kafka reales en Docker.

## Resultados

`python scripts/check_phase6.py --faults` terminó con código 0:

- Reserva → Kafka → Inventario → Kafka → proyección de Préstamos.
- Reenvío de comandos con el mismo event_id sin repetir movimientos.
- Cancelación previa que impide una reserva tardía.
- Entrega repetida y liberación de una entrega ya realizada.
- JSON inválido, esquema inválido, colisión de event_id y reserva_id incorrecto: DLQ.
- Continuación de la partición tras mensajes inválidos y respuesta SIN_STOCK.
- Barrido de vencimientos con devolución de existencias y evento persistido.
- Fallo inyectado dentro de transacción: se revierten reserva, inbox y resultado.
- Contador durable de cuatro intentos, esperas de 5/15/60 segundos y DLQ al agotarse.
- Replay diagnóstico sin efectos y reencolado de un fallo desde la herramienta del operador.
- Timeout real por bloqueo PostgreSQL y reinicio del consumidor durante el periodo de reintento.
- Consumidor detenido: recuperación de comandos acumulados al arrancar.
- Caída de Kafka y reinicio del publicador: el outbox conserva el comando y se entrega tras recuperar el broker.

`python scripts/check_phase5.py` terminó con código 0 después del último ajuste a la consulta HTTP de Inventario. Se conservaron autorización, idempotencia HTTP, concurrencia por la última unidad y comportamiento del dominio.

`python scripts/validate_contracts.py`: 74.265 comprobaciones estáticas aprobadas.

`python scripts/check_infrastructure.py` terminó con código 0: frontend/proxy, salud, migraciones, aislamiento de bases, ACL de Kafka, topics y MLflow.

El frontend compiló con `tsc --noEmit` y `vite build`. Los módulos Python modificados pasaron compilación.

## Incidencias resueltas y alcance

El primer ensayo de fallos se detuvo por timeout de `docker compose start inventario`: Compose intentó arrancar trabajos de inicialización dependientes que no eran necesarios. Se restauró Inventario, se cambió el script a `restart --no-deps` y se ejecutó nuevamente la suite con éxito.

La prueba del agotamiento de reintentos verifica los instantes persistidos mediante inyección controlada, sin esperar los 80 segundos completos. La prueba adicional de bloqueo ejecuta un fallo transitorio real y un reinicio durante la espera. No se afirma haber probado todas las combinaciones posibles de partición de red, carga y caída del sistema operativo.

Los fixtures se conservan: cuentas/datos de fases previas, existencias sintéticas, reservas, movimientos, mensajes, inbox/outbox y fallos de prueba. No se borraron bases ni volúmenes.

La fase 6 no incluye entrenamiento, inferencia, aprobación crediticia ni una prueba visual completa del navegador. Préstamos conserva una proyección de inventario y su `/ready` sigue devolviendo 503 por ausencia del modelo. Kafka continúa siendo un único broker local sin alta disponibilidad.
