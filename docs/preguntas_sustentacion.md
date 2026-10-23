# Preguntas y Respuestas Técnicas para Sustentación

Este documento compila las preguntas conceptuales y de diseño arquitectónico más relevantes sobre el sistema CrediMarket, con sus respuestas técnicas fundamentadas en la implementación real del proyecto.

---

## 1. Arquitectura y Microservicios

### ¿Por qué se implementaron bases de datos independientes por servicio en lugar de una base de datos compartida?
- **Respuesta**: Para garantizar el aislamiento de dominio, autonomía de despliegue y evitar el acoplamiento a nivel de esquema (patrón *Database-per-Service*). Cada servicio (`productos`, `clientes`, `prestamos`, `inventario`) tiene su propio usuario de PostgreSQL con credenciales distintas y sin permisos de conexión (`CONNECT`) sobre las bases ajenas. Esto previene que un error en una consulta o una modificación de esquema en un servicio impacte a los demás, y fuerza a que cualquier interacción se realice mediante APIs explícitas o mensajería asíncrona.

### ¿Cómo se comunican los microservicios entre sí de forma síncrona y cómo se autentican?
- **Respuesta**: La comunicación síncrona se realiza mediante peticiones HTTP internas sobre la red privada de Docker. Se utiliza autenticación asimétrica basada en JWT firmados con algoritmo **RS256**:
  - El servicio emisor genera un token de servicio con la audiencia `credimarket-internal`, firmado con la clave privada RSA.
  - El token incluye un arreglo de *scopes* mínimos necesarios para la operación solicitada (por ejemplo, `productos:cotizar`, `clientes:read`, `reservas:read`).
  - El servicio receptor valida la firma utilizando la clave pública (`jwt_public.pem`) y verifica que el token contenga el scope exigido por el endpoint antes de retornar la información.

### ¿Cuál es la función del reverse proxy Nginx en el frontend?
- **Respuesta**: Centraliza el punto de entrada HTTP en el puerto `8080`, sirviendo los archivos estáticos de la aplicación React y enrutando los prefijos `/api/productos/`, `/api/clientes/`, `/api/prestamos/` e `/api/inventario/` hacia sus contenedores internos correspondientes. Esto previene problemas de CORS en el navegador, oculta la topología interna de red y evita exponer puertos innecesarios hacia el host exterior.

---

## 2. Consistencia Transaccional y Máquina de Estados

### ¿Qué problema resuelve el patrón Transactional Outbox y por qué no se publica directamente a Kafka desde el controlador HTTP?
- **Respuesta**: Si el servicio guardara en la base de datos y luego hiciera `producer.send()` a Kafka, la aplicación podría caerse justo después de hacer commit en la base de datos pero antes de enviar el mensaje, o viceversa, dejando el sistema en un estado inconsistente (el problema de la doble escritura distribuida). Con el patrón **Transactional Outbox**, la inserción del préstamo y la inserción del comando (`ReservaSolicitada`) se ejecutan dentro de la **misma transacción local ACID de PostgreSQL**. Un hilo trabajador en segundo plano lee los registros pendientes de la tabla `outbox`, los publica a Kafka y solo cuando recibe el ACK del broker marca `sent_at = NOW()`.

### ¿Cómo se maneja la idempotencia en las peticiones HTTP de creación (`POST /prestamos`)?
- **Respuesta**: Se exige la cabecera `Idempotency-Key` (entre 8 y 128 caracteres). El servicio calcula el hash canónico SHA-256 del cuerpo JSON de la petición y consulta la tabla `prestamos_idempotencia`:
  - Si no existe: procesa la solicitud, almacena la clave, el hash, el código HTTP y el cuerpo de respuesta en una transacción.
  - Si existe con el mismo hash: retorna de inmediato la respuesta previamente guardada (`202 Accepted` o `201 Created` en replay idéntico) sin recalcular ni duplicar la operación.
  - Si existe con un hash distinto: retorna `409 Conflict`, señalando que se reutilizó una clave para una intención de negocio distinta.

