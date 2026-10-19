# Código de la fase 3

Copia de consulta de los archivos implementados. Los archivos originales del repositorio son la fuente de verdad. No contiene claves ni contraseñas. Para ejecución y explicación ver [FASE_3.md](FASE_3.md).

## services/clientes/app/models.py

```python
from sqlalchemy import MetaData, Table, Column, String, Boolean, Integer, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB

metadata = MetaData()
clientes = Table('clientes', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True),
    Column('clave_externa', String(250), unique=True),
    Column('nombre', String(250)), Column('email', String(254)),
    Column('activo', Boolean, nullable=False, server_default='true'),
    Column('version', Integer, nullable=False, server_default='1'),
    Column('finanzas', JSONB),
    Column('created_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column('updated_at', DateTime(timezone=True), nullable=False, server_default=func.now()))
usuarios = Table('usuarios', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True),
    Column('cliente_id', UUID(as_uuid=True), ForeignKey('clientes.id'), unique=True),
    Column('email', String(254), unique=True, nullable=False),
    Column('password_hash', String(512), nullable=False),
    Column('rol', String(20), nullable=False),
    Column('activo', Boolean, nullable=False, server_default='true'))
importaciones = Table('importaciones', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True),
    Column('reporte', JSONB, nullable=False))
```

## services/clientes/migrations/versions/0002_clientes.py

```python
"""Clientes, usuarios y reportes de importación."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('clientes',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('clave_externa', sa.String(250), unique=True),
        sa.Column('nombre', sa.String(250)), sa.Column('email', sa.String(254)),
        sa.Column('activo', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('finanzas', JSONB),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('version >= 1', name='ck_cliente_version'))
    op.create_table('usuarios',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('cliente_id', UUID(as_uuid=True), sa.ForeignKey('clientes.id'), unique=True),
        sa.Column('email', sa.String(254), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(512), nullable=False),
        sa.Column('rol', sa.String(20), nullable=False),
        sa.Column('activo', sa.Boolean, nullable=False, server_default='true'),
        sa.CheckConstraint("rol IN ('cliente','administrador')", name='ck_usuario_rol'),
        sa.CheckConstraint("rol != 'cliente' OR cliente_id IS NOT NULL", name='ck_usuario_cliente'))
    op.create_table('importaciones', sa.Column('id', UUID(as_uuid=True), primary_key=True),
                    sa.Column('reporte', JSONB, nullable=False))


def downgrade():
    op.drop_table('importaciones')
    op.drop_table('usuarios')
    op.drop_table('clientes')
```

## services/clientes/app/schemas.py

```python
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictBool, field_validator, model_validator

Text = Annotated[str, Field(min_length=1, max_length=250)]
Count = Annotated[int, Field(ge=0, strict=True)]
Money = Annotated[str, Field(pattern=r'^(0|[1-9][0-9]{0,15})\.[0-9]{2}$')]


class Closed(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Finanzas(Closed):
    ingresos_mensuales_cop: Money
    obligaciones_mensuales_cop: Money
    tipo_empleo: Literal['dependiente', 'independiente', 'temporal'] | None
    antiguedad_laboral_meses: Count | None
    meses_historial_crediticio: Count | None
    creditos_previos: Count
    atrasos_previos_30d: Count
    porcentaje_pago_puntual: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False, strict=True)] | None

    @model_validator(mode='after')
    def coherent(self):
        if Decimal(self.ingresos_mensuales_cop) <= 0:
            raise ValueError('Los ingresos deben ser positivos')
        if (self.creditos_previos == 0) != (self.porcentaje_pago_puntual is None):
            raise ValueError('El porcentaje es nulo únicamente cuando no hay créditos previos')
        return self


class Login(Closed):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=128)]

    @field_validator('email')
    @classmethod
    def normalize_email(cls, value):
        return str(value).lower()


class Registro(Login):
    nombre: Text
    password: Annotated[str, Field(min_length=12, max_length=128)]


class ClienteEditar(Closed):
    version_esperada: Annotated[int, Field(ge=1, strict=True)]
    nombre: Text | None = None
    email: EmailStr | None = None
    activo: StrictBool | None = None
    finanzas: Finanzas | None = None

    @model_validator(mode='after')
    def not_empty(self):
        fields = self.model_fields_set - {'version_esperada'}
        if not fields or any(getattr(self, field) is None for field in fields):
            raise ValueError('Incluye al menos un campo no nulo para editar')
        return self
```

## services/clientes/app/security.py

```python
from functools import lru_cache
from pathlib import Path
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
import jwt

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash('dummy-not-a-login-account')


def verify_password(password, stored):
    try:
        return hasher.verify(stored or DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return False


@lru_cache
def private_key():
    return Path('/run/secrets/jwt_private.pem').read_bytes()


def issue_token(subject, *, role=None, cliente_id=None, scopes=None):
    now = datetime.now(timezone.utc)
    internal = scopes is not None
    payload = {'sub': str(subject), 'iss': 'credimarket-clientes',
        'aud': 'credimarket-internal' if internal else 'credimarket-api',
        'iat': now, 'exp': now + timedelta(minutes=30), 'jti': str(uuid4())}
    if internal:
        payload['scopes'] = scopes
    else:
        payload.update(role=role, cliente_id=str(cliente_id) if cliente_id else None)
    return jwt.encode(payload, private_key(), algorithm='RS256')
```

## shared/auth.py

```python
"""Signature verification only: other services never receive the signing key."""
from functools import lru_cache
from pathlib import Path
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt

bearer = HTTPBearer(auto_error=False)


@lru_cache
def public_key():
    return Path('/run/secrets/jwt_public.pem').read_bytes()


def decode_token(token, audience='credimarket-api'):
    try:
        return jwt.decode(token, public_key(), algorithms=['RS256'],
            audience=audience, issuer='credimarket-clientes',
            options={'require': ['sub', 'iss', 'aud', 'iat', 'exp', 'jti']})
    except jwt.InvalidTokenError:
        raise HTTPException(401, 'Token inválido o vencido', headers={'WWW-Authenticate': 'Bearer'})


def user_claims(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    if not credentials:
        raise HTTPException(401, 'Inicia sesión', headers={'WWW-Authenticate': 'Bearer'})
    claims = decode_token(credentials.credentials)
    if claims.get('role') not in ('cliente', 'administrador'):
        raise HTTPException(403, 'Rol no autorizado')
    return claims


def internal_claims(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    if not credentials:
        raise HTTPException(401, 'Credencial interna requerida')
    claims = decode_token(credentials.credentials, 'credimarket-internal')
    if claims['sub'] != 'prestamos' or 'clientes:read' not in claims.get('scopes', []):
        raise HTTPException(403, 'Servicio o alcance no autorizado')
    return claims
```

## services/clientes/app/main.py

