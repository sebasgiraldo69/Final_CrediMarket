# CrediMarket: desarrollo por etapas con Kafka

Este documento define el orden de trabajo con Codex. Complementa el análisis de `PLAN_IMPLEMENTACION_CREDIMARKET.md` y reemplaza su cronograma inicial. Kafka es el broker elegido. Las etapas 1–12 están implementadas; ver [fase 12](docs/FASE_12.md) y [resultados](docs/validacion-fase-12.md). Sigue pendiente la etapa 13: entrega y sustentación.

Stack base: cuatro microservicios FastAPI, PostgreSQL con bases y credenciales separadas, Kafka, Redis, React con TypeScript, scikit-learn, MLflow y Docker Compose. El entrenamiento es offline; el modelo se sirve dentro de Préstamos.

## Etapa 1. Cerrar arquitectura y contratos

**Qué se hace:** convertir el enunciado en decisiones concretas antes de programar.

- Definir responsabilidades de Productos, Clientes, Préstamos e Inventario y sus tablas propias.
- Diseñar endpoints, entradas, respuestas, permisos y errores.
- Definir estados del préstamo y de la reserva, transiciones, tiempos de espera, entrega, cancelación y vencimiento.
- Definir contratos JSON de comandos y eventos Kafka, incluyendo identificadores, versión y correlación.
- Escribir el ADR Kafka frente a RabbitMQ: justificar la elección, supuestos de carga, retención, orden, consumidores, fallos y costo operativo.
- Mapear los 16 casos de aceptación a pruebas y responsables; mantener autenticación y roles dentro del alcance evaluado.

**Entregables:** diagramas, contratos REST/eventos, tabla completa de estados, ADR y backlog.

**Se termina cuando:** cada operación tiene servicio responsable, datos de entrada, resultado esperado y prueba de aceptación identificada.

## Etapa 2. Crear repositorio e infraestructura reproducible

**Qué se hace:** preparar una base ejecutable para desarrollar todos los componentes.

- Crear carpetas de servicios, frontend, ML, contratos, infraestructura, scripts y pruebas.
- Configurar dependencias reproducibles, Dockerfiles, `.env.example` y exclusión de secretos.
- Preparar Compose con PostgreSQL, Kafka en KRaft, Redis, MLflow y esqueletos de los cuatro servicios.
- Crear bases/usuarios independientes y migraciones; persistir bases, Kafka y artefactos MLflow en volúmenes.
- Configurar listeners Kafka accesibles desde contenedores y herramientas locales; crear topics mediante un paso repetible.
- Preparar healthchecks, logs con correlation_id y comandos de arranque/parada.
- Crear la base React y su navegación; las pantallas se conectan progresivamente cuando existan APIs.

**Entregables:** infraestructura local, servicios mínimos, estructura del frontend y guía de arranque.

**Se termina cuando:** el entorno arranca siguiendo la guía, cada servicio usa solo su base y los datos sobreviven a un reinicio normal. Todavía no se considera implementado el flujo de crédito.

## Etapa 3. Implementar Clientes, acceso e importación

**Qué se hace:** disponer de clientes persistidos y usuarios autorizados para operar.

- Registrar, consultar y actualizar clientes; definir qué campos puede editar el cliente y cuáles administra un responsable.
- Implementar sesión, contraseñas hasheadas, tokens con vencimiento y roles cliente/administrador.
- Verificar identidad y permisos en backend; preparar protección para comunicación interna.
- Importar atributos de cliente desde CSV usando `cliente_id` como clave externa única.
- Validar por fila y reportar insertados, actualizados, sin cambios y rechazados con causa.
- Separar registros financieros de cuentas de acceso: importar un cliente no le crea automáticamente una contraseña.
- Conectar acceso, edición de cliente e importación a las pantallas disponibles.

**Entregables:** servicio Clientes, migraciones, autenticación, importador y pantallas correspondientes.

**Se termina cuando:** importar dos veces no duplica clientes, los errores se explican por fila y un usuario no puede operar con permisos ajenos.

## Etapa 4. Implementar Productos y Redis

**Qué se hace:** construir catálogo, precios y cotizaciones confiables.

