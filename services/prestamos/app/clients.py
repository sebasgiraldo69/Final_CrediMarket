"""Clientes HTTP internos para comunicación entre microservicios (Fase 9)."""
import json
import os
import urllib.error
import urllib.request
from uuid import UUID

from shared.auth import issue_service_token


class ServiceCommunicationError(Exception):
    def __init__(self, service: str, status_code: int, message: str, details=None):
        super().__init__(f"Error comunicando con {service}: {status_code} - {message}")
        self.service = service
        self.status_code = status_code
        self.message = message
        self.details = details or []


def get_service_url(service_name: str, default_url: str) -> str:
    env_var = f"{service_name.upper()}_URL"
    return os.getenv(env_var, default_url).rstrip("/")


def _internal_get(service: str, url: str, scopes: list[str], correlation_id: str | None = None) -> dict | None:
    token = issue_service_token("prestamos", scopes=scopes)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if correlation_id:
        headers["X-Correlation-ID"] = str(correlation_id)

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return None
        raw_err = err.read().decode("utf-8")
        parsed = {}
        try:
            parsed = json.loads(raw_err) if raw_err else {}
        except Exception:
            pass
        msg = parsed.get("message", f"HTTP {err.code}")
        details = parsed.get("details", [])
        raise ServiceCommunicationError(service, err.code, msg, details)
    except urllib.error.URLError as err:
        raise ServiceCommunicationError(service, 503, f"Servicio {service} no disponible ({err.reason})")


def fetch_product_quote(product_id: UUID, correlation_id: str | None = None) -> dict | None:
    base = get_service_url("productos", "http://productos:8000")
    url = f"{base}/interno/productos/{product_id}/cotizacion"
    return _internal_get("productos", url, ["productos:cotizar"], correlation_id)


def fetch_client_profile(client_id: UUID, correlation_id: str | None = None) -> dict | None:
    base = get_service_url("clientes", "http://clientes:8000")
    url = f"{base}/interno/clientes/{client_id}"
    return _internal_get("clientes", url, ["clientes:read"], correlation_id)


def fetch_inventory_reservation(prestamo_id: UUID, correlation_id: str | None = None) -> dict | None:
    base = get_service_url("inventario", "http://inventario:8000")
    url = f"{base}/interno/reservas/por-prestamo/{prestamo_id}"
    return _internal_get("inventario", url, ["reservas:read"], correlation_id)