```python
from uuid import UUID, uuid4
from fastapi import Depends, HTTPException, Query, Request, Response, UploadFile, File
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError, OperationalError
from shared.runtime import create_app
from shared.auth import user_claims, internal_claims
from .models import clientes, usuarios, importaciones
from .schemas import Registro, Login, ClienteEditar
from .security import hasher, verify_password, issue_token
from .importer import import_csv

app = create_app('clientes')
app.version = '0.3.0'
app.description = 'Clientes, autenticación y CSV. Fase 3.'


def connection(request: Request):
    with request.app.state.engine.begin() as conn:
        yield conn


def current_user(claims=Depends(user_claims), conn=Depends(connection)):
    try:
        user_id = UUID(claims['sub'])
    except ValueError:
        raise HTTPException(401, 'Identidad inválida')
    user = conn.execute(select(usuarios).where(usuarios.c.id == user_id)).mappings().first()
    if not user or not user['activo'] or user['rol'] != claims['role']:
        raise HTTPException(401, 'La cuenta no está disponible')
    return user


def admin(user=Depends(current_user)):
    if user['rol'] != 'administrador':
        raise HTTPException(403, 'Se requiere administrador')
    return user


def authorize_profile(user, profile_id):
    if user['rol'] != 'administrador' and user['cliente_id'] != profile_id:
        raise HTTPException(404, 'Cliente no encontrado')


def profile(conn, profile_id, lock=False):
    query = select(clientes).where(clientes.c.id == profile_id)
    if lock:
        query = query.with_for_update()
    row = conn.execute(query).mappings().first()
    if not row:
        raise HTTPException(404, 'Cliente no encontrado')
    return dict(row)


def error_response(request, status, message, details=None, headers=None):
    codes = {401: 'UNAUTHORIZED', 403: 'FORBIDDEN', 404: 'NOT_FOUND', 409: 'CONFLICT',
             413: 'FILE_TOO_LARGE', 422: 'INVALID_INPUT', 503: 'UNAVAILABLE'}
    return JSONResponse(status_code=status, headers=headers, content={
        'code': codes.get(status, 'ERROR'), 'message': message,
        'correlation_id': request.state.correlation_id, 'details': details or []})


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return error_response(request, exc.status_code, str(exc.detail), headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Do not echo the original input: registration/login errors may contain a password.
    details = [{'field': '.'.join(map(str, item['loc'])), 'message': item['msg']} for item in exc.errors()]
    return error_response(request, 422, 'Entrada inválida', details)


@app.exception_handler(IntegrityError)
async def integrity_error(request, exc):
    return error_response(request, 409, 'El correo o la relación de cliente ya existe')


@app.exception_handler(OperationalError)
async def unavailable(request, exc):
    return error_response(request, 503, 'Base de datos no disponible')


@app.post('/clientes', status_code=201)
def register(body: Registro, response: Response, conn=Depends(connection)):
    client_id = uuid4()
    conn.execute(clientes.insert().values(id=client_id, nombre=body.nombre, email=str(body.email)))
    conn.execute(usuarios.insert().values(id=uuid4(), cliente_id=client_id, email=str(body.email),
        password_hash=hasher.hash(body.password), rol='cliente'))
    response.headers['Location'] = f'/api/clientes/clientes/{client_id}'
    result = profile(conn, client_id)
    conn.commit()
    return result


@app.post('/auth/login')
def login(body: Login, conn=Depends(connection)):
    user = conn.execute(select(usuarios).where(usuarios.c.email == str(body.email))).mappings().first()
    valid = verify_password(body.password, user['password_hash'] if user else None)
    if not user or not valid or not user['activo']:
        raise HTTPException(401, 'Correo o contraseña incorrectos')
    return {'access_token': issue_token(user['id'], role=user['rol'], cliente_id=user['cliente_id']),
        'token_type': 'bearer', 'expires_in': 1800, 'role': user['rol'],
        'cliente_id': str(user['cliente_id']) if user['cliente_id'] else None}


@app.get('/clientes')
def list_clients(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                 user=Depends(admin), conn=Depends(connection)):
    items = conn.execute(select(clientes).order_by(clientes.c.created_at, clientes.c.id)
                         .limit(limit).offset(offset)).mappings().all()
    total = conn.execute(select(func.count()).select_from(clientes)).scalar_one()
    return {'items': [dict(row) for row in items], 'total': total, 'limit': limit, 'offset': offset}


@app.post('/clientes/importaciones', status_code=201)
def upload_csv(response: Response, file: UploadFile = File(...), user=Depends(admin), conn=Depends(connection)):
    raw = file.file.read(10 * 1024 * 1024 + 1)
    report = import_csv(conn, raw)
    conn.commit()
    response.headers['Location'] = f'/api/clientes/clientes/importaciones/{report["id"]}'
    return report


@app.get('/clientes/importaciones/{id}')
def import_report(id: UUID, user=Depends(admin), conn=Depends(connection)):
    report = conn.execute(select(importaciones.c.reporte).where(importaciones.c.id == id)).scalar_one_or_none()
    if report is None:
        raise HTTPException(404, 'Importación no encontrada')
    return report


@app.get('/clientes/{id}')
def get_client(id: UUID, user=Depends(current_user), conn=Depends(connection)):
    authorize_profile(user, id)
    return profile(conn, id)


@app.patch('/clientes/{id}')
def edit_client(id: UUID, body: ClienteEditar, user=Depends(current_user), conn=Depends(connection)):
    authorize_profile(user, id)
    changes = body.model_dump(mode='json', exclude_unset=True)
    expected = changes.pop('version_esperada')
    if user['rol'] != 'administrador' and set(changes) - {'nombre', 'email'}:
        raise HTTPException(403, 'Solo el administrador puede modificar finanzas o estado')
    current = profile(conn, id, lock=True)
    if current['version'] != expected:
        raise HTTPException(409, 'El cliente cambió. Consulta la versión actual antes de guardar')
    conn.execute(clientes.update().where(clientes.c.id == id).values(**changes,
        version=expected + 1, updated_at=func.now()))
    result = profile(conn, id)
    conn.commit()
    return result


@app.get('/interno/clientes/{id}')
def get_internal(id: UUID, claims=Depends(internal_claims), conn=Depends(connection)):
    return profile(conn, id)
```

## services/clientes/app/importer.py

