# Codigo de la fase 11

Copia de consulta. Los archivos originales son la fuente de verdad. Ver [guia](FASE_11.md) y [verificacion](validacion-fase-11.md). El middleware HTTP de `shared/runtime.py` agrega fecha y version del modelo a los logs.

## ml/src/phase11.py

```python
"""Version 2 and simulated drift. No test-set access or automatic promotion."""
from datetime import datetime, timezone
import argparse
import json
import os
import platform
from pathlib import Path
import joblib
import mlflow
import numpy as np
import pandas as pd
import sklearn
from sklearn.linear_model import LogisticRegression
from .contract import FEATURES, TARGET_COLUMN, normalize_features_df, build_candidate_pipeline, sha256_file
from .export_and_promote import atomic_json, export_candidate_to_models, validate_model_package
from .train_and_select import compute_classification_metrics, optimize_threshold_on_validation

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / 'ml/reports'


def split(name):
    manifest = json.loads((ROOT / 'ml/manifests/split_manifest.json').read_text())
    item = manifest['splits'][name]
    path = ROOT / item['file']
    if sha256_file(path) != item['sha256']:
        raise ValueError('Split hash mismatch')
    return pd.read_csv(path)


def train_v2():
    output = ROOT / 'models/riesgo-v2/manifest.json'
    if output.exists():
        manifest = json.loads(output.read_text())
        validate_model_package(manifest, output.parent / 'pipeline.joblib')
        print('riesgo-v2 already exported; immutable version preserved')
        return
    train, val = split('train'), split('val')
    x_train = normalize_features_df(train, FEATURES)
    x_val = normalize_features_df(val, FEATURES)
    y_train, y_val = train[TARGET_COLUMN].to_numpy(), val[TARGET_COLUMN].to_numpy()
    params = dict(C=0.5, max_iter=1000, solver='lbfgs', random_state=42)
    spec = {'scale_numeric': True, 'estimator': LogisticRegression(**params)}
    pipeline = build_candidate_pipeline(spec)
    pipeline.fit(x_train, y_train)
    probabilities = pipeline.predict_proba(x_val)[:, 1]
    threshold = optimize_threshold_on_validation(y_val, probabilities)['optimal_threshold']
    metrics = compute_classification_metrics(y_val, probabilities, threshold)
    parent = json.loads((ROOT / 'models/riesgo-v1/manifest.json').read_text())
    validate_model_package(parent, ROOT / parent['artifact_path'])
    baseline = joblib.load(ROOT / parent['artifact_path'])
    baseline_metrics = compute_classification_metrics(y_val, baseline.predict_proba(x_val)[:, 1], parent['umbral'])
    folder = ROOT / 'ml/artifacts/candidate_v2'
    folder.mkdir(parents=True, exist_ok=True)
    artifact = folder / 'pipeline.joblib'
    joblib.dump(pipeline, artifact)
    mlflow.set_tracking_uri(os.getenv('MLFLOW_TRACKING_URI', 'http://mlflow:5000'))
    mlflow.set_experiment('credimarket-riesgo-v2')
    with mlflow.start_run(run_name='logreg_C05_phase11') as run:
        mlflow.log_params({**params, 'parent_version': 'riesgo-v1', 'threshold': threshold,
                           'test_set_used': False, 'variation': 'C: 1.0 -> 0.5'})
        mlflow.log_metrics({'val_' + k: v for k, v in metrics.items() if isinstance(v, (int, float))})
        comparison = {'variation': 'LogisticRegression C=0.5 instead of C=1.0; same train and validation splits',
            'selection_data': 'validation only; test remains untouched', 'parent_version': 'riesgo-v1',
            'v1_validation': baseline_metrics, 'v2_validation': metrics,
            'promotion_policy': 'Manual demonstration; no assertion that v2 outperforms v1',
            'created_at': datetime.now(timezone.utc).isoformat(), 'run_id': run.info.run_id}
        candidate = {**parent, 'model_version': 'riesgo-v2', 'experiment_name': 'credimarket-riesgo-v2',
            'run_id': run.info.run_id, 'run_name': 'logreg_C05_phase11', 'hyperparameters': params,
            'umbral': threshold, 'artifact_path': 'ml/artifacts/candidate_v2/pipeline.joblib',
            'artifact_sha256': sha256_file(artifact),
            'selection_rule': {'data': 'validation only', 'variation': 'C=0.5 fixed before evaluation',
                               'parent_version': 'riesgo-v1'},
            'cost_model': {**parent['cost_model'], 'optimal_threshold': threshold},
            'metrics': {'val_at_optimal_threshold': metrics},
            'dependencies': {'python': platform.python_version(), 'scikit-learn': sklearn.__version__,
                'numpy': np.__version__, 'pandas': pd.__version__, 'joblib': joblib.__version__, 'mlflow': mlflow.__version__}}
        atomic_json(ROOT / 'ml/manifests/candidate_v2.json', candidate)
        atomic_json(REPORTS / 'v2_comparison.json', comparison)
        mlflow.log_dict(comparison, 'v2_comparison.json')
        mlflow.log_dict(candidate, 'candidate_manifest.json')
        mlflow.log_artifact(str(artifact))
    export_candidate_to_models(ROOT / 'ml/manifests/candidate_v2.json')
    print(json.dumps({'version': 'riesgo-v2', 'run_id': candidate['run_id'], 'threshold': threshold,
                      'val_average_precision': metrics['average_precision'], 'active_changed': False}))


def proportions(values, categories):
    counts = np.array([(values == c).sum() for c in categories], dtype=float)
    # Additive smoothing makes empty bins explicit and avoids division by zero.
    return (counts + 0.5) / (counts.sum() + 0.5 * len(categories))


def psi(reference, current, categorical=False):
    if categorical:
        a = pd.Series(reference).fillna('__MISSING__').astype(str)
        b = pd.Series(current).fillna('__MISSING__').astype(str)
        categories = sorted(set(a) | set(b))
    else:
        a, b = pd.to_numeric(pd.Series(reference)), pd.to_numeric(pd.Series(current))
        cuts = np.unique(np.nanquantile(a.to_numpy(dtype=float), np.linspace(0, 1, 11)[1:-1]))
        a = np.where(a.isna(), -1, np.searchsorted(cuts, a, side='right'))
        b = np.where(b.isna(), -1, np.searchsorted(cuts, b, side='right'))
        categories = [-1, *range(len(cuts) + 1)]
    p, q = proportions(a, categories), proportions(b, categories)
    return float(np.sum((q - p) * np.log(q / p)))


def drift():
    reference = split('train')
    current = pd.read_csv(ROOT / 'solicitudes_nuevas.csv')
    simulated = current.copy()
    simulated['ingresos_mensuales_cop'] *= 0.45
    simulated['obligaciones_mensuales_cop'] *= 1.5
    simulated.loc[simulated.index % 3 == 0, 'tipo_empleo'] = None
    # No identifiers or complete financial rows are written to the monitoring report.
    manifest = json.loads((ROOT / 'models/riesgo-v1/manifest.json').read_text())
    if sha256_file(ROOT / 'solicitudes_nuevas.csv') != manifest['dataset_hashes']['solicitudes_nuevas.csv']:
        raise ValueError('Unlabeled source hash mismatch')
    validate_model_package(manifest, ROOT / manifest['artifact_path'])
    pipeline = joblib.load(ROOT / manifest['artifact_path'])
    ref_scores = pipeline.predict_proba(normalize_features_df(reference, FEATURES))[:, 1]
    batches = {}
    for name, data in [('unlabeled_current', current), ('explicitly_simulated', simulated)]:
        scores = pipeline.predict_proba(normalize_features_df(data, FEATURES))[:, 1]
        batches[name] = {'rows': len(data), 'simulated': name == 'explicitly_simulated',
            'features': {f: {'psi': psi(reference[f], data[f], f == 'tipo_empleo'),
                            'reference_missing_rate': float(reference[f].isna().mean()),
                            'current_missing_rate': float(data[f].isna().mean())} for f in FEATURES},
            'score_psi': psi(ref_scores, scores),
            'score_histogram': np.histogram(scores, bins=np.linspace(0, 1, 11))[0].tolist(),
            'mean_score': float(scores.mean())}
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'model_version': 'riesgo-v1',
        'reference': 'training split; decile bins fixed on reference', 'reference_rows': len(reference),
        'current_source': 'solicitudes_nuevas.csv (academic dataset, not a production stream)',
        'source_hashes': {'reference': sha256_file(ROOT / 'ml/data/splits/train.csv'),
                          'current': sha256_file(ROOT / 'solicitudes_nuevas.csv')},
        'reference_score_histogram': np.histogram(ref_scores, bins=np.linspace(0, 1, 11))[0].tolist(),
        'reference_mean_score': float(ref_scores.mean()),
        'psi_formula': 'sum((current-reference)*log(current/reference)); smoothing=0.5 counts; missing bin',
        'simulation': {'income_multiplier': .45, 'obligations_multiplier': 1.5,
                       'employment_missing': 'every third current row'},
        'batches': batches, 'interpretation': 'Distribution change only. No new labels: no claim of precision degradation.'}
    atomic_json(REPORTS / 'drift_report.json', report)
    print(json.dumps({'report': 'ml/reports/drift_report.json', 'simulated_score_psi': batches['explicitly_simulated']['score_psi']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['train-v2', 'drift'])
    args = parser.parse_args()
    train_v2() if args.action == 'train-v2' else drift()
```

