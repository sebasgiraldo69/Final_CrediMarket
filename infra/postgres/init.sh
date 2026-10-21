#!/bin/sh
set -eu
# Values passed as psql variables, never interpolated into SQL identifiers or literals.
psql --username "$POSTGRES_USER" --dbname postgres --set ON_ERROR_STOP=1 \
  --set productos_pw="$PRODUCTOS_DB_PASSWORD" --set clientes_pw="$CLIENTES_DB_PASSWORD" \
  --set prestamos_pw="$PRESTAMOS_DB_PASSWORD" --set inventario_pw="$INVENTARIO_DB_PASSWORD" \
  --set mlflow_pw="$MLFLOW_DB_PASSWORD" <<'SQL'
CREATE ROLE productos_app LOGIN PASSWORD :'productos_pw';
CREATE ROLE clientes_app LOGIN PASSWORD :'clientes_pw';
CREATE ROLE prestamos_app LOGIN PASSWORD :'prestamos_pw';
CREATE ROLE inventario_app LOGIN PASSWORD :'inventario_pw';
CREATE ROLE mlflow_app LOGIN PASSWORD :'mlflow_pw';
CREATE DATABASE productos_db OWNER productos_app;
CREATE DATABASE clientes_db OWNER clientes_app;
CREATE DATABASE prestamos_db OWNER prestamos_app;
CREATE DATABASE inventario_db OWNER inventario_app;
CREATE DATABASE mlflow_db OWNER mlflow_app;
REVOKE CONNECT ON DATABASE postgres, template1, productos_db, clientes_db, prestamos_db, inventario_db, mlflow_db FROM PUBLIC;
GRANT CONNECT ON DATABASE productos_db TO productos_app;
GRANT CONNECT ON DATABASE clientes_db TO clientes_app;
GRANT CONNECT ON DATABASE prestamos_db TO prestamos_app;
GRANT CONNECT ON DATABASE inventario_db TO inventario_app;
GRANT CONNECT ON DATABASE mlflow_db TO mlflow_app;
SQL
for database in productos_db clientes_db prestamos_db inventario_db mlflow_db; do
  psql --username "$POSTGRES_USER" --dbname "$database" --set ON_ERROR_STOP=1 \
    -c 'REVOKE CREATE ON SCHEMA public FROM PUBLIC;'
done