```python
"""CSV adapter: financial records never create users or login credentials."""
import csv
import hashlib
import io
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, text, func
from sqlalchemy.dialects.postgresql import insert
from .models import clientes, importaciones
from .schemas import Finanzas

REQUIRED = {'cliente_id', *Finanzas.model_fields}
OPTIONAL = {'solicitud_id', 'monto_solicitado_cop', 'plazo_meses', 'tasa_mensual_simulada',
            'cuota_estimada_cop', 'incumplimiento_90d'}


def financial_row(row):
    value = {}
    for field in Finanzas.model_fields:
        raw = row[field].strip()
        if not raw:
            value[field] = None
        elif field == 'tipo_empleo':
            value[field] = raw
        elif field.endswith('_cop'):
            number = Decimal(raw)
            if not number.is_finite() or number != number.quantize(Decimal('0.01')):
                raise ValueError('Importe inválido o con más de dos decimales')
            value[field] = format(number, '.2f')
        elif field == 'porcentaje_pago_puntual':
            value[field] = float(raw)
        else:
            number = Decimal(raw)
            if not number.is_finite() or number != number.to_integral_value():
                raise ValueError('Meses y conteos deben ser enteros')
            value[field] = int(number)
    return Finanzas.model_validate(value).model_dump(mode='json')


def import_csv(connection, raw):
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, 'El archivo supera 10 MiB')
    try:
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')), strict=True)
        headers = reader.fieldnames or []
        if (len(headers) != len(set(headers)) or not REQUIRED <= set(headers)
                or set(headers) - REQUIRED - OPTIONAL):
            raise HTTPException(422, 'Cabeceras faltantes, repetidas o desconocidas')
        rows = []
        for row in reader:
            rows.append(row)
            if len(rows) > 20000:
                raise HTTPException(413, 'El archivo supera 20.000 filas')
    except (UnicodeDecodeError, csv.Error):
        raise HTTPException(422, 'CSV inválido: usa UTF-8 y separador coma')

    report = {'id': str(uuid4()), 'archivo_sha256': hashlib.sha256(raw).hexdigest(),
        'estado': 'COMPLETADA', 'total_filas': len(rows), 'insertados': 0, 'actualizados': 0,
        'sin_cambios': 0, 'rechazados': 0, 'errores': [],
        'created_at': datetime.now(timezone.utc).isoformat()}
    valid = {}
    seen = set()
    for line, row in enumerate(rows, start=2):
        try:
            if None in row or any(value is None for value in row.values()):
                raise ValueError('Número de columnas incorrecto')
            key = row['cliente_id'].strip()
            if not key or len(key) > 250:
                raise ValueError('cliente_id vacío o demasiado largo')
            if key in seen:
                raise ValueError('cliente_id repetido dentro del archivo')
            seen.add(key)
            valid[key] = financial_row(row)
        except (ValueError, InvalidOperation, OverflowError, ValidationError) as exc:
            field = 'fila'
            message = str(exc) if isinstance(exc, ValueError) else 'Número fuera de rango o inválido'
            if isinstance(exc, ValidationError):
                error = exc.errors()[0]
                field = '.'.join(map(str, error['loc'])) or 'finanzas'
                message = error['msg']
            report['rechazados'] += 1
            report['errores'].append({'fila': line, 'campo': field, 'codigo': 'FILA_INVALIDA',
                'mensaje': message})

    # Serialize imports, including two simultaneous uploads of the same file.
    # External keys cannot be edited through public HTTP endpoints.
    connection.execute(text('SELECT pg_advisory_xact_lock(734201)'))
    existing = {}
    if valid:
        existing = {r.clave_externa: r.finanzas for r in connection.execute(
            select(clientes.c.clave_externa, clientes.c.finanzas).where(
                clientes.c.clave_externa.in_(list(valid))).with_for_update())}
    pending = []
    for key, financial in valid.items():
        if key not in existing:
            report['insertados'] += 1
        elif existing[key] == financial:
            report['sin_cambios'] += 1
            continue
        else:
            report['actualizados'] += 1
        pending.append({'id': uuid4(), 'clave_externa': key, 'finanzas': financial})
    for offset in range(0, len(pending), 500):
        statement = insert(clientes).values(pending[offset:offset + 500])
        statement = statement.on_conflict_do_update(index_elements=['clave_externa'], set_={
            'finanzas': statement.excluded.finanzas, 'version': clientes.c.version + 1,
            'updated_at': func.now()})
        connection.execute(statement)
    connection.execute(importaciones.insert().values(id=report['id'], reporte=report))
    return report
```

## services/clientes/app/cli.py

```python
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
```

## frontend/src/Clientes.tsx

