import os
import json
import logging
from uuid import UUID, uuid4
from typing import Optional, Dict, Any
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import func
from .models import invalidaciones_cache

logger = logging.getLogger("productos.cache")

PRODUCTO_TTL_SECONDS = 60
CACHE_KEY_PREFIX = "producto"


def _cache_key(product_id: UUID | str) -> str:
    return f"{CACHE_KEY_PREFIX}:{product_id}"


def get_redis_client() -> Redis:
    return Redis(
        host=os.environ.get("REDIS_HOST", "redis"),
        port=int(os.environ.get("REDIS_PORT", 6379)),
        password=os.environ.get("REDIS_PASSWORD"),
        socket_connect_timeout=0.2,
        socket_timeout=0.2,
        decode_responses=True
    )


def get_cached_product(product_id: UUID | str) -> Optional[Dict[str, Any]]:
    """Obtiene un producto de Redis (Cache-Aside). Devuelve None si es cache miss o ante caída de Redis."""
    try:
        with get_redis_client() as client:
            raw = client.get(_cache_key(product_id))
            if raw:
                return json.loads(raw)
            return None
    except (RedisError, OSError) as exc:
        logger.warning(f"Error consultando Redis para producto {product_id} (fallback a PostgreSQL): {exc}")
        return None


def set_cached_product(product_id: UUID | str, product_data: Dict[str, Any], ttl: int = PRODUCTO_TTL_SECONDS) -> None:
    """Guarda un producto serializado en Redis con TTL documentado."""
    try:
        with get_redis_client() as client:
            client.set(_cache_key(product_id), json.dumps(product_data), ex=ttl)
    except (RedisError, OSError) as exc:
        logger.warning(f"Error guardando en Redis para producto {product_id}: {exc}")


def invalidate_cached_product(conn, product_id: UUID | str, version: int) -> bool:
    """Invalida la caché del producto en Redis. Si Redis falla, registra la invalidación pendiente en PostgreSQL."""
    key = _cache_key(product_id)
    try:
        with get_redis_client() as client:
            client.delete(key)
        return True
    except (RedisError, OSError) as exc:
        logger.warning(f"Fallo al invalidar Redis para {product_id}. Registrando en PostgreSQL para reintento: {exc}")
        try:
            conn.execute(invalidaciones_cache.insert().values(
                id=uuid4(),
                producto_id=UUID(str(product_id)),
                version=version,
                intentos=1,
                reintentar_en=func.now(),
                procesado=False
            ))
        except Exception as db_exc:
            logger.error(f"Error registrando invalidación fallida en base de datos: {db_exc}")
        return False
