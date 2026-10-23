# Guía de estudio de CrediMarket

Objetivo: explicar el sistema, encontrar la implementación, demostrar su comportamiento y reconocer sus límites. Esta guía corresponde al repositorio revisado después del commit `5ed73ea`. No sustituye leer el código ni acredita que toda afirmación de documentos de diseño esté implementada.

## Cómo estudiar

En cada bloque sigue cuatro pasos: explica el concepto con tus palabras, localiza el código, realiza el ejercicio y responde las preguntas sin leer. Si solo reconoces términos pero no puedes reconstruir el recorrido de los datos, repite el bloque.

Plan sugerido: diez sesiones de 60–90 minutos. Combina los bloques 1–2 en la primera; dedica una sesión a cada bloque 3–10 y la última al examen. Puedes aumentar el tiempo según tu experiencia. No necesitas memorizar cada línea: sí necesitas explicar las decisiones y localizar las partes importantes.

## 1. Problema y alcance

CrediMarket permite solicitar financiación de productos tecnológicos. El cliente se registra, consulta el catálogo y solicita un crédito. Préstamos obtiene datos del cliente y precio vigente, aplica reglas y evalúa riesgo. Una evaluación favorable inicia una reserva de existencias. El administrador puede confirmar la entrega; el cliente puede solicitar cancelación mientras las reglas lo permitan.

El sistema integra un clasificador de riesgo y una operación de inventario. El clasificador estima probabilidad de incumplimiento a 90 días; no conoce por sí mismo las existencias, no entrega productos y no garantiza pagos futuros. Una solicitud aprobada exige también una reserva vigente.

No hay pasarela real de pagos ni un sistema completo de recaudo de cuotas. La cuota calculada representa la financiación académica, no una integración bancaria.

**Ejercicio:** explica en un minuto quién usa el producto, qué problema resuelve y qué necesita para completar una entrega.

**Preguntas:** ¿riesgo favorable equivale a entrega? ¿Qué diferencia hay entre rechazo por riesgo y cancelación por falta de stock?

## 2. Mapa del repositorio y tecnologías

| Ruta | Responsabilidad | Lectura inicial |
|---|---|---|
| `frontend/` | Interfaz React y TypeScript, compilación con Vite y publicación con Nginx | `src/main.tsx`, `src/api.ts`, `nginx.conf` |
| `services/clientes/` | Registro, autenticación, perfiles e importación | `app/main.py`, `app/security.py`, `app/importer.py` |
| `services/productos/` | Catálogo, precios y caché | `app/main.py`, `app/cache.py` |
| `services/inventario/` | Existencias, reservas y movimientos | `app/domain.py`, `app/messaging.py` |
| `services/prestamos/` | Solicitudes, reglas, evaluación y coordinación | `app/main.py`, `app/domain.py`, `app/model_service.py` |
| `shared/` | Autenticación, ejecución y mensajería comunes | `auth.py`, `runtime.py`, `messaging.py` |
| `ml/src/` | Preparación, entrenamiento, selección y operación del modelo | `contract.py`, `train_and_select.py`, `phase11.py` |
| `models/` | Paquetes publicados y selección activa | `active_model.json`, manifiestos de cada versión |
| `contracts/` | Contratos de APIs y mensajes | `openapi/`, `events/` |
| `scripts/` | Configuración, operación y validaciones | `bootstrap.py`, `check_phase12.py` |
| `docs/` | Arquitectura, fases y evidencias | `arquitectura.md`, `estados.md`, `validacion-fase-12.md` |
| `compose.yaml` | Servicios, redes, secretos, volúmenes y salud | Archivo completo |

FastAPI define las APIs Python; Pydantic valida entradas; SQLAlchemy permite acceder a PostgreSQL; Alembic mantiene migraciones del esquema. PostgreSQL conserva datos durables. Redis sirve como caché opcional. Kafka transporta comandos y resultados. scikit-learn implementa el pipeline; MLflow conserva experimentos y artefactos. Docker Compose coordina los contenedores locales.

**Ejercicio:** encuentra dónde se implementa cada acción visible de la interfaz. Empieza por «Solicitar a crédito» y sigue su llamada HTTP.

