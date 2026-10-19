# Fase 1: arquitectura y contratos

Fecha: 18 de octubre de 2026. Alcance: diseño verificable para implementación, sin desplegar servicios.

## Decisiones cerradas para implementar

1. Cuatro servicios FastAPI, una base PostgreSQL lógica y credencial restringida por servicio. No hay consultas cruzadas ni un quinto servicio de modelo/autenticación.
2. Clientes administra usuarios y perfiles. Préstamos coordina la operación, sirve el modelo y conserva la evidencia de decisión. Inventario arbitra reservas, entrega y vencimiento mediante transacciones locales.
3. Kafka con KRaft, dos topics de negocio, clave por préstamo y grupos por consumidor. Outbox/inbox en ambas bases; configuración y límites en el [ADR](adr/001-kafka.md).
4. Identidad derivada del token para solicitar préstamos; el cuerpo no acepta precio, monto ni cliente ajeno. Administrador no solicita créditos en nombre de otro en v1.
5. Cancelación y entrega son solicitudes asíncronas. El estado final exige confirmación de Inventario. Una cancelación que precede a la reserva deja una marca durable.
6. Redis cache-aside solo para catálogo. La cotización del préstamo consulta PostgreSQL. Precio, versión, características y versión del modelo quedan guardados.
7. Autenticación y roles se incluyen por la rúbrica y la prueba 13, aunque otras secciones los marcan opcionales. Monitoreo, drift, v2 y rollback cubren la etapa F omitida en el desarrollo del enunciado.
8. Contratos OpenAPI 3.1 y JSON Schema 2020-12 con objetos cerrados para detectar campos inesperados. Versionar cambios incompatibles.

## Entregables

| Documento/artefacto | Contenido |
|---|---|
| [Arquitectura](arquitectura.md) | Componentes, secuencia, propiedad de tablas y reglas ML |
| [Estados](estados.md) | Transiciones, fallos, tiempos y reglas ante duplicados/desorden |
| [API y seguridad](api-y-seguridad.md) | Semántica HTTP, identidad, permisos, importación y validaciones |
| [ADR Kafka](adr/001-kafka.md) | Comparación, configuración, justificación y límites |
| `contracts/openapi/*.json` | Operaciones, entradas, salidas, errores y políticas por servicio |
| `contracts/events/` | Esquemas, ejemplos y catálogo de comandos/resultados/DLQ |
| [Aceptación y backlog](aceptacion-y-backlog.md) | Los 16 casos, responsables por frente y dependencias |
| `scripts/validate_contracts.py` | Comprobaciones reproducibles de referencias, ejemplos y contratos |
| [Verificación ejecutada](validacion-fase-1.md) | Alcance y resultado de las comprobaciones estáticas |

## Precedencia y pendientes

Estos documentos y contratos concretan las propuestas de los dos planes iniciales. La numeración vigente es la del plan por etapas: fase 1 es diseño, fase 2 infraestructura. No usar la numeración histórica 0–8 del primer plan para ejecutar trabajo.

Las versiones de imágenes/dependencias de ejecución se fijan en fase 2, tras verificar compatibilidad. Nombres de integrantes y fecha calendario de entrega siguen pendientes; no bloquean el diseño. Las métricas ML y el umbral se obtienen en fase 7, no se inventan aquí. Los valores de los ejemplos de contratos son ilustrativos.

Se considera cerrada esta fase al validar los artefactos estáticos y comprobar la cobertura de los 16 casos. Las pruebas funcionales están **pendientes de implementación**, no aprobadas.
