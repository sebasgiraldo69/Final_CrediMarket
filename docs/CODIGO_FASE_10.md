# Guía de código: Fase 10 — Frontend integrado

Recorrido por los archivos de `frontend/src`, en el orden recomendado de lectura.

| Archivo | Responsabilidad |
|---|---|
| [`api.ts`](../frontend/src/api.ts) | `api()` para todas las llamadas; `ApiError` con estado, `details` y `retryable`; mensajes por código HTTP; `IdempotencyKeys` |
| [`session.ts`](../frontend/src/session.ts) | Sesión en `sessionStorage`, vencimiento a partir del `exp` del JWT |
| [`labels.ts`](../frontend/src/labels.ts) | Textos de estados y motivos, estados pendientes/cancelables, política de montos y fórmula de cuota estimada |
| [`ui.tsx`](../frontend/src/ui.tsx) | Componentes comunes (`Feedback`, `Modal`, `Pagination`), formato de moneda/fecha, `usePolling`, nombres de producto |
| [`main.tsx`](../frontend/src/main.tsx) | Rutas por `pathname`, navegación por rol, cierre de sesión por 401 o vencimiento, página de inicio |
| [`Acceso.tsx`](../frontend/src/Acceso.tsx) | Registro e ingreso |
| [`Catalogo.tsx`](../frontend/src/Catalogo.tsx) | Catálogo, administración de productos y `SolicitudCredito` |
| [`Solicitudes.tsx`](../frontend/src/Solicitudes.tsx) | Seguimiento con polling, detalle, cancelación y entrega |
| [`Clientes.tsx`](../frontend/src/Clientes.tsx) | Perfil, listado, importación CSV y edición con `version_esperada` |
| [`Inventario.tsx`](../frontend/src/Inventario.tsx) | Existencias, reservas, movimientos y entradas |
| [`Modelo.tsx`](../frontend/src/Modelo.tsx) | Ficha del modelo activo y enlace a MLflow |

## Idempotencia en el navegador

```ts
// api.ts
keyFor(scope: string, payload: unknown): string {
  const serialized = JSON.stringify(payload ?? {});
  const current = this.pending.get(scope);
  if (current && current.payload === serialized) return current.key;
  const key = newKey(scope.split(':')[0]);
  this.pending.set(scope, { payload: serialized, key });
  return key;
}
```

Cada operación usa un `scope` (`solicitud:<producto>`, `cancelacion:<préstamo>`, `entrega:<préstamo>`, `entrada`). Tras una respuesta definitiva se llama `settle(scope)`. Si el error es transitorio (`retryable`: sin respuesta o 5xx), la clave se conserva y el botón cambia a «Reintentar». Las instancias viven a nivel de módulo, así que cerrar y reabrir el formulario con los mismos datos también reutiliza la clave.

## Polling con retroceso

```ts
// ui.tsx
const schedule = () => { timer = setTimeout(tick, fails ? Math.min(maxMs, baseMs * 2 ** fails) : baseMs); };
```

`Solicitudes` lo activa con 2 s si hay estados pendientes y con 10 s si solo hay aprobadas. `Inventario` refresca la pestaña visible cada 5 s y descarta respuestas de una pestaña o página anterior.

## Errores y sesión

`api()` llama al manejador registrado por `main.tsx` cuando un request con token recibe 401: la sesión se borra y cualquier ruta protegida muestra el acceso con el aviso de vencimiento. Un 409 recarga los datos del módulo (producto, cliente o préstamo) para que el siguiente intento use la versión vigente.