### ¿Qué es el patrón Inbox y cómo previene duplicados en los consumidores de Kafka?
- **Respuesta**: Kafka ofrece semántica de entrega *al menos una vez* (*at-least-once*), por lo que ante un reinicio o fallo de red pueden llegar mensajes repetidos. En la tabla `inbox`, cada evento procesado se registra con una clave primaria compuesta por `(consumer_group, event_id)`. Al recibir un mensaje, el consumidor intenta insertar en `inbox` dentro de la misma transacción en la que aplica el cambio de negocio. Si el `event_id` ya fue procesado, la transacción ignora el mensaje duplicado sin volver a modificar el saldo de existencias ni el estado del préstamo.

### ¿Por qué existe la regla de que ningún evento tardío puede reactivar un estado terminal (Invariante 5)?
- **Respuesta**: Los estados `RECHAZADA`, `ERROR_TECNICO`, `CANCELADA_SIN_STOCK`, `CANCELADA` y `COMPLETADA` representan el fin definitivo del ciclo de vida de una solicitud. Si un cliente cancela su préstamo mientras la reserva estaba en trámite (`CANCELACION_PENDIENTE` $\rightarrow$ `CANCELADA`), un evento tardío `InventarioReservado` podría llegar segundos después. La máquina de estados descarta la aprobación, mantiene el estado en `CANCELADA` y despacha automáticamente una orden de liberación (`LiberacionSolicitada`) a Inventario para no dejar inventario huérfano.

---

## 3. Apache Kafka y Mensajería Asíncrona

### ¿Por qué se eligió Apache Kafka frente a RabbitMQ para este flujo? (ADR-001)
- **Respuesta**: Aunque ambos brokers podían coordinar el flujo, se seleccionó Kafka por:
  1. **Log particionado y persistente**: Los mensajes no se eliminan al ser leídos; se retienen durante 7 días, permitiendo que múltiples grupos de consumidores (producción, monitoreo, auditoría o diagnóstico) lean el historial de forma independiente sin interferirse.
  2. **Particionamiento por clave**: Al usar `prestamo_id` como clave de partición, todos los eventos relativos a un mismo crédito se enrutan a la misma partición, garantizando orden estricto secuencial por préstamo.
  3. **Replay y depuración**: Permite reiniciar offsets para reproducir fallos y verificar la resiliencia de los consumidores.

### ¿Qué es KRaft y por qué no se usa ZooKeeper en este despliegue?
- **Respuesta**: KRaft (*Kafka Raft Metadata mode*) es el protocolo nativo de consenso de Apache Kafka que elimina la dependencia de un clúster externo de Apache ZooKeeper. Los propios nodos de Kafka gestionan los metadatos y el quórum mediante una máquina de estados Raft integrada, lo que reduce el consumo de recursos, simplifica la configuración de Docker Compose y acelera los tiempos de inicialización y recuperación ante fallos.

### ¿Cómo opera la Dead Letter Queue (DLQ) ante errores de procesamiento?
- **Respuesta**: Ante un mensaje corrupto (JSON inválido o violación de esquema), el mensaje se despacha directamente a la DLQ (`<topic>.dlq`) sin reintentos innecesarios. Ante un error transitorio de base de datos o red, el consumidor ejecuta hasta 3 reintentos con retraso exponencial (5s, 15s, 60s) registrados en la tabla `message_failures`. Si se agotan los reintentos, el mensaje se envía a la DLQ con sus metadatos de diagnóstico (topic, partición, offset original, causa del fallo y carga útil en base64) y se avanza el offset para no bloquear el flujo de la partición.

---

## 4. Rendimiento y Caché con Redis

### ¿Cómo funciona el patrón Cache-Aside implementado en Productos?
- **Respuesta**: Al consultar una cotización (`GET /productos/{id}/cotizacion`):
  1. El servicio consulta primero la clave en Redis (`cotizacion:<id>`).
  2. Si hay un acierto (*Cache HIT*), retorna inmediatamente el valor almacenado en memoria.
  3. Si no existe (*Cache MISS*), consulta la base de datos PostgreSQL, calcula la cotización, la almacena en Redis con un TTL de 60 segundos y la retorna al cliente.
  4. Los encabezados HTTP `X-Cache: HIT`, `X-Cache: MISS` o `X-Cache: BYPASS` informan de manera auditable el origen de la respuesta.

### ¿Cómo se gestiona la consistencia de la caché cuando se modifica el precio de un producto?
- **Respuesta**: Cuando un administrador actualiza el precio (`PATCH /productos/{id}`):
  1. Se actualiza el registro y se incrementa el número de versión en PostgreSQL.
  2. Inmediatamente se elimina la clave de caché en Redis (`DEL cotizacion:<id>`).
  3. La siguiente consulta de cotización forzará un *Cache MISS* y leerá el nuevo precio directamente de la base de datos, evitando que se originen préstamos con precios desactualizados.

