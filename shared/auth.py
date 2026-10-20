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


def require_internal(required_scope: str):
    def dependency(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
        if not credentials:
            raise HTTPException(401, 'Credencial interna requerida')
        claims = decode_token(credentials.credentials, 'credimarket-internal')
        if claims.get('sub') != 'prestamos' or required_scope not in claims.get('scopes', []):
            raise HTTPException(403, 'Servicio o alcance no autorizado')
        return claims
    return dependency


internal_claims = require_internal('clientes:read')
cotizar_claims = require_internal('productos:cotizar')
reservas_read_claims = require_internal('reservas:read')