```tsx
import { FormEvent, useEffect, useState } from 'react';

type Session = { access_token: string; role: string; cliente_id: string | null; email: string };
type Finances = Record<string, string | number | null>;
type Client = { id: string; nombre: string | null; email: string | null; clave_externa: string | null; activo: boolean; version: number; finanzas: Finances | null };
type Report = { id: string; total_filas: number; insertados: number; actualizados: number; sin_cambios: number; rechazados: number; errores: { fila: number; mensaje: string }[] };
const fields = [
  ['ingresos_mensuales_cop', 'Ingresos mensuales (COP)'],
  ['obligaciones_mensuales_cop', 'Obligaciones mensuales (COP)'],
  ['antiguedad_laboral_meses', 'Antigüedad laboral (meses)'],
  ['meses_historial_crediticio', 'Historial crediticio (meses)'],
  ['creditos_previos', 'Créditos previos'], ['atrasos_previos_30d', 'Atrasos previos de 30 días'],
  ['porcentaje_pago_puntual', 'Pago puntual (%)'],
];

export function Clientes() {
  const [session, setSession] = useState<Session | null>(null);
  const [register, setRegister] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [clients, setClients] = useState<Client[]>([]);
  const [selected, setSelected] = useState<Client | null>(null);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [report, setReport] = useState<Report | null>(null);
  const isAdmin = session?.role === 'administrador';

  function logout() {
    setSession(null); setClients([]); setSelected(null); setReport(null); setOffset(0); setTotal(0);
  }

  async function api(path: string, options: RequestInit = {}, token = session?.access_token) {
    const headers = new Headers(options.headers);
    if (token) headers.set('Authorization', `Bearer ${token}`);
    if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
    const response = await fetch(`/api/clientes${path}`, { ...options, headers });
    let data;
    try { data = await response.json(); } catch { throw new Error('El servicio no está disponible. Intenta de nuevo.'); }
    if (!response.ok) {
      if (response.status === 401 && token) logout();
      const details = data.details?.map((d: { field: string; message: string }) => `${d.field}: ${d.message}`).join(' · ');
      throw new Error(response.status === 401 && token ? 'Tu sesión venció. Inicia sesión nuevamente.' : [data.message || 'No se pudo completar la operación', details].filter(Boolean).join(' · '));
    }
    return data;
  }

  async function action(work: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try { await work(); } catch (e) { setError(e instanceof Error ? e.message : 'No se pudo conectar con el servicio.'); }
    finally { setBusy(false); }
  }

  async function reload() {
    if (!session) return;
    if (session.role === 'administrador') {
      const data = await api(`/clientes?limit=20&offset=${offset}`);
      setClients(data.items); setTotal(data.total);
    } else setSelected(await api(`/clientes/${session.cliente_id}`));
  }
  useEffect(() => { if (session) void action(reload); }, [session, offset]);

  async function submitAccess(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await action(async () => {
      const credentials = { email: form.get('email'), password: form.get('password') };
      if (register) {
        await api('/clientes', { method: 'POST', body: JSON.stringify({ ...credentials, nombre: form.get('nombre') }) });
        setRegister(false); setNotice('Cuenta creada. Ahora puedes iniciar sesión.');
      } else {
        const data = await api('/auth/login', { method: 'POST', body: JSON.stringify(credentials) });
        setSession({ ...data, email: String(credentials.email) });
      }
    });
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected) return;
    const form = new FormData(event.currentTarget);
    const payload: Record<string, unknown> = { version_esperada: selected.version };
    for (const field of ['nombre', 'email']) {
      const value = String(form.get(field) || '').trim();
      if (value) payload[field] = value;
    }
    if (isAdmin) {
      payload.activo = form.get('activo') === 'on';
      if (form.get('editar_finanzas') === 'on') {
        const finances: Finances = { tipo_empleo: String(form.get('tipo_empleo') || '') || null };
        for (const [field] of fields) {
          const raw = String(form.get(field) || '').trim();
          finances[field] = raw === '' ? null : field.endsWith('_cop') ? Number(raw).toFixed(2) : Number(raw);
        }
        payload.finanzas = finances;
      }
    }
    await action(async () => {
      setSelected(await api(`/clientes/${selected.id}`, { method: 'PATCH', body: JSON.stringify(payload) }));
      if (isAdmin) await reload();
      setNotice('Datos guardados.');
    });
  }

  return <section className="panel client-module">
    <div className="module-heading"><h1>{session ? (isAdmin ? 'Administrar clientes' : 'Mi perfil') : 'Acceso a CrediMarket'}</h1>{session && <button onClick={logout} disabled={busy}>Cerrar sesión</button>}</div>
    {error && <p role="alert" className="error">{error}</p>}{notice && <p role="status" className="success">{notice}</p>}
    {busy && <p role="status">Procesando…</p>}
    {!session ? <form onSubmit={submitAccess} className="form-grid" key={String(register)}>
      {register && <label>Nombre<input name="nombre" required maxLength={250} autoComplete="name" /></label>}
      <label>Correo de acceso<input name="email" type="email" required autoComplete="username" /></label>
      <label>Contraseña<input name="password" type="password" required minLength={register ? 12 : 1} maxLength={128} autoComplete={register ? 'new-password' : 'current-password'} /></label>
      <button className="back" disabled={busy}>{register ? 'Crear cuenta' : 'Iniciar sesión'}</button>
      <button type="button" disabled={busy} onClick={() => { setRegister(!register); setError(''); }}>{register ? 'Ya tengo cuenta' : 'Registrarme'}</button>
    </form> : <>
      <p>Sesión de {session.email} · {isAdmin ? 'Administrador' : 'Cliente'}</p>
      {isAdmin && <>
        <form className="import-form" onSubmit={event => {
          event.preventDefault(); const form = new FormData(event.currentTarget);
          void action(async () => { setReport(await api('/clientes/importaciones', { method: 'POST', body: form })); await reload(); });
        }}><h2>Importar clientes</h2><label>Archivo CSV<input type="file" name="file" accept=".csv,text/csv" required /></label><button disabled={busy}>Importar</button></form>
        <form className="report-query" onSubmit={event => {
          event.preventDefault(); const id = String(new FormData(event.currentTarget).get('report_id')).trim();
          void action(async () => { setReport(await api(`/clientes/importaciones/${encodeURIComponent(id)}`)); });
        }}><label>Consultar una importación por identificador<input name="report_id" required /></label><button disabled={busy}>Consultar informe</button></form>
        {report && <div className="report"><h2>Resultado de la importación</h2><p>Identificador: {report.id}</p><p>Total: {report.total_filas} · Insertados: {report.insertados} · Actualizados: {report.actualizados} · Sin cambios: {report.sin_cambios} · Rechazados: {report.rechazados}</p>
          {report.errores.length > 0 && <><p>Primeros {Math.min(50, report.errores.length)} errores de {report.errores.length}:</p><ul>{report.errores.slice(0, 50).map((e, index) => <li key={index}>Fila {e.fila}: {e.mensaje}</li>)}</ul></>}</div>}
        <div className="table-scroll"><table><thead><tr><th>Cliente</th><th>Estado</th><th>Acción</th></tr></thead><tbody>{clients.map(client => <tr key={client.id}><td>{client.nombre || client.clave_externa || client.id}</td><td>{client.activo ? 'Activo' : 'Inactivo'}</td><td><button disabled={busy} onClick={() => void action(async () => { setSelected(await api(`/clientes/${client.id}`)); })}>Editar</button></td></tr>)}</tbody></table></div>
        <div className="pagination"><button disabled={busy || offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Anterior</button><span>{total} clientes · Página {Math.floor(offset / 20) + 1}</span><button disabled={busy || offset + 20 >= total} onClick={() => setOffset(offset + 20)}>Siguiente</button></div>
      </>}
      {selected && <form key={`${selected.id}:${selected.version}`} onSubmit={save} className="profile-form"><h2>{isAdmin ? 'Editar cliente' : 'Mis datos'}</h2>
        <p>Versión {selected.version}{selected.clave_externa && ` · Referencia: ${selected.clave_externa}`}</p>
        <div className="form-grid"><label>Nombre<input name="nombre" defaultValue={selected.nombre || ''} maxLength={250} required={!isAdmin} /></label><label>Correo de contacto<input name="email" type="email" defaultValue={selected.email || ''} /></label></div>
        <p className="note">El correo de contacto no cambia tu correo de acceso.</p>
        {isAdmin && <label className="check"><input name="activo" type="checkbox" defaultChecked={selected.activo} />Cliente activo</label>}
        <h3>Información financiera</h3>
        {isAdmin ? <label className="check"><input name="editar_finanzas" type="checkbox" defaultChecked={!!selected.finanzas} />Guardar también la información financiera</label> : <p>Estos datos los administra un responsable de CrediMarket.</p>}
        <fieldset disabled={!isAdmin}><div className="form-grid">
          <label>Tipo de empleo<select name="tipo_empleo" defaultValue={String(selected.finanzas?.tipo_empleo || '')}><option value="">Sin dato</option><option value="dependiente">Dependiente</option><option value="independiente">Independiente</option><option value="temporal">Temporal</option></select></label>
          {fields.map(([field, label]) => <label key={field}>{label}<input name={field} type="number" min="0" max={field === 'porcentaje_pago_puntual' ? 100 : undefined} step={field.endsWith('_cop') || field === 'porcentaje_pago_puntual' ? '0.01' : '1'} defaultValue={selected.finanzas?.[field] ?? ''} /></label>)}
        </div></fieldset><p className="note">Sin créditos previos, el porcentaje de pago puntual debe quedar vacío.</p>
        <button className="back" disabled={busy}>Guardar cambios</button><button type="button" disabled={busy} onClick={() => void action(async () => { setSelected(await api(`/clientes/${selected.id}`)); })}>Recargar datos</button>
      </form>}
    </>}
  </section>;
}
```