## ml/src/export_and_promote.py

```python
"""Exportación de artefacto versionado y promoción explícita a modelo activo (models/active_model.json)."""
import argparse
from datetime import datetime, timezone
import json
import os
import re
import tempfile
import shutil
from pathlib import Path
from typing import Any, Dict
import joblib
import numpy as np
import pandas as pd
import sklearn
from uuid import uuid4

from .contract import FEATURES, POSITIVE_CLASS, normalize_features_df, sha256_file

ROOT = Path(__file__).resolve().parents[2]
ML_DIR = ROOT / "ml"
MODELS_DIR = ROOT / "models"


def checked_version(version: str) -> str:
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}', version):
        raise ValueError('Identificador de versión inválido')
    return version


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)  # Model metadata must be readable by the non-root API user.
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_model_package(manifest: Dict[str, Any], artifact_path: Path) -> None:
    """Valida integridad SHA-256, contrato de variables, umbral, compatibilidad y ejecución de prueba."""
    if not artifact_path.exists():
        raise FileNotFoundError(f"Artefacto de modelo no encontrado: {artifact_path}")

    actual_hash = sha256_file(artifact_path)
    expected_hash = manifest.get("artifact_sha256")
    if actual_hash != expected_hash:
        raise ValueError(
            f"Fallo de integridad SHA-256 en {artifact_path}: esperado={expected_hash}, actual={actual_hash}"
        )

    if manifest.get("variables") != FEATURES:
        raise ValueError(f"Las variables del manifiesto no coinciden con el contrato: {manifest.get('variables')}")

    if manifest.get("clase_positiva") != POSITIVE_CLASS:
        raise ValueError(f"clase_positiva debe ser {POSITIVE_CLASS}, recibido: {manifest.get('clase_positiva')}")

    umbral = manifest.get("umbral")
    if not isinstance(umbral, (int, float)) or not (0.0 <= float(umbral) <= 1.0):
        raise ValueError(f"Umbral fuera de rango [0, 1]: {umbral}")

    req_sklearn = manifest.get("dependencies", {}).get("scikit-learn", "")
    if req_sklearn:
        req_major_minor = ".".join(req_sklearn.split(".")[:2])
        cur_major_minor = ".".join(sklearn.__version__.split(".")[:2])
        if req_major_minor != cur_major_minor:
            raise ValueError(
                f"Incompatibilidad de scikit-learn: modelo entrenado con {req_sklearn}, runtime actual {sklearn.__version__}"
            )

    pipeline = joblib.load(artifact_path)
    if not hasattr(pipeline, "predict_proba"):
        raise ValueError("El artefacto cargado no expone predict_proba")

    # Smoke test de inferencia con una fila sintética válida del contrato
    sample_df = pd.DataFrame(
        [
            {
                "ingresos_mensuales_cop": 4200000.0,
                "obligaciones_mensuales_cop": 950000.0,
                "tipo_empleo": "dependiente",
                "antiguedad_laboral_meses": 36.0,
                "meses_historial_crediticio": 48.0,
                "creditos_previos": 2.0,
                "atrasos_previos_30d": 0.0,
                "porcentaje_pago_puntual": 95.5,
                "monto_solicitado_cop": 3000000.0,
                "plazo_meses": 12.0,
                "cuota_estimada_cop": 280205.78,
            }
        ]
    )
    X_sample = normalize_features_df(sample_df, FEATURES)
    probs = pipeline.predict_proba(X_sample)
    if probs.shape != (1, 2):
        raise ValueError(f"Forma inesperada en salida de predict_proba: {probs.shape}")
    prob_pos = float(probs[0, 1])
    if not np.isfinite(prob_pos) or not (0.0 <= prob_pos <= 1.0):
        raise ValueError(f"Probabilidad inválida en smoke test: {prob_pos}")


def export_candidate_to_models(
    candidate_manifest_path: Path | None = None,
    version_override: str | None = None,
) -> Dict[str, Any]:
    """Exporta un candidato desde ml/manifests/ y ml/artifacts/ hacia models/<model_version>/."""
    manifest_src = candidate_manifest_path or (ML_DIR / "manifests" / "candidate_v1.json")
    if not manifest_src.exists():
        raise FileNotFoundError(f"No existe manifiesto candidato: {manifest_src}")

    cand = json.loads(manifest_src.read_text(encoding="utf-8"))
    model_version = checked_version(version_override or cand["model_version"])
    artifact_src = ROOT / cand["artifact_path"]

    validate_model_package(cand, artifact_src)

    version_dir = MODELS_DIR / model_version
    if version_dir.exists():
        existing_path = version_dir / 'manifest.json'
        if not existing_path.exists():
            raise ValueError('Paquete de versión incompleto; revisar antes de exportar')
        existing = json.loads(existing_path.read_text(encoding='utf-8'))
        validate_model_package(existing, version_dir / 'pipeline.joblib')
        if (existing['artifact_sha256'] != cand['artifact_sha256'] or
                existing['run_id'] != cand['run_id'] or existing['umbral'] != cand['umbral']):
            raise ValueError('Una versión publicada es inmutable; usa otro identificador')
        return existing
    version_dir.mkdir(parents=True, exist_ok=True)

    dest_artifact = version_dir / "pipeline.joblib"
    shutil.copy2(artifact_src, dest_artifact)

    exported_manifest = {
        "model_version": model_version,
        "experiment_name": cand["experiment_name"],
        "run_id": cand["run_id"],
        "run_name": cand["run_name"],
        "algorithm": cand["algorithm"],
        "hyperparameters": cand["hyperparameters"],
        "variables": cand["variables"],
        "clase_positiva": cand["clase_positiva"],
        "umbral": float(cand["umbral"]),
        "artifact_path": f"models/{model_version}/pipeline.joblib",
        "artifact_sha256": sha256_file(dest_artifact),
        "dataset_hashes": cand["dataset_hashes"],
        "selection_rule": cand["selection_rule"],
        "cost_model": cand["cost_model"],
        "metrics": cand["metrics"],
        "dependencies": cand["dependencies"],
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    validate_model_package(exported_manifest, dest_artifact)

    dest_manifest = version_dir / "manifest.json"
    dest_manifest.write_text(json.dumps(exported_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return exported_manifest


def promote_model_version(model_version: str, action: str = 'promote', reason: str = 'Activación explícita') -> Dict[str, Any]:
    """Promueve explícitamente una versión exportada en models/<model_version>/ a models/active_model.json."""
    checked_version(model_version)
    if action not in ('promote', 'rollback'):
        raise ValueError('Operación de promoción inválida')
    version_dir = MODELS_DIR / model_version
    manifest_path = version_dir / "manifest.json"
    artifact_path = version_dir / "pipeline.joblib"

    if not manifest_path.exists() or not artifact_path.exists():
        raise FileNotFoundError(
            f"La versión '{model_version}' no está exportada en {version_dir}. "
            f"Ejecute primero la exportación del candidato."
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest['model_version'] != model_version:
        raise ValueError('La versión del manifiesto no coincide con la solicitada')
    validate_model_package(manifest, artifact_path)

    active_config = {
        "active_version": model_version,
        "model_version": manifest["model_version"],
        "run_id": manifest["run_id"],
        "run_name": manifest.get("run_name"),
        "algorithm": manifest.get("algorithm"),
        "manifest_path": f"models/{model_version}/manifest.json",
        "artifact_path": f"models/{model_version}/pipeline.joblib",
        "artifact_sha256": manifest["artifact_sha256"],
        "variables": manifest["variables"],
        "clase_positiva": manifest["clase_positiva"],
        "umbral": float(manifest["umbral"]),
        "dependencies": manifest.get("dependencies", {}),
        "promoted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    active_file = MODELS_DIR / "active_model.json"
    previous = json.loads(active_file.read_text(encoding='utf-8')) if active_file.exists() else None
    # The audit entry is a validated request; API observation proves activation after restart.
    atomic_json(MODELS_DIR / 'promotions' / f'{uuid4()}.json', {
        'record_type': 'validated_activation_request', 'action': action, 'reason': reason,
        'previous_version': previous.get('model_version') if previous else None,
        'requested_version': model_version, 'run_id': manifest['run_id'],
        'artifact_sha256': manifest['artifact_sha256'], 'requested_at': active_config['promoted_at']})
    atomic_json(active_file, active_config)
    return active_config


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exportar y promover versión de modelo de riesgo")
    parser.add_argument("--version", default="riesgo-v1", help="Versión del modelo a exportar/promover")
    parser.add_argument("--manifest", default=None, help="Ruta opcional al manifiesto candidato")
    parser.add_argument("--export-only", action="store_true", help="Solo exportar sin cambiar active_model.json")
    args = parser.parse_args()

    manifest_p = Path(args.manifest) if args.manifest else None
    if manifest_p or not (MODELS_DIR / args.version / "manifest.json").exists():
        export_candidate_to_models(candidate_manifest_path=manifest_p, version_override=args.version)

    if not args.export_only:
        active = promote_model_version(args.version)
        print(json.dumps(active, indent=2, ensure_ascii=False))
```

