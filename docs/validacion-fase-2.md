# Resultado de verificación de fase 2

Fecha de cierre: 19 de octubre de 2026. Infraestructura local verificada en Docker Desktop con motor Linux.

## Resultado

- Construcción de las seis imágenes propias: cuatro APIs, frontend y MLflow.
- Arranque con `docker compose up -d --build --wait --wait-timeout 300`: satisfactorio.
- Nueve contenedores persistentes en estado healthy; `kafka-init` y `kafka-volume-init` terminan correctamente como trabajos de inicialización.
- Frontend y proxy responden; health y correlación HTTP de los cuatro servicios correctos.
- Migración 0001 aplicada independientemente en las cuatro bases de negocio.
- Usuarios sin privilegios administrativos y conexiones a bases ajenas denegadas.
- Identidades de Préstamos e Inventario autenticadas en Kafka; creación arbitraria de topics denegada por ACL.
- Topics de negocio y DLQ creados; MLflow accesible.
- Después de reiniciar PostgreSQL, Kafka, MLflow y las cuatro APIs, las filas de infraestructura conservan sus timestamps originales.
- Run, parámetro y artefacto de MLflow recuperados tras el reinicio. El mismo identificador de diagnóstico fue recuperado del artefacto MLflow y del mensaje Kafka persistido.
- Secretos generados excluidos mediante Git y contexto Docker; comprobación de ausencia de contraseñas generadas en archivos de texto versionables satisfactoria.
- Sintaxis Python y contratos de fase 1 verificados.

## Correcciones realizadas durante la verificación

1. El volumen nuevo de Kafka no permitía escribir al usuario 1000. Se agregó un trabajo de inicialización del propietario, sin ejecutar el broker como root ni borrar datos.
2. MLflow 3.4.0 fallaba con SQLAlchemy 2.1.5. Se fijó SQLAlchemy 2.0.43 en su entrada y lock de dependencias; la imagen reconstruida arrancó correctamente.
3. La primera ejecución de `check_infrastructure.py --restart` completó las comprobaciones anteriores, pero su lectura final de Kafka agotó 5 segundos durante la asignación de un grupo nuevo. No hubo pérdida de datos. Se cambió la comprobación a asignación directa de partición 0 y timeout de 15 segundos. La función corregida se ejecutó sobre el identificador original recuperado de MLflow y pasó. No se repitió un segundo reinicio completo después de esa corrección.

El chequeo disponible es `python scripts/check_infrastructure.py`; con `--restart` comprueba además persistencia. El experimento `infrastructure-smoke` y el topic `credimarket.infra.smoke.v1` son diagnósticos, no entrenamiento ni operaciones de crédito.

## Alcance cerrado y siguiente fase

La fase 2 queda cerrada como infraestructura y esqueletos ejecutables. `/ready` de Préstamos sigue devolviendo 503 con modelo no disponible, de forma intencional; health 200 no significa que ya se puedan conceder préstamos. Autenticación, CRUD, reservas, consumidores de negocio y entrenamiento se implementarán en sus fases respectivas.

Siguiente: fase 3, Clientes, acceso e importación CSV.