## frontend/src/main.tsx

```tsx
import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import { Clientes } from './Clientes';

const sections = ['Inicio', 'Catálogo', 'Mis solicitudes', 'Clientes', 'Inventario', 'Modelo'];
const services = ['productos', 'clientes', 'prestamos', 'inventario'];

function App() {
  const [active, setActive] = useState('Inicio');
  const [status, setStatus] = useState<Record<string, string>>({});
  useEffect(() => {
    const controller = new AbortController();
    Promise.all(services.map(async service => {
      try {
        const response = await fetch(`/api/${service}/health`, { signal: controller.signal });
        const data = await response.json();
        return [service, response.ok && data.status === 'ok' ? 'Disponible' : 'Sin conexión'];
      } catch { return [service, 'Sin conexión']; }
    })).then(entries => { if (!controller.signal.aborted) setStatus(Object.fromEntries(entries)); });
    return () => controller.abort();
  }, []);
  return <div className="layout">
    <header><a href="#" onClick={() => setActive('Inicio')} className="brand">CrediMarket<span>Financiación de tecnología</span></a><span className="badge">En desarrollo</span></header>
    <nav aria-label="Navegación principal">{sections.map(section => <button key={section} aria-current={active === section ? 'page' : undefined} onClick={() => setActive(section)}>{section}</button>)}</nav>
    <main>{active === 'Inicio' ? <>
      <p className="eyebrow">Proyecto académico · Fase 3</p>
      <h1>La base de CrediMarket<br />ya está en marcha.</h1>
      <p className="intro">Ya puedes registrarte y administrar tu perfil desde Clientes. El catálogo y las solicitudes de financiación se incorporarán en las siguientes etapas.</p>
      <section className="panel" aria-label="Conectividad de servicios"><h2>Conexión con los servicios</h2><div className="grid">{services.map(service => <article key={service}><h3>{service}</h3><p aria-live="polite">{status[service] || 'Comprobando…'}</p></article>)}</div><p className="note">Clientes ya permite registro y acceso. Los servicios de las siguientes fases siguen en desarrollo.</p></section>
    </> : active === 'Clientes' ? null : <section className="panel"><p className="eyebrow">Próxima etapa</p><h1>{active}</h1><p>Este módulo todavía no está implementado. Aquí aparecerán las operaciones conectadas a los servicios reales.</p><button className="back" onClick={() => setActive('Inicio')}>Volver al inicio</button></section>}<div hidden={active !== 'Clientes'}><Clientes /></div></main>
    <footer>Datos y operaciones ficticios para aprendizaje.</footer>
  </div>;
}

createRoot(document.getElementById('root')!).render(<App />);
```

## frontend/src/style.css

```css
:root{font-family:Inter,system-ui,sans-serif;color:#16332b;background:#f3f6f3;font-synthesis:none}*{box-sizing:border-box}body{margin:0}.layout{max-width:1180px;margin:auto;padding:0 32px}header{display:flex;justify-content:space-between;align-items:center;padding:30px 0}.brand{color:inherit;text-decoration:none;font-size:25px;font-weight:800;letter-spacing:-1px}.brand span{display:block;font-size:12px;font-weight:400;letter-spacing:.3px;margin-top:4px}.badge{border:1px solid #b8cbbf;border-radius:24px;padding:7px 14px;font-size:12px}nav{display:flex;gap:8px;border-bottom:1px solid #d5dfd8;padding-bottom:16px;overflow:auto}button{font:inherit;cursor:pointer}nav button{border:0;background:transparent;border-radius:8px;padding:10px 16px;white-space:nowrap;color:#52645b}nav button[aria-current]{background:#163d30;color:white}main{padding:54px 0;min-height:65vh}.eyebrow{text-transform:uppercase;letter-spacing:2px;font-size:12px;color:#4a7663;font-weight:700}h1{font-size:clamp(32px,5vw,54px);line-height:1.12;letter-spacing:-1.5px;margin:20px 0}.intro{max-width:650px;line-height:1.8;color:#5a6b62}.panel{background:white;padding:28px;border:1px solid #dfe6df;border-radius:16px;margin-top:36px}h2{font-size:18px;margin:0 0 20px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.grid article{padding:16px;border-radius:10px;background:#f2f6f2}.grid h3{text-transform:capitalize;font-size:15px;margin:0}.grid p{font-size:13px;color:#52725e;margin-bottom:0}.note,footer{font-size:12px;color:#69796f;line-height:1.6}.note{margin:20px 0 0}footer{border-top:1px solid #d5dfd8;padding:20px 0}.back{background:#163d30;color:white;border:0;padding:10px 18px;border-radius:8px;margin-top:18px}button:focus-visible,a:focus-visible{outline:3px solid #e0ab45;outline-offset:3px}@media(max-width:650px){.layout{padding:0 18px}.grid{grid-template-columns:repeat(2,1fr)}.panel{padding:20px}main{padding-top:32px}.badge{font-size:10px}}

.client-module h1{font-size:30px}.module-heading{display:flex;justify-content:space-between;align-items:center;gap:16px}.form-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}.client-module label{display:flex;flex-direction:column;gap:6px;font-size:14px}.client-module input,.client-module select{font:inherit;padding:10px;border:1px solid #a6b8ab;border-radius:6px;min-width:0;width:100%}.client-module button{padding:10px 16px;border:1px solid #a6b8ab;border-radius:7px}.client-module button:disabled{opacity:.5;cursor:wait}.client-module .check{flex-direction:row;align-items:center;margin:18px 0}.check input{width:auto}.error{background:#fff0ed;color:#8e3024;padding:14px;border-radius:7px}.success{background:#e9f5e8;color:#28502c;padding:14px;border-radius:7px}fieldset{border:0;padding:0;margin:18px 0}fieldset:disabled{opacity:.8}.import-form,.report-query,.profile-form{border-top:1px solid #d5dfd8;padding-top:24px;margin-top:24px}.report{background:#f2f6f2;padding:18px;margin:20px 0;overflow-wrap:anywhere}.table-scroll{overflow:auto;margin:24px 0}table{border-collapse:collapse;width:100%;text-align:left}th,td{padding:12px;border-bottom:1px solid #d5dfd8}.pagination{display:flex;justify-content:space-between;align-items:center;gap:10px;font-size:13px}.client-module input[type=file]{margin-bottom:12px}.report-query input{margin-bottom:10px}
```

## frontend/nginx.conf

```text
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;
    client_max_body_size 11m;
    resolver 127.0.0.11 valid=10s ipv6=off;
    location ~ ^/api/(productos|clientes|prestamos|inventario)/(.*)$ {
        set $service $1;
        set $path $2;
        proxy_pass http://$service:8000/$path$is_args$args;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Correlation-ID $http_x_correlation_id;
        proxy_connect_timeout 3s;
        proxy_read_timeout 120s;
    }
    location / { try_files $uri $uri/ /index.html; }
}
```

