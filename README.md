# CrediMarket

Proyecto académico de cuatro microservicios: Productos, Clientes, Préstamos e Inventario. Broker elegido: **Kafka**. Modelo de riesgo servido dentro de Préstamos, entrenamiento offline y trazabilidad en MLflow.

## Estado

Fases 1–4 completadas: arquitectura, infraestructura, Clientes con registro/roles/importación y Productos con catálogo, Redis cache-aside y cotización interna. Ver [fase 3](docs/FASE_3.md) y [fase 4 y pruebas](docs/FASE_4.md). La siguiente fase es Inventario y reservas atómicas. El flujo de préstamos y el modelo entrenado siguen pendientes.

## Ejecutar localmente

Con Docker Desktop (motor Linux) activo, desde la raíz:

```powershell
python -m pip install -r requirements-bootstrap.txt
python scripts/bootstrap.py
docker compose up -d --build --wait --wait-timeout 300
python scripts/check_infrastructure.py
python scripts/check_phase4.py
```

Frontend: http://localhost:8080; abrir **Clientes** para registrarse o **Catálogo** para explorar productos. MLflow: http://localhost:5000. Préstamos, inventario y modelo siguen pendientes. Préstamos devuelve 503 en `/ready` porque aún no tiene modelo; su `/health` sí debe responder 200.

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
