# Fase 13: Preparar entrega y sustentación

Esta fase consolida la entrega final del sistema CrediMarket, documenta los procedimientos de despliegue desde un clon limpio, la gestión de secretos, cuentas de demostración, puertos, recuperación de volúmenes persistentes, reproducibilidad del pipeline de Machine Learning y la preparación técnica para la sustentación.

---

## 1. Procedimiento de despliegue desde clon limpio

El sistema está diseñado para ser clonado e inicializado en un entorno con Docker Desktop (motor Linux) y Python 3.12 sin requerir configuración manual previa de bases de datos o brokers.

### Pasos de inicialización:

```powershell
# 1. Clonar el repositorio
git clone <URL_DEL_REPOSITORIO>
cd Final_CrediMarket

# 2. Instalar dependencias del script de inicialización
python -m pip install -r requirements-bootstrap.txt

# 3. Generar archivo .env y pares de claves RSA locales
python scripts/bootstrap.py

# 4. Construir y levantar todos los contenedores con healthchecks
docker compose up -d --build --wait --wait-timeout 300

# 5. Ejecutar verificación de infraestructura base
python scripts/check_infrastructure.py
```

Al completar estos pasos, los 9 contenedores del stack se encuentran en estado saludable (`healthy`), con esquemas migrados en sus respectivas bases de datos y topics creados en Kafka.

---

## 2. Gestión local de secretos y credenciales

El script `scripts/bootstrap.py` genera criptográficamente todos los secretos requeridos de forma determinista para el entorno local:

1. **Par de claves asimétricas RSA (2048 bits)**:
   - Clave privada: `.secrets/jwt_private.pem` (utilizada exclusivamente por el servicio `clientes` y montada en modo solo lectura en `prestamos` para emisión de tokens de servicio interno).
   - Clave pública: `.secrets/jwt_public.pem` (montada en todos los microservicios para validación de firma de tokens de usuario y servicio).
2. **Contraseñas independientes por base de datos**:
   - Variables generadas en `.env`: `POSTGRES_PASSWORD`, `PRODUCTOS_DB_PASSWORD`, `CLIENTES_DB_PASSWORD`, `PRESTAMOS_DB_PASSWORD`, `INVENTARIO_DB_PASSWORD`, `MLFLOW_DB_PASSWORD`.
   - Cada microservicio se conecta con su propio usuario de aplicación (`<servicio>_app`) sin permisos de superusuario ni privilegios de conexión cruzada a bases de datos ajenas.
3. **Credenciales de infraestructura**:
   - `REDIS_PASSWORD`: contraseña de autenticación para Redis.
   - `KAFKA_PRESTAMOS_PASSWORD`, `KAFKA_INVENTARIO_PASSWORD`: credenciales SASL/PLAIN con ACLs granulares por topic y grupo de consumidores.

Los archivos generados en `.secrets/` y el archivo `.env` están excluidos del control de versiones en `.gitignore`.

---

## 3. Cuentas de demostración preconfiguradas

Para la ejecución de la demostración y evaluación, el entorno cuenta con dos cuentas estándar verificadas:

| Rol | Correo electrónico | Contraseña | Descripción y perfil |
|---|---|---|---|
| **Administrador** | `admin@credimarket.com` | `Admin12345678!` | Acceso total a módulos administrativos: gestión de productos, inventario (entradas y confirmación de entregas), importación de clientes y ficha del modelo. |
| **Cliente** | `cliente@credimarket.com` | `Cliente12345678!` | Cliente registrado con perfil financiero favorable preconfigurado (ingresos $6.500.000 COP, obligaciones $800.000 COP, 0 atrasos, 98.5% puntualidad). Permite solicitar créditos con aprobación inmediata en vivo. |

Para crear administradores adicionales en cualquier momento:

```powershell
python scripts/gestionar_admin.py crear nuevo_admin@credimarket.com Password12345678!
```

---

## 4. Topología de puertos y rutas de acceso

El frontend actúa como punto de entrada único HTTP para el usuario y navegador a través de un proxy reverso Nginx:

