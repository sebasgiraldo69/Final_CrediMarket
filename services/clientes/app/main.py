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
    items = conn.execute(select(clientes).order_by(clientes.c.created_at.desc(), clientes.c.id.desc())
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
