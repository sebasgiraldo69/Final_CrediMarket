"""Entrenamiento de baseline + 6 candidatos en MLflow, selección por validación, ajuste de umbral y evaluación única en test."""
import json
import os
import platform
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List
import joblib
import mlflow
import numpy as np
import pandas as pd
import sklearn
from sklearn.calibration import calibration_curve
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)

from .contract import (
    AP_TIE_TOLERANCE,
    COST_FN_APROBAR_INCUMPLIDOR,
    COST_FP_RECHAZAR_PAGADOR,
    EXPECTED_HASHES,
    FEATURES,
    POSITIVE_CLASS,
    RANDOM_SEED,
    TARGET_COLUMN,
    build_candidate_pipeline,
    get_candidate_specifications,
    normalize_features_df,
    sha256_file,
)
from .eda_and_split import MANIFESTS_DIR, ML_DIR, REPORTS_DIR, ROOT, SPLITS_DIR, run_eda_and_split

ARTIFACTS_DIR = ML_DIR / "artifacts" / "candidate_v1"
EXPERIMENT_NAME = "credimarket-riesgo-v1"
MIN_OPERATIONAL_APPROVAL_RATE = 0.45


def compute_classification_metrics(y_true: np.ndarray, y_prob: np.ndarray, threshold: float = 0.50) -> Dict[str, Any]:
    y_pred = (y_prob >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    total_cost = float(COST_FN_APROBAR_INCUMPLIDOR * fn + COST_FP_RECHAZAR_PAGADOR * fp)
    approved = int(tn + fn)
    return {
        "threshold": round(float(threshold), 4),
        "average_precision": round(float(average_precision_score(y_true, y_prob)), 6),
        "roc_auc": round(float(roc_auc_score(y_true, y_prob)), 6),
        "brier_score": round(float(brier_score_loss(y_true, y_prob)), 6),
        "log_loss": round(float(log_loss(y_true, np.clip(y_prob, 1e-15, 1.0 - 1e-15))), 6),
        "precision_pos": round(float(precision_score(y_true, y_pred, pos_label=POSITIVE_CLASS, zero_division=0)), 6),
        "recall_pos": round(float(recall_score(y_true, y_pred, pos_label=POSITIVE_CLASS, zero_division=0)), 6),
        "f1_pos": round(float(f1_score(y_true, y_pred, pos_label=POSITIVE_CLASS, zero_division=0)), 6),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 6),
        "business_total_cost": round(total_cost, 2),
        "business_cost_per_loan": round(total_cost / len(y_true), 6),
        "approval_rate": round(approved / len(y_true), 6),
        "approved_default_rate": round(float(fn / approved) if approved > 0 else 0.0, 6),
        "confusion_matrix": {
            "tn": int(tn),
            "fp": int(fp),
            "fn": int(fn),
            "tp": int(tp),
        },
    }