- Crear, listar, editar y desactivar productos con precio decimal, categoría y versión.
- Agregar datos iniciales de productos: los CSV entregados no contienen catálogo.
- Implementar cache-aside con claves y TTL documentados.
- Invalidar después de actualizar la base y responder desde PostgreSQL si Redis falla.
- Implementar cotización interna que consulte la fuente de verdad y verifique producto activo.
- Conectar catálogo y administración de productos al frontend.

**Entregables:** Productos, integración Redis, cotización interna y catálogo funcional.

**Se termina cuando:** se demuestran miss, hit, expiración, invalidación y caída; cambiar el precio produce una cotización nueva verificable.

## Etapa 5. Implementar Inventario y reservas atómicas

**Qué se hace:** proteger las existencias frente a operaciones simultáneas.

- Crear existencias, reservas y movimientos, separando stock físico, reservado y disponible.
- Registrar entradas autorizadas y consultar reservas/movimientos.
- Implementar reserva mediante transacción y actualización condicional en PostgreSQL.
- Impedir stock negativo y reservas duplicadas por préstamo.
- Implementar operaciones de liberar, entregar y vencer bajo control transaccional.
- Definir una marca durable de cancelación para impedir reservas que lleguen después de cancelar.
- Probar el dominio antes de conectarlo completamente a Kafka; las pruebas no crean endpoints públicos de reserva para el navegador.

**Entregables:** dominio Inventario, migraciones y pruebas de concurrencia.

**Se termina cuando:** dos solicitudes por la última unidad producen una sola reserva; liberar o entregar dos veces no altera nuevamente el stock.

## Etapa 6. Integrar Kafka con entrega y consumo confiables

**Qué se hace:** transportar comandos y resultados reales entre Préstamos e Inventario.

| Elemento | Configuración inicial propuesta |
|---|---|
| Despliegue local | Un nodo KRaft persistente; sin alta disponibilidad |
| Topic de comandos | `credimarket.inventario.comandos.v1` |
| Topic de resultados | `credimarket.inventario.eventos.v1` |
| Particiones y retención | Tres por topic; siete días de retención |
| Clave | `prestamo_id` |
| Grupos | `inventario-v1` y `prestamos-v1` |
| Productor | Idempotencia habilitada y `acks=all` |
| Consumidor | Confirmación manual de offsets después de persistir |
| Fallos permanentes | Topics `.dlq`, retención inicial de 14 días |

- Implementar transactional outbox en ambos servicios: guardar cambios y publicación pendiente en una misma transacción.
- Publicar y marcar enviado únicamente después de recibir confirmación del productor.
- Guardar event_id procesado y efecto en una misma transacción local mediante inbox.
- Procesar secuencialmente dentro de cada partición; no confirmar offsets que cubran registros aún sin terminar.
- Manejar reinicios y rebalanceos. Definir reintentos de aplicación con contador durable, pausas de 5/15/60 s y polling activo; distinguirlos de los reintentos del cliente Kafka.
- Al agotar reintentos, persistir fallo y outbox de DLQ antes de avanzar el offset; el publicador completa el envío durablemente.
- Preparar inspección de mensajes, lag, reenvío autorizado desde DLQ y replay diagnóstico sin efectos de negocio.