### ¿Qué ocurre si Redis se cae o no responde durante una actualización de precio?
- **Respuesta**: El sistema implementa un mecanismo de fallback resiliente. Si la conexión a Redis falla, el servicio registra la orden en la tabla `invalidaciones_pendientes` dentro de la transacción de PostgreSQL y permite que la actualización continúe. Al recuperarse la conectividad, las invalidaciones pendientes se ejecutan, y mientras tanto las lecturas operan en modo *BYPASS* directamente contra PostgreSQL sin degradar la disponibilidad del negocio.

---

## 5. Machine Learning y MLOps

### ¿Por qué el modelo de riesgo se sirve dentro del microservicio de Préstamos y no como un microservicio independiente?
- **Respuesta**: Para minimizar la latencia de red en el camino crítico de la evaluación del crédito, eliminar un punto único de fallo adicional y garantizar consistencia transaccional. El modelo (`pipeline.joblib`) es una función determinista y sin estado que se carga una sola vez en la memoria del proceso web al iniciar. Con esto se logran tiempos de inferencia de 8 a 15 ms por solicitud sin sobrecargar la red interna.

### ¿Cómo se previno el Data Leakage durante el entrenamiento y la ingeniería de características?
- **Respuesta**: Se separaron estrictamente los conjuntos de datos en entrenamiento (70%), validación (15%) y prueba (15%) de forma estratificada por la variable objetivo antes de cualquier transformación. Los estimadores de imputación (medianas para variables numéricas, modas para categóricas) y los escaladores estándar (*StandardScaler*) se ajustaron (*fit*) **exclusivamente sobre el conjunto de entrenamiento** y únicamente se aplicaron (*transform*) sobre validación y prueba. Además, el conjunto de prueba se mantuvo completamente ciego hasta la evaluación final del modelo ganador.

### ¿Por qué se seleccionó Regresión Logística frente a algoritmos de ensamble como Random Forest o Gradient Boosting?
- **Respuesta**: Tras entrenar y comparar 7 arquitecturas en MLflow bajo las mismas condiciones:
  - La Regresión Logística con penalización L2 logró un **ROC-AUC de 0.7719** en validación y **0.7813** en prueba, superando el umbral mínimo exigido de 0.70.
  - Ofrece máxima interpretabilidad en sus coeficientes para cumplimiento normativo crediticio (explicabilidad de por qué se rechaza una solicitud).
  - Su latencia de inferencia en CPU es inferior a 10 ms con un consumo despreciable de memoria en comparación con modelos basados en árboles profundos.

### ¿Cómo se calculó el umbral óptimo de decisión de 0.26 en lugar del estándar 0.50?
- **Respuesta**: En riesgo crediticio, los costos de los errores son altamente asimétricos: aprobar a un cliente que no paga (Falso Positivo) genera pérdidas financieras considerables sobre el capital prestado, mientras que rechazar a un cliente cumplidor (Falso Negativo) únicamente representa un costo de oportunidad del margen de interés. Mediante una matriz de utilidad económica sobre el conjunto de validación, se evaluaron umbrales entre 0.05 y 0.90, encontrando que el umbral de **0.26** maximiza la ganancia neta esperada del portafolio.

### ¿Cómo se monitoriza el Data Drift y cómo se ejecuta una promoción de versión o un rollback?
- **Respuesta**:
  - **Monitoreo de Drift**: El script `scripts/monitor_model.py` compara las distribuciones de las características en producción contra la línea base de entrenamiento mediante la prueba de dos muestras de Kolmogorov-Smirnov (KS-test) y el Índice de Estabilidad Poblacional (PSI).
  - **Promoción y Rollback**: Se gestionan mediante el puntero declarativo [`models/active_model.json`](../models/active_model.json). Al ejecutar `python scripts/promote_model.py --version riesgo-v2`, el archivo se actualiza atómicamente con la nueva ruta, hash SHA-256 y umbral. Si se requiere volver a la versión anterior, `python scripts/promote_model.py --version riesgo-v1` restaura el modelo inmediatamente sin necesidad de reentrenar ni reconstruir imágenes Docker.
