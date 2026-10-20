# Fase 9: Completar el flujo de Préstamos

Integración completa y coordinada del ciclo de vida de créditos en CrediMarket. Conecta al **Cliente** autenticado (perfil y finanzas desde `clientes`), la cotización vigente del **Producto** con invalidación de caché (`productos`), la evaluación de riesgo crediticio en tiempo real con el modelo promovido `riesgo-v1` (`prestamos`), y la reserva atómica de stock mediante coreografía de eventos asíncrona sobre Apache Kafka con el patrón Transactional Outbox (`inventario`).

---

## Probar y verificar la fase

Con el stack de Docker Compose activo y saludable:

```powershell
# Ejecutar la suite completa de pruebas de aceptación de la Fase 9:
python scripts/check_phase9.py

# Verificar que los contratos OpenAPI y schemas de eventos sigan conformes:
python scripts/validate_contracts.py

# Comprobar la infraestructura global y estado de migraciones:
python scripts/check_infrastructure.py
```

También se puede inspeccionar la documentación interactiva OpenAPI en:
- `http://localhost:8080/api/prestamos/docs`
- `http://localhost:8080/api/prestamos/redoc`

Y realizar el flujo visual en el navegador web:
- Catálogo de productos: `http://localhost:8080/` (botón **"Solicitar a crédito"** con selección de cuotas y cálculo en tiempo real).
- Panel de solicitudes: `http://localhost:8080/solicitudes` (seguimiento en vivo mediante sondeo a 2.5s, visualización de estado de la reserva, contador de vencimiento, cancelación por el cliente y confirmación de entrega por el administrador).

---

## Casos de Aceptación Cubiertos

| ID | Caso y preparación | Acción / resultado observable | Estado |
|---|---|---|:---:|
| **AC01** | Cliente favorable, producto con stock | `POST /prestamos` → `202 PENDIENTE_INVENTARIO` → Kafka `ReservaSolicitada` → `InventarioReservado` → `APROBADA` (reserva utilizable); entrega por admin `POST /prestamos/{id}/entrega` → `202 ENTREGA_PENDIENTE` → `EntregaConfirmada` → `COMPLETADA` con exactamente una salida física registrada en inventario. | **PASS** |
| **AC02** | Cliente con riesgo desfavorable real | Evaluación con `riesgo-v1` (`probabilidad > umbral 0.26`) → `201 RECHAZADA` con motivo `RIESGO_DESFAVORABLE` y detalles del modelo (`model_version`, `run_id`, `umbral`); verificación estricta de que **cero** comandos de reserva se emiten hacia Kafka. | **PASS** |
| **AC03** | Cliente favorable, stock cero | `POST /prestamos` → `202 PENDIENTE_INVENTARIO` → Kafka `ReservaSolicitada` → Inventario detecta stock disponible 0 → `InventarioInsuficiente` → `CANCELADA_SIN_STOCK`; verificación de que el stock no resulta negativo. | **PASS** |
| **AC04** | Stock de una unidad, dos préstamos concurrentes | Dos peticiones paralelas compiten por la última unidad → Kafka + bloqueos a nivel de fila (`SELECT ... FOR UPDATE`) en `inventario` otorgan la reserva a uno y rechazan al otro → exactamente una solicitud `APROBADA` y una `CANCELADA_SIN_STOCK`; stock físico = 1, reservado = 1, disponible = 0. | **PASS** |
| **AC05** | Idempotencia HTTP y unicidad durable | Validación de cabecera `Idempotency-Key` (8-128 caracteres; menor o ausente → 422). Primer envío exitoso → `202 Accepted` con cabecera `Location`. Reintento con misma clave y mismo cuerpo → `202 Replay idéntico` devolviendo el mismo `id`. Mismo clave con cuerpo diferente → `409 Conflict`. | **PASS** |
| **AC07** | Cancelación y protección contra eventos tardíos | Cancelación de préstamo `APROBADA` por cliente → `202 CANCELACION_PENDIENTE` → Kafka `LiberacionSolicitada` → `ReservaLiberada` → `CANCELADA`. Simulación de evento tardío `InventarioReservado` sobre préstamo cancelado: **Invariante 5 de estados garantizado**, el préstamo permanece en `CANCELADA` y nunca se reactiva. | **PASS** |
| **AC09** | Editar precio con caché caliente en Productos | Actualización de precio de producto en `productos` invalida la clave Redis de cotización; la siguiente solicitud de préstamo consulta el precio nuevo, lo persiste en el préstamo y recalcula la cuota según la fórmula matemática de anualidad a tasa fija 1.8%. | **PASS** |
| **AC13** | Aislamiento estricto y privacidad de clientes | Cliente B intentando consultar `GET /prestamos/{id_A}` o cancelar `POST /prestamos/{id_A}/cancelacion` recibe `404 Not Found` (ocultamiento estricto para evitar oráculos de existencia). Listado `GET /prestamos` filtra exclusivamente las solicitudes del cliente autenticado. El administrador puede consultar el listado global y cualquier solicitud individual. | **PASS** |