El orden por partición no sustituye la reserva atómica: dos préstamos del mismo producto pueden ir a particiones distintas. Tampoco hay atomicidad automática entre Kafka y PostgreSQL; por eso se conservan outbox, inbox y restricciones de negocio. Referencia: [diseño de Kafka](https://kafka.apache.org/41/design/design/).

**Entregables:** productores, consumidores, creación de topics, outbox/inbox, reintentos y DLQ.

**Se termina cuando:** una reserva real viaja por Kafka y devuelve un resultado; reiniciar un consumidor o duplicar el mensaje no duplica el efecto. Esta etapa usa comandos de prueba de integración, sin presentar todavía una aprobación de crédito completa.

## Etapa 7. Preparar datos y entrenar el modelo

**Qué se hace:** producir un modelo reproducible y evaluar su desempeño sin fuga de datos.

- Validar tipos, rangos, faltantes, duplicados y clases; crear EDA y diccionario.
- Registrar hashes y separar entrenamiento/validación/prueba 60/20/20 con estratificación y semilla fija.
- Excluir identificadores y objetivo de las entradas; documentar tasa constante y redundancia de cuota.
- Tratar correctamente el porcentaje puntual ausente por falta de historial.
- Construir pipeline con imputación, codificación y escalado cuando corresponda, aprendidos solo con entrenamiento.
- Ejecutar baseline más seis candidatos repartidos entre regresión logística, árbol y random forest.
- Registrar parámetros, métricas y artefactos en MLflow; seleccionar por criterio previamente fijado y ajustar umbral con validación y costos ficticios.
- Evaluar prueba solamente después de congelar las decisiones.

**Entregables:** scripts, particiones, historial MLflow, informe de selección y pipeline candidato.

**Se termina cuando:** se pueden consultar al menos siete ejecuciones y reproducir la preparación. Las 200 solicitudes nuevas se reservan para inferencia, sin inventar métricas de clasificación.

## Etapa 8. Exportar y servir el modelo desde Préstamos

**Qué se hace:** transformar el experimento elegido en una dependencia estable del sistema.

- Exportar pipeline completo y manifiesto con versión, run ID, hashes, variables, clase positiva, umbral y dependencias.
- Crear promoción explícita de candidato a modelo activo.
- Cargar el modelo al iniciar Préstamos y comprobar integridad/compatibilidad.
- Implementar `/riesgo/predict`, `/modelo/info`, `/health` y `/ready`.
- Validar entradas y proteger inferencia interna; devolver probabilidad, decisión de riesgo, umbral y versión.
- Comparar predicciones offline/API y ejecutar inferencia batch del CSV sin etiqueta.

**Entregables:** artefacto versionado, manifiesto, selección de versión activa y API real de riesgo.

**Se termina cuando:** las predicciones coinciden dentro de una tolerancia documentada y la API informa que no está lista si falta el modelo. No se entrena dentro de una petición.

## Etapa 9. Completar el flujo de Préstamos

**Qué se hace:** unir cliente, cotización, riesgo e inventario en una operación trazable.

- Implementar `POST /prestamos` con Idempotency-Key y unicidad durable; misma clave/cuerpo devuelve la misma solicitud, otro cuerpo devuelve 409.
- Obtener cliente por API y precio vigente desde Productos; calcular monto y cuota en backend.
- Guardar características, cotización, probabilidad, umbral y versión utilizados.
- Rechazar por reglas/riesgo sin solicitar inventario.
- Guardar estado pendiente y comando en outbox; devolver HTTP 202 para la solicitud favorable aceptada.
- Procesar resultados Kafka y aprobar solo cuando exista reserva confirmada y vigente.
- Implementar cancelación, liberación, entrega, vencimiento y sus estados intermedios.
- Resolver eventos tardíos, duplicados, operaciones incompatibles y solicitudes detenidas por caídas.
- Exponer consulta/listado con control de propietario y conectar la primera compra completa al navegador.

**Entregables:** flujo completo, máquina de estados implementada e historial auditable. Ver informe en [docs/FASE_9.md](docs/FASE_9.md).

**Se termina cuando:** funcionan aprobación, rechazo, falta de stock, entrega y cancelación; ningún evento tardío reactiva un préstamo cancelado y ningún fallo técnico se registra como rechazo crediticio. (Verificado mediante [scripts/check_phase9.py](scripts/check_phase9.py)). Estado: **COMPLETADO**.

## Etapa 10. Completar el frontend

**Qué se hace:** cerrar los módulos y convertir el flujo integrado en una experiencia demostrable.

- Completar catálogo, clientes/importación, solicitud, seguimiento, inventario y ficha del modelo.
- Mostrar pendientes y actualizar estados automáticamente mediante polling.
- Mantener la clave de idempotencia en reintentos del mismo envío.
- Ofrecer administración de stock, entrega y cancelación con las APIs autorizadas.
- Manejar carga, formularios inválidos, sesión vencida, permisos, conflicto y API caída.
- Ajustar navegación por rol y visualización en móvil; incluir acceso documentado a MLflow.

**Entregables:** interfaz integrada y pruebas de navegador.

**Se termina cuando:** el usuario puede recorrer las operaciones exigidas sin herramientas API y los cambios persisten. Las pantallas no simulan respuestas exitosas.

## Etapa 11. Completar MLOps: monitoreo, v2 y rollback

**Qué se hace:** demostrar que el modelo tiene un ciclo de vida controlado.

- Registrar errores, latencia, versión, scores y faltantes evitando datos financieros completos en logs.
- Comparar distribuciones y generar un lote de drift explícitamente simulado.
- Crear una segunda versión mediante una variación documentada; no ajustar repetidamente usando prueba.
- Promover v1 a v2 y restaurar v1 con procedimiento explícito.
- Verificar que los préstamos históricos conservan la versión que los evaluó.

**Entregables:** reporte de monitoreo/drift, segunda versión y comandos de promoción/rollback.

**Se termina cuando:** el cambio y la restauración se demuestran por API y MLflow con trazabilidad. No se afirma que drift implica pérdida de precisión sin etiquetas nuevas.

## Etapa 12. Ejecutar aceptación, fallos y mediciones

**Qué se hace:** comprobar sistemáticamente los 16 casos del enunciado.

- Ejecutar todos los casos de negocio, autorización, frontend, importación y modelo.
- Competir por la última unidad y repetir solicitudes HTTP y eventos.
- Interrumpir Kafka, consumidores y publicadores en puntos de fallo: después del commit de BD, antes de publicar y antes de confirmar offsets.
- Verificar recuperación, outbox, DLQ, rebalanceos y ausencia de efectos duplicados.
- Medir Redis: hit/miss, expiración, invalidación, caída, p50/p95 y tasa de aciertos bajo cargas comparables.
- Medir recursos del entorno y documentar límites reales, incluida la ausencia de alta disponibilidad del nodo Kafka único.
- Corregir defectos y guardar evidencia reproducible por caso.

**Entregables:** matriz de aceptación ejecutada, scripts de fallos, resultados y reporte de rendimiento.

**Se termina cuando:** pasan los 16 casos y se conservan evidencias; no basta con que funcione únicamente el recorrido favorable.

## Etapa 13. Preparar entrega y sustentación

**Qué se hace:** asegurar que otra persona pueda levantar y explicar el proyecto.

- Completar README, integrantes, responsabilidades, diagramas y ADR.
- Documentar generación local de secretos, cuentas de demo, puertos y recuperación de volúmenes.
- Incluir artefacto inicial propio, manifiestos y forma de restaurar o reproducir el historial MLflow.
- Probar instalación desde un clon limpio siguiendo únicamente la documentación.
- Preparar guion de demo: aprobación, rechazo, falta de stock, cancelación, entrega, cambio de precio, importación, Kafka y versión/rollback.
- Ensayar preguntas cruzadas para que todos expliquen arquitectura, consistencia y ML.

**Entregables:** repositorio reproducible, documentación y demostración preparada. Ver guía en [docs/FASE_13.md](docs/FASE_13.md), guion de demo en [docs/guion_demo.md](docs/guion_demo.md) y preguntas técnicas en [docs/preguntas_sustentacion.md](docs/preguntas_sustentacion.md).

**Se termina cuando:** un integrante distinto al autor de cada componente puede ejecutar y explicar el sistema con lo entregado. (Verificado mediante [scripts/check_phase13.py](scripts/check_phase13.py)). Estado: **COMPLETADO**.

## Dependencias y forma de trabajo

Orden recomendado: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13. La etapa 7 puede avanzar después de 2 mientras otro integrante desarrolla backend; 8 necesita 7 y 9 necesita 3–6 y 8. El frontend empieza en 2 y se integra progresivamente, aunque su cierre sea la etapa 10.

La estimación inicial sigue siendo de 15–20 jornadas de equipo, sujeta a dedicación, experiencia y recursos. Las etapas son unidades de entrega, no equivalen a un día cada una. Ajustar el calendario al completar infraestructura y la primera integración Kafka.

Para trabajar con Codex, pedir una etapa o una parte verificable de ella por vez. En cada ciclo se revisa el repositorio, se implementa, se ejecutan las pruebas pertinentes y se informa qué quedó listo y qué falta. No dar una etapa por cerrada solo porque se generaron archivos.

Proyecto completado: las 13 etapas del plan de desarrollo han sido implementadas, verificadas y documentadas para su entrega final.