**Pregunta:** ¿dónde está el backend? En los cuatro directorios de `services/`, con apoyo de `shared/`.

## 3. Arquitectura, Docker y propiedad de datos

Hay cuatro microservicios de negocio. Cada uno tiene responsabilidad y base de datos propias. Comparten una instancia PostgreSQL local, pero utilizan bases y credenciales independientes. MLflow también usa almacenamiento propio para sus metadatos. No hay claves foráneas entre las bases de servicios; los UUID referencian recursos externos y las APIs o mensajes permiten coordinarlos.

Separar carpetas no basta para tener microservicios: importan los procesos, interfaces y límites de datos. La separación facilita evolución y aislamiento, pero introduce latencia, fallos parciales y consistencia eventual. Para un proyecto pequeño, un monolito modular sería más sencillo; aquí la separación permite demostrar integración distribuida.

Una imagen es la plantilla construida desde un Dockerfile. Un contenedor es una ejecución de esa imagen. Un volumen conserva datos fuera del ciclo de vida del contenedor. Una red permite resolver nombres internos como `postgres` o `clientes`. Dentro de un contenedor, `localhost` apunta a ese mismo contenedor.

Nginx publica la interfaz y enruta `/api/{servicio}/...` hacia el servicio correspondiente. PostgreSQL y Redis no tienen puertos publicados al host en el Compose revisado. Los accesos principales son `localhost:8080`, `127.0.0.1:5000` para MLflow y `localhost:19092` para Kafka externo.

`bootstrap.py` genera configuración y secretos locales sin reemplazar los existentes. Sus secretos son aleatorios; no se generan de forma determinista. Git no transporta los datos de tus volúmenes Docker ni crea automáticamente cuentas de usuario.

**Ejercicio:** identifica en Compose una imagen externa, un servicio construido localmente, una red, un volumen y un montaje de secretos.

**Preguntas:** ¿por qué recrear un contenedor no necesariamente borra los préstamos? ¿Por qué un pull no copia la base de datos del compañero?

## 4. HTTP, frontend, contratos y errores

Una API es una interfaz de operaciones y formatos. HTTP transporta solicitudes y respuestas; JSON representa sus datos. GET consulta, POST crea o solicita acciones y PATCH modifica parcialmente. El navegador llama al proxy; no se conecta directamente a Kafka, Redis o PostgreSQL.

`frontend/src/api.ts` centraliza `fetch`, token, `Idempotency-Key` y errores. `session.ts` gestiona la sesión. Los componentes muestran módulos según rol; el backend debe volver a comprobar los permisos. Ocultar un botón no protege una API.

El frontend consulta periódicamente solicitudes pendientes: es polling, no WebSocket. Una pantalla puede mostrar un estado intermedio hasta que el resultado asíncrono llegue. Una respuesta HTTP de aceptación no prueba que Inventario ya procesó el comando.

| Código | Significado útil en CrediMarket |
|---|---|
| 200 | Consulta o acción completada según el endpoint |
| 201 | Recurso creado; puede representar una solicitud rechazada persistida |
| 202 | Trabajo aceptado con procesamiento pendiente |
| 401 | Falta autenticación válida o las credenciales no sirven |
| 403 | Identidad válida sin permiso para esa operación |
| 404 | Recurso inexistente o ajeno según la política de privacidad |
| 409 | Conflicto de estado, versión o idempotencia |
| 422 | Datos inválidos |
| 502/504 | Fallo de comunicación o tiempo agotado en el proxy |
| 503 | Servicio o dependencia imprescindible no disponible |

OpenAPI describe las operaciones REST y JSON Schema describe los mensajes. Un contrato no ejecuta autorización ni demuestra por sí solo que una implementación lo cumple. La validación estática y las pruebas contra el sistema son evidencias diferentes.

**Ejercicio:** abre las herramientas del navegador, pestaña Network, crea una solicitud y registra método, ruta, estado HTTP, cuerpo y consultas posteriores. No compartas el token.

## 5. Identidad y seguridad

Clientes guarda hashes Argon2 de contraseñas, no contraseñas recuperables. Al ingresar correctamente emite un JWT firmado con RS256. La firma permite verificar integridad y emisor; un JWT firmado no está cifrado y su contenido puede leerse.

