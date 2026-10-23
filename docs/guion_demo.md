# Guion de Demostración Técnica: CrediMarket

Este documento establece el orden secuencial de casos de prueba y demostración técnica para la sustentación del proyecto frente a evaluadores. Cada paso detalla la acción en la interfaz gráfica o terminal, la URL o comando correspondiente y el resultado verificable esperado.

---

## Preparación previa

1. Asegurar que los contenedores estén levantados y saludables:
   ```powershell
   docker compose ps
   ```
2. Cuentas de acceso utilizadas durante la demostración:
   - Administrador: `admin@credimarket.com` / `Admin12345678!`
   - Cliente favorable: `cliente@credimarket.com` / `Cliente12345678!`

---

## Escenario 1: Estado de salud e infraestructura base (AC01 / Infraestructura)

- **Objetivo**: Demostrar que los cuatro microservicios, el broker Kafka, la caché Redis y MLflow están operativos y desacoplados.
- **Acción**:
  1. Abrir en el navegador: `http://localhost:8080/api/prestamos/ready`
  2. Verificar que el JSON reporte estado `"ready"` con dependencias `"database": "ok"`, `"model": "ok"`, `"kafka": "ok"`.
  3. Abrir la consola de MLflow: `http://127.0.0.1:5000` y mostrar el experimento activo `credimarket-riesgo-v1`.

---

## Escenario 2: Solicitud de crédito aprobada con stock disponible (AC01)

- **Objetivo**: Demostrar el flujo favorable de extremo a extremo: creación de solicitud, evaluación de riesgo positiva, reserva atómica en Inventario vía Kafka y aprobación automática.
- **Acción**:
  1. Iniciar sesión en `http://localhost:8080/catalogo` con la cuenta de cliente:
     - Correo: `cliente@credimarket.com`
     - Contraseña: `Cliente12345678!`
  2. Seleccionar un producto con stock (por ejemplo, *Apple MacBook Air 13 M2* o *Samsung Galaxy S24*) y presionar **"Solicitar a crédito"**.
  3. En el modal, seleccionar el plazo a 12 meses. Observar el cálculo de la cuota mensual en tiempo real según la fórmula de anualidad con tasa fija del 1.8%.
  4. Confirmar la solicitud.
  5. La interfaz redirige a `http://localhost:8080/solicitudes`.
- **Resultado observable**:
  - La solicitud aparece inicialmente en estado `PENDIENTE_INVENTARIO`.
  - En un intervalo inferior a 3 segundos (sondeo automático cada 2.5s), el estado transiciona a `APROBADA` tras recibir el evento `InventarioReservado` desde Kafka.
  - Se visualiza el identificador de la reserva y el contador regresivo de vencimiento (10 minutos).

---

## Escenario 3: Despacho y entrega por el administrador (AC01 / AC07)

- **Objetivo**: Demostrar la autorización de entrega de mercadería y el registro contable de salida física en el inventario.
- **Acción**:
  1. Cerrar sesión de cliente e iniciar sesión como administrador (`admin@credimarket.com` / `Admin12345678!`).
  2. Navegar a **"Mis Solicitudes"** / listado global de solicitudes (`http://localhost:8080/solicitudes`).
  3. En la solicitud previamente aprobada en el Escenario 2, presionar el botón **"Confirmar entrega"**.
- **Resultado observable**:
  - El estado cambia a `ENTREGA_PENDIENTE` y se emite el comando `EntregaSolicitada` a Kafka.
  - Inventario descuenta el stock físico, registra un movimiento de tipo `SALIDA` y emite `EntregaConfirmada`.
  - La solicitud alcanza su estado terminal `COMPLETADA`.
  - Se puede verificar en `http://localhost:8080/inventario` que el stock reservado volvió a 0 y el stock físico disminuyó en una unidad.

---

## Escenario 4: Solicitud rechazada por riesgo crediticio desfavorable (AC02)

- **Objetivo**: Demostrar que un cliente con perfil de alto riesgo o sobreendeudamiento es evaluado por el modelo `riesgo-v1` y rechazado sin solicitar inventario a Kafka.
- **Acción**:
  1. Crear un cliente con finanzas desfavorables o ejecutar el comando CLI de prueba:
     ```powershell
     python -c "from scripts.check_phase9 import api_request, BASE_PRESTAMOS, token_client_b, prod_favorable_id; st, res, _ = api_request(f'{BASE_PRESTAMOS}/prestamos', 'POST', {'producto_id': prod_favorable_id, 'cantidad': 1, 'plazo_meses': 12}, token=token_client_b, headers_extra={'Idempotency-Key': 'demo-unfav-key-001'}); print('HTTP Status:', st); print('Estado:', res['estado']); print('Motivo:', res['motivo']); print('Riesgo:', res['riesgo'])"
     ```
- **Resultado observable**:
  - Respuesta HTTP `201 Created` con estado `RECHAZADA`.
  - Motivo: `RIESGO_DESFAVORABLE`.
  - Se adjunta la evaluación del modelo: `decision_riesgo: "DESFAVORABLE"`, `probabilidad_incumplimiento > 0.26`, `model_version: "riesgo-v1"`.
  - Se comprueba que **cero** comandos de reserva fueron encolados en la tabla `outbox` hacia Kafka.

---

## Escenario 5: Solicitud con stock insuficiente (AC03)

- **Objetivo**: Demostrar la consistencia del sistema cuando el cliente tiene riesgo favorable pero el producto no dispone de unidades libres.
- **Acción**:
  1. Identificar o crear un producto con stock disponible = 0.
  2. El cliente solicita el crédito para dicho producto.