## scripts/bootstrap.py

```python
"""Create local credentials once, without printing or overwriting secrets."""
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]
env_path = ROOT / ".env"
template = (ROOT / ".env.example").read_text(encoding="utf-8")
if not env_path.exists():
    lines = []
    for line in template.splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            if key.endswith("PASSWORD"):
                value = secrets.token_hex(24)
            line = f"{key}={value}"
        lines.append(line)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

env = {}
for line in env_path.read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.startswith("#"):
        key, value = line.split("=", 1)
        env[key] = value
for key in ["KAFKA_ADMIN_PASSWORD", "KAFKA_PRESTAMOS_PASSWORD", "KAFKA_INVENTARIO_PASSWORD"]:
    if not env.get(key) or any(c not in "0123456789abcdef" for c in env[key]):
        raise SystemExit(f"{key} must contain generated hexadecimal credentials; no files overwritten.")

secret_dir = ROOT / ".secrets"
secret_dir.mkdir(exist_ok=True)
jaas = '\n'.join([
    'KafkaServer {', '  org.apache.kafka.common.security.plain.PlainLoginModule required',
    '  username="admin"', f'  password="{env["KAFKA_ADMIN_PASSWORD"]}"',
    f'  user_admin="{env["KAFKA_ADMIN_PASSWORD"]}"',
    f'  user_prestamos="{env["KAFKA_PRESTAMOS_PASSWORD"]}"',
    f'  user_inventario="{env["KAFKA_INVENTARIO_PASSWORD"]}";', '};', '',
])
client = '\n'.join([
    'security.protocol=SASL_PLAINTEXT', 'sasl.mechanism=PLAIN',
    'sasl.jaas.config=org.apache.kafka.common.security.plain.PlainLoginModule required '
    f'username="admin" password="{env["KAFKA_ADMIN_PASSWORD"]}";', '',
])
for name, content in [("kafka_server_jaas.conf", jaas), ("kafka_admin.properties", client)]:
    target = secret_dir / name
    if target.exists() and target.read_text(encoding="utf-8") != content:
        raise SystemExit(f"{name} differs from .env. Rotate credentials deliberately; not overwriting.")
    if not target.exists():
        target.write_text(content, encoding="utf-8")
print("Local configuration ready. Credentials not displayed; existing values preserved.")

# Signing key only goes to Clientes; all other APIs receive only the public key.
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
private_file = secret_dir / "jwt_private.pem"
public_file = secret_dir / "jwt_public.pem"
if private_file.exists() != public_file.exists():
    raise SystemExit("Incomplete JWT key pair. Restore the missing key; do not rotate silently.")
if not private_file.exists():
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    private_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public_file.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo))
print("JWT keys ready; existing keys preserved.")
```

## compose.yaml