Los claims incluyen sujeto (`sub`), emisor (`iss`), audiencia (`aud`), emisión (`iat`), vencimiento (`exp`), identificador (`jti`) y rol o scopes. Los tokens de usuario duran 30 minutos en el código revisado. Los tokens internos usan audiencia y scopes distintos.

Los servicios verifican firma, algoritmo, emisor, audiencia y vencimiento. La clave pública permite verificar; la privada permite firmar. Clientes y Préstamos tienen necesidades de firma en el despliegue actual; no afirmes que la privada solo existe en Clientes. Kafka usa SASL/PLAIN y ACL; el transporte configurado es SASL_PLAINTEXT, no TLS.

Autenticación responde «quién eres». Autorización responde «qué puedes hacer». Además del rol importa la propiedad: un cliente solo puede consultar sus solicitudes. Un administrador de usuario no obtiene automáticamente permisos de servicio interno.

Cerrar sesión elimina el token del navegador; no implica revocación inmediata del JWT emitido. `.env` y `.secrets/` no deben publicarse. En producción harían falta medidas adicionales según el despliegue, como HTTPS, administración de secretos y controles de acceso operativos.

**Ejercicio:** compara el acceso a Inventario como cliente y administrador. Localiza `shared/auth.py` y explica cómo una API puede rechazar a un usuario aunque este construya la llamada manualmente.

## 6. Persistencia, dinero e importación

Una transacción local confirma o revierte conjuntamente cambios en una base. No convierte automáticamente operaciones de varios servicios en una transacción distribuida. Las restricciones UNIQUE evitan identidades u operaciones repetidas; CHECK protege invariantes; los bloqueos serializan modificaciones concurrentes.

Los UUID identifican recursos. Los importes usan Decimal y columnas numéricas decimales para evitar errores binarios de `float` en dinero. Las fechas se manejan en UTC. Las versiones esperadas detectan ediciones concurrentes: no se debe sobrescribir silenciosamente un cambio ajeno.

La importación adapta atributos financieros del CSV. La clave externa permite actualizar el mismo perfil sin crear otro cliente por cada importación. No crea automáticamente credenciales de acceso. Tampoco convierte montos del CSV en precios de productos. El reporte conserva filas válidas, errores y totales.

**Ejercicio:** compara `usuarios` y `clientes` en sus modelos. Explica por qué importar un perfil y registrar una cuenta son operaciones distintas. Revisa los modelos SQLAlchemy y sus migraciones: el primero describe tablas usadas por el código; las segundas evolucionan el esquema instalado.

## 7. Crédito: reglas, fórmula y estados

El servidor obtiene el precio vigente de Productos y calcula `monto = precio × cantidad`. La cotización interna consulta la base, evitando un precio viejo de caché. Guarda snapshots para explicar después qué datos se utilizaron, aunque el cliente o el precio cambien.

Política académica: cantidades 1–100, plazos de 6/12/18/24/36 meses y monto entre COP 500.000 y 15.000.000. La tasa mensual fija es 0,018. La cuota es:

`cuota = monto × r / (1 − (1 + r)^(-n))`

`r` es la tasa mensual y `n` el plazo. Se redondea con HALF_UP a dos decimales. El modelo usa esa cuota calculada como una característica; no inventa la tasa ni el precio.

Recorrido principal: evaluación y reglas → pendiente de inventario → aprobada con reserva → entrega pendiente → completada. La interfaz muestra «Entregada» para `COMPLETADA`. Existen rechazo, cancelación, falta de stock y verificación pendiente.

`APROBADA` significa que existe evidencia de una reserva vigente, no que se entregó físicamente el producto. `VERIFICACION_PENDIENTE` evita dar por utilizable una reserva cuya situación necesita confirmación. Un timeout no demuestra falta de stock ni autoriza inventar una cancelación final.

La especificación completa está en `estados.md`; contrástala con `domain.py`, `main.py` y los workers. No presentes todos los tiempos o mecanismos previstos en documentos iniciales como implementados sin encontrar su código y prueba.

**Ejercicio:** sigue una creación desde `main.py` a `evaluar_y_crear_solicitud` en `domain.py`; identifica lectura de perfil, cotización, predicción, persistencia y mensaje de salida.

