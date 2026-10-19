# Convenciones REST y seguridad

Los archivos `contracts/openapi/{servicio}.json` son contratos de diseño OpenAPI 3.1.0, no APIs ya desplegadas. Las rutas se expresan relativas a cada servicio; el proxy expondrá `/api/{servicio}`. No agregar un prefijo distinto en la implementación sin actualizar los contratos.

## Datos y respuestas

- JSON UTF-8, objetos cerrados, UUID, fechas RFC3339 UTC, paginación `limit` (1–100, defecto 20) y `offset` (>=0). Listas devuelven items, total, limit y offset; orden estable por created_at e id.
- Importes REST como cadenas decimales con exactamente dos decimales; convertir a Decimal. Features del endpoint técnico ML usan números JSON finitos. Correlación: `X-Correlation-ID` UUID opcional de entrada y siempre devuelto; generar uno si falta.
- Error común: `code`, `message`, `correlation_id`, `details` con pares campo/mensaje, sin stack ni secretos.
- 401 token ausente/inválido; 403 rol incorrecto; 404 inexistente o recurso ajeno; 409 conflicto de versión/estado/idempotencia; 422 estructura/rangos; 503 dependencia imprescindible no disponible.
- PATCH exige `version_esperada`; conflicto devuelve 409 y obliga a releer. Todos los cambios incrementan versión una vez. Producto desactivado sigue visible para admin; cliente ve solo activos.
- GET health indica proceso vivo. Ready indica modelo/BD críticos; devuelve 503 si faltan. Broker temporalmente caído: Préstamos puede aceptar a outbox hasta 1.000 mensajes pendientes; después 503 antes de aceptar nueva solicitud. Redis caído es degradación, no indisponibilidad de Productos.
- Validaciones de relación se implementan además del esquema: cuota de features coincide con la fórmula de tasa fija dentro de COP 0,01; disponible = físico − reservado; totales de importación suman total_filas. El endpoint técnico no acepta una cuota arbitraria inconsistente.

## Identidad y permisos

Clientes emite JWT con firma asimétrica, `sub` usuario, `cliente_id` si aplica, `role`, `iss=credimarket-clientes`, `aud=credimarket-api`, `iat`, `exp` y `jti`. Duración inicial 30 minutos; sin refresh en v1. Los servicios solo reciben la clave pública, validan algoritmo permitido, firma, audiencia, emisor y expiración. Logout borra el token en el navegador; no promete revocación inmediata de tokens ya emitidos. Secretos se generan fuera de Git.

Registro público `POST /clientes`: nombre, email y contraseña; crea usuario cliente y perfil financiero incompleto. No acepta rol, clave externa ni atributos financieros. Admin puede completar y validar finanzas; un cliente solo edita nombre/email de contacto. Email de contacto no cambia identidad de login. Cuentas de demo vinculadas a perfiles importados se provisionan mediante comando admin local, no por endpoint público. Un cliente incompleto recibe RECHAZADA/INFORMACION_INCOMPLETA al solicitar; null permitidos del pipeline no son incompletitud.

JWT de servicio emitido por comando controlado (no por login público), audiencia `credimarket-internal`, sub de servicio y scopes específicos. Endpoints internos requieren identidad de servicio; tener rol admin de usuario no basta. `/riesgo/predict` admite admin o servicio de pruebas con scope `riesgo:predict`. Claves privadas nunca van al frontend. Kafka usa credenciales por servicio y ACL de topics/grupos; su configuración se implementa en fase 2/6. Endpoints de infraestructura solo accesibles localmente para la demo.

| Operación | Cliente | Administrador | Servicio interno |
|---|---|---|---|
| Login / registro | Público | Login | No |
| Catálogo activo | Sí | Sí, incluye inactivos | Cotización con scope |
| Crear/editar/desactivar producto | No | Sí | No |
| Consultar/editar cliente | Propio, solo contacto | Todos, finanzas/activo | Préstamos: lectura financiera |
| Listar/importar clientes | No | Sí | No |
| Crear préstamo | Sí, identidad del token | No | No |
| Consultar/listar préstamo | Propios | Todos | No |
| Cancelar préstamo | Propio | Todos | No |
| Solicitar entrega | No | Sí | No |
| Inventario y entradas | No | Sí | Préstamos: consultar reserva |
| Modelo/info | No | Sí | Scope `modelo:read` |
| Inferencia técnica | No | Sí | Scope `riesgo:predict` |