## services/prestamos/app/model_service.py

```python
"""Carga única al inicio, validación de integridad SHA-256 y servicio de inferencia del modelo de riesgo."""
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import time
from datetime import datetime, timezone
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


def _metricas_prueba(manifest: Dict[str, Any]) -> Dict[str, float] | None:
    """Métricas numéricas finitas del conjunto de prueba al umbral operativo, si el manifiesto las trae."""
    metrics = (manifest.get("metrics") or {}).get("test_at_optimal_threshold")
    if not isinstance(metrics, dict):
        return None
    return {
        key: float(value)
        for key, value in metrics.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
    }


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
        try:
            active = json.loads(active_file.read_text(encoding='utf-8'))
            for field in ('model_version', 'artifact_sha256', 'run_id', 'umbral'):
                if active.get(field) != self._active_config.get(field):
                    return False  # Explicit restart is required to activate another version.
        except (ValueError, OSError):
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
            # Ficha del modelo (fase 10): campos opcionales del manifiesto, nunca inventados.
            "algoritmo": self._manifest.get("algorithm"),
            "experimento": self._manifest.get("experiment_name"),
            "exportado_en": self._manifest.get("exported_at"),
            "metricas_prueba": _metricas_prueba(self._manifest),
        }

    def predict_one(self, features: Dict[str, Any], correlation_id: str | None = None) -> Dict[str, Any]:
        self.ensure_ready()
        assert self._pipeline is not None and self._manifest is not None

        t0 = time.perf_counter()
        try:
            X = _normalize_single_or_batch([features], EXPECTED_FEATURES)
            prob = float(self._pipeline.predict_proba(X)[0, 1])
            if not math.isfinite(prob) or not 0 <= prob <= 1:
                raise ValueError('Invalid model score')
        except Exception as exc:
            logger.error(json.dumps({'service': 'prestamos', 'event': 'risk_prediction_failed',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'correlation_id': correlation_id, 'model_version': self._manifest['model_version'],
                'error_type': type(exc).__name__,
                'latency_ms': round((time.perf_counter() - t0) * 1000, 3)}))
            raise
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
                    "timestamp": datetime.now(timezone.utc).isoformat(),
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
```

