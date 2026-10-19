# Mensajes Kafka v1

Cada archivo `schemas/{type}.schema.json` es JSON Schema 2020-12 y tiene un ejemplo correspondiente en `examples/`. JSON UTF-8, key = prestamo_id, event_id estable al republicar el mismo registro outbox. `correlation_id` relaciona todo el flujo; `causation_id` identifica el comando que produjo un resultado (null para vencimiento por barrido).

| Type | Productor → consumidor | Payload y efecto |
|---|---|---|
| ReservaSolicitada | Préstamos → Inventario | producto_id, cantidad; intentar reserva una sola vez |
| LiberacionSolicitada | Préstamos → Inventario | motivo; liberar o dejar marca previa |
| EntregaSolicitada | Préstamos → Inventario | reserva_id; salida solo si coincide y sigue vigente |
| InventarioReservado | Inventario → Préstamos | snapshot ACTIVA, revisión y vencimiento |
| InventarioInsuficiente | Inventario → Préstamos | snapshot SIN_STOCK |
| ReservaLiberada | Inventario → Préstamos | snapshot CANCELADA o SIN_STOCK; confirmación de no reserva utilizable |
| ReservaExpirada | Inventario → Préstamos | snapshot VENCIDA |
| EntregaConfirmada | Inventario → Préstamos | snapshot ENTREGADA |
| EntregaRechazada | Inventario → Préstamos | snapshot VENCIDA/CANCELADA/SIN_STOCK/SIN_RESERVA y motivo |
| LiberacionRechazada | Inventario → Préstamos | snapshot ENTREGADA y motivo YA_ENTREGADA |

Comandos van a `credimarket.inventario.comandos.v1`; resultados a `credimarket.inventario.eventos.v1`. Campos obligatorios comunes: event_id, type, schema_version=1, occurred_at, correlation_id, causation_id, prestamo_id y payload. El esquema no contiene información personal ni financiera.

Resultados contienen la revisión autoritativa de la reserva: cambios incrementan revisión; respuestas idempotentes pueden repetir la revisión. SIN_RESERVA exige reserva_id null y revisión 0, los demás estados exigen UUID y revisión >= 1. ACTIVA/VENCIDA/ENTREGADA conservan vence_en; CANCELADA admite null si nació como marca previa. El tipo de resultado debe concordar con su snapshot. Entrega con reserva_id distinto al registro es conflicto a DLQ, sin tocar stock.

`catalog.json` fija topic, productor, consumidor, schema y ejemplo para cada tipo. `dlq.schema.json` define la envoltura de mensajes fallidos; incluye bytes base64 incluso si el mensaje original no era JSON válido. No confiar solo en flags de reentrega; deduplicar por inbox y operación de negocio.

Objetos cerrados en v1: cambios de campos requieren coordinar consumidores; cambios incompatibles exigen nuevo schema_version/topic. Los ejemplos sirven para validar forma, no representan decisiones reales ni un modelo entrenado.