```yaml
name: credimarket

x-api: &api
  restart: unless-stopped
  networks: [backend]
  secrets:
    - source: jwt_public
      target: jwt_public.pem
  healthcheck:
    test: [CMD, python, -c, "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"]
    interval: 15s
    timeout: 5s
    retries: 5
    start_period: 30s

x-api-env: &api-env
  DB_HOST: postgres
  CORS_ORIGINS: http://localhost:${FRONTEND_PORT:-8080}

services:
  postgres:
    image: postgres:17.6-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: credimarket_root
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?Run python scripts/bootstrap.py}
      PRODUCTOS_DB_PASSWORD: ${PRODUCTOS_DB_PASSWORD:?Missing password}
      CLIENTES_DB_PASSWORD: ${CLIENTES_DB_PASSWORD:?Missing password}
      PRESTAMOS_DB_PASSWORD: ${PRESTAMOS_DB_PASSWORD:?Missing password}
      INVENTARIO_DB_PASSWORD: ${INVENTARIO_DB_PASSWORD:?Missing password}
      MLFLOW_DB_PASSWORD: ${MLFLOW_DB_PASSWORD:?Missing password}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./infra/postgres/init.sh:/docker-entrypoint-initdb.d/10-databases.sh:ro
    networks: [backend]
    healthcheck:
      test: [CMD-SHELL, "pg_isready -U credimarket_root -d postgres"]
      interval: 5s
      timeout: 5s
      retries: 20

  redis:
    image: redis:8.2.1-alpine
    restart: unless-stopped
    environment:
      REDIS_PASSWORD: ${REDIS_PASSWORD:?Missing password}
    command: [sh, -c, 'exec redis-server --requirepass "$$REDIS_PASSWORD" --maxmemory 128mb --maxmemory-policy allkeys-lru --save "" --appendonly no']
    networks: [backend]
    healthcheck:
      test: [CMD-SHELL, 'REDISCLI_AUTH="$$REDIS_PASSWORD" redis-cli ping | grep -q PONG']
      interval: 5s
      timeout: 3s
      retries: 10

  kafka-volume-init:
    image: apache/kafka:4.1.0
    user: "0:0"
    entrypoint: [chown, "1000:1000", /data]
    volumes:
      - kafka_data:/data
    network_mode: none
    restart: "no"

  kafka:
    image: apache/kafka:4.1.0
    restart: unless-stopped
    depends_on:
      kafka-volume-init: {condition: service_completed_successfully}
    ports:
      - "127.0.0.1:${KAFKA_EXTERNAL_PORT:-19092}:${KAFKA_EXTERNAL_PORT:-19092}"
    environment:
      CLUSTER_ID: MkU3OEVBNTcwNTJENDM2Qk
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_LISTENERS: INTERNAL://:9092,EXTERNAL://:${KAFKA_EXTERNAL_PORT:-19092},CONTROLLER://:9093
      KAFKA_ADVERTISED_LISTENERS: INTERNAL://kafka:9092,EXTERNAL://localhost:${KAFKA_EXTERNAL_PORT:-19092}
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: INTERNAL:SASL_PLAINTEXT,EXTERNAL:SASL_PLAINTEXT,CONTROLLER:PLAINTEXT
      KAFKA_INTER_BROKER_LISTENER_NAME: INTERNAL
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
      KAFKA_SASL_ENABLED_MECHANISMS: PLAIN
      KAFKA_SASL_MECHANISM_INTER_BROKER_PROTOCOL: PLAIN
      KAFKA_AUTHORIZER_CLASS_NAME: org.apache.kafka.metadata.authorizer.StandardAuthorizer
      KAFKA_SUPER_USERS: User:admin;User:ANONYMOUS
      KAFKA_ALLOW_EVERYONE_IF_NO_ACL_FOUND: "false"
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: 1
      KAFKA_MIN_INSYNC_REPLICAS: 1
      KAFKA_NUM_PARTITIONS: 3
      KAFKA_AUTO_CREATE_TOPICS_ENABLE: "false"
      KAFKA_LOG_RETENTION_HOURS: 168
      KAFKA_LOG_DIRS: /tmp/kraft-combined-logs
      KAFKA_HEAP_OPTS: -Xms256m -Xmx512m
      KAFKA_OPTS: -Djava.security.auth.login.config=/run/secrets/kafka_server_jaas.conf
    secrets:
      - source: kafka_server_jaas
        target: kafka_server_jaas.conf
      - source: kafka_admin
        target: kafka_admin.properties
    volumes:
      - kafka_data:/tmp/kraft-combined-logs
    networks: [backend]
    healthcheck:
      test: [CMD-SHELL, '/opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --command-config /run/secrets/kafka_admin.properties --list >/dev/null']
      interval: 15s
      timeout: 10s
      retries: 10
      start_period: 45s

  kafka-init:
    image: apache/kafka:4.1.0
    depends_on:
      kafka: {condition: service_healthy}
    entrypoint: [sh, /init.sh]
    volumes:
      - ./infra/kafka/init.sh:/init.sh:ro
    secrets:
      - source: kafka_admin
        target: kafka_admin.properties
    networks: [backend]
    restart: "no"

  mlflow:
    build:
      context: .
      dockerfile: infra/mlflow/Dockerfile
    environment:
      MLFLOW_DB_PASSWORD: ${MLFLOW_DB_PASSWORD:?Missing password}
    ports:
      - "127.0.0.1:${MLFLOW_PORT:-5000}:5000"
    volumes:
      - mlflow_artifacts:/mlartifacts
    depends_on:
      postgres: {condition: service_healthy}
    networks: [backend]
    restart: unless-stopped
    healthcheck:
      test: [CMD, python, -c, "import urllib.request; urllib.request.urlopen('http://localhost:5000/health', timeout=3)"]
      interval: 15s
      timeout: 5s
      retries: 10
      start_period: 90s

  productos:
    <<: *api
    build:
      context: .
      dockerfile: infra/python/Dockerfile
      args: {SERVICE: productos}
    environment:
      <<: *api-env
      DB_NAME: productos_db
      DB_USER: productos_app
      DB_PASSWORD: ${PRODUCTOS_DB_PASSWORD:?Missing password}
      REDIS_PASSWORD: ${REDIS_PASSWORD:?Missing password}
    depends_on:
      postgres: {condition: service_healthy}

  clientes:
    <<: *api
    secrets:
      - source: jwt_public
        target: jwt_public.pem
      - source: jwt_private
        target: jwt_private.pem
    build:
      context: .
      dockerfile: infra/python/Dockerfile
      args: {SERVICE: clientes}
    environment:
      <<: *api-env
      DB_NAME: clientes_db
      DB_USER: clientes_app
      DB_PASSWORD: ${CLIENTES_DB_PASSWORD:?Missing password}
    depends_on:
      postgres: {condition: service_healthy}

  prestamos:
    <<: *api
    build:
      context: .
      dockerfile: infra/python/Dockerfile
      args: {SERVICE: prestamos}
    environment:
      <<: *api-env
      DB_NAME: prestamos_db
      DB_USER: prestamos_app
      DB_PASSWORD: ${PRESTAMOS_DB_PASSWORD:?Missing password}
      KAFKA_PASSWORD: ${KAFKA_PRESTAMOS_PASSWORD:?Missing password}
    depends_on:
      postgres: {condition: service_healthy}
      kafka-init: {condition: service_completed_successfully}

  inventario:
    <<: *api
    build:
      context: .
      dockerfile: infra/python/Dockerfile
      args: {SERVICE: inventario}
    environment:
      <<: *api-env
      DB_NAME: inventario_db
      DB_USER: inventario_app
      DB_PASSWORD: ${INVENTARIO_DB_PASSWORD:?Missing password}
      KAFKA_PASSWORD: ${KAFKA_INVENTARIO_PASSWORD:?Missing password}
    depends_on:
      postgres: {condition: service_healthy}
      kafka-init: {condition: service_completed_successfully}

  frontend:
    build: ./frontend
    ports:
      - "127.0.0.1:${FRONTEND_PORT:-8080}:80"
    depends_on:
      productos: {condition: service_healthy}
      clientes: {condition: service_healthy}
      prestamos: {condition: service_healthy}
      inventario: {condition: service_healthy}
    networks: [backend]
    restart: unless-stopped
    healthcheck:
      test: [CMD, wget, -q, -O, /dev/null, http://127.0.0.1/]
      interval: 15s
      timeout: 5s
      retries: 5

networks:
  backend:

volumes:
  postgres_data:
  kafka_data:
  mlflow_artifacts:

secrets:
  jwt_private:
    file: ./.secrets/jwt_private.pem
  jwt_public:
    file: ./.secrets/jwt_public.pem
  kafka_server_jaas:
    file: ./.secrets/kafka_server_jaas.conf
    name: credimarket_kafka_server_jaas
  kafka_admin:
    file: ./.secrets/kafka_admin.properties
    name: credimarket_kafka_admin
```

## infra/python/requirements.in

```text
fastapi==0.118.0
uvicorn==0.37.0
SQLAlchemy==2.0.43
psycopg[binary]==3.2.10
alembic==1.16.5
redis==6.4.0
confluent-kafka==2.11.1
PyJWT[crypto]==2.10.1
cryptography==45.0.7
argon2-cffi==25.1.0
email-validator==2.2.0
python-multipart==0.0.20
```

## requirements-bootstrap.txt

```text
cryptography==45.0.7
```

## scripts/check_phase3.py

