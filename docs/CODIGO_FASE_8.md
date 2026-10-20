# Código de Fase 8 para estudiar

Este documento reúne el código fuente implementado en la **Fase 8: Exportar y servir el modelo desde Préstamos**.

---

## 1. Registro del modelo, integridad SHA-256 e inferencia (`services/prestamos/app/model_service.py`)

Carga el modelo promovido en `models/active_model.json` una sola vez al iniciar el servicio, verifica su hash SHA-256, el contrato de 11 variables y la compatibilidad de versión de `scikit-learn`, y ejecuta inferencias en memoria registrando telemetría estructurada sin datos financieros sensibles.

```python
class ModelRegistry:
    """Gestiona el modelo activo promovido en models/active_model.json cargado al iniciar el proceso."""

    def __init__(self, models_root: Path | None = None) -> None:
        default_dir = Path(os.environ.get("MODELS_DIR", "/app/models"))
        if not default_dir.exists():
            fallback = Path(__file__).resolve().parents[3] / "models"
            if fallback.exists():
                default_dir = fallback
        self.models_root = models_root or default_dir
        self._pipeline: Any = None
        self._manifest: Dict[str, Any] | None = None
        self._active_config: Dict[str, Any] | None = None
        self._artifact_path: Path | None = None
        self._ready: bool = False
        self._error: str | None = "NOT_LOADED"

    def load(self) -> None:
        """Carga y valida el pipeline promovido en models/active_model.json."""
        active_file = self.models_root / "active_model.json"
        if not active_file.exists():
            self._error = f"Archivo de promoción {active_file} no encontrado"
            raise ModelUnavailableError(self._error)

        active_cfg = json.loads(active_file.read_text(encoding="utf-8"))
        manifest_path = self._resolve_model_path(active_cfg["manifest_path"])
        artifact_path = self._resolve_model_path(active_cfg["artifact_path"])

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        # 1. Verificar integridad SHA-256
        actual_sha = _sha256_file(artifact_path)
        expected_sha = manifest.get("artifact_sha256")
        if actual_sha != expected_sha or active_cfg.get("artifact_sha256") != expected_sha:
            self._error = "El hash SHA-256 del artefacto no coincide con el manifiesto o active_model.json"
            raise ModelUnavailableError(self._error)

        # 2. Verificar contrato de variables, clase positiva y umbral
        if manifest.get("variables") != EXPECTED_FEATURES:
            raise ModelUnavailableError("Contrato de variables incompatible")
```

---

## 2. Validación relacional y semántica de `Features` (`services/prestamos/app/schemas.py`)

Garantiza que el endpoint técnico `/riesgo/predict` rechace con `HTTP 422` cualquier incumplimiento del contrato de datos, incluyendo cuotas que no correspondan a la fórmula de anualidad con tasa mensual fija de `1.8%` (`±0.01 COP`) o inconsistencias entre `creditos_previos` y `porcentaje_pago_puntual`.

```python
    @model_validator(mode="after")
    def validate_relational_rules(self) -> "Features":
        if self.creditos_previos == 0 and self.porcentaje_pago_puntual is not None:
            raise ValueError("porcentaje_pago_puntual debe ser null cuando creditos_previos == 0")
        if self.creditos_previos > 0 and self.porcentaje_pago_puntual is None:
            raise ValueError("porcentaje_pago_puntual es obligatorio cuando creditos_previos > 0")

        cuota_esperada = calcular_cuota_anualidad(self.monto_solicitado_cop, self.plazo_meses)
        cuota_recibida = Decimal(str(round(self.cuota_estimada_cop, 4)))
        if abs(cuota_recibida - cuota_esperada) > Decimal("0.01"):
            raise ValueError(
                f"cuota_estimada_cop ({self.cuota_estimada_cop:.2f}) no coincide con la fórmula de anualidad "
                f"a tasa fija 0.018 ({cuota_esperada}) dentro de +/- 0.01 COP"
            )
        return self
```

---

## 3. Endpoints `/modelo/info` y `/riesgo/predict` (`services/prestamos/app/main.py`)

```python
@app.get("/modelo/info", response_model=ModeloInfo)
def informacion_modelo(
    _claims=Depends(modelo_read_claims),
    registry: ModelRegistry = Depends(get_registry),
):
    return registry.get_model_info()


@app.post("/riesgo/predict", response_model=Riesgo)
def predecir_riesgo(
    payload: Features,
    request: Request,
    _claims=Depends(riesgo_predict_claims),
    registry: ModelRegistry = Depends(get_registry),
):
    correlation_id = getattr(request.state, "correlation_id", None)
    return registry.predict_one(payload.model_dump(), correlation_id=correlation_id)
```

---

## 4. Autorización dual Admin / Servicio (`shared/auth.py`)

Permite que `/modelo/info` y `/riesgo/predict` sean invocados por un usuario con rol `administrador` (`aud = credimarket-api`) o por un token interno de servicio (`aud = credimarket-internal`) con el scope correspondiente (`modelo:read` o `riesgo:predict`).

```python
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
```
