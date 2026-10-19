# Fase 3: Clientes, acceso e importación

Implementación del microservicio Clientes y sus pantallas. Se mantienen separados los perfiles financieros y las cuentas que permiten iniciar sesión.

## Probar desde la interfaz

1. Abrir http://localhost:8080 y entrar en **Clientes**.
2. Pulsar **Registrarme**, introducir nombre, correo y contraseña de al menos 12 caracteres.
3. Iniciar sesión y editar nombre o correo de contacto. El correo de acceso no cambia.
4. Para administrar clientes, crear una cuenta mediante el comando siguiente y acceder con ella:

```powershell
docker compose exec clientes python -m app.cli create-user --email admin@example.com --role administrador
```

El comando pide la contraseña dos veces sin mostrarla. No hay contraseña predeterminada ni registro público de administradores. Desde esa cuenta se puede listar y editar clientes, cargar `prestamos_entrenamiento.csv` y recuperar un informe guardado mediante su identificador.

Para vincular una cuenta a un perfil importado, un operador puede ejecutar lo siguiente, sustituyendo el UUID por el `id` interno del perfil (no por el identificador del CSV):

```powershell
docker compose exec clientes python -m app.cli create-user --email cliente@example.com --role cliente --cliente-id UUID_DEL_PERFIL
```

## Código y responsabilidades

- `services/clientes/app/models.py`: tablas de perfiles, usuarios e informes.
- `services/clientes/migrations/versions/0002_clientes.py`: migración PostgreSQL aplicada al arrancar.
- `schemas.py`: validación de entradas, importes y coherencia del historial.
- `security.py`: contraseñas Argon2 y emisión de JWT RS256 por 30 minutos.
- `shared/auth.py`: verificación de firma, emisor, audiencia, vencimiento, rol y alcance interno.
- `main.py`: registro, login, consulta, edición e importación.
- `importer.py`: lectura CSV, validación por fila, inserción/actualización e informe persistido.
- `cli.py`: provisión local de cuentas y credenciales internas.
- `frontend/src/Clientes.tsx`: formularios conectados a las APIs reales.

El [cuaderno de código](CODIGO_FASE_3.md) contiene los archivos fuente completos de esta fase, sin secretos ni dependencias generadas.

## Comportamiento

El cliente solo consulta su propio perfil y modifica sus datos de contacto. El administrador puede modificar datos financieros y estado. Consultar un perfil ajeno devuelve 404; editar campos reservados devuelve 403. El estado `activo` del perfil es una regla de negocio para las fases de crédito; es distinto del estado de la cuenta de acceso.

Cada perfil tiene una versión. Al editar se exige `version_esperada`; una edición simultánea con una versión antigua recibe 409. Registro y edición se guardan mediante transacciones; un correo de acceso duplicado no deja un perfil huérfano.

La clave privada RSA se monta únicamente en Clientes. Los otros servicios reciben la pública. Las rutas internas aceptan tokens para la audiencia interna, sujeto `prestamos` y alcance `clientes:read`; no aceptan tokens del navegador. El token de sesión se conserva en memoria, permanece al cambiar de sección y se pierde al recargar la página. Cerrar sesión descarta ese token del navegador; no existe todavía una lista de revocación de tokens.

CSV: UTF-8, separador coma, máximo 10 MiB y 20.000 filas. Se requieren `cliente_id` y los ocho atributos financieros del contrato. Las columnas conocidas de préstamos se ignoran; no se entrena ningún modelo. La clave externa es única. Se conservan nombre, contacto y estado al reimportar; solo se actualizan finanzas cuando cambian. No se crean cuentas de acceso por importar perfiles.

Las filas válidas se aplican aunque otras sean rechazadas. El informe guarda cantidades, fila, campo y motivo del error. Las claves repetidas dentro del archivo se rechazan desde la segunda aparición. Los errores de formato general rechazan todo el archivo. Dos importaciones simultáneas se serializan en PostgreSQL.

## Verificación

```powershell
python -m pip install -r requirements-contracts.txt
python scripts/check_phase3.py
```

Prueba de integración contra HTTP y PostgreSQL reales: registro/login, correo normalizado, rollback de duplicados, propietario y roles, firma/vencimiento/audiencia de tokens, edición concurrente, validación financiera, carga de las 12.000 filas dos veces sin duplicación, informe persistido, filas inválidas, límites y respuestas compatibles con los contratos de fase 1.

La prueba conserva cuentas sintéticas, perfiles e informes en la base local y usa contraseñas aleatorias que no imprime. Puede ejecutarse nuevamente. La compilación del frontend incluye comprobación TypeScript. No se ha realizado una prueba automatizada de navegador; queda pendiente junto con el cierre visual e integrado de la fase 10.

Resultado local del 19 de octubre de 2026: `check_phase3.py` terminó con código 0 y sus cuatro grupos de comprobaciones en PASS. `validate_contracts.py` terminó con 74.250 comprobaciones estáticas aprobadas. `tsc --noEmit` y `vite build` terminaron correctamente dentro de la imagen del frontend.

Kafka sigue disponible como infraestructura; este módulo usa HTTP y PostgreSQL. Los productores y consumidores de negocio corresponden a la fase 6. Siguiente trabajo: fase 4, Productos y Redis.
