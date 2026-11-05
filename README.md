# CrediMarket

Proyecto académico de cuatro microservicios: Productos, Clientes, Préstamos e Inventario. Broker elegido: **Kafka**. Modelo de riesgo servido dentro de Préstamos, entrenamiento offline y trazabilidad en MLflow.

## Estado

Fases 1–13 implementadas: arquitectura, infraestructura, Clientes, Productos/Redis, Inventario, Kafka, modelo, préstamos, frontend, MLOps, aceptación y preparación de sustentación. La [fase 12](docs/FASE_12.md) ejecutó los 16 casos de aceptación, navegador, fallos y mediciones (ver [resultados](docs/validacion-fase-12.md)). La [fase 13](docs/FASE_13.md) formaliza la entrega reproducible, cuentas demo, [guion de demostración](docs/guion_demo.md) y [preguntas de sustentación](docs/preguntas_sustentacion.md). La versión activa es `riesgo-v1`.

## Ejecutar localmente

Con Docker Desktop (motor Linux) activo y [uv](https://docs.astral.sh/uv/getting-started/installation/) instalado (0.13.3 o superior), desde la raíz:

```powershell
uv sync
uv run python scripts/bootstrap.py
docker compose up -d --build --wait --wait-timeout 300
uv run python scripts/check_infrastructure.py
uv run python scripts/check_phase4.py
uv run python scripts/check_phase5.py
uv run python scripts/check_phase7.py
uv run python scripts/check_phase8.py
uv run python scripts/check_phase9.py
```

Para comprobar Kafka: `uv run python scripts/check_phase6.py`. La variante `uv run python scripts/check_phase6.py --faults` interrumpe temporalmente el broker y reinicia consumidores para verificar recuperación. Las pruebas crean datos sintéticos que se conservan; no son necesarias para abrir la aplicación. Para re-ejecutar el entrenamiento del modelo en MLflow: `uv run python scripts/run_phase7_training.py`. Para promover el modelo activo e inferencia batch: `uv run python scripts/promote_model.py --version riesgo-v1`.

Frontend: http://localhost:8080 (rutas `/catalogo`, `/solicitudes`, `/clientes`, `/inventario`, `/modelo`). Registrarse como cliente en **Ingresar**; crear un administrador con `uv run python scripts/gestionar_admin.py crear <correo> <contraseña>`. Pruebas de navegador: `uv sync --group test`, `uv run --group test playwright install chromium` y `uv run --group test python scripts/check_phase10.py`. MLflow: http://127.0.0.1:5000 (experimento `credimarket-riesgo-v1`; en macOS `localhost:5000` puede abrir AirPlay en su lugar), enlazado desde la ficha del modelo. Todos los microservicios (incluido Préstamos con su modelo activo cargado) responden `200` en `/health` y `/ready`.

Consultar [la guía de fase 2](docs/FASE_2.md) para secretos locales, puertos, volúmenes, reinicios y comprobación de persistencia.

## Dependencias Python

Las dependencias Python se gestionan con [uv](https://docs.astral.sh/uv/). `pyproject.toml` y `uv.lock` son la fuente de verdad; las versiones están fijadas y `uv.lock` incluye hashes. Hay dos proyectos independientes:

| Proyecto | Grupo | Contenido | Quién lo usa |
|---|---|---|---|
| raíz | `tools` (por defecto) | `cryptography`, `jsonschema` 4.26.0 | `bootstrap.py`, `validate_contracts.py`, `build_contracts.py` y las comprobaciones `check_phase*.py` |
| raíz | `test` | `tools` + `playwright` 1.52.0 | `check_phase10.py` y `check_phase12.py` |
| raíz | `backend` | FastAPI, SQLAlchemy, Alembic, psycopg, Redis, Kafka, JWT, `jsonschema` 4.25.1… | Las cuatro imágenes de microservicios |
| raíz | `inference` | `scikit-learn`, `pandas`, `numpy`, `joblib` | Solo la imagen de Préstamos (además de `backend`) |
| `infra/mlflow` | dependencias + `training` | MLflow 3.4.0 y las mismas librerías de entrenamiento | Imagen de MLflow, donde también corre el entrenamiento (`ml/src`) |

```powershell
uv sync                                                    # herramientas locales (grupo por defecto)
uv sync --group test                                       # añade Playwright
uv run --group test playwright install chromium            # navegador de las pruebas de navegador
uv sync --no-default-groups --group backend --group inference   # entorno de Préstamos, sin Docker
uv sync --project infra/mlflow                             # entorno de MLflow y entrenamiento, sin Docker
```

Los grupos `backend` y `tools`/`test` no pueden instalarse en el mismo entorno porque fijan versiones distintas de `jsonschema`; uv lo rechaza con un error explícito. Los scripts se ejecutan con `uv run python scripts/…` (o `uv run --group test python scripts/…` para los de navegador), o bien activando el entorno `.venv` que crea `uv sync`.

**Por qué dos proyectos.** El servidor MLflow resuelve versiones distintas de `fastapi` (0.146.0 frente a 0.118.0), `starlette` (1.9.0 frente a 0.48.0), `uvicorn`, `alembic` y `redis` (8.1.0 frente a 6.4.0), entre otras, que las que usan los microservicios. Unificarlos cambiaría paquetes de una imagen que hoy funciona, así que cada proyecto conserva su propio lock.

**Versiones del modelo.** `scikit-learn` 1.9.1, `numpy` 2.5.4, `pandas` 2.3.3 y `joblib` 1.6.0 son idénticas en `inference` y en `training` y coinciden con `dependencies` en `models/*/manifest.json`. Préstamos rechaza un artefacto si la versión menor de scikit-learn difiere. Cambiar esas versiones exige reentrenar, exportar y promover un modelo nuevo. Tampoco conviene un `uv lock --upgrade` general: movería dependencias transitivas del modelo (por ejemplo, hoy resolvería `python-dateutil` 4.0.0 en lugar de 2.9.0.post0), así que actualiza paquetes concretos con `--upgrade-package` y comprueba la carga del modelo.

**Actualizar una dependencia.** Editar el pin en el `pyproject.toml` correspondiente y ejecutar `uv lock` (o `uv lock --project infra/mlflow`). Para subir una sola dependencia transitiva: `uv lock --upgrade-package <paquete>`. `uv lock --check` comprueba que el lock está al día. Después reconstruir con `docker compose up -d --build`: las imágenes instalan con `uv sync --frozen`, usan uv 0.13.3 fijado por versión y digest, y no incluyen uv en la imagen final.

## Documentación

- [Desarrollo por etapas](PLAN_DESARROLLO_POR_ETAPAS.md)
- [Análisis del enunciado y datos](PLAN_IMPLEMENTACION_CREDIMARKET.md)
- [Índice y decisiones de la fase 1](docs/FASE_1.md)
- [Infraestructura de fase 2](docs/FASE_2.md)
- [Clientes, acceso e importación: fase 3](docs/FASE_3.md)
- [Productos y Redis: fase 4](docs/FASE_4.md)
- [Inventario y reservas atómicas: fase 5](docs/FASE_5.md)
- [Kafka, reintentos y DLQ: fase 6](docs/FASE_6.md)
- [Datos, EDA, MLflow y entrenamiento del modelo: fase 7](docs/FASE_7.md)
- [Exportación, promoción y servicio del modelo en Préstamos: fase 8](docs/FASE_8.md)
- [Flujo de préstamos: fase 9](docs/FASE_9.md)
- [Frontend integrado: fase 10](docs/FASE_10.md)
- [MLOps, monitoreo, v2 y rollback: fase 11](docs/FASE_11.md)
- [Resultados de fase 11](docs/validacion-fase-11.md)
- [Aceptación, fallos y mediciones: fase 12](docs/FASE_12.md)
- [Matriz ejecutada y resultados: fase 12](docs/validacion-fase-12.md)
- [Entrega y sustentación: fase 13](docs/FASE_13.md)
- [Guion de demostración técnica](docs/guion_demo.md)
- [Preguntas técnicas para sustentación](docs/preguntas_sustentacion.md)
- [Diccionario de datos de riesgo](docs/diccionario_datos.md)
- [Arquitectura y datos](docs/arquitectura.md)
- [Estados y consistencia](docs/estados.md)
- [APIs y permisos](docs/api-y-seguridad.md)
- [Decisión Kafka](docs/adr/001-kafka.md)
- [Contratos de mensajería](contracts/events/README.md)
- [Matriz de aceptación y backlog](docs/aceptacion-y-backlog.md)

Los contratos OpenAPI se encuentran en `contracts/openapi/`, uno por servicio. Los esquemas y ejemplos de eventos están en `contracts/events/`.

## Verificar contratos

```powershell
uv run python scripts/validate_contracts.py
```

La verificación estática no sustituye las pruebas de integración de las fases posteriores. El generador `scripts/build_contracts.py` mantiene los contratos; después de cambiarlo, ejecutar `uv run python scripts/build_contracts.py` y validar nuevamente.

## Equipo

| Integrante | Frente sugerido |
|---|---|
| Sebastián Giraldo | Productos, Redis e Inventario |
| Martin Restrepo | Clientes, seguridad y frontend |
| Sebastián Giraldo | Préstamos, Kafka y recuperación |
| Miguel Ángel Zuleta | Datos, modelo y MLOps |

Los archivos originales del enunciado y los dos CSV se conservan en la raíz.