## 8. Inventario y concurrencia

La invariante central es `fisico >= reservado >= 0`; `disponible = fisico − reservado`.

| Acción | Físico | Reservado | Disponible |
|---|---:|---:|---:|
| Inicio | 3 | 0 | 3 |
| Reservar una unidad | 3 | 1 | 2 |
| Cancelar esa reserva | 3 | 0 | 3 |
| Reservar otra vez | 3 | 1 | 2 |
| Entregar | 2 | 0 | 2 |

Reservar no descuenta físico. Entregar descuenta físico y reservado. Cancelar o vencer libera reservado. Inventario es la autoridad sobre esos cambios, no la pantalla del cliente.

Una consulta previa de disponibilidad no basta para evitar sobreventa: dos peticiones podrían leer la última unidad a la vez. La operación debe comprobar y modificar bajo transacción y bloqueos adecuados. Revisa los locks y restricciones en `services/inventario/app/domain.py`.

La reserva tiene vencimiento. Entrega y vencimiento deben competir bajo la misma protección para que una sola operación consuma la reserva. Una marca terminal de cancelación también protege contra una reserva que llegue tarde.

**Ejercicio:** con una unidad y dos solicitudes, explica por qué solo una puede reservar. Después explica qué debería pasar al repetir el mensaje de entrega.

## 9. Kafka, outbox, inbox e idempotencia

Kafka conserva registros en topics divididos en particiones. Un productor publica y un consumidor procesa. El offset identifica una posición dentro de una partición. Un grupo de consumidores reparte particiones entre sus miembros. La clave ayuda a mantener operaciones relacionadas en la misma partición; no existe orden global entre todas las particiones.

Un comando pide una acción: `ReservaSolicitada`, `LiberacionSolicitada`, `EntregaSolicitada`. Un resultado informa lo ocurrido: `InventarioReservado`, `InventarioInsuficiente`, `ReservaLiberada`, `ReservaExpirada`, `EntregaConfirmada` o rechazos de las acciones.

Kafka permite desacoplar la petición HTTP del trabajo de Inventario y absorber interrupciones. No sustituye PostgreSQL ni ejecuta las reglas de negocio. La configuración local con un solo broker no demuestra alta disponibilidad.

**Outbox:** la misma transacción guarda el cambio local y el mensaje pendiente. Un publicador envía posteriormente a Kafka. Evita perder la intención de publicar si el proceso cae después del commit. Puede enviar un duplicado si cae después del ACK y antes de marcar el envío.

**Inbox:** el consumidor guarda el mensaje procesado junto con el efecto local. Confirma el offset después del commit. Si cae entre ambos, Kafka puede entregar de nuevo y la deduplicación evita aplicar el efecto dos veces.

La entrega es al menos una vez; no afirmes «Kafka garantiza exactamente una vez en todo el sistema». Hay tres defensas distintas: clave HTTP contra reintentos del usuario, `event_id` contra reentrega del mismo mensaje y restricciones/estado de dominio contra repetir la operación con otro `event_id`.

La misma clave HTTP con el mismo cuerpo debe recuperar el resultado; cambiar el cuerpo con la misma clave produce conflicto. El mismo `event_id` con otro contenido es un problema de integridad. Un mensaje inválido o un fallo permanente puede ir a DLQ, donde se investiga y se controla su reenvío. Reintentar ciegamente no corrige datos inválidos.

La reconciliación consulta el estado autoritativo de Inventario cuando se necesita recuperar certeza. Complementa Kafka; no reemplaza el flujo normal por HTTP.

**Ejercicio:** explica las dos caídas anteriores y localiza sus evidencias en `check_phase12_faults.py` y `docs/evidencias/`. Lee `shared/messaging.py` para comprobar cuándo se guarda inbox y cuándo se confirma el offset.

## 10. Redis y degradación

Productos usa cache-aside: buscar en Redis; si hay HIT, utilizar el valor; si hay MISS, consultar PostgreSQL y poblar la caché. El TTL configurado es 60 segundos. Ante indisponibilidad de Redis, la consulta puede pasar a PostgreSQL con BYPASS.

