# Fase 2: infraestructura local

Estado: completada y verificada. Consultar [resultados y alcance de las pruebas](validacion-fase-2.md).

La base ejecutable incluye cuatro procesos FastAPI con `/health`, `/ready`, documentación de API implementada y migraciones independientes; PostgreSQL, Kafka KRaft, Redis, MLflow y frontend React con navegación inicial. No implementa todavía operaciones de clientes, catálogo, crédito ni inventario.

## Arranque

Requisitos: Docker Desktop con motor Linux/WSL2 activo, Docker Compose y Python 3 para scripts del host. El proyecto usa imágenes Linux; las dependencias Python/Node de ejecución se instalan dentro de las imágenes. La primera construcción necesita conexión a los registros de contenedores, PyPI y npm.

Desde la raíz, en PowerShell:

```powershell
python scripts/bootstrap.py
docker compose config --quiet
docker compose up -d --build --wait --wait-timeout 300
docker compose ps --all
python scripts/check_infrastructure.py
```

El primer arranque tarda más por las descargas y la creación de topics/ACL Kafka. `kafka-volume-init` prepara el propietario del volumen para el usuario no root de Kafka; `kafka-init` crea topics y ACL. Ambos deben terminar con código 0: son trabajos de inicialización, no servicios que deban permanecer activos. Las migraciones de cada API se ejecutan antes de Uvicorn. Docker usa `/health` para arrancar la infraestructura; no confundir esa señal con disponibilidad del flujo de crédito.

| Acceso | Dirección local |
|---|---|
| Frontend | http://localhost:8080 |
| MLflow | http://localhost:5000 |
| Documentación Productos | http://localhost:8080/api/productos/docs |
| Documentación Clientes | http://localhost:8080/api/clientes/docs |
| Documentación Préstamos | http://localhost:8080/api/prestamos/docs |
| Documentación Inventario | http://localhost:8080/api/inventario/docs |
| Kafka desde herramientas locales | localhost:19092, SASL/PLAIN |
| Kafka desde contenedores | kafka:9092, SASL/PLAIN |

Puertos configurables en `.env`: FRONTEND_PORT, MLFLOW_PORT y KAFKA_EXTERNAL_PORT. Cambiarlos requiere `docker compose up -d` para recrear la configuración. Los puertos publicados se vinculan solo a loopback. PostgreSQL, Redis y las APIs no publican puertos directos al host.

Préstamos devuelve **503 en `/ready` con `model=unavailable`** deliberadamente, hasta integrar el modelo real en fase 8. Productos, Clientes e Inventario comprueban su base; Productos también Redis e Inventario/Préstamos consultan metadatos Kafka con su propia identidad. La caída de Redis/Kafka se informa como degradación; falta de BD o modelo crítico es indisponibilidad. El frontend muestra conectividad de procesos real, no aprobaciones simuladas.

## Configuración y secretos

`bootstrap.py` crea `.env` y `.secrets/` con contraseñas aleatorias, sin imprimirlas ni cambiarlas al repetirlo. Ambos están excluidos de Git y del contexto de construcción Docker. Solo `.env.example` se versiona. No copiar salida de `docker compose config` sin `--quiet`: incluye variables resueltas.

PostgreSQL crea productos_db, clientes_db, prestamos_db, inventario_db y mlflow_db, cada una con propietario distinto. Se revoca CONNECT público y se concede solo al dueño. Las APIs no reciben la contraseña del superusuario. Las credenciales de inicialización se aplican únicamente con volumen PostgreSQL vacío; cambiar `.env` no rota contraseñas de una base existente.

Kafka usa admin para inicialización/diagnóstico e identidades prestamos/inventario con ACL de sus topics y grupos. Los archivos JAAS son secretos montados, no parte de la imagen. CONTROLLER es un listener interno no publicado; su principal anónimo se reserva para coordinación KRaft. Los listeners de clientes exigen SASL. SASL_PLAINTEXT es la elección de demo local, no cifra el tráfico; un despliegue remoto necesitará TLS.

