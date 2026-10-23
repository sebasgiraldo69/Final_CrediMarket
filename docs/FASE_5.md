# Fase 5: Inventario y Reservas Atómicas

Implementación del microservicio Inventario, control de existencias con aislamiento transaccional PostgreSQL, separación de stock físico, reservado y disponible, reservas atómicas, movimientos auditables, idempotencia HTTP y marcas durables de pre-cancelación.

## Probar desde la interfaz

1. Abrir http://localhost:8080 y navegar a la pestaña **Inventario**.
2. Si no has iniciado sesión o estás conectado como cliente, el sistema indicará que la administración de inventario está restringida a administradores.
3. Al iniciar sesión como administrador:
   - Se presenta el tablero con pestañas para **Existencias**, **Movimientos** y **Reservas**.
   - En **Existencias** se observa el catálogo inicial con stock físico, reservado y disponible, con validación de invariantes en tiempo real.
   - En **Movimientos** se auditan cronológicamente todas las operaciones (`ENTRADA`, `RESERVA`, `LIBERACION`, `SALIDA`, `VENCIMIENTO`).
   - El botón **+ Registrar Entrada de Stock** permite ingresar existencias adicionales con ID de producto, cantidad y motivo, protegido con claves de idempotencia.
   - En **Reservas** se visualiza el estado autoritativo (`ACTIVA`, `SIN_STOCK`, `CANCELADA`, `VENCIDA`, `ENTREGADA`), la revisión (`revision_reserva >= 1`) y la fecha de expiración.

## Código y responsabilidades

- `services/inventario/app/models.py`: tablas `existencias`, `reservas`, `movimientos` e `idempotencia_http`, con restricciones de integridad de datos y verificación de no negatividad (`fisico >= reservado`, `disponible = fisico - reservado`).
- `services/inventario/migrations/versions/0002_inventario.py`: migración Alembic que crea las 4 tablas, índices y constraints, y siembra el stock inicial (10 unidades por producto del catálogo) con sus respectivos movimientos de `ENTRADA`.
- `services/inventario/app/domain.py`: máquina de estados y operaciones transaccionales bajo bloqueo `FOR UPDATE`:
  - `reservar`: evalúa existencias atómicamente; si hay suficiente stock reserva y genera `ACTIVA`; si no hay stock genera marca `SIN_STOCK`.
  - `liberar`: si no hay reserva previa, genera una marca durable de pre-cancelación (`CANCELADA`, revisión 1); si está activa, restituye disponible y reservado; operaciones repetidas son idempotentes; rechaza liberar reservas ya entregadas (`YA_ENTREGADA`).
  - `entregar`: descuenta físico y reservado pasando a `ENTREGADA` y registra `SALIDA`; entregas duplicadas son idempotentes y no duplican movimientos; rechaza si la reserva expiró.
  - `vencer`: detecta expiración de reservas activas, devuelve el stock a disponible y registra `VENCIMIENTO`.
  - `agregar_stock`: incrementa físico y disponible y registra `ENTRADA`.
  - `get_reserva_by_prestamo`: consulta autoritativa del snapshot.
- `services/inventario/app/schemas.py`: modelos Pydantic con validación de estados y conformidad estricta con OpenAPI 3.1.0 (`Entrada`, `Existencia`, `Existencias`, `Movimiento`, `Movimientos`, `Reserva`, `Reservas`).
- `services/inventario/app/main.py`: endpoints REST protegidos:
  - `GET /inventario`: listado de existencias para administradores.
  - `POST /inventario/entradas`: registro de entrada con validación de clave de idempotencia (`Idempotency-Key`): replay idéntico con 201 y detección de conflicto 409 si cambia el payload.
  - `GET /inventario/reservas`: consulta de reservas y marcas terminales para administradores.
  - `GET /inventario/movimientos`: historial auditable de movimientos de stock para administradores.
  - `GET /interno/reservas/por-prestamo/{prestamo_id}`: consulta interna segura con `ServiceBearer` y scope `reservas:read` para el servicio de Préstamos; evalúa vencimientos al vuelo.
- `shared/auth.py`: dependencia `reservas_read_claims = require_internal('reservas:read')`.
- `frontend/src/Inventario.tsx`: módulo reactivo en React + Vite para consultar existencias, movimientos, reservas y registrar entradas de stock.
- `frontend/src/main.tsx`: integración de navegación de Inventario y estado de sesión.
- `scripts/check_phase5.py`: suite completa de pruebas de concurrencia (carrera por la última unidad), doble liberación/entrega, idempotencia HTTP, marca de cancelación previa, expiración y conformidad OpenAPI.


## Comportamiento y decisiones de diseño