| Servicio | Puerto host | URL local | Función principal |
|---|:---:|---|---|
| **Frontend y API Proxy** | `8080` | `http://localhost:8080` | Interfaz web React SPA y proxy hacia `/api/{productos,clientes,prestamos,inventario}`. |
| **MLflow UI** | `5000` | `http://127.0.0.1:5000` | Servidor de seguimiento de experimentos y registro de modelos ML. |
| **Kafka External** | `19092` | `localhost:19092` | Listener externo para inspección de topics y pruebas de integración. |
| **PostgreSQL** | `5432` | `localhost:5432` (interno) | Instancia multibase con aislamiento por usuario. |
| **Redis** | `6379` | `localhost:6379` (interno) | Servidor de caché en memoria con persistencia desactivada. |

### Documentación OpenAPI interactiva:
- Productos: `http://localhost:8080/api/productos/docs`
- Clientes: `http://localhost:8080/api/clientes/docs`
- Préstamos: `http://localhost:8080/api/prestamos/docs`
- Inventario: `http://localhost:8080/api/inventario/docs`

---

## 5. Persistencia y recuperación de volúmenes Docker

Los datos del sistema están respaldados en volúmenes nombrados gestionados por Docker:

- `postgres_data`: contiene las bases de datos `productos_db`, `clientes_db`, `prestamos_db`, `inventario_db` y `mlflow_db`.
- `kafka_data`: almacena los logs de particiones de Apache Kafka KRaft.
- `mlflow_artifacts`: almacena los artefactos serializados de las ejecuciones de entrenamiento.

Un reinicio estándar mediante `docker compose down` y `docker compose up -d` conserva íntegramente el estado, usuarios, historial de préstamos, existencias de inventario y configuración del modelo activo.

---

## 6. Reproducibilidad de MLOps y artefactos del modelo

El microservicio de Préstamos opera con el modelo promovido de forma desacoplada del servidor de entrenamiento.

1. **Configuración activa**: [`models/active_model.json`](../models/active_model.json) define la versión activa (`riesgo-v1`), su hash SHA-256 verificado y el umbral de decisión (`0.26`).
2. **Artefactos versionados**:
   - Versión 1: [`models/riesgo-v1/manifest.json`](../models/riesgo-v1/manifest.json) y `models/riesgo-v1/pipeline.joblib`.
   - Versión 2: [`models/riesgo-v2/manifest.json`](../models/riesgo-v2/manifest.json) y `models/riesgo-v2/pipeline.joblib`.
3. **Reproducción del historial en MLflow**:
   Si se levanta el stack en un equipo nuevo donde la base de datos de MLflow no contenga las corridas históricas, estas pueden reproducirse ejecutando:

   ```powershell
   python scripts/run_phase7_training.py
   ```

4. **Promoción y Rollback**:
   - Promover v2: `python scripts/promote_model.py --version riesgo-v2`
   - Rollback a v1: `python scripts/promote_model.py --version riesgo-v1`

---

## 7. Ejecución de la suite completa de pruebas

El repositorio cuenta con scripts de validación automatizada para cada etapa del desarrollo:

```powershell
# 1. Validación estática de contratos y esquemas OpenAPI / Eventos
python scripts/validate_contracts.py

# 2. Pruebas de integración por microservicio
python scripts/check_infrastructure.py
python scripts/check_phase3.py     # Clientes e importador
python scripts/check_phase4.py     # Productos y Redis
python scripts/check_phase5.py     # Inventario y reservas atómicas
python scripts/check_phase6.py     # Kafka, outbox y DLQ
python scripts/check_phase7.py     # Entrenamiento y métricas ML
python scripts/check_phase8.py     # Paridad offline vs API (AC10)
python scripts/check_phase9.py     # Flujo completo de préstamos
python scripts/check_phase10.py    # Interfaz gráfica y navegación
python scripts/check_phase11.py    # MLOps, drift y rollback
python scripts/check_phase13.py    # Verificación global de entrega y sustentación
```

---

## 8. Documentos de soporte para la sustentación

- [Guion de demostración técnica paso a paso](guion_demo.md): secuencia de casos a mostrar en vivo con entradas, salidas esperadas y comandos de soporte.
- [Batería de preguntas cruzadas para sustentación](preguntas_sustentacion.md): preguntas y respuestas técnicas fundamentales para la defensa del proyecto.