- **Resultado observable**:
  - Solicitud ingresa como `PENDIENTE_INVENTARIO`.
  - El consumidor de Inventario detecta `disponible <= 0` y emite `InventarioInsuficiente`.
  - La solicitud transiciona automáticamente a `CANCELADA_SIN_STOCK`.
  - El stock físico y disponible en existencias nunca toma valores negativos.

---

## Escenario 6: Concurrencia por la última unidad (AC04)

- **Objetivo**: Demostrar que dos solicitudes simultáneas por un producto con una única unidad física no generan sobreventa ni doble reserva.
- **Acción**:
  1. Ejecutar la sección de concurrencia de la suite de pruebas:
     ```powershell
     python scripts/check_phase9.py
     ```
- **Resultado observable**:
  - En la terminal se observa el resultado del caso AC04:
    - Una solicitud gana la reserva y pasa a `APROBADA`.
    - La otra solicitud es rechazada por stock y pasa a `CANCELADA_SIN_STOCK`.
    - El disponible resultante en existencias es exactamente `0`.

---

## Escenario 7: Cancelación y garantía de no reactivación por eventos tardíos (AC07)

- **Objetivo**: Demostrar la cancelación de un crédito aprobado con liberación atómica del stock en Inventario y comprobar la inmutabilidad de los estados terminales.
- **Acción**:
  1. Desde la sesión del cliente, en una solicitud en estado `APROBADA`, presionar el botón **"Cancelar"**.
  2. Observar el paso a `CANCELACION_PENDIENTE`, la emisión de `LiberacionSolicitada` y la transición final a `CANCELADA`.
  3. En terminal, inyectar un evento tardío `InventarioReservado` con la misma clave de préstamo.
- **Resultado observable**:
  - El préstamo permanece estrictamente en `CANCELADA`.
  - Se cumple el **Invariante 5 de estados**: ningún evento tardío reactiva un préstamo en estado terminal.

---

## Escenario 8: Actualización de precio e invalidación de caché en Redis (AC09)

- **Objetivo**: Demostrar el patrón Cache-Aside y la consistencia de cotizaciones en tiempo real.
- **Acción**:
  1. Iniciar sesión como administrador y acceder a `/catalogo` o `/productos`.
  2. Modificar el precio de un producto existente (por ejemplo, cambiar de $3.000.000 a $3.800.000 COP).
  3. El endpoint de actualización invalida la clave Redis `cotizacion:<id>`.
  4. Realizar una nueva solicitud de crédito para dicho producto.
- **Resultado observable**:
  - La nueva solicitud toma el precio actualizado ($3.800.000 COP) y calcula la cuota sobre ese nuevo valor.
  - La cotización anterior en caché no afecta las nuevas operaciones.

---

## Escenario 9: Importación masiva de clientes desde archivo CSV (AC12)

- **Objetivo**: Demostrar la carga por lotes de clientes y atributos financieros con validación fila por fila.
- **Acción**:
  1. Desde la sesión de administrador, ingresar a la pestaña **"Clientes"** (`http://localhost:8080/clientes`).
  2. Cargar un archivo CSV con filas válidas e inválidas.
- **Resultado observable**:
  - La interfaz muestra el reporte detallado: total procesado, insertados, actualizados y lista de filas rechazadas con el motivo exacto del fallo.
  - Las filas válidas se persisten en la base de datos `clientes_db`.

---

## Escenario 10: Tolerancia a fallos en Kafka y Outbox Pattern (AC06)

- **Objetivo**: Demostrar que una caída abrupta de Kafka o del consumidor no ocasiona pérdida de transacciones ni doble reserva.
- **Acción**:
  1. Ejecutar la suite de fallos controlados:
     ```powershell
     python scripts/check_phase12_faults.py
     ```
- **Resultado observable**:
  - Los procesos terminan abruptamente antes de confirmar `sent_at` en outbox o antes de confirmar offsets de Kafka.
  - Al restaurar los procesos, la tabla `inbox` detecta los duplicados y procesa la transacción exactamente una vez.

---

## Escenario 11: MLOps: monitoreo de drift, promoción de v2 y rollback seguro (AC10 / AC11)

- **Objetivo**: Demostrar la gobernanza de modelos en Préstamos, la detección de deriva de datos y la capacidad de rollback inmediato sin reentrenar.
- **Acción**:
  1. Consultar la ficha del modelo en la interfaz web: `http://localhost:8080/modelo`.
  2. Mostrar la versión activa (`riesgo-v1`), su hash SHA-256 y umbral (`0.26`).
  3. Ejecutar el script de monitoreo de drift en terminal:
     ```powershell
     python scripts/monitor_model.py
     ```
  4. Promover la versión alternativa `riesgo-v2`:
     ```powershell
     python scripts/promote_model.py --version riesgo-v2
     ```
  5. Refrescar la página web del modelo para confirmar que ahora informa `riesgo-v2`.
  6. Realizar el rollback seguro a la versión original `riesgo-v1`:
     ```powershell
     python scripts/promote_model.py --version riesgo-v1
     ```
- **Resultado observable**:
  - El archivo `models/active_model.json` se actualiza de forma atómica.
  - El microservicio Préstamos carga la versión indicada sin necesidad de reentrenamiento ni tiempo de inactividad.
  - Las solicitudes históricas evaluadas con versiones anteriores conservan su trazabilidad intacta en la base de datos.
