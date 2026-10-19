"""Controlled operator commands. Passwords are entered interactively, never in argv."""
import argparse
from getpass import getpass
from uuid import uuid4, UUID
from sqlalchemy import create_engine, select
from pydantic import ValidationError
from shared.runtime import database_url
from .models import clientes, usuarios
from .schemas import Registro
from .security import hasher, issue_token


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    provision = sub.add_parser('create-user')
    provision.add_argument('--email', required=True)
    provision.add_argument('--role', choices=['cliente', 'administrador'], required=True)
    provision.add_argument('--cliente-id', type=UUID)
    internal = sub.add_parser('service-token')
    internal.add_argument('--service', choices=['prestamos'], required=True)
    args = parser.parse_args()
    if args.command == 'service-token':
        print(issue_token(args.service, scopes=['clientes:read']))
        return
    if args.role == 'cliente' and not args.cliente_id:
        parser.error('Un usuario cliente requiere --cliente-id de un perfil existente')
    password = getpass('Contraseña (mínimo 12 caracteres): ')
    if password != getpass('Repetir contraseña: '):
        raise SystemExit('Las contraseñas no coinciden')
    try:
        data = Registro(nombre='Operador', email=args.email, password=password)
    except ValidationError:
        raise SystemExit('Revisa el correo y la contraseña (12–128 caracteres).') from None
    with create_engine(database_url(), hide_parameters=True).begin() as conn:
        if conn.execute(select(usuarios.c.id).where(usuarios.c.email == str(data.email))).first():
            raise SystemExit('La cuenta ya existe; no se modificó')
        if args.cliente_id and not conn.execute(select(clientes.c.id).where(clientes.c.id == args.cliente_id)).first():
            raise SystemExit('Cliente no encontrado')
        conn.execute(usuarios.insert().values(id=uuid4(), cliente_id=args.cliente_id,
            email=str(data.email), password_hash=hasher.hash(data.password), rol=args.role))
    print('Cuenta creada; contraseña no mostrada.')


if __name__ == '__main__':
    main()