---

## Componentes y Arquitectura de la Solución

### 1. Modelo de Datos y Migración (`prestamos_db`)
- [`services/prestamos/app/models.py`](../services/prestamos/app/models.py): Definición de tablas `prestamos`, `prestamos_idempotencia` y `prestamos_historial`.
- [`services/prestamos/migrations/versions/0003_prestamos.py`](../services/prestamos/migrations/versions/0003_prestamos.py): Migración Alembic versión `0003` que aplica las estructuras relacionales con llaves foráneas e índices de búsqueda rápida por `cliente_id` y `estado`.

### 2. Clientes HTTP Internos con JWT de Servicio
- [`services/prestamos/app/clients.py`](../services/prestamos/app/clients.py): Clientes internos que consumen `GET /interno/productos/{id}/cotizacion`, `GET /interno/clientes/{id}` y `GET /interno/reservas/por-prestamo/{id}` utilizando tokens asimétricos RS256 firmados por la clave privada del clúster con audiencia `credimarket-internal` y scopes mínimos (`productos:cotizar`, `clientes:read`, `reservas:read`).
- [`shared/auth.py`](../shared/auth.py): Generación y validación homogénea de tokens de usuario y servicio.

### 3. Máquina de Estados y Lógica de Dominio
- [`services/prestamos/app/domain.py`](../services/prestamos/app/domain.py):
  - Validación de políticas de crédito: montos permitidos entre $500,000 y $15,000,000 COP, plazos válidos {6, 12, 18, 24, 36}, productos activos y clientes con finanzas completas.
  - Cálculo financiero de cuota fija mensual mediante fórmula de anualidad:
    $$\text{Cuota} = \text{Monto} \times \frac{i}{1 - (1 + i)^{-n}} \quad (i = 0.018)$$
  - Evaluación de riesgo crediticio con `ModelRegistry` cargado en memoria (`riesgo-v1`).
  - Idempotencia durable almacenando hash SHA-256 del cuerpo y respuesta serializada.
  - Bloqueo consultivo de PostgreSQL (`pg_advisory_xact_lock`) para evitar condiciones de carrera en transiciones concurrentes.

### 4. Coreografía Asíncrona con Apache Kafka
- [`services/prestamos/app/messaging.py`](../services/prestamos/app/messaging.py):
  - Consumo de eventos desde el topic `credimarket.inventario.eventos.v1`: `InventarioReservado`, `InventarioInsuficiente`, `ReservaLiberada`, `ReservaExpirada`, `EntregaConfirmada`, `EntregaRechazada`.
  - Emisión de comandos transaccionales mediante Outbox hacia `credimarket.inventario.comandos.v1`: `ReservaSolicitada`, `LiberacionSolicitada`, `EntregaSolicitada`.
  - Manejo de snapshots de inventario y barrido periódico en segundo plano (`sweep`) para detectar reservas expiradas.
  - Guardas estrictos que impiden la reactivación de estados terminales (`RECHAZADA`, `ERROR_TECNICO`, `CANCELADA_SIN_STOCK`, `CANCELADA`, `COMPLETADA`).

### 5. API REST OpenAPI 3.1
- [`services/prestamos/app/main.py`](../services/prestamos/app/main.py):
  - `POST /prestamos`: evaluación, persistencia de solicitud y encolado de reserva (HTTP 201 o 202).
  - `GET /prestamos`: listado paginado filtrado por cliente o global para admin.
  - `GET /prestamos/{id}`: detalle con cálculo dinámico de expiración (`VERIFICACION_PENDIENTE`).
  - `POST /prestamos/{id}/cancelacion`: solicitud de cancelación por cliente o admin.
  - `POST /prestamos/{id}/entrega`: autorización y orden de despacho por admin.

### 6. Frontend y Experiencia de Usuario
- [`frontend/src/Catalogo.tsx`](../frontend/src/Catalogo.tsx): Integración de botón "Solicitar a crédito", modal de selección de cuotas y cálculo reactivo de la cuota estimada mensual.
- [`frontend/src/Solicitudes.tsx`](../frontend/src/Solicitudes.tsx): Módulo interactivo "Mis solicitudes" con sondeo cada 2.5s, etiquetas visuales de estado, contador regresivo de expiración de reserva, botón de cancelación para el cliente y botón de entrega para el administrador.
