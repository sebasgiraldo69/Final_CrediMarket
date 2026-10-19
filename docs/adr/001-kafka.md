# ADR-001: Kafka para coordinación de inventario

Estado: decidido para implementar, por elección explícita del equipo. Fecha: 18 de octubre de 2026.

## Contexto y comparación

CrediMarket tiene cuatro servicios, pero solo Préstamos e Inventario intercambian comandos y resultados por broker. La demo asume decenas de usuarios y hasta 10 solicitudes/s como objetivo por medir, no como requisito de escala comprobado.

| Criterio | Kafka | RabbitMQ |
|---|---|---|
| Patrón | Log particionado y grupos de consumidores | Enrutamiento de mensajes a colas |
| Uso en este proyecto | Comandos/resultados con historial retenido consultable | También podría resolver el flujo mediante colas de trabajo |
| Retención y replay | Consumir no elimina el registro; posición independiente por grupo | En colas convencionales, mensajes reconocidos dejan de estar disponibles para ese consumidor; streams es otra alternativa |
| Orden/distribución | Orden por partición; particiones repartidas entre consumidores del grupo | Orden de procesamiento depende de cola, consumidores y reentregas |
| Fallos | Offsets manuales, reintentos/DLQ en aplicación y deduplicación local | Acks, publisher confirms, dead-letter y deduplicación local |
| Operación | Planificar particiones, retención, disco, lag y rebalanceos | Planificar exchanges, bindings, colas, confirmaciones y dead-letter |

No se necesita throughput masivo para justificar la entrega. Se elige Kafka para aprender y demostrar retención, replay de diagnóstico y consumidores independientes, manteniendo el flujo real por eventos. El costo de recursos se medirá en la fase 12; no se afirma superioridad universal frente a RabbitMQ. Si el objetivo cambiara a despacho con enrutamiento complejo y sin replay, se reconsideraría RabbitMQ. La comparación no exige instalar ambos brokers.

## Configuración de diseño

- Un nodo broker/controller KRaft con volumen para demo. Tres particiones por topic, replication.factor=1 y min.insync.replicas=1. No ofrece alta disponibilidad si se pierde el nodo/volumen. Fijar versión de imagen tras compatibilidad en fase 2; no usar `latest`.
- `credimarket.inventario.comandos.v1`: Préstamos publica, grupo `inventario-v1` consume.
- `credimarket.inventario.eventos.v1`: Inventario publica, grupo `prestamos-v1` consume.
- `cleanup.policy=delete`, retención 604800000 ms (7 días). DLQ por topic, sufijo `.dlq`, retención 1209600000 ms (14 días). El borrado ocurre por segmentos, no como expiración exacta por mensaje.
- Key UTF-8 = prestamo_id. Orden por partición de un topic; no entre topics. No aumentar particiones durante la demo: puede alterar asignación de claves. La competencia por producto se arbitra en PostgreSQL.
- Un consumidor por grupo inicialmente; hasta tres pueden repartir las tres particiones. Secuencial por partición. Lag mide retraso y orienta alertas, no aprueba/rechaza préstamos.
- Productor idempotente, `acks=all`, máximo cinco solicitudes en vuelo por conexión compatible con idempotencia; comprobar nombres equivalentes en el cliente Python elegido. Marcar outbox enviado solo tras confirmación de entrega. Publicación ordenada por agregado, con un publicador inicial por servicio y secuencia guardada.
- Autocommit deshabilitado y offsets gestionados explícitamente; confirmar offset N+1 solo al completar N y todos los anteriores de esa partición. Revocación: terminar o abandonar trabajo sin confirmar offsets pendientes.

El productor idempotente limita duplicados de sus reintentos; no elimina republicaciones después de caídas ni hace transaccionales PostgreSQL y Kafka. El diseño usa entrega al menos una vez con efectos idempotentes. Estas garantías y configuraciones se basan en [productor Kafka](https://kafka.apache.org/41/configuration/producer-configs/) y [consumidor Kafka](https://kafka.apache.org/41/configuration/consumer-configs/).

## Errores y recuperación

Outbox se escribe con el cambio de negocio. Inbox y efecto se guardan juntos antes de confirmar offset. Publicación confirmada seguida de caída antes de marcar outbox produce duplicado admisible. Nunca borrar inbox para demostrar replay.

Tres reintentos adicionales de aplicación (5, 15 y 60 s), con contador durable por grupo/topic/partición/offset y pausa de partición sin detener poll/heartbeats. Si PostgreSQL está caído y no puede registrar intentos/disposición, no avanzar offset ni enviar a DLQ como si se hubiera guardado: pausar y recuperar. JSON mal formado o versión incompatible puede pasar directamente a disposición DLQ.

Al agotar intentos, transacción local de fallo + intención de publicar a DLQ; solo después avanzar offset. El outbox completa la publicación pendiente. Este fallo no se registra como inbox de negocio aplicado, para permitir reenvío autorizado con mismo event_id luego de corregir la causa. DLQ conserva bytes originales en base64, topic, partición, offset, intentos y error sin secretos. Reenvío auditado con identidad de operador; puede llegar fuera de orden y debe pasar guardas de estados.

Grupo diagnóstico independiente lee eventos retenidos sin mutar bases. Retención no es backup: alertar al superar 60 s de lag operativo y antes de acercarse a 7 días; conservar outbox e historial en BD y documentar reconciliación si se supera la ventana. Acceso a broker restringido a servicios/operador; Inventario no recibe información financiera.

## Evidencia exigida

Topics/grupos visibles, comandos reales, key documentada, offset que avanza después del commit, reentrega sin doble movimiento, caída/reinicio de Kafka y consumidor, replay diagnóstico y DLQ recuperable. Las pruebas se implementan en fases 6 y 12; este ADR no afirma haberlas ejecutado.
