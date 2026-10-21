# Fase 10: Completar el frontend

Interfaz integrada para recorrer todas las operaciones exigidas desde el navegador, sin herramientas de API y sin respuestas simuladas: cada pantalla llama a los cuatro microservicios a través del proxy `/api/{servicio}` de nginx.

## Ejecutar y probar

```powershell
docker compose up -d --build --wait --wait-timeout 300
python -m pip install -r requirements-e2e.txt
python -m playwright install chromium
python scripts/check_phase10.py
```

Abrir http://localhost:8080. Las rutas son directas y sobreviven a la recarga: `/catalogo`, `/solicitudes`, `/clientes`, `/inventario`, `/modelo`, `/acceso`. Para tener un administrador: `python scripts/gestionar_admin.py crear admin@ejemplo.com <contraseña>`.

## Módulos

| Módulo | Cliente | Administrador |
|---|---|---|
| Acceso | Registro (con confirmación de contraseña) e ingreso | Ingreso |
| Catálogo | Búsqueda, filtro por categoría, cuota estimada, **solicitud a crédito** | Crear, editar (con `version_esperada`) y desactivar productos; incluir inactivos |
| Solicitudes | Mis solicitudes, detalle, cancelación | Todas las solicitudes, detalle, cancelación y **entrega** |
| Clientes | Mi perfil: contacto editable, finanzas de solo lectura | Listado, importación CSV, consulta de informes, edición de contacto, estado y finanzas |
| Inventario | — | Existencias, reservas y movimientos con nombres de producto; entradas de stock por selector |
| Modelo | — | Ficha: versión, umbral, algoritmo, run y experimento de MLflow, SHA-256, métricas de prueba, variables y enlace a MLflow |

La navegación muestra solo lo que el rol puede usar; si se abre una ruta de otro rol aparece «Permiso insuficiente». Los servicios siguen validando cada permiso (403/404).

## Decisiones

- **Cliente HTTP único** (`frontend/src/api.ts`): agrega el token, traduce 401/403/404/409/413/422/502/503 y la caída de red a mensajes legibles, y muestra los `details` de validación.
- **Idempotencia**: `IdempotencyKeys` conserva la clave mientras se reintenta el mismo contenido (red caída, 5xx, 503) y genera otra si el contenido cambia o la respuesta fue definitiva. Se usa en solicitud, cancelación, entrega y entrada de inventario. Los botones se deshabilitan durante el envío, pero esa no es la única protección.
- **Polling** (`usePolling` en `ui.tsx`): 2 s mientras haya estados pendientes (`EVALUANDO`, `PENDIENTE_INVENTARIO`, `CANCELACION_PENDIENTE`, `ENTREGA_PENDIENTE`, `VERIFICACION_PENDIENTE`). Cada 10 s si solo hay aprobadas cuya reserva puede vencer. Al fallar retrocede exponencialmente hasta 30 s y se pausa con la pestaña oculta. Los cambios de estado se anuncian en pantalla.
- **Evaluación favorable ≠ aprobada**: `PENDIENTE_INVENTARIO` se muestra como «Reservando producto» con la aclaración de que falta la confirmación de Inventario; cancelación y entrega se ven pendientes hasta el evento de confirmación.
- **Sesión**: el token se guarda en `sessionStorage` (no en `localStorage`) y se descarta al vencer su `exp`. Cualquier 401 cierra la sesión y lleva al acceso con el aviso «Tu sesión venció».
- **Móvil**: en pantallas de menos de 650 px las tablas se convierten en tarjetas, los modales se abren desde abajo y los formularios pasan a una columna.
- **MLflow**: la URL pública se pasa en la construcción de la imagen (`VITE_MLFLOW_URL`, por defecto `http://127.0.0.1:${MLFLOW_PORT}`). Se usa `127.0.0.1` y no `localhost` porque Docker publica MLflow solo en IPv4 y, en macOS, `localhost:5000` resuelve a `::1`, donde escucha el receptor de AirPlay.

## Cambio en Préstamos

`GET /modelo/info` incluye campos opcionales para la ficha: `algoritmo`, `experimento`, `exportado_en` y `metricas_prueba` (métricas numéricas de `test_at_optimal_threshold` del manifiesto). Son `null` si el manifiesto no los trae y no cambian los campos existentes. El contrato `contracts/openapi/prestamos.json` se regeneró con `scripts/build_contracts.py`.

## Pruebas de navegador

`scripts/check_phase10.py` (Playwright) crea sus propios datos y recorre:

| Caso | Resultado esperado |
|---|---|
| Admin crea producto y registra entrada desde la UI | Mensajes de éxito; existencias con el nuevo stock |
| Admin abre la ficha del modelo y Clientes | `riesgo-v1`, métricas e importación visibles |
| Cliente favorable solicita a crédito (AC14/AC01) | Resultado con precio cotizado; «Aprobada» por polling sin recargar |
| Respuesta perdida tras llegar al servidor | El reintento envía la misma `Idempotency-Key`; existe una sola solicitud nueva |
| Cliente cancela | «Cancelada» tras la confirmación de Inventario |
| Admin entrega | «Entregada» para el admin y, por polling, para el cliente |
| Recarga y ruta de otro rol | Datos persistidos; «Permiso insuficiente» en `/inventario` |
| API de Productos caída | Error legible y recuperación con «Actualizar» |
| Token inválido | Vuelta al acceso con «Tu sesión venció» |
| Cliente desfavorable | «Rechazada» con motivo del modelo de riesgo |
| Móvil 375 px | Sin desplazamiento horizontal en solicitudes, catálogo y perfil |

## Estado de la verificación

Verificado con el stack completo levantado (macOS, Docker Desktop):

- `npm run build` (incluye `tsc --noEmit`) sin errores.
- `python scripts/check_phase10.py`: los diez recorridos pasan, incluida la comprobación de que el enlace «Abrir MLflow» responde desde MLflow.
- Sin regresiones: `check_infrastructure.py`, `check_phase8.py`, `check_phase9.py` y `validate_contracts.py` pasan.

Ajustes hechos al verificar en macOS:

- La URL de MLflow usa `127.0.0.1` (en el frontend y en `check_infrastructure.py`): `localhost:5000` resolvía al receptor de AirPlay.
- `check_phase8.py` espera hasta 5 s el 503 tras borrar `active_model.json`: Docker Desktop tarda unos 0,5 s en reflejar el borrado en el bind mount.
- `infra/postgres/init.sh` es ejecutable: sin ese permiso, Postgres se inicializaba sin roles ni bases de datos.
