# Verificación de la fase 1

Validación ejecutada localmente el 18 de octubre de 2026 con Python y jsonschema 4.26.0.

```powershell
python scripts/build_contracts.py
python scripts/validate_contracts.py
```

Alcance de las comprobaciones:

- Cuatro documentos OpenAPI y 34 operaciones, con referencias locales resolubles, parámetros de ruta, esquemas de respuesta, correlación y políticas de acceso.
- Diez tipos de mensaje Kafka, cada uno con JSON Schema y ejemplo; envoltura de DLQ con bytes originales válidos en base64.
- Ejemplos REST de solicitud, inferencia, catálogo, entrada de stock y respuesta pendiente.
- Casos inválidos rechazados: precio o cliente ajeno enviado al crear préstamo, cantidades/plazos inválidos, ID mal formado, etiqueta/IDs dentro de features, empleo desconocido, porcentaje incompatible con ausencia de historial, mensaje sin event_id, versión desconocida, datos financieros enviados a Inventario y aprobación sin reserva confirmada.
- Adaptación de las 12.200 filas de los dos CSV al contrato de características. Verificación de cuota calculada dentro de COP 0,01 y enteros exactos para meses/conteos.
- Hashes de ambos CSV iguales a los originales; links locales, bloques Markdown y cobertura de los 16 casos de aceptación.

Resultado: validación estática satisfactoria. No se entrenó un modelo ni se iniciaron servicios. Las comprobaciones OpenAPI son estructurales y de esquemas, no una certificación exhaustiva de la especificación. Los casos de aceptación de negocio se implementarán y ejecutarán en las fases posteriores.

La fase 1 puede cerrarse como entrega de diseño. El trabajo siguiente es la infraestructura de fase 2.
