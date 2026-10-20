"""Signature verification only: other services never receive the signing key."""
from datetime import datetime, timezone, timedelta
from functools import lru_cache
from pathlib import Path
from uuid import uuid4
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt

bearer = HTTPBearer(auto_error=False)


@lru_cache
def public_key():
    path = Path('/run/secrets/jwt_public.pem')
    if not path.exists():
        path = Path(__file__).resolve().parents[1] / '.secrets' / 'jwt_public.pem'
    return path.read_bytes()


@lru_cache
def private_key():
    path = Path('/run/secrets/jwt_private.pem')
    if not path.exists():
        path = Path(__file__).resolve().parents[1] / '.secrets' / 'jwt_private.pem'
    return path.read_bytes()


def issue_service_token(service: str, scopes: list[str], expires_in_minutes: int = 30) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        'sub': str(service),
        'iss': 'credimarket-clientes',
        'aud': 'credimarket-internal',
        'iat': now,
        'exp': now + timedelta(minutes=expires_in_minutes),
        'jti': str(uuid4()),
        'scopes': scopes,
    }
    return jwt.encode(payload, private_key(), algorithm='RS256')


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


def require_internal(required_scope: str):
    def dependency(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
        if not credentials:
            raise HTTPException(401, 'Credencial interna requerida')
        claims = decode_token(credentials.credentials, 'credimarket-internal')
        if claims.get('sub') != 'prestamos' or required_scope not in claims.get('scopes', []):
            raise HTTPException(403, 'Servicio o alcance no autorizado')
        return claims
    return dependency


def require_admin_or_service(required_scope: str):
    def dependency(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
        if not credentials:
            raise HTTPException(401, 'Credencial requerida', headers={'WWW-Authenticate': 'Bearer'})
        claims = decode_token(credentials.credentials, ['credimarket-api', 'credimarket-internal'])
        aud = claims.get('aud')
        if aud == 'credimarket-api':
            if claims.get('role') != 'administrador':
                raise HTTPException(403, 'Se requiere rol administrador')
            return claims
        if aud == 'credimarket-internal':
            if required_scope not in claims.get('scopes', []):
                raise HTTPException(403, 'Alcance de servicio no autorizado')
            return claims
        raise HTTPException(403, 'Audiencia no autorizada')
    return dependency


internal_claims = require_internal('clientes:read')
cotizar_claims = require_internal('productos:cotizar')
reservas_read_claims = require_internal('reservas:read')
modelo_read_claims = require_admin_or_service('modelo:read')
riesgo_predict_claims = require_admin_or_service('riesgo:predict')
