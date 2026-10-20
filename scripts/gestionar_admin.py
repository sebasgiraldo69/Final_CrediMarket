"""Herramienta CLI para gestionar administradores en CrediMarket.

Uso:
    python scripts/gestionar_admin.py listar
    python scripts/gestionar_admin.py promover usuario@ejemplo.com
    python scripts/gestionar_admin.py crear nuevo_admin@ejemplo.com MiContrasena123
"""
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_in_clientes(code: str) -> str:
    result = subprocess.run(
        ['docker', 'compose', 'exec', '-T', 'clientes', 'python', '-'],
        cwd=ROOT, input=code, text=True, capture_output=True, encoding='utf-8'
    )
    if result.returncode != 0:
        print(f"Error: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def listar_admins():
    code = """
from sqlalchemy import create_engine, select
from shared.runtime import database_url
from app.models import usuarios

engine = create_engine(database_url())
with engine.connect() as conn:
    rows = conn.execute(select(usuarios.c.email, usuarios.c.rol, usuarios.c.activo).where(usuarios.c.rol == 'administrador')).mappings().all()
    if not rows:
        print("No hay usuarios administradores registrados.")
    else:
        print("Administradores actuales:")
        for r in rows:
            estado = "Activo" if r['activo'] else "Inactivo"
            print(f" - {r['email']} ({estado})")
"""
    output = run_in_clientes(code)
    print(output)


def promover_usuario(email: str):
    code = f"""
from sqlalchemy import create_engine, select, update
from shared.runtime import database_url
from app.models import usuarios

engine = create_engine(database_url())
with engine.begin() as conn:
    user = conn.execute(select(usuarios).where(usuarios.c.email == {repr(email)})).mappings().first()
    if not user:
        print(f"ERROR: No se encontró ningún usuario con el correo '{email}'. Regístralo primero en la interfaz.")
    else:
        conn.execute(update(usuarios).where(usuarios.c.email == {repr(email)}).values(rol='administrador'))
        print(f"ÉXITO: El usuario '{email}' ha sido promovido a rol 'administrador'.")
"""
    output = run_in_clientes(code)
    print(output)


def crear_admin(email: str, password: str):
    code = f"""
from uuid import uuid4
from sqlalchemy import create_engine, select
from shared.runtime import database_url
from app.models import usuarios
from app.security import hasher

engine = create_engine(database_url())
with engine.begin() as conn:
    user = conn.execute(select(usuarios).where(usuarios.c.email == {repr(email)})).mappings().first()
    if user:
        print(f"El usuario '{email}' ya existe (rol actual: {user['rol']}). Usa 'promover' para asignarle permisos de administrador.")
    else:
        conn.execute(usuarios.insert().values(
            id=uuid4(),
            email={repr(email)},
            password_hash=hasher.hash({repr(password)}),
            rol='administrador',
            activo=True
        ))
        print(f"ÉXITO: Administrador '{email}' creado correctamente.")
"""
    output = run_in_clientes(code)
    print(output)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    comando = sys.argv[1].lower()
    if comando == 'listar':
        listar_admins()
    elif comando == 'promover':
        if len(sys.argv) < 3:
            print("Uso: python scripts/gestionar_admin.py promover <email>")
            sys.exit(1)
        promover_usuario(sys.argv[2])
    elif comando == 'crear':
        if len(sys.argv) < 4:
            print("Uso: python scripts/gestionar_admin.py crear <email> <contraseña>")
            sys.exit(1)
        crear_admin(sys.argv[2], sys.argv[3])
    else:
        print(f"Comando desconocido: '{comando}'")
        print(__doc__)


if __name__ == '__main__':
    main()