Redis no es la fuente de verdad ni la deduplicación durable. La caché puede mostrar temporalmente datos antiguos; por eso la cotización interna obtiene el precio desde PostgreSQL. Al modificar un producto se intenta invalidar su entrada.

La fase 12 detectó demoras en DNS y reintentos del cliente Redis. Se acotó la espera inicial de resolución, se conserva la última IP conocida y se desactivaron reintentos internos para facilitar el fallback. Los timeouts de socket no acotan por sí solos toda resolución DNS.

Existe registro durable de invalidaciones pendientes, pero no un trabajador automático completo que vacíe esa tabla. No prometas esa recuperación como implementada. En la medición local la caché caliente no fue más rápida: explica los datos observados sin inventar una mejora. Consulta valores, unidades y condiciones en `validacion-fase-12.md`.

**Ejercicio:** encuentra el encabezado `X-Cache` y explica HIT/MISS/BYPASS. Distingue la caché Redis del broker Kafka y de PostgreSQL.

## 11. Datos y machine learning

El histórico tiene 12.000 registros etiquetados. Las 200 solicitudes nuevas se utilizan para inferencia y paridad; no tienen etiqueta para medir exactitud. La etiqueta es `incumplimiento_90d`; clase 1 significa incumplimiento, no aprobación.

Hay once predictores: ingresos, obligaciones, empleo, antigüedad laboral, meses de historial, créditos previos, atrasos, porcentaje puntual, monto, plazo y cuota. Identificadores, etiqueta y tasa constante no se usan como predictores.

El split es estratificado 60/20/20 con semilla 42: entrenamiento aprende parámetros; validación selecciona candidato y umbral; prueba evalúa al ganador congelado. Estratificar conserva aproximadamente la proporción de clases. La semilla ayuda a reproducir el experimento, pero no demuestra validez externa.

El pipeline incluye imputación, indicadores de faltantes donde corresponde, codificación one-hot y escalado para los estimadores que lo requieren. La mediana y demás transformaciones aprendidas se ajustan solo con entrenamiento para evitar fuga de información.

Se compara un baseline `DummyClassifier` con seis candidatos: dos regresiones logísticas, dos árboles y dos Random Forest. La selección usa Average Precision de validación; dentro de 0,005 del máximo usa Brier y complejidad como desempate. El ganador publicado es regresión logística C=1.

Una regresión logística transforma una combinación de características en una probabilidad mediante la función sigmoide. El parámetro C controla inversamente la regularización. No interpretes directamente coeficientes sin considerar escalado y codificación.

| Métrica | Qué debes explicar |
|---|---|
| Average Precision | Resume la relación precisión–recall al variar umbrales; mayor es mejor |
| ROC AUC | Capacidad de ordenar positivos sobre negativos; no equivale a exactitud |
| Brier | Error cuadrático de probabilidades frente a etiquetas; menor es mejor |
| Precision | De los clasificados como incumplidores, cuántos lo son |
| Recall | De los incumplidores reales, cuántos se detectan |
| Matriz de confusión | TP/FN/FP/TN respecto de clase positiva incumplimiento |

El umbral operativo publicado es 0,26. Un riesgo mayor o igual al umbral se clasifica como desfavorable. El código optimiza el umbral sobre validación con costos académicos: 5 por aprobar a un incumplidor y 1 por rechazar a un pagador. No son costos bancarios reales ni una garantía de rentabilidad.

Ejemplo: probabilidad 0,18 representa un riesgo estimado del 18 %, no una certeza individual. Si es favorable y cumple reglas, todavía necesita reservar stock. Una probabilidad no prueba que esa persona pagará.

**Ejercicio:** dibuja la matriz de confusión y ubica el error más costoso. Explica qué ocurre al bajar el umbral y por qué las 200 solicitudes sin etiquetas no permiten calcular recall real.

## 12. MLflow, publicación y MLOps

Entrenar aprende parámetros; inferir usa parámetros ya aprendidos. MLflow registra parámetros, métricas, ejecuciones y artefactos. No evalúa cada compra en línea: el modelo está cargado dentro de Préstamos.