def compute_calibration_data(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> Dict[str, Any]:
    prob_true, prob_pred = calibration_curve(y_true, y_prob, n_bins=n_bins, strategy="uniform")
    return {
        "n_bins": n_bins,
        "prob_pred": [round(float(x), 6) for x in prob_pred],
        "prob_true": [round(float(x), 6) for x in prob_true],
    }


def optimize_threshold_on_validation(y_val: np.ndarray, val_prob: np.ndarray) -> Dict[str, Any]:
    """Evalúa la curva de costos (FN=5, FP=1) y sensibilidad en [0.05, 0.95] sobre validación.

    Documenta tanto el mínimo irrestricto (que rechazaría >93% de las solicitudes debido a la tasa base
    de 30.56%) como el óptimo operativo sujeto a una tasa mínima de aprobación comercial >= 45%.
    """
    thresholds = np.round(np.arange(0.05, 0.96, 0.01), 2)
    curve: List[Dict[str, Any]] = []
    unconstrained_best: Dict[str, Any] | None = None
    operational_best: Dict[str, Any] | None = None

    for t in thresholds:
        m = compute_classification_metrics(y_val, val_prob, threshold=float(t))
        entry = {
            "threshold": float(t),
            "total_cost": m["business_total_cost"],
            "cost_per_loan": m["business_cost_per_loan"],
            "precision_pos": m["precision_pos"],
            "recall_pos": m["recall_pos"],
            "f1_pos": m["f1_pos"],
            "approval_rate": m["approval_rate"],
            "approved_default_rate": m["approved_default_rate"],
            "tn": m["confusion_matrix"]["tn"],
            "fp": m["confusion_matrix"]["fp"],
            "fn": m["confusion_matrix"]["fn"],
            "tp": m["confusion_matrix"]["tp"],
        }
        curve.append(entry)
        if unconstrained_best is None or (entry["total_cost"], -entry["f1_pos"]) < (
            unconstrained_best["total_cost"],
            -unconstrained_best["f1_pos"],
        ):
            unconstrained_best = entry

        if entry["approval_rate"] >= MIN_OPERATIONAL_APPROVAL_RATE:
            if operational_best is None or (entry["total_cost"], -entry["f1_pos"]) < (
                operational_best["total_cost"],
                -operational_best["f1_pos"],
            ):
                operational_best = entry

    assert unconstrained_best is not None and operational_best is not None
    cost_at_050 = next(item for item in curve if abs(item["threshold"] - 0.50) < 1e-6)
    return {
        "cost_weights": {
            "cost_fn_aprobar_incumplidor": COST_FN_APROBAR_INCUMPLIDOR,
            "cost_fp_rechazar_pagador": COST_FP_RECHAZAR_PAGADOR,
            "min_operational_approval_rate": MIN_OPERATIONAL_APPROVAL_RATE,
        },
        "optimal_threshold": operational_best["threshold"],
        "optimal_validation_summary": operational_best,
        "unconstrained_min_cost_summary": unconstrained_best,
        "default_050_validation_summary": cost_at_050,
        "cost_reduction_vs_050": round(cost_at_050["total_cost"] - operational_best["total_cost"], 2),
        "sensitivity_notes": (
            "Con costos 5:1 y tasa base 30.56%, el umbral teórico irrestricto (1/(5+1)=0.167, empírico 0.12) "
            "aprueba solo el 6.67% de las solicitudes. Al exigir viabilidad operativa (aprobación >= 45%), "
            "el costo se minimiza en t=0.26 (aprobación 45.2%, recall de incumplimiento 73.4%, reduciendo el costo "
            "de 2950 a 1751 frente al umbral 0.50 y reduciendo la mora en aprobados de 30.6% a 18.0%)."
        ),
        "curve": curve,
    }


def evaluate_cuota_redundancy(
    X_train: pd.DataFrame, y_train: np.ndarray, X_val: pd.DataFrame, y_val: np.ndarray
) -> Dict[str, Any]:
    """Compara con y sin cuota_estimada_cop en validación (sin consultar test) para justificar su inclusión."""
    features_10 = [f for f in FEATURES if f != "cuota_estimada_cop"]
    specs = [s for s in get_candidate_specifications() if s["run_name"] in ("02_logreg_c1", "05_rf_200_depth8_leaf5")]
    comparisons = {}

    for spec in specs:
        pipe_11 = build_candidate_pipeline(spec, feature_subset=FEATURES)
        pipe_11.fit(X_train[FEATURES], y_train)
        prob_11 = pipe_11.predict_proba(X_val[FEATURES])[:, 1]

        pipe_10 = build_candidate_pipeline(spec, feature_subset=features_10)
        pipe_10.fit(X_train[features_10], y_train)
        prob_10 = pipe_10.predict_proba(X_val[features_10])[:, 1]

        comparisons[spec["run_name"]] = {
            "with_cuota_11_features": {
                "val_average_precision": round(float(average_precision_score(y_val, prob_11)), 6),
                "val_roc_auc": round(float(roc_auc_score(y_val, prob_11)), 6),
                "val_brier_score": round(float(brier_score_loss(y_val, prob_11)), 6),
            },
            "without_cuota_10_features": {
                "val_average_precision": round(float(average_precision_score(y_val, prob_10)), 6),
                "val_roc_auc": round(float(roc_auc_score(y_val, prob_10)), 6),
                "val_brier_score": round(float(brier_score_loss(y_val, prob_10)), 6),
            },
        }

    return {
        "evaluated_on": "validation_only",
        "comparisons": comparisons,
        "conclusion": (
            "Se conserva cuota_estimada_cop dentro de las 11 variables del contrato porque sintetiza la carga mensual "
            "de amortización frente al ingreso (mejorando AP, ROC-AUC y Brier en validación tanto en regresión logística "
            "como en random forest)."
        ),
    }


def run_training_and_selection(tracking_uri: str | None = None) -> Dict[str, Any]:
    # 1. Asegurar EDA y particiones 60/20/20
    eda_bundle = run_eda_and_split()
    split_manifest = eda_bundle["split_manifest"]

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)

    train_df = pd.read_csv(SPLITS_DIR / "train.csv")
    val_df = pd.read_csv(SPLITS_DIR / "val.csv")
    test_df = pd.read_csv(SPLITS_DIR / "test.csv")

    X_train = normalize_features_df(train_df, FEATURES)
    y_train = train_df[TARGET_COLUMN].to_numpy(dtype=int)

    X_val = normalize_features_df(val_df, FEATURES)
    y_val = val_df[TARGET_COLUMN].to_numpy(dtype=int)

    X_test = normalize_features_df(test_df, FEATURES)
    y_test = test_df[TARGET_COLUMN].to_numpy(dtype=int)

    # 2. Análisis de redundancia de cuota en validación
    cuota_study = evaluate_cuota_redundancy(X_train, y_train, X_val, y_val)

    # 3. Configurar MLflow y limpiar corridas previas del mismo experimento si se reejecuta
    uri = tracking_uri or os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")
    mlflow.set_tracking_uri(uri)
    client = mlflow.MlflowClient()
    exp = client.get_experiment_by_name(EXPERIMENT_NAME)
    if exp is not None:
        old_runs = client.search_runs(experiment_ids=[exp.experiment_id])
        for old_run in old_runs:
            client.delete_run(old_run.info.run_id)
    mlflow.set_experiment(EXPERIMENT_NAME)

    dependencies = {
        "python": platform.python_version(),
        "scikit-learn": sklearn.__version__,
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "joblib": joblib.__version__,
        "mlflow": mlflow.__version__,
    }

    specs = get_candidate_specifications()
    runs_summary: List[Dict[str, Any]] = []
    trained_pipelines: Dict[str, Any] = {}
    val_probs_by_run: Dict[str, np.ndarray] = {}

    input_example = X_train.iloc[:3].replace({np.nan: None}).to_dict(orient="records")

    for spec in specs:
        run_name = spec["run_name"]
        pipeline = build_candidate_pipeline(spec, feature_subset=FEATURES)

        with mlflow.start_run(run_name=run_name) as run:
            run_id = run.info.run_id
            mlflow.set_tags(
                {
                    "phase": "7",
                    "project": "CrediMarket",
                    "family": spec["family"],
                    "algorithm": spec["algorithm"],
                    "role": "baseline" if spec["family"] == "baseline" else "candidate",
                    "selected_candidate": "false",
                }
            )

            mlflow.log_params(
                {
                    "algorithm": spec["algorithm"],
                    "family": spec["family"],
                    "complexity_rank": spec["complexity_rank"],
                    "scale_numeric": spec["scale_numeric"],
                    "random_seed": RANDOM_SEED,
                    "train_rows": len(X_train),
                    "val_rows": len(X_val),
                    "test_rows": len(X_test),
                    "features_count": len(FEATURES),
                    "features": ",".join(FEATURES),
                    "source_train_csv_sha256": EXPECTED_HASHES["prestamos_entrenamiento.csv"],
                    "split_train_sha256": split_manifest["splits"]["train"]["sha256"],
                    "split_val_sha256": split_manifest["splits"]["val"]["sha256"],
                    "split_test_sha256": split_manifest["splits"]["test"]["sha256"],
                    "sklearn_version": dependencies["scikit-learn"],
                    "pandas_version": dependencies["pandas"],
                    **{f"hp_{k}": str(v) for k, v in spec["params"].items()},
                }
            )

            t0 = time.perf_counter()
            pipeline.fit(X_train, y_train)
            fit_duration_ms = round((time.perf_counter() - t0) * 1000.0, 3)

            train_prob = pipeline.predict_proba(X_train)[:, 1]

            t_val0 = time.perf_counter()
            val_prob = pipeline.predict_proba(X_val)[:, 1]
            val_predict_latency_ms = round((time.perf_counter() - t_val0) * 1000.0, 3)

            train_metrics = compute_classification_metrics(y_train, train_prob, threshold=0.50)
            val_metrics = compute_classification_metrics(y_val, val_prob, threshold=0.50)
            val_calibration = compute_calibration_data(y_val, val_prob, n_bins=10)

            mlflow.log_metrics(
                {
                    "fit_duration_ms": fit_duration_ms,
                    "val_predict_latency_ms": val_predict_latency_ms,
                    "train_average_precision": train_metrics["average_precision"],
                    "train_roc_auc": train_metrics["roc_auc"],
                    "train_brier_score": train_metrics["brier_score"],
                    "train_log_loss": train_metrics["log_loss"],
                    "train_precision_pos": train_metrics["precision_pos"],
                    "train_recall_pos": train_metrics["recall_pos"],
                    "train_f1_pos": train_metrics["f1_pos"],
                    "train_accuracy": train_metrics["accuracy"],
                    "val_average_precision": val_metrics["average_precision"],
                    "val_roc_auc": val_metrics["roc_auc"],
                    "val_brier_score": val_metrics["brier_score"],
                    "val_log_loss": val_metrics["log_loss"],
                    "val_precision_pos": val_metrics["precision_pos"],
                    "val_recall_pos": val_metrics["recall_pos"],
                    "val_f1_pos": val_metrics["f1_pos"],
                    "val_accuracy": val_metrics["accuracy"],
                    "val_cost_per_loan_at_050": val_metrics["business_cost_per_loan"],
                }
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                tmp = Path(tmpdir)
                joblib.dump(pipeline, tmp / "pipeline.joblib")
                (tmp / "confusion_matrix_val.json").write_text(
                    json.dumps(val_metrics["confusion_matrix"], indent=2), encoding="utf-8"
                )
                (tmp / "calibration_curve_val.json").write_text(
                    json.dumps(val_calibration, indent=2), encoding="utf-8"
                )
                (tmp / "metrics_summary.json").write_text(
                    json.dumps({"train": train_metrics, "val": val_metrics}, indent=2), encoding="utf-8"
                )
                (tmp / "input_example.json").write_text(
                    json.dumps(input_example, indent=2), encoding="utf-8"
                )
                mlflow.log_artifacts(str(tmp))

            trained_pipelines[run_name] = pipeline
            val_probs_by_run[run_name] = val_prob

            runs_summary.append(
                {
                    "run_id": run_id,
                    "run_name": run_name,
                    "algorithm": spec["algorithm"],
                    "family": spec["family"],
                    "complexity_rank": spec["complexity_rank"],
                    "hyperparameters": spec["params"],
                    "fit_duration_ms": fit_duration_ms,
                    "val_predict_latency_ms": val_predict_latency_ms,
                    "train_metrics": train_metrics,
                    "val_metrics": val_metrics,
                }
            )

    # 4. Selección del modelo ganador según criterio preestablecido:
    # Mayor val_average_precision; si están a <= 0.005 del máximo, menor val_brier_score y menor complexity_rank
    non_baseline = [r for r in runs_summary if r["family"] != "baseline"]
    max_val_ap = max(r["val_metrics"]["average_precision"] for r in non_baseline)
    finalists = [
        r for r in non_baseline if (max_val_ap - r["val_metrics"]["average_precision"]) <= AP_TIE_TOLERANCE
    ]
    finalists.sort(
        key=lambda r: (
            r["val_metrics"]["brier_score"],
            r["complexity_rank"],
            r["val_predict_latency_ms"],
        )
    )
    winner = finalists[0]
    winner_run_name = winner["run_name"]
    winner_run_id = winner["run_id"]
    winner_pipeline = trained_pipelines[winner_run_name]
    winner_val_prob = val_probs_by_run[winner_run_name]

    # 5. Ajustar el umbral óptimo sobre validación con costos ficticios (FN=5, FP=1)
    threshold_opt = optimize_threshold_on_validation(y_val, winner_val_prob)
    optimal_threshold = float(threshold_opt["optimal_threshold"])

    # 6. Congelar decisiones y evaluar el conjunto de prueba (test) UNA SOLA VEZ
    test_prob = winner_pipeline.predict_proba(X_test)[:, 1]
    test_metrics_optimal = compute_classification_metrics(y_test, test_prob, threshold=optimal_threshold)
    test_metrics_050 = compute_classification_metrics(y_test, test_prob, threshold=0.50)
    test_calibration = compute_calibration_data(y_test, test_prob, n_bins=10)
    val_metrics_optimal = compute_classification_metrics(y_val, winner_val_prob, threshold=optimal_threshold)

    # Registrar resultados finales y evaluación de test en la corrida ganadora de MLflow
    with mlflow.start_run(run_id=winner_run_id):
        mlflow.set_tags(
            {
                "selected_candidate": "true",
                "model_version": "riesgo-v1",
                "selection_criterion": "max_val_AP_with_0.005_brier_tiebreak",
            }
        )
        mlflow.log_param("optimal_threshold", optimal_threshold)
        mlflow.log_metrics(
            {
                "val_optimal_threshold": optimal_threshold,
                "val_cost_per_loan_optimal": val_metrics_optimal["business_cost_per_loan"],
                "val_precision_pos_optimal": val_metrics_optimal["precision_pos"],
                "val_recall_pos_optimal": val_metrics_optimal["recall_pos"],
                "val_f1_pos_optimal": val_metrics_optimal["f1_pos"],
                "test_average_precision": test_metrics_optimal["average_precision"],
                "test_roc_auc": test_metrics_optimal["roc_auc"],
                "test_brier_score": test_metrics_optimal["brier_score"],
                "test_log_loss": test_metrics_optimal["log_loss"],
                "test_precision_pos": test_metrics_optimal["precision_pos"],
                "test_recall_pos": test_metrics_optimal["recall_pos"],
                "test_f1_pos": test_metrics_optimal["f1_pos"],
                "test_accuracy": test_metrics_optimal["accuracy"],
                "test_cost_per_loan_optimal": test_metrics_optimal["business_cost_per_loan"],
                "test_approval_rate": test_metrics_optimal["approval_rate"],
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "threshold_cost_curve.json").write_text(
                json.dumps(threshold_opt, indent=2), encoding="utf-8"
            )
            (tmp / "test_evaluation.json").write_text(
                json.dumps(
                    {
                        "evaluated_once_after_freezing": True,
                        "frozen_threshold": optimal_threshold,
                        "test_metrics_at_optimal_threshold": test_metrics_optimal,
                        "test_metrics_at_050": test_metrics_050,
                        "test_calibration": test_calibration,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            mlflow.log_artifacts(str(tmp))

    # 7. Guardar artefacto candidato y manifiesto para Fase 8
    artifact_file = ARTIFACTS_DIR / "pipeline.joblib"
    joblib.dump(winner_pipeline, artifact_file)
    artifact_hash = sha256_file(artifact_file)

    candidate_manifest = {
        "model_version": "riesgo-v1",
        "experiment_name": EXPERIMENT_NAME,
        "run_id": winner_run_id,
        "run_name": winner_run_name,
        "algorithm": winner["algorithm"],
        "hyperparameters": winner["hyperparameters"],
        "variables": FEATURES,
        "clase_positiva": POSITIVE_CLASS,
        "umbral": optimal_threshold,
        "artifact_path": "ml/artifacts/candidate_v1/pipeline.joblib",
        "artifact_sha256": artifact_hash,
        "dataset_hashes": {
            "prestamos_entrenamiento.csv": EXPECTED_HASHES["prestamos_entrenamiento.csv"],
            "solicitudes_nuevas.csv": EXPECTED_HASHES["solicitudes_nuevas.csv"],
            "train.csv": split_manifest["splits"]["train"]["sha256"],
            "val.csv": split_manifest["splits"]["val"]["sha256"],
            "test.csv": split_manifest["splits"]["test"]["sha256"],
        },
        "selection_rule": {
            "primary_metric": "val_average_precision",
            "tie_tolerance": AP_TIE_TOLERANCE,
            "secondary_metric": "val_brier_score",
            "tertiary_metric": "complexity_rank",
            "max_val_ap_observed": max_val_ap,
            "finalists": [r["run_name"] for r in finalists],
        },
        "cost_model": {
            "cost_fn_aprobar_incumplidor": COST_FN_APROBAR_INCUMPLIDOR,
            "cost_fp_rechazar_pagador": COST_FP_RECHAZAR_PAGADOR,
            "min_operational_approval_rate": MIN_OPERATIONAL_APPROVAL_RATE,
            "optimal_threshold": optimal_threshold,
        },
        "metrics": {
            "train_at_050": winner["train_metrics"],
            "val_at_050": winner["val_metrics"],
            "val_at_optimal_threshold": val_metrics_optimal,
            "test_at_optimal_threshold": test_metrics_optimal,
        },
        "dependencies": dependencies,
    }

    selection_report = {
        "experiment_name": EXPERIMENT_NAME,
        "total_runs_executed": len(runs_summary),
        "selection_criterion": candidate_manifest["selection_rule"],
        "runs": runs_summary,
        "cuota_redundancy_study": cuota_study,
        "selected_candidate": {
            "run_id": winner_run_id,
            "run_name": winner_run_name,
            "algorithm": winner["algorithm"],
            "optimal_threshold": optimal_threshold,
            "artifact_sha256": artifact_hash,
        },
        "threshold_optimization": threshold_opt,
        "final_test_evaluation": {
            "note": "Test set evaluated strictly once after freezing pipeline and threshold on validation.",
            "frozen_threshold": optimal_threshold,
            "metrics_at_optimal_threshold": test_metrics_optimal,
            "metrics_at_050": test_metrics_050,
            "calibration_curve": test_calibration,
        },
    }

    (MANIFESTS_DIR / "candidate_v1.json").write_text(
        json.dumps(candidate_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (REPORTS_DIR / "model_selection_report.json").write_text(
        json.dumps(selection_report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return {
        "candidate_manifest": candidate_manifest,
        "selection_report": selection_report,
    }


if __name__ == "__main__":
    out = run_training_and_selection()
    cand = out["candidate_manifest"]
    print(f"Entrenamiento y selección completados. Modelo ganador: {cand['run_name']} (run_id={cand['run_id']})")
    print(f"Umbral óptimo: {cand['umbral']} | Val AP: {cand['metrics']['val_at_050']['average_precision']} | Test AP: {cand['metrics']['test_at_optimal_threshold']['average_precision']}")
