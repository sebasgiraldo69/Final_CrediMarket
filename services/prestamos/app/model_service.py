"""Carga única al inicio, validación de integridad SHA-256 y servicio de inferencia del modelo de riesgo."""
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import time
from typing import Any, Dict, List
import joblib
import numpy as np
import pandas as pd
import sklearn

logger = logging.getLogger("prestamos")

EXPECTED_FEATURES: List[str] = [
    "ingresos_mensuales_cop",
    "obligaciones_mensuales_cop",
    "tipo_empleo",
    "antiguedad_laboral_meses",
    "meses_historial_crediticio",
    "creditos_previos",
    "atrasos_previos_30d",
    "porcentaje_pago_puntual",
    "monto_solicitado_cop",
    "plazo_meses",
    "cuota_estimada_cop",
]


class ModelUnavailableError(RuntimeError):
    """Se lanza cuando el modelo activo no está cargado o no pasa la validación de integridad."""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_single_or_batch(records: List[Dict[str, Any]], feature_names: List[str]) -> pd.DataFrame:
    df = pd.DataFrame(records)[feature_names].copy()
    for col in feature_names:
        if col == "tipo_empleo":
            df[col] = df[col].replace({None: np.nan, "": np.nan}).astype(object)
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    return df


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

    def _resolve_model_path(self, relative_or_manifest_path: str) -> Path:
        # relative_or_manifest_path viene como "models/riesgo-v1/pipeline.joblib"
        rel = Path(relative_or_manifest_path)
        if rel.parts and rel.parts[0] == "models":
            return self.models_root / Path(*rel.parts[1:])
        return self.models_root / rel

    def load(self) -> None:
        """Carga y valida el pipeline promovido en models/active_model.json."""
        self._ready = False
        self._pipeline = None
        self._manifest = None
        self._active_config = None
        self._artifact_path = None

        active_file = self.models_root / "active_model.json"
        if not active_file.exists():
            self._error = f"Archivo de promoción {active_file} no encontrado"
            raise ModelUnavailableError(self._error)

        active_cfg = json.loads(active_file.read_text(encoding="utf-8"))
        manifest_path = self._resolve_model_path(active_cfg["manifest_path"])
        artifact_path = self._resolve_model_path(active_cfg["artifact_path"])

        if not manifest_path.exists():
            self._error = f"Manifiesto {manifest_path} no encontrado"
            raise ModelUnavailableError(self._error)
        if not artifact_path.exists():
            self._error = f"Artefacto {artifact_path} no encontrado"
            raise ModelUnavailableError(self._error)

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        # 1. Verificar integridad SHA-256
        actual_sha = _sha256_file(artifact_path)
        expected_sha = manifest.get("artifact_sha256")
        if actual_sha != expected_sha or active_cfg.get("artifact_sha256") != expected_sha:
            self._error = "El hash SHA-256 del artefacto no coincide con el manifiesto o active_model.json"
            raise ModelUnavailableError(self._error)

        # 2. Verificar contrato de variables, clase positiva y umbral
        variables = manifest.get("variables")
        if variables != EXPECTED_FEATURES:
            self._error = f"Contrato de variables incompatible: {variables}"
            raise ModelUnavailableError(self._error)

        if manifest.get("clase_positiva") != 1:
            self._error = f"clase_positiva inválida: {manifest.get('clase_positiva')}"
            raise ModelUnavailableError(self._error)

        umbral = float(manifest.get("umbral", -1.0))
        if not (0.0 <= umbral <= 1.0):
            self._error = f"Umbral fuera de rango [0, 1]: {umbral}"
            raise ModelUnavailableError(self._error)

        # 3. Verificar compatibilidad de scikit-learn (major.minor)
        req_sklearn = manifest.get("dependencies", {}).get("scikit-learn", "")
        if req_sklearn:
            if ".".join(req_sklearn.split(".")[:2]) != ".".join(sklearn.__version__.split(".")[:2]):
                self._error = (
                    f"Incompatibilidad de versión scikit-learn: artefacto={req_sklearn}, runtime={sklearn.__version__}"
                )
                raise ModelUnavailableError(self._error)

        # 4. Cargar pipeline en memoria y ejecutar warmup de inferencia
        pipeline = joblib.load(artifact_path)
        if not hasattr(pipeline, "predict_proba"):
            self._error = "El pipeline cargado no implementa predict_proba"
            raise ModelUnavailableError(self._error)

        warmup_row = {
            "ingresos_mensuales_cop": 4200000.0,
            "obligaciones_mensuales_cop": 950000.0,
            "tipo_empleo": "dependiente",
            "antiguedad_laboral_meses": 36,
            "meses_historial_crediticio": 48,
            "creditos_previos": 2,
            "atrasos_previos_30d": 0,
            "porcentaje_pago_puntual": 95.5,
            "monto_solicitado_cop": 3000000.0,
            "plazo_meses": 12,
            "cuota_estimada_cop": 280205.78,
        }
        X_warm = _normalize_single_or_batch([warmup_row], EXPECTED_FEATURES)
        warm_prob = float(pipeline.predict_proba(X_warm)[0, 1])
        if not math.isfinite(warm_prob) or not (0.0 <= warm_prob <= 1.0):
            self._error = "Fallo en prueba de calentamiento del pipeline"
            raise ModelUnavailableError(self._error)

        self._pipeline = pipeline
        self._manifest = manifest
        self._active_config = active_cfg
        self._artifact_path = artifact_path
        self._ready = True
        self._error = None

        logger.info(
            json.dumps(
                {
                    "service": "prestamos",
                    "event": "model_loaded",
                    "model_version": manifest["model_version"],
                    "run_id": manifest["run_id"],
                    "umbral": umbral,
                    "artifact_sha256": expected_sha,
                }
            )
        )

    def load_safe(self) -> bool:
        try:
            self.load()
            return True
        except Exception as exc:
            self._ready = False
            self._pipeline = None
            logger.warning(
                json.dumps(
                    {
                        "service": "prestamos",
                        "event": "model_load_failed",
                        "reason": str(exc),
                    }
                )
            )
            return False

    def is_ready(self) -> bool:
        if not self._ready or self._pipeline is None or self._manifest is None or self._artifact_path is None:
            return False
        active_file = self.models_root / "active_model.json"
        if not active_file.exists() or not self._artifact_path.exists():
            return False
        return True

    def ensure_ready(self) -> None:
        if not self.is_ready():
            raise ModelUnavailableError(self._error or "Modelo de riesgo no disponible")

    def get_model_info(self) -> Dict[str, Any]:
        self.ensure_ready()
        assert self._manifest is not None
        return {
            "model_version": str(self._manifest["model_version"]),
            "run_id": str(self._manifest["run_id"]),
            "variables": list(self._manifest["variables"]),
            "clase_positiva": 1,
            "umbral": float(self._manifest["umbral"]),
            "artifact_sha256": str(self._manifest["artifact_sha256"]),
        }

    def predict_one(self, features: Dict[str, Any], correlation_id: str | None = None) -> Dict[str, Any]:
        self.ensure_ready()
        assert self._pipeline is not None and self._manifest is not None

        t0 = time.perf_counter()
        X = _normalize_single_or_batch([features], EXPECTED_FEATURES)
        prob = float(self._pipeline.predict_proba(X)[0, 1])
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)

        umbral = float(self._manifest["umbral"])
        decision = "FAVORABLE" if prob < umbral else "DESFAVORABLE"
        model_version = str(self._manifest["model_version"])
        run_id = str(self._manifest["run_id"])

        missing_fields = [
            col
            for col in ("tipo_empleo", "antiguedad_laboral_meses", "meses_historial_crediticio", "porcentaje_pago_puntual")
            if features.get(col) is None
        ]

        # Registro estructurado MLOps sin exponer montos financieros sensibles en texto plano
        logger.info(
            json.dumps(
                {
                    "service": "prestamos",
                    "event": "risk_prediction",
                    "correlation_id": correlation_id,
                    "model_version": model_version,
                    "run_id": run_id,
                    "probabilidad_incumplimiento": round(prob, 10),
                    "umbral": umbral,
                    "decision_riesgo": decision,
                    "missing_fields_count": len(missing_fields),
                    "missing_fields": missing_fields,
                    "latency_ms": latency_ms,
                }
            )
        )

        return {
            "probabilidad_incumplimiento": prob,
            "decision_riesgo": decision,
            "umbral": umbral,
            "model_version": model_version,
            "run_id": run_id,
        }