Las extensiones `x-roles`, `x-scope` y `x-owner` de OpenAPI expresan la política a implementar; OpenAPI por sí mismo no ejecuta autorización. Para PATCH de clientes, `x-field-policy` restringe campos financieros a admin. Validar permisos antes de devolver o mutar información.

## Idempotencia y creación

Obligatoria `Idempotency-Key` en creación de préstamo, entradas de inventario, cancelación y entrega. Clave 8–128 caracteres; namespace por actor, método y recurso. Canonicalizar JSON validado, ordenar claves, guardar SHA-256 y restricción única. Misma clave/cuerpo: misma identidad/resultado de aceptación; cuerpo diferente: 409. GET muestra el estado actual, no el snapshot de creación.

Reclamar clave y préstamo EVALUANDO en transacción corta, con lease 30 s. Worker puede retomar tras vencer lease mediante bloqueo/compare-and-set. Guardar decisión y respuesta 201/202 junto al cambio final de evaluación; una caída entre commit y respuesta no pierde identidad. Si aún evalúa un duplicado, devolver 202 EVALUANDO y Location; no volver a evaluar en paralelo. Ante caída de API interna devolver 503 con recurso recuperable en details y conservar trabajo EVALUANDO; el worker reintenta y el cliente reutiliza la clave. No guardar 503 como respuesta final perpetua. El máximo de evaluación es 5 min: terminar ERROR_TECNICO sin inventario, permitiendo nueva solicitud con otra clave.

201 RECHAZADA representa resultado de negocio persistido. 202 PENDIENTE_INVENTARIO significa estado y outbox confirmados, aun cuando Kafka no haya recibido todavía el comando. Nunca responder APROBADA antes de la confirmación de reserva. Solicitud y acciones devuelven Location. Repetir cancelar un préstamo ya cancelado o entregar uno completado es un no-op 200 si la operación es la misma; acciones incompatibles devuelven 409. El control durable en BD protege aunque cambie la clave HTTP.

## Importación

`POST /clientes/importaciones`: multipart CSV UTF-8, máximo 10 MiB y 20.000 filas; 413 si excede, 422 cabecera/formato inválido, 201 si el procesamiento completo generó informe (incluye errores por fila). Procesamiento síncrono para los 12.000 registros; si las mediciones no lo permiten, versionar el contrato para importación asíncrona.

Cabeceras mínimas: cliente_id y ocho atributos financieros. Adaptador acepta columnas adicionales conocidas del histórico/nuevas (solicitud_id, monto, plazo, tasa, cuota, etiqueta) y las descarta; rechaza cabeceras desconocidas. No vincula clientes por email ni modifica usuarios. UNIQUE(clave_externa) y upsert de atributos financieros, conservando id, contacto y activo existentes. Nuevo perfil importado activo; actualizar no reactiva un cliente desactivado. Dos filas con la misma clave dentro del archivo: procesar la primera y rechazar las siguientes. Validar cada fila completa antes de escribir; filas válidas no se revierten por otras inválidas. Cada importación conserva un reporte consultable; reimportar puede crear un nuevo reporte, nunca otro cliente para la misma clave.

## Ejemplo de solicitud

```http
POST /prestamos
Authorization: Bearer <token-cliente>
Idempotency-Key: solicitud-demo-0001
Content-Type: application/json

{"producto_id":"22222222-2222-4222-8222-222222222222","cantidad":1,"plazo_meses":12}
```

La respuesta 202 devuelve préstamo con estado pendiente, URL en Location y snapshot de riesgo disponible; el navegador consulta GET cada 2 s. Un timeout de navegador no autoriza cambiar la clave ni mostrar éxito ficticio.

Referencia del formato: [OpenAPI 3.1](https://spec.openapis.org/oas/v3.1.0.html). Los permisos específicos son decisiones de este proyecto.