```python
"""Integration checks for phase 3. Uses real PostgreSQL and HTTP APIs.

Creates uniquely named synthetic test accounts and durable import reports.
No deletes, volume resets or production credentials.
"""
from concurrent.futures import ThreadPoolExecutor
import io
import csv
import json
from pathlib import Path
import secrets
import subprocess
import urllib.request
import urllib.error
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
env = dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
BASE = f"http://127.0.0.1:{env.get('FRONTEND_PORT', '8080')}/api/clientes"
tag = uuid4().hex[:12]
password = secrets.token_urlsafe(24)


def inside(source):
    result = subprocess.run(['docker', 'compose', 'exec', '-T', 'clientes', 'python', '-'],
        cwd=ROOT, input=source, text=True, capture_output=True, encoding='utf-8', timeout=60)
    if result.returncode:
        raise RuntimeError('Fixture setup failed inside Clientes (output suppressed to protect credentials)')
    return result.stdout.strip()


def api(path, method='GET', body=None, token=None, file=None):
    headers = {}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if file is not None:
        boundary = 'Boundary' + uuid4().hex
        data = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="test.csv"\r\nContent-Type: text/csv\r\n\r\n'.encode()
                + file + f'\r\n--{boundary}--\r\n'.encode())
        headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
    else:
        data = json.dumps(body).encode() if body is not None else None
        if data:
            headers['Content-Type'] = 'application/json'
    try:
        response = urllib.request.urlopen(urllib.request.Request(BASE + path, data=data, headers=headers, method=method), timeout=120)
    except urllib.error.HTTPError as exc:
        response = exc
    content = response.read()
    try:
        result = json.loads(content)
    except ValueError:
        raise AssertionError(f'Non-JSON response: HTTP {response.status} {path}')
    return response.status, result


def expect(status, result, code):
    assert status == code, (status, code, result.get('message', result.get('code', 'Unexpected response')))
    return result


admin_email = f'admin-{tag}@example.com'
inside('''
from uuid import uuid4
from sqlalchemy import create_engine
from shared.runtime import database_url
from app.models import usuarios
from app.security import hasher
with create_engine(database_url()).begin() as conn:
    conn.execute(usuarios.insert().values(id=uuid4(), email=EMAIL, password_hash=hasher.hash(PASSWORD), rol='administrador'))
'''.replace('EMAIL', repr(admin_email)).replace('PASSWORD', repr(password)))
admin = expect(*api('/auth/login', 'POST', {'email': admin_email, 'password': password}), 200)['access_token']
clients = []
for name in ['a', 'b']:
    email = f'{name}-{tag}@example.com'
    row = expect(*api('/clientes', 'POST', {'nombre': 'Prueba ' + name, 'email': email, 'password': password}), 201)
    login = expect(*api('/auth/login', 'POST', {'email': email.upper(), 'password': password}), 200)
    assert login['role'] == 'cliente' and login['cliente_id'] == row['id']
    clients.append((row, login['access_token'], email))
a, a_token, a_email = clients[0]
b, b_token, _ = clients[1]
assert a['finanzas'] is None
expect(*api('/clientes', 'POST', {'nombre': 'Ataque', 'email': f'bad-{tag}@example.com', 'password': password, 'role': 'administrador'}), 422)
expect(*api('/auth/login', 'POST', {'email': a_email, 'password': 'incorrecta'}), 401)
before = expect(*api('/clientes', token=admin), 200)['total']
expect(*api('/clientes', 'POST', {'nombre': 'Duplicado', 'email': a_email, 'password': password}), 409)
assert expect(*api('/clientes', token=admin), 200)['total'] == before
expect(*api('/clientes'), 401)
expect(*api('/clientes', token=a_token), 403)
expect(*api('/clientes/' + b['id'], token=a_token), 404)
expect(*api('/clientes/' + a['id'], 'PATCH', {'version_esperada': 1, 'activo': False}, a_token), 403)
expect(*api('/clientes/importaciones', 'POST', token=a_token, file=b'cliente_id\n'), 403)
expect(*api('/interno/clientes/' + a['id'], token=admin), 401)
expect(*api('/clientes/' + a['id'], token=a_token[:-8] + 'AAAAAAAA'), 401)
expired = inside('''
import jwt, time
from app.security import private_key
claims=jwt.decode(TOKEN, options={'verify_signature': False})
claims['iat']=int(time.time())-3600
claims['exp']=int(time.time())-60
print(jwt.encode(claims, private_key(), algorithm='RS256'))
'''.replace('TOKEN', repr(a_token)))
expect(*api('/clientes/' + a['id'], token=expired), 401)
service_token = inside("from app.security import issue_token; print(issue_token('prestamos', scopes=['clientes:read']))")
expect(*api('/interno/clientes/' + a['id'], token=service_token), 200)
expect(*api('/clientes/' + a['id'], token=service_token), 401)
print('PASS register, password login, duplicate rollback, owner/role, expired/forged token and service scope')

with ThreadPoolExecutor(max_workers=2) as executor:
    results = list(executor.map(lambda name: api('/clientes/' + a['id'], 'PATCH', {'version_esperada': 1, 'nombre': name}, a_token), ['Edición uno', 'Edición dos']))
assert sorted(code for code, _ in results) == [200, 409]
financial = {'ingresos_mensuales_cop': '2500000.00', 'obligaciones_mensuales_cop': '300000.00',
    'tipo_empleo': 'dependiente', 'antiguedad_laboral_meses': 12, 'meses_historial_crediticio': None,
    'creditos_previos': 0, 'atrasos_previos_30d': 0, 'porcentaje_pago_puntual': None}
updated = expect(*api('/clientes/' + a['id'], 'PATCH', {'version_esperada': 2, 'finanzas': financial}, admin), 200)
assert updated['finanzas'] == financial and updated['version'] == 3
expect(*api('/clientes/' + a['id'], 'PATCH', {'version_esperada': 3, 'finanzas': {**financial, 'creditos_previos': 1}}, admin), 422)
print('PASS concurrent version check and validated admin financial update')

raw = (ROOT / 'prestamos_entrenamiento.csv').read_bytes()
first = expect(*api('/clientes/importaciones', 'POST', token=admin, file=raw), 201)
assert first['total_filas'] == 12000 and first['rechazados'] == 0
second = expect(*api('/clientes/importaciones', 'POST', token=admin, file=raw), 201)
assert second['insertados'] == second['actualizados'] == second['rechazados'] == 0 and second['sin_cambios'] == 12000
assert expect(*api('/clientes/importaciones/' + second['id'], token=admin), 200) == second

sample = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))[:3]
for index, row in enumerate(sample):
    row['cliente_id'] = f'TEST-{tag}-{index}'
sample[1]['cliente_id'] = sample[0]['cliente_id']
sample[2]['ingresos_mensuales_cop'] = '-1'
out = io.StringIO(); writer = csv.DictWriter(out, fieldnames=sample[0].keys()); writer.writeheader(); writer.writerows(sample)
mixed = expect(*api('/clientes/importaciones', 'POST', token=admin, file=out.getvalue().encode()), 201)
assert mixed['insertados'] == 1 and mixed['rechazados'] == 2 and len(mixed['errores']) == 2
assert 'repetido' in mixed['errores'][0]['mensaje']
assert mixed['errores'][1]['campo'] == 'ingresos_mensuales_cop'
expect(*api('/clientes/importaciones', 'POST', token=admin, file=b'cliente_id,unknown\nx,y\n'), 422)
expect(*api('/clientes/importaciones', 'POST', token=admin, file=b'x' * (10 * 1024 * 1024 + 1)), 413)
print('PASS 12,000-row import twice, durable report, duplicate/invalid rows and upload limits')

# Validate representative real responses against the phase-1 design contracts.
from jsonschema import Draft202012Validator, FormatChecker
contract = json.loads((ROOT / 'contracts/openapi/clientes.json').read_text(encoding='utf-8'))
for schema_name, value in [('Cliente', updated), ('Importacion', first)]:
    schema = {'$ref': '#/components/schemas/' + schema_name, 'components': contract['components']}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
print('PASS response contracts. Phase 3 API checks completed; synthetic test accounts retained.')
```
