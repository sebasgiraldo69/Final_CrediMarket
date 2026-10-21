# CrediMarket

Proyecto académico de cuatro microservicios: Productos, Clientes, Préstamos e Inventario. Broker elegido: **Kafka**. Modelo de riesgo servido dentro de Préstamos, entrenamiento offline y trazabilidad en MLflow.

## Estado

Fases 1–12 implementadas: arquitectura, infraestructura, Clientes, Productos/Redis, Inventario, Kafka, modelo, préstamos, frontend y MLOps. La [fase 12](docs/FASE_12.md) ejecutó los 16 casos de aceptación, navegador, fallos y mediciones; ver [resultados y límites](docs/validacion-fase-12.md). La versión activa es `riesgo-v1`. Siguiente fase: entrega y sustentación (fase 13).

## Ejecutar localmente

Con Docker Desktop (motor Linux) activo, desde la raíz:

```powershell
python -m pip install -r requirements-bootstrap.txt
python scripts/bootstrap.py
docker compose up -d --build --wait --wait-timeout 300
python scripts/check_infrastructure.py
python scripts/check_phase4.py
python scripts/check_phase5.py
python scripts/check_phase7.py
python scripts/check_phase8.py
python scripts/check_phase9.py
```

Para comprobar Kafka: `python scripts/check_phase6.py`. La variante `python scripts/check_phase6.py --faults` interrumpe temporalmente el broker y reinicia consumidores para verificar recuperación. Las pruebas crean datos sintéticos que se conservan; no son necesarias para abrir la aplicación. Para re-ejecutar el entrenamiento del modelo en MLflow: `python scripts/run_phase7_training.py`. Para promover el modelo activo e inferencia batch: `python scripts/promote_model.py --version riesgo-v1`.

Frontend: http://localhost:8080 (rutas `/catalogo`, `/solicitudes`, `/clientes`, `/inventario`, `/modelo`). Registrarse como cliente en **Ingresar**; crear un administrador con `python scripts/gestionar_admin.py crear <correo> <contraseña>`. Pruebas de navegador: `python -m pip install -r requirements-e2e.txt`, `python -m playwright install chromium` y `python scripts/check_phase10.py`. MLflow: http://127.0.0.1:5000 (experimento `credimarket-riesgo-v1`; en macOS `localhost:5000` puede abrir AirPlay en su lugar), enlazado desde la ficha del modelo. Todos los microservicios (incluido Préstamos con su modelo activo cargado) responden `200` en `/health` y `/ready`.

Consultar [la guía de fase 2](docs/FASE_2.md) para secretos locales, puertos, volúmenes, reinicios y comprobación de persistencia.

## Documentación

- [Desarrollo por etapas](PLAN_DESARROLLO_POR_ETAPAS.md)
- [Análisis del enunciado y datos](PLAN_IMPLEMENTACION_CREDIMARKET.md)
- [Índice y decisiones de la fase 1](docs/FASE_1.md)
- [Infraestructura de fase 2](docs/FASE_2.md)
- [Clientes, acceso e importación: fase 3](docs/FASE_3.md)
- [Código de fase 3 para estudiar](docs/CODIGO_FASE_3.md)
- [Productos y Redis: fase 4](docs/FASE_4.md)
- [Código de fase 4 para estudiar](docs/CODIGO_FASE_4.md)
- [Inventario y reservas atómicas: fase 5](docs/FASE_5.md)
- [Código de fase 5 para estudiar](docs/CODIGO_FASE_5.md)
- [Kafka, reintentos y DLQ: fase 6](docs/FASE_6.md)
- [Código de fase 6 para estudiar](docs/CODIGO_FASE_6.md)
- [Datos, EDA, MLflow y entrenamiento del modelo: fase 7](docs/FASE_7.md)
- [Código de fase 7 para estudiar](docs/CODIGO_FASE_7.md)
- [Exportación, promoción y servicio del modelo en Préstamos: fase 8](docs/FASE_8.md)
- [Código de fase 8 para estudiar](docs/CODIGO_FASE_8.md)
- [Flujo de préstamos: fase 9](docs/FASE_9.md)
- [Código de fase 9 para estudiar](docs/CODIGO_FASE_9.md)
- [Frontend integrado: fase 10](docs/FASE_10.md)
- [Código de fase 10 para estudiar](docs/CODIGO_FASE_10.md)
- [MLOps, monitoreo, v2 y rollback: fase 11](docs/FASE_11.md)
- [Código de fase 11 para estudiar](docs/CODIGO_FASE_11.md)
- [Resultados de fase 11](docs/validacion-fase-11.md)
- [Aceptación, fallos y mediciones: fase 12](docs/FASE_12.md)
- [Matriz ejecutada y resultados: fase 12](docs/validacion-fase-12.md)
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
python -m pip install -r requirements-contracts.txt
python scripts/validate_contracts.py
```

La verificación estática no sustituye las pruebas de integración de las fases posteriores. El generador `scripts/build_contracts.py` mantiene los contratos; después de cambiarlo, ejecutar `python scripts/build_contracts.py` y validar nuevamente.

## Equipo

Los nombres se completarán con los integrantes reales. Los frentes son asignaciones sugeridas, no evidencia de contribuciones existentes.

| Integrante | Frente sugerido |
|---|---|
| Por asignar A | Productos, Redis e Inventario |
| Por asignar B | Clientes, seguridad y frontend |
| Por asignar C | Préstamos, Kafka y recuperación |
| Por asignar D | Datos, modelo y MLOps |

Los archivos originales del enunciado y los dos CSV se conservan en la raíz.