## scripts/promote_model.py

```python
"""Promueve explícitamente una versión de modelo a models/active_model.json y ejecuta la inferencia batch."""
import argparse
import subprocess
from pathlib import Path
import sys
import json
import time
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Promover versión de modelo activo y actualizar inferencia batch")
    parser.add_argument("--version", default="riesgo-v1", help="Versión del modelo a promover (por defecto: riesgo-v1)")
    parser.add_argument("--restart", action="store_true", help="Reiniciar el contenedor prestamos tras promover")
    parser.add_argument('--rollback', action='store_true', help='Registrar la activación como rollback')
    parser.add_argument('--reason', default='Activación explícita del operador')
    args = parser.parse_args()

    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{ROOT}:/workspace",
        "-w",
        "/workspace",
        "credimarket-mlflow",
        "python",
        "-c",
        (
            f"from ml.src.export_and_promote import export_candidate_to_models, promote_model_version, MODELS_DIR; "
            f"from ml.src.batch_inference import run_batch_inference; "
            f"import json; "
            f"ver = {args.version!r}; "
            f"assert ver == 'riesgo-v1' or (MODELS_DIR / ver / 'manifest.json').exists(), 'Primero entrenar y exportar la versión solicitada'; "
            f"export_candidate_to_models(version_override=ver) if not (MODELS_DIR / ver / 'manifest.json').exists() else None; "
            f"active = promote_model_version(ver, action={('rollback' if args.rollback else 'promote')!r}, reason={args.reason!r}); "
            f"batch = run_batch_inference(); "
            f"print(json.dumps({{'active_model': active, 'batch_summary': batch['summary']}}, indent=2))"
        ),
    ]
    res = subprocess.run(cmd, cwd=ROOT)
    if res.returncode != 0:
        sys.exit(res.returncode)

    if args.restart:
        subprocess.run(["docker", "compose", "restart", '--no-deps', "prestamos"], cwd=ROOT, check=True)
        env = dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines()
                   if '=' in line and not line.startswith('#'))
        token_result = subprocess.run(['docker', 'compose', 'exec', '-T', 'clientes', 'python', '-c',
            "from shared.auth import issue_service_token; print(issue_service_token('prestamos', ['modelo:read']))"],
            cwd=ROOT, capture_output=True, text=True, check=True)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{env.get('FRONTEND_PORT', '8080')}/api/prestamos/modelo/info",
                    headers={'Authorization': 'Bearer ' + token_result.stdout.strip()})
                with urllib.request.urlopen(req, timeout=5) as response:
                    info = json.load(response)
                if info['model_version'] == args.version:
                    print('API verificada: ' + args.version)
                    break
            except (OSError, ValueError):
                pass
            time.sleep(1)
        else:
            raise SystemExit('La API no confirmó la versión solicitada. Revisar estado y ejecutar rollback explícito.')


if __name__ == "__main__":
    main()
```

## scripts/run_phase11.py

```python
"""Operator commands for model monitoring, v2 training and explicit rollback."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['train-v2', 'drift', 'monitor', 'promote', 'rollback'])
    parser.add_argument('--version')
    parser.add_argument('--reason', default='Demostración académica fase 11')
    args = parser.parse_args()
    if args.action in ('train-v2', 'drift'):
        command = ['docker', 'run', '--rm', '--network', 'credimarket_backend',
            '--mount', f'type=bind,source={ROOT},target=/workspace', '-w', '/workspace',
            '-e', 'MLFLOW_TRACKING_URI=http://mlflow:5000', '-e', 'GIT_PYTHON_REFRESH=quiet',
            'credimarket-mlflow', 'python', '-m', 'ml.src.phase11', args.action]
    elif args.action == 'monitor':
        command = [sys.executable, str(ROOT / 'scripts/monitor_model.py')]
    else:
        version = args.version or ('riesgo-v1' if args.action == 'rollback' else 'riesgo-v2')
        command = [sys.executable, str(ROOT / 'scripts/promote_model.py'), '--version', version,
                   '--restart', '--reason', args.reason]
        if args.action == 'rollback':
            command.append('--rollback')
    raise SystemExit(subprocess.run(command, cwd=ROOT).returncode)


if __name__ == '__main__':
    main()
```

## scripts/monitor_model.py

```python
"""Aggregate retained inference logs. Never writes raw financial inputs or tokens."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * fraction
    low = int(index)
    return round(values[low] + (values[min(low + 1, len(values) - 1)] - values[low]) * (index - low), 3)


def summarize(records):
    versions = {}
    http = {'requests': 0, 'errors_4xx': 0, 'errors_5xx': 0, 'latencies_ms': []}
    for record in records:
        if record.get('path') in ('/riesgo/predict', '/prestamos'):
            http['requests'] += 1
            status = record.get('status', 0)
            http['errors_4xx'] += int(400 <= status < 500)
            http['errors_5xx'] += int(status >= 500)
            if isinstance(record.get('duration_ms'), (int, float)):
                http['latencies_ms'].append(record['duration_ms'])
        if record.get('event') not in ('risk_prediction', 'risk_prediction_failed'):
            continue
        version = record.get('model_version') or 'unknown'
        row = versions.setdefault(version, {'predictions': 0, 'inference_errors': 0,
            'favorable': 0, 'unfavorable': 0, 'missing_fields': {}, 'scores': [], 'latencies': []})
        if isinstance(record.get('latency_ms'), (int, float)):
            row['latencies'].append(record['latency_ms'])
        if record['event'] == 'risk_prediction_failed':
            row['inference_errors'] += 1
            continue
        row['predictions'] += 1
        row['favorable'] += int(record.get('decision_riesgo') == 'FAVORABLE')
        row['unfavorable'] += int(record.get('decision_riesgo') == 'DESFAVORABLE')
        score = record.get('probabilidad_incumplimiento')
        if isinstance(score, (int, float)) and math.isfinite(score) and 0 <= score <= 1:
            row['scores'].append(score)
        for field in record.get('missing_fields', []):
            row['missing_fields'][field] = row['missing_fields'].get(field, 0) + 1
    for row in versions.values():
        times, scores = row.pop('latencies'), row.pop('scores')
        row.update({'latency_p50_ms': percentile(times, .5), 'latency_p95_ms': percentile(times, .95),
                    'mean_score': sum(scores) / len(scores) if scores else None,
                    'score_histogram': [sum(min(int(p * 10), 9) == i for p in scores) for i in range(10)]})
        row['missing_rates'] = {f: n / row['predictions'] for f, n in row['missing_fields'].items()} if row['predictions'] else {}
    times = http.pop('latencies_ms')
    http.update({'latency_p50_ms': percentile(times, .5), 'latency_p95_ms': percentile(times, .95)})
    return {'versions': versions, 'http': http}


def collect(since='24h'):
    result = subprocess.run(['docker', 'compose', 'logs', '--no-color', '--no-log-prefix',
        '--since', since, 'prestamos'], cwd=ROOT, text=True, encoding='utf-8', errors='replace',
        capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError('No se pudieron consultar los logs de Préstamos')
    records = []
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            records.append(item)
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'requested_window': since,
        'scope': 'Only logs retained in the current prestamos container; recreation may truncate history',
        'records_read': len(records), **summarize(records),
        'interpretation': 'HTTP validation/authentication errors are separate from inference failures. No accuracy without labels.'}
    destination = ROOT / 'ml/reports/monitoring_report.json'
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--since', default='24h')
    print(json.dumps(collect(parser.parse_args().since), indent=2, ensure_ascii=False))
```

## scripts/check_phase11.py

```python
"""Real API v1 -> v2 -> rollback demonstration. Retains synthetic fixtures.

Restores the original active version in finally. Does not retrain or evaluate test.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request
import urllib.error
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
env = dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines()
           if '=' in line and not line.startswith('#'))
BASE = f"http://127.0.0.1:{env.get('FRONTEND_PORT', '8080')}/api/prestamos"


def docker(*args, stdin=None):
    result = subprocess.run(['docker', 'compose', *args], cwd=ROOT, input=stdin,
        text=True, encoding='utf-8', capture_output=True, timeout=90)
    if result.returncode:
        raise RuntimeError('Docker fixture operation failed (credentials suppressed)')
    return result.stdout.strip()


def inside(service, source):
    prefix = '''
import json
from uuid import UUID, uuid4
from sqlalchemy import create_engine, select
from shared.runtime import database_url
engine = create_engine(database_url(), hide_parameters=True)
'''
    return docker('exec', '-T', service, 'python', '-', stdin=prefix + source)


def api(path, body=None, token=None, key=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if key:
        headers['Idempotency-Key'] = key
    request = urllib.request.Request(BASE + path,
        data=json.dumps(body).encode() if body is not None else None, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=20)
    except urllib.error.HTTPError as exc:
        response = exc
    return response.status, json.load(response)


def activate(version, rollback=False):
    command = [sys.executable, str(ROOT / 'scripts/promote_model.py'), '--version', version,
               '--restart', '--reason', 'Prueba reproducible de fase 11']
    if rollback:
        command.append('--rollback')
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=180)
    if result.returncode:
        raise RuntimeError('Promotion failed: ' + result.stderr[-1500:])


def history():
    return json.loads(inside('prestamos', '''
from app.models import prestamos
with engine.connect() as c:
    rows=c.execute(select(prestamos.c.id, prestamos.c.model_version, prestamos.c.run_id,
        prestamos.c.probabilidad_incumplimiento, prestamos.c.umbral_riesgo)).all()
print(json.dumps({str(row[0]): [str(value) if value is not None else None for value in row[1:]] for row in rows}))
'''))


def main():
    original = json.loads((ROOT / 'models/active_model.json').read_text())
    v1_hash = hashlib.sha256((ROOT / 'models/riesgo-v1/pipeline.joblib').read_bytes()).hexdigest()
    before = history()
    product, client, account = str(uuid4()), str(uuid4()), str(uuid4())
    service_token = inside('clientes', "from shared.auth import issue_service_token; print(issue_service_token('prestamos', ['modelo:read','riesgo:predict']))")
    client_token = inside('clientes', '''
from app.models import clientes, usuarios
from app.security import hasher, issue_token
with engine.begin() as c:
    c.execute(clientes.insert().values(id=UUID(CLIENT), nombre='Prueba fase 11', finanzas={
        'ingresos_mensuales_cop': '10000000.00', 'obligaciones_mensuales_cop': '200000.00',
        'tipo_empleo': 'dependiente', 'antiguedad_laboral_meses': 60,
        'meses_historial_crediticio': 60, 'creditos_previos': 5,
        'atrasos_previos_30d': 0, 'porcentaje_pago_puntual': 100.0}))
    c.execute(usuarios.insert().values(id=UUID(ACCOUNT), cliente_id=UUID(CLIENT),
        email=ACCOUNT+'@example.com', password_hash=hasher.hash(str(uuid4())), rol='cliente'))
print(issue_token(ACCOUNT, role='cliente', cliente_id=CLIENT))
'''.replace('CLIENT', repr(client)).replace('ACCOUNT', repr(account)))
    inside('productos', '''
from app.models import productos
with engine.begin() as c:
    c.execute(productos.insert().values(id=UUID(PRODUCT), nombre='Producto prueba fase 11',
        categoria='Portátiles', precio_cop=3000000))
'''.replace('PRODUCT', repr(product)))
    inside('inventario', '''
from app.domain import agregar_stock
with engine.begin() as c:
    agregar_stock(c, UUID(PRODUCT), 3, 'Fixture fase 11')
'''.replace('PRODUCT', repr(product)))
    sample = dict(ingresos_mensuales_cop=10000000.0, obligaciones_mensuales_cop=200000.0,
        tipo_empleo='dependiente', antiguedad_laboral_meses=60, meses_historial_crediticio=60,
        creditos_previos=5, atrasos_previos_30d=0, porcentaje_pago_puntual=100.0,
        monto_solicitado_cop=3000000.0, plazo_meses=12)
    sample['cuota_estimada_cop'] = float((Decimal('3000000') * Decimal('.018') /
        (1 - Decimal('1.018') ** -12)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))
    observed = []
    loans = []
    try:
        for version, rollback in [('riesgo-v1', False), ('riesgo-v2', False), ('riesgo-v1', True)]:
            activate(version, rollback)
            status, info = api('/modelo/info', token=service_token)
            assert status == 200 and info['model_version'] == version
            status, risk = api('/riesgo/predict', sample, service_token)
            assert status == 200 and risk['model_version'] == version
            status, loan = api('/prestamos', {'producto_id': product, 'cantidad': 1, 'plazo_meses': 12},
                               client_token, str(uuid4()))
            assert status in (201, 202), (status, loan.get('message'))
            assert loan['riesgo']['model_version'] == version
            loans.append({'id': loan['id'], 'model_version': version, 'run_id': loan['riesgo']['run_id']})
            observed.append({'model_version': version, 'run_id': info['run_id'],
                'artifact_sha256': info['artifact_sha256'], 'prediction': risk,
                'loan_id': loan['id'], 'api_verified_at': datetime.now(timezone.utc).isoformat()})
            print('PASS API prediction and persisted loan: ' + version, flush=True)
        assert observed[0]['prediction'] == observed[2]['prediction'], 'Rollback prediction changed'
        assert observed[0]['artifact_sha256'] != observed[1]['artifact_sha256']
        after = history()
        assert all(after.get(identity) == value for identity, value in before.items())
        for loan in loans:
            assert after[loan['id']][:2] == [loan['model_version'], loan['run_id']]
        print('PASS historical model metadata preserved across promotion and rollback', flush=True)
        assert api('/riesgo/predict', sample)[0] == 401
        assert api('/riesgo/predict', {**sample, 'creditos_previos': 0}, service_token)[0] == 422

        # Corruption must be rejected before activation, without touching active pointer.
        active_before = (ROOT / 'models/active_model.json').read_bytes()
        bad_version = 'invalid-phase11-' + uuid4().hex[:8]
        folder = ROOT / 'models' / bad_version
        folder.mkdir()
        try:
            manifest = json.loads((ROOT / 'models/riesgo-v1/manifest.json').read_text())
            manifest['model_version'] = bad_version
            (folder / 'manifest.json').write_text(json.dumps(manifest))
            (folder / 'pipeline.joblib').write_bytes(b'corrupt-test-artifact')
            result = subprocess.run(['docker', 'run', '--rm', '--mount',
                f'type=bind,source={ROOT},target=/workspace', '-w', '/workspace', 'credimarket-mlflow',
                'python', '-c', 'from ml.src.export_and_promote import promote_model_version; promote_model_version(' + repr(bad_version) + ')'],
                cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=60)
            assert result.returncode != 0
            assert (ROOT / 'models/active_model.json').read_bytes() == active_before
        finally:
            (folder / 'pipeline.joblib').unlink()
            (folder / 'manifest.json').unlink()
            folder.rmdir()
        print('PASS corrupt artifact rejected; active pointer unchanged', flush=True)

        inside('prestamos', '''
from unittest.mock import patch, Mock
from app.model_service import ModelRegistry
registry=ModelRegistry()
registry.load()
registry._pipeline=Mock()
registry._pipeline.predict_proba.side_effect=RuntimeError('sensitive-input-do-not-log')
sample=SAMPLE
with patch('app.model_service.logger.error') as log:
    try: registry.predict_one(sample)
    except RuntimeError: pass
    else: raise AssertionError('Expected inference failure')
    payload=json.loads(log.call_args.args[0])
    assert payload['event']=='risk_prediction_failed' and payload['error_type']=='RuntimeError'
    assert 'sensitive-input' not in json.dumps(payload)
    assert not any(key in payload for key in sample)
'''.replace('SAMPLE', repr(sample)))

        from monitor_model import collect, summarize
        synthetic = summarize([{'event': 'risk_prediction_failed', 'model_version': 'fixture', 'latency_ms': 2}])
        assert synthetic['versions']['fixture']['inference_errors'] == 1
        report = collect()
        assert all(v in report['versions'] for v in ('riesgo-v1', 'riesgo-v2'))
        assert report['http']['errors_4xx'] >= 2
        for row in report['versions'].values():
            assert row['latency_p95_ms'] is not None
            assert sum(row['score_histogram']) == row['predictions']
        drift = json.loads((ROOT / 'ml/reports/drift_report.json').read_text())
        simulated = drift['batches']['explicitly_simulated']
        normal = drift['batches']['unlabeled_current']
        assert simulated['simulated'] is True and simulated['features']['ingresos_mensuales_cop']['psi'] > normal['features']['ingresos_mensuales_cop']['psi']
        assert hashlib.sha256((ROOT / 'models/riesgo-v1/pipeline.joblib').read_bytes()).hexdigest() == v1_hash
        comparison = json.loads((ROOT / 'ml/reports/v2_comparison.json').read_text())
        assert not any(key.startswith('test') for key in json.loads(
            (ROOT / 'models/riesgo-v2/manifest.json').read_text())['metrics'])
        result = {'passed': True, 'verified_at': datetime.now(timezone.utc).isoformat(),
            'observed_sequence': observed, 'historical_loans_checked': len(before),
            'historical_metadata_unchanged': True, 'v1_artifact_unchanged': True,
            'v2_run_id': comparison['run_id'], 'monitoring_versions': list(report['versions']),
            'drift_is_simulated': True, 'fixtures_retained': True}
        (ROOT / 'ml/reports/phase11_validation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print('PASS monitoring, explicit simulated drift and immutable v1 artifact', flush=True)
    finally:
        current = json.loads((ROOT / 'models/active_model.json').read_text())['model_version']
        if current != original['model_version']:
            activate(original['model_version'], rollback=True)
    print('Phase 11 verified. Original active version restored.', flush=True)


if __name__ == '__main__':
    main()
```