`pipeline.joblib` serializa el preprocesamiento y estimador. El manifiesto describe variables, clase positiva, umbral, dependencias y hash. `active_model.json` selecciona el paquete publicado. Al iniciar, Préstamos comprueba integridad y compatibilidad antes de servirlo. Un hash acredita correspondencia de bytes, no que el modelo sea bueno o provenga de una fuente confiable.

Publicar una nueva versión no reescribe decisiones históricas: los préstamos conservan snapshot de datos, versión y evaluación. Git versiona artefactos y reportes, pero no transporta automáticamente la base de MLflow. `restore_tracking.py` permite reproducir y enlazar corridas cuando faltan, con procedencia explícita; no debe presentarse una reproducción como la ejecución original.

La fase 11 incorporó v2 con regresión logística C=0,5, comparación, promoción y rollback. V2 no se declara superior: su AP de validación fue ligeramente menor. No se reutilizó test para elegir v2.

Promoción y retorno explícitos, cuando quieras hacer el ejercicio:

```powershell
python scripts/promote_model.py --version riesgo-v2 --restart
python scripts/promote_model.py --version riesgo-v1 --rollback --restart
```

Estos comandos sí cambian la versión activa y reinician Préstamos. Hazlos en un ensayo controlado y verifica la ficha del modelo después.

Drift significa cambio de distribución respecto de una referencia. PSI cuantifica diferencias por intervalos; no prueba por sí solo pérdida de exactitud. El ensayo usa datos alterados de forma simulada. Para evaluar degradación predictiva real hacen falta resultados etiquetados. El monitoreo agregado desde logs se ejecuta por scripts, no es una plataforma continua de alertas.

**Ejercicio:** explica la diferencia entre entrenar, exportar, promover y reiniciar. Localiza el hash activo y la versión guardada en el detalle de un préstamo anterior.

## 13. Pruebas, operación y evidencia

Las pruebas estáticas revisan estructuras y consistencia de archivos; las de integración ejecutan servicios reales; las de navegador verifican recorridos visibles; las de fallos observan recuperación. Ninguna prueba demuestra ausencia absoluta de errores.

La fase 12 guardó una ejecución con 16 casos de aceptación aprobados y 15 suites. Sus pruebas cubren negocio, contratos, modelo, navegador, Kafka, caídas, duplicados y mediciones. La evidencia describe esa revisión y ese entorno, no certifica automáticamente cualquier cambio futuro ni capacidad de producción.

Los percentiles describen una muestra: p50 es mediana; p95 deja aproximadamente el 95 % de observaciones por debajo. No equivalen al peor caso ni a un SLA. Las mediciones locales secuenciales no demuestran rendimiento bajo alta concurrencia.

`/health` verifica vida del servicio; `/ready` comprueba preparación según las dependencias implementadas. Un 200 no demuestra que todos los recorridos del negocio funcionen. Para diagnosticar: identifica la acción, revisa Network, mira logs del servicio, verifica dependencias y sigue el identificador de correlación.

Comandos de operación desde la raíz:

```powershell
docker compose up -d --build --wait --wait-timeout 300
docker compose ps
docker compose logs --tail 80 prestamos inventario
python scripts/validate_contracts.py
```

La suite completa `python scripts/check_phase12.py` crea datos sintéticos, tarda varios minutos y detiene temporalmente servicios. No es necesaria para abrir la aplicación. Las cuentas demo escritas en fase 13 no se crean automáticamente; al revisar el último pull sus credenciales devolvieron 401 en este equipo. `check_phase13.py` depende de esas cuentas y no sustituye la suite completa.

## 14. Recorrido que debes dominar sin apuntes

1. El cliente hace clic y React construye una petición con identidad e idempotencia.
2. Nginx enruta la llamada hacia Préstamos.
3. Préstamos comprueba permisos, entrada y repetición de operación.
4. Consulta perfil y cotización autorizados, calcula monto y cuota y aplica reglas.
5. El pipeline estima riesgo con la versión cargada.
6. Si rechaza, persiste explicación y no solicita reserva. Si es favorable, persiste estado pendiente y mensaje outbox.
7. El publicador envía `ReservaSolicitada` a Kafka.
8. Inventario valida y deduplica, protege la operación y modifica stock bajo transacción.
9. Inventario guarda el resultado en outbox y este se publica a Kafka.
10. Préstamos consume el resultado, actualiza su estado y el navegador lo observa al consultar.
11. Entrega o cancelación recorren otro ciclo de comando y confirmación. El vencimiento puede liberar la reserva según su estado.