* **Invariantes de existencias y protección contra stock negativo:**
  - A nivel de PostgreSQL, la tabla `existencias` cuenta con check constraints estrictos:
    - `fisico >= 0`
    - `reservado >= 0`
    - `disponible >= 0`
    - `fisico >= reservado`
    - `disponible = fisico - reservado`
  - Toda modificación de stock se realiza dentro de una transacción con bloqueo explícito de fila (`FOR UPDATE`) para garantizar aislamiento Serializable/Read Committed sin condiciones de carrera.
* **Competencia por la última unidad:**
  - Si dos transacciones intentan reservar la última unidad disponible simultáneamente, la primera que adquiere el bloqueo de fila decrementa `disponible` a 0 e incrementa `reservado` a 1, generando una reserva `ACTIVA`.
  - La segunda transacción espera el bloqueo; al desbloquearse, observa `disponible == 0`, no altera el stock y genera una reserva con estado terminal `SIN_STOCK` (revisión 1).
* **Idempotencia HTTP en entradas de inventario:**
  - Cada solicitud a `POST /inventario/entradas` requiere el encabezado `Idempotency-Key` (8 a 128 caracteres).
  - La clave se almacena junto al actor (`sub`), la operación, el hash SHA-256 del cuerpo y la respuesta generada en la tabla `idempotencia_http`.
  - Si se reenvía la petición con la misma clave y el mismo cuerpo, se reproduce exactamente la respuesta original (201 Created con cabecera `Location` y el mismo ID de movimiento) sin aumentar el stock físico por segunda vez.
  - Si se intenta utilizar la misma clave con un cuerpo diferente, el sistema rechaza la operación con `HTTP 409 Conflict`.
* **Idempotencia de operaciones terminales:**
  - **Doble liberar:** Una segunda llamada a `liberar` sobre una reserva ya cancelada, vencida o sin stock es un no-op idempotente: responde el snapshot terminal sin volver a incrementar el stock disponible.
  - **Doble entregar:** Una segunda llamada a `entregar` sobre una reserva ya entregada responde el snapshot existente `ENTREGADA` sin descontar unidades físicas adicionales ni crear un segundo movimiento de salida.
  - **Entrega de reserva entregada/cancelada:** Intentar liberar un producto ya entregado es rechazado con error `YA_ENTREGADA`.
* **Marca durable de pre-cancelación:**
  - En arquitecturas asíncronas de microservicios, una solicitud de cancelación puede llegar antes del comando de reserva debido a latencia de red o desorden de mensajes.
  - Si se invoca `liberar` sobre un `prestamo_id` sin reserva previa (`SIN_RESERVA`), Inventario inserta inmediatamente una fila en `reservas` con estado `CANCELADA`, revisión 1 y producto/cantidad nulos.
  - Cualquier intento posterior de `reservar` para ese préstamo encuentra la marca `CANCELADA`, la respeta y no compromete existencias.
* **Control de vencimiento y expiración:**
  - Las reservas activas se crean con un TTL configurable (10 minutos por defecto).
  - La función `vencer` o la consulta autoritativa en `/interno/reservas/por-prestamo/{prestamo_id}` detectan si `vence_en < now()`, transfieren automáticamente las unidades de `reservado` a `disponible`, actualizan el estado a `VENCIDA`, incrementan la revisión y registran un movimiento de tipo `VENCIMIENTO`.
  - Intentar entregar una reserva cuyo tiempo de vencimiento ya expiró es rechazado con error de vencimiento.

## Verificación

Para ejecutar la verificación automatizada contra la infraestructura real:

```powershell
python scripts/check_phase5.py
```

Resultados obtenidos en la ejecución:
- **Autenticación y roles:** Validación de permisos para clientes y administradores.
- **Health y Ready:** Verificación de salud y dependencias PostgreSQL del microservicio.
- **Idempotencia HTTP:** Verificación de repetición con 201 replay y detección de 409 Conflict ante variación del payload.
- **Autorización interna:** Verificación de rechazo con 401/403 a tokens de usuario o sin scope `reservas:read`.
- **Concurrencia multihilo:** Carrera simultánea por la última unidad: una transacción obtiene `ACTIVA` y la otra `SIN_STOCK`; existencias se mantienen no negativas.
- **Doble liberación y entrega:** Verificación de que repeticiones no alteran existencias dos veces ni generan movimientos duplicados.
- **Pre-cancelación durable:** Creación de marca `CANCELADA` que bloquea reservas tardías.
- **Expiración automática:** Detección de vencimiento, restitución de stock a `disponible` y registro de movimiento `VENCIMIENTO`.
- **Conformidad OpenAPI:** Validación estricta con `jsonschema` contra `contracts/openapi/inventario.json`.
