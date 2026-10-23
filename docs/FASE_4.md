# Fase 4: Productos y Redis

Implementación del microservicio Productos, catálogo tecnológico, integración de caché Redis mediante el patrón Cache-Aside y cotización interna para Préstamos.

## Probar desde la interfaz

1. Abrir http://localhost:8080 y navegar a **Catálogo**.
2. Si no has iniciado sesión, la pantalla te indicará ingresar a **Clientes** para acceder como cliente o administrador.
3. Al iniciar sesión como cliente:
   - Se muestra el catálogo de productos tecnológicos activos con precio en COP, categoría, versión e identificador.
   - Puedes filtrar por categoría tecnológica (Portátiles, Celulares, Tablets, Monitores, etc.).
4. Al iniciar sesión como administrador:
   - Se habilita el botón **+ Nuevo Producto** para agregar nuevos artículos al catálogo.
   - Aparece la opción de **Incluir productos inactivos**.
   - Cada producto cuenta con botones para **Editar** (nombre, categoría, precio con control de versión optimista) y **Desactivar** (ocultándolo a los clientes).

## Código y responsabilidades

- `services/productos/app/models.py`: tablas `productos` (catálogo) e `invalidaciones_cache` (registro durable en PostgreSQL ante fallos de Redis).
- `services/productos/migrations/versions/0002_productos.py`: migración Alembic que crea las tablas y siembra el catálogo tecnológico inicial (10 productos de alta gama y consumo masivo).
- `services/productos/app/schemas.py`: esquemas Pydantic para validación de precios estrictamente positivos (`Money`), edición con versión esperada (`ProductoEditar`), desactivación y cotización.
- `services/productos/app/cache.py`: lógica Cache-Aside con TTL de 60 segundos, manejo de excepciones de conexión y registro de invalidaciones pendientes si Redis no está disponible.
- `services/productos/app/main.py`: endpoints REST según especificación OpenAPI (`GET /productos`, `POST /productos`, `GET /productos/{id}`, `PATCH /productos/{id}`, `POST /productos/{id}/desactivar`, `GET /interno/productos/{id}/cotizacion`).
- `shared/auth.py`: dependencia `require_internal` y `cotizar_claims` para autorizar únicamente peticiones internas con alcance `productos:cotizar`.
- `frontend/src/Catalogo.tsx`: vista de catálogo, filtrado, paginación, edición, creación y desactivación reactiva.
- `frontend/src/main.tsx`: integración de navegación y estado de sesión compartido entre módulos.
- `scripts/check_phase4.py`: suite completa de integración que valida catálogo, roles, concurrencia, cotización interna, Redis miss/hit/expiración/invalidación y resiliencia ante caída de Redis.


## Comportamiento y decisiones de diseño

* **Patrón Cache-Aside:**
  - Al consultar un producto por `GET /productos/{id}`, se busca primero en Redis con la clave `producto:{id}`.
  - Si no existe (*cache miss*), se consulta PostgreSQL, se almacena en Redis con un TTL de 60 segundos y se devuelve la respuesta.
  - Las consultas siguientes (*cache hit*) se sirven directamente desde la memoria de Redis.
* **Invalidación y consistencia:**
  - Al modificar el precio, datos o desactivar un producto, se actualiza PostgreSQL en una transacción atómica incrementando la `version`.
  - Inmediatamente se elimina la clave de Redis. La siguiente consulta obtendrá el valor fresco de PostgreSQL y volverá a calentar la caché.
  - Si Redis falla durante la invalidación, la falla se registra de forma durable en `invalidaciones_cache` en PostgreSQL para reintentos.
* **Tolerancia a caídas (Resiliencia):**
  - Si Redis está caído o detenido, el microservicio continúa respondiendo desde PostgreSQL. Conexión y lectura de Redis tienen timeout de 0.2 s por operación; eso no equivale al tiempo total de la petición. La fase 12 acotó también DNS y eliminó reintentos internos, y midió el fallback completo.
  - El endpoint `/ready` reporta estado `degraded` con `dependencies.redis = "degraded"` y responde HTTP 200, conforme a la arquitectura donde Redis es una mejora de rendimiento y no un punto único de falla.
* **Cotización interna para Préstamos:**
  - El endpoint `/interno/productos/{id}/cotizacion` exige un JWT interno emitido para la audiencia `credimarket-internal`, sujeto `prestamos` y alcance `productos:cotizar`.
  - Esta ruta omite Redis y consulta directamente PostgreSQL (fuente de verdad), garantizando que el servicio de Préstamos evalúe solicitudes con el precio oficial vigente sin riesgo de leer caché desactualizada.
* **Control de versiones optimista:**
  - Las operaciones de edición (`PATCH`) y desactivación exigen `version_esperada`. Una petición concurrente con una versión desactualizada recibe `HTTP 409 Conflict`.

## Verificación

Para ejecutar la verificación automatizada contra la infraestructura real:

```powershell
python scripts/check_phase4.py
```

Prueba realizada el 19 de octubre de 2026:
- Autenticación y control de acceso por roles (cliente vs administrador).
- Listado de catálogo activo y bloqueo de productos inactivos para clientes regulares.
- Creación de producto y comprobación del encabezado `Location`.
- Demostración de Redis Cache-Aside: Cache Miss inicial, Cache Hit y verificación de TTL (60 s).
- Control de versiones optimista (409) e invalidación comprobada de la clave en Redis tras cambio de precio.
- Desactivación de producto, ocultamiento a clientes (404) e invalidación de caché.
- Cotización interna protegida con JWT interno (`productos:cotizar`) consultando directamente PostgreSQL.
- Simulación de caída de Redis (`docker compose stop redis`): degradación controlada y respuesta continua desde PostgreSQL, seguida de recuperación automática al reiniciar el contenedor.
- Validación estática de todas las respuestas contra el contrato OpenAPI 3.1.
