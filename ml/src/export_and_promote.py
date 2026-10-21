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