MLflow usa su propia base y volumen de artefactos. Su interfaz de esta fase es local y no tiene acceso remoto público. No hay aún emisión de JWT de usuarios; se implementa en fase 3. El frontend no recibe contraseñas.

## Persistencia y operación

Volúmenes de Compose: postgres_data, kafka_data y mlflow_artifacts (prefijo del proyecto). Redis es caché descartable, sin persistencia. MLflow almacena metadatos en PostgreSQL y sirve artefactos mediante HTTP desde `/mlartifacts`; clientes no necesitan montar ese directorio.

```powershell
docker compose logs --tail 100 productos clientes prestamos inventario
docker compose restart productos
docker compose stop
docker compose start
```

`docker compose down` elimina contenedores/red pero conserva volúmenes. No agregar `--volumes` al detener el trabajo: borra los datos de este proyecto. No es necesario hacerlo para reconstruir imágenes o repetir la inicialización Kafka. `kafka-init` crea topics con `--if-not-exists` y añade ACL repetibles; cambios de retención/particiones de topics existentes deben aplicarse explícitamente, no se simulan como actualizados.

## Pruebas reproducibles

```powershell
python scripts/check_infrastructure.py
python scripts/check_infrastructure.py --restart
python scripts/validate_contracts.py
```

La primera prueba comprueba proxy/frontend, correlación HTTP, health/readiness, migraciones, usuarios sin privilegios de administrador, denegación de conexiones entre bases, metadatos Kafka y MLflow. La variante `--restart` reinicia solo los contenedores de este proyecto, verifica timestamps de las bases y conserva un mensaje diagnóstico Kafka, un run y un artefacto MLflow. No borra volúmenes.

El experimento `infrastructure-smoke` de MLflow está etiquetado como prueba de infraestructura; no cuenta como entrenamiento ni experimento candidato. El topic `credimarket.infra.smoke.v1` es diagnóstico, accesible al admin; no se introducen comandos ficticios en los topics de negocio.

## Estructura y versiones

Cada servicio tiene `app/main.py`, `alembic.ini` y su propio directorio de migraciones. La revisión 0001 crea únicamente `infrastructure_metadata`; las tablas de negocio se agregan en fases posteriores. `shared/` contiene solo arranque, conexión configurable, logs y comprobaciones; no contiene modelos de negocio compartidos ni consultas cruzadas.

Imágenes fijadas: Python 3.12.12, PostgreSQL 17.6, Kafka 4.1.0, Redis 8.2.1, Node 22.20.0 y Nginx 1.28.0. MLflow 3.4.0. Los archivos `requirements.lock` incluyen dependencias transitivas y hashes; `package-lock.json` bloquea el frontend. El build instala con `pip --require-hashes` y `npm ci`. Las imágenes tienen etiqueta fija, no digest inmutable; conservar digests del build si se exige reproducción binaria exacta.

Las fuentes editables son `infra/python/requirements.in`, `infra/mlflow/requirements.in` y `frontend/package.json`. Resolver nuevamente los locks dentro de Python 3.12 Linux / Node 22 antes de actualizar dependencias; no regenerarlos en un entorno Windows diferente y asumir equivalencia.

Limitaciones de alcance: un nodo Kafka no ofrece alta disponibilidad; los consumidores de negocio/outbox llegan en fase 6; autorización HTTP en fase 3; pipeline en fase 8. Las pantallas actuales son navegación y estado de conectividad, con los módulos futuros identificados como no implementados.

Fuentes consultadas para el montaje: [imagen oficial Kafka](https://hub.docker.com/r/apache/kafka), [contenedores FastAPI](https://fastapi.tiangolo.com/deployment/docker/) y [tracking server MLflow](https://mlflow.org/docs/latest/self-hosting/architecture/tracking-server/).
