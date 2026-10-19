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
