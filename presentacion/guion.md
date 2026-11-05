# Guion de sustentación · CrediMarket

Duración sugerida: 10–15 minutos. Las cifras y capturas son evidencia histórica del repositorio.

## 1. CrediMarket

Presentar el propósito: financiar la compra de productos y coordinar la evaluación con la disponibilidad real. Es un proyecto académico. Recorreremos producto, arquitectura, modelo y evidencia.

Fuente: README.md

## 2. Una compra necesita dos confirmaciones

Una evaluación favorable no basta para aprobar. La reserva debe estar confirmada por Inventario. La aplicación tiene dos roles principales, cliente y administrador.

Fuente: docs/arquitectura.md · docs/api-y-seguridad.md

## 3. De la solicitud a la entrega

Describir el caso de un cliente que quiere comprar un computador a 12 meses. La evaluación usa el precio vigente. Si el riesgo es favorable se espera la reserva. La aprobación conserva una reserva de diez minutos. La entrega consume el stock reservado.

Fuente: docs/estados.md · docs/guion_demo.md

## 4. Cuatro servicios, responsabilidades claras

Explicar de arriba a abajo. El proxy solo enruta. Cada servicio controla sus datos; no consulta tablas ajenas. Las líneas a Kafka representan comandos y resultados. Redis es opcional para el catálogo. El entrenamiento ocurre fuera de las solicitudes; MLflow usa además su propia base de metadatos.

Fuente: docs/arquitectura.md · compose.yaml

## 5. Cada servicio es dueño de sus datos

La independencia es lógica: una instancia de PostgreSQL contiene varias bases con credenciales distintas. Los permisos evitan leer directamente las bases de otros servicios. Las referencias entre servicios son identificadores, sin claves foráneas cruzadas.

Fuente: docs/arquitectura.md

## 6. Préstamos coordina la decisión

Responder explícitamente a la duda sobre si Préstamos solo llama al modelo: hace más. Reúne y valida datos, aplica reglas, ejecuta inferencia, coordina la reserva y audita el resultado. El modelo no es un quinto microservicio remoto.

Fuente: services/prestamos/app/domain.py · services/prestamos/app/model_service.py

## 7. Un modelo entrenado fuera del flujo de compra

El preprocesamiento se aprende únicamente en entrenamiento. La selección usa Average Precision en validación, con desempate por Brier y complejidad. El umbral se fija antes de evaluar el conjunto de prueba. Las 200 solicitudes nuevas no tienen etiquetas y se usan para inferencia, no para medir precisión.

Fuente: ml/README.md · ml/reports/model_selection_report.json

## 8. El riesgo es una probabilidad, no una garantía

No presentar AUC como porcentaje de exactitud. AUC mide ordenamiento de riesgos; Average Precision resume precisión y recall de la clase de incumplimiento. Recall del 72 por ciento indica qué proporción de incumplidores se identifica en este conjunto histórico. El costo 5:1 es una política ficticia del proyecto.

Fuente: models/riesgo-v1/manifest.json · metrics.test_at_optimal_threshold

## 9. Kafka conecta la reserva con la aprobación

Seguir el comando de izquierda a derecha y el resultado de vuelta. Préstamos no confirma stock antes de recibir evidencia. Puede haber reentregas; no se promete exactly-once de extremo a extremo. Ante fallos se conserva el estado pendiente y se recupera o reconcilia.

Fuente: shared/messaging.py · docs/adr/001-kafka.md · docs/estados.md

## 10. El inventario protege la última unidad

Se usan bloqueos y transacciones para mantener físico mayor o igual que reservado, y reservado no negativo. Si la reserva parece vencida se pasa a verificación, sin inventar una cancelación por timeout. La entrega y el vencimiento compiten bajo el mismo bloqueo.

Fuente: services/inventario/app/domain.py · docs/estados.md

## 11. Cambiar el modelo también deja rastro

El modelo no se escoge por ser el archivo más nuevo. Se comprueban hash y compatibilidad. La promoción modifica el puntero, reinicia solo Préstamos y verifica lo que sirve la API. El monitoreo agrega logs retenidos y PSI; no es alertamiento automático ni prueba de pérdida de precisión sin etiquetas.

Fuente: docs/FASE_11.md · models/active_model.json

## 12. La validación cubre negocio y recuperación

Mencionar los logs y resultados estructurados. La validación detuvo procesos en fronteras de confirmación y revisó que hubiera un solo movimiento de reserva. El ensayo local de Redis no mostró una mejora de latencia con caché caliente; no se vende ese resultado como ganancia de rendimiento.

Fuente: docs/validacion-fase-12.md · docs/evidencias/phase12_latest.json

## 13. La interfaz permite seguir la recuperación

Reservar alrededor de un minuto para explicar o mostrar el flujo. Esta imagen es evidencia guardada, no una sesión en vivo. Si se demuestra en el navegador, verificar antes salud, cuentas y stock; no ejecutar fallos durante la sustentación sin preparación.

Fuente: docs/guion_demo.md · docs/evidencias/.../AC15-recovered.png

## 14. Una decisión trazable, de principio a fin

Cerrar conectando las tres áreas: producto, sistemas distribuidos y aprendizaje automático. Lo demostrado es un flujo reproducible y auditable dentro del alcance académico. Una operación pública exigiría trabajar alta disponibilidad, seguridad de transporte y observabilidad persistente.

Fuente: README.md · docs/FASE_11.md · docs/validacion-fase-12.md