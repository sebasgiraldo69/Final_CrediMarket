"""Inferencia batch sobre solicitudes_nuevas.csv (200 filas sin etiqueta) usando el modelo promovido activo."""
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict
import joblib
import numpy as np
import pandas as pd

from .contract import (
    EXPECTED_HASHES,
    FEATURES,
    normalize_features_df,
    sha256_file,
    validate_dataset,
)
from .export_and_promote import MODELS_DIR, ROOT, ML_DIR, validate_model_package

REPORTS_DIR = ML_DIR / "reports"


def run_batch_inference() -> Dict[str, Any]:
    active_file = MODELS_DIR / "active_model.json"
    if not active_file.exists():
        raise FileNotFoundError(f"No existe configuración de modelo activo: {active_file}")

    active = json.loads(active_file.read_text(encoding="utf-8"))
    manifest_path = ROOT / active["manifest_path"]
    artifact_path = ROOT / active["artifact_path"]

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_model_package(manifest, artifact_path)

    nuevas_path = ROOT / "solicitudes_nuevas.csv"
    nuevas_hash = sha256_file(nuevas_path)
    if nuevas_hash != EXPECTED_HASHES["solicitudes_nuevas.csv"]:
        raise ValueError(f"Hash inesperado en solicitudes_nuevas.csv: {nuevas_hash}")

    df = pd.read_csv(nuevas_path)
    if "incumplimiento_90d" in df.columns:
        raise ValueError("solicitudes_nuevas.csv no debe contener columna de etiqueta incumplimiento_90d")

    validate_dataset(df, is_training=False)

    pipeline = joblib.load(artifact_path)
    X_nuevas = normalize_features_df(df, FEATURES)
    probs = pipeline.predict_proba(X_nuevas)[:, 1]

    if len(probs) != 200 or not np.all(np.isfinite(probs)) or not np.all((probs >= 0.0) & (probs <= 1.0)):
        raise ValueError("Probabilidades fuera de rango o no finitas en inferencia batch")

    umbral = float(manifest["umbral"])
    model_version = str(manifest["model_version"])
    run_id = str(manifest["run_id"])

    decisions = np.where(probs < umbral, "FAVORABLE", "DESFAVORABLE")

    out_df = pd.DataFrame(
        {
            "solicitud_id": df["solicitud_id"],
            "cliente_id": df["cliente_id"],
            "probabilidad_incumplimiento": np.round(probs, 10),
            "decision_riesgo": decisions,
            "umbral": umbral,
            "model_version": model_version,
            "run_id": run_id,
        }
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    pred_csv_path = REPORTS_DIR / "solicitudes_nuevas_predictions.csv"
    out_df.to_csv(pred_csv_path, index=False)

    favorable_count = int((decisions == "FAVORABLE").sum())
    desfavorable_count = int((decisions == "DESFAVORABLE").sum())

    report = {
        "source_file": "solicitudes_nuevas.csv",
        "source_sha256": nuevas_hash,
        "predictions_file": "ml/reports/solicitudes_nuevas_predictions.csv",
        "predictions_sha256": sha256_file(pred_csv_path),
        "rows_evaluated": int(len(out_df)),
        "has_ground_truth_labels": False,
        "supervised_metrics_computed": None,
        "note": (
            "Las 200 solicitudes nuevas carecen de etiqueta incumplimiento_90d; se utilizan exclusivamente "
            "para inferencia batch y verificación de paridad offline/API (AC10), sin inventar métricas de clasificación."
        ),
        "model_version": model_version,
        "run_id": run_id,
        "artifact_sha256": manifest["artifact_sha256"],
        "umbral": umbral,
        "summary": {
            "favorable_count": favorable_count,
            "desfavorable_count": desfavorable_count,
            "favorable_rate": round(favorable_count / len(out_df), 6),
            "prob_min": round(float(np.min(probs)), 6),
            "prob_p25": round(float(np.percentile(probs, 25)), 6),
            "prob_median": round(float(np.median(probs)), 6),
            "prob_mean": round(float(np.mean(probs)), 6),
            "prob_p75": round(float(np.percentile(probs, 75)), 6),
            "prob_max": round(float(np.max(probs)), 6),
        },
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    report_path = REPORTS_DIR / "batch_inference_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


if __name__ == "__main__":
    rep = run_batch_inference()
    print(json.dumps(rep, indent=2, ensure_ascii=False))