En cada paso responde: ¿quién ejecuta?, ¿qué datos usa?, ¿qué persiste?, ¿qué pasa si cae?, ¿qué ocurre si se repite?

## 15. Examen de sustentación

Responde en voz alta antes de consultar los bloques anteriores:

1. ¿Qué problema resuelve CrediMarket y qué queda fuera de alcance?
2. Dibuja componentes, bases de datos y conexiones HTTP/Kafka.
3. ¿Por qué no comparten tablas los servicios?
4. ¿En qué se diferencian imagen, contenedor y volumen?
5. ¿Cómo llega una llamada del navegador a FastAPI?
6. ¿Por qué 202 no significa aprobación?
7. ¿Cómo se evita usar un precio viejo al financiar?
8. ¿Cómo se calcula la cuota y por qué se usa Decimal?
9. ¿Qué diferencia autenticación de autorización y propiedad?
10. ¿Por qué un JWT firmado se puede leer y aun así no se puede modificar válidamente?
11. ¿Qué operación cambia físico, reservado y disponible?
12. ¿Cómo evitas vender dos veces la última unidad?
13. ¿Qué pasa si una cancelación llega antes de la reserva?
14. ¿Qué guardan outbox e inbox y en qué transacción?
15. ¿Qué pasa al caer después del ACK o antes de confirmar el offset?
16. ¿Por qué necesitas idempotencia de dominio además de event_id?
17. ¿Qué orden garantiza una partición y qué no garantiza Kafka?
18. ¿Cuándo envías a DLQ y cómo investigas un mensaje?
19. ¿Para qué sirve Redis si PostgreSQL ya tiene los productos?
20. ¿Qué limitación tienen las invalidaciones pendientes?
21. ¿Qué predice el modelo y cuáles son las once variables?
22. ¿Por qué separar entrenamiento, validación y prueba?
23. ¿Qué fuga produce calcular imputaciones antes de separar datos?
24. ¿Qué representan AP, Brier y los falsos negativos en este problema?
25. ¿Por qué 0,26 y no necesariamente 0,50?
26. ¿Por qué v2 no significa automáticamente mejor modelo?
27. ¿Qué sucede si MLflow cae pero Préstamos ya tiene su modelo cargado?
28. ¿Qué hacen el manifiesto, SHA-256 y el rollback?
29. ¿Drift demuestra caída de exactitud? ¿Qué datos faltan para saberlo?
30. ¿Qué prueban realmente las evidencias y qué necesitarías para producción?

Puntúa cada respuesta: 0 si no puedes explicarla; 1 si defines el concepto; 2 si lo relacionas con un archivo y ejemplo; 3 si además explicas un fallo y la evidencia que lo verifica. Repite los bloques donde no llegues a 2 y ensaya el recorrido completo antes de la sustentación.

## 16. Relación con las fases del proyecto

| Fase | Aprendizaje que debes demostrar |
|---|---|
| 1 | Requisitos, contratos, arquitectura e invariantes |
| 2 | Docker, redes, secretos, persistencia e infraestructura |
| 3 | Clientes, acceso, permisos e importación |
| 4 | Productos, precios y caché |
| 5 | Reservas, movimientos y concurrencia |
| 6 | Kafka, reintentos, deduplicación y DLQ |
| 7 | Datos, comparación de modelos y selección |
| 8 | Artefactos, publicación, inferencia y paridad |
| 9 | Coordinación del préstamo y acciones de negocio |
| 10 | Interfaz, sesión, formularios y estados visibles |
| 11 | Monitoreo, drift, v2, promoción y rollback |
| 12 | Aceptación, caídas, recuperación y mediciones |
| 13 | Entrega reproducible, demostración y defensa de decisiones |

Material de contraste: las guías `FASE_*.md`, `preguntas_sustentacion.md`, `guion_demo.md` y los reportes de validación. Las guías iniciales incluyen decisiones previstas; ante discrepancias debes contrastar implementación y evidencia antes de prometer un comportamiento.
