"""Reproduce train/validation runs in a fresh local MLflow, preserving frozen v1.

Original test metrics are imported with explicit provenance, never reevaluated.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import joblib
import mlflow
import numpy as np
from .contract import FEATURES, TARGET_COLUMN, get_candidate_specifications, build_candidate_pipeline, normalize_features_df, sha256_file
from .phase11 import split
from .train_and_select import compute_classification_metrics, compute_calibration_data, optimize_threshold_on_validation
from .export_and_promote import atomic_json, validate_model_package

ROOT = Path(__file__).resolve().parents[2]


def main():
    source_path = ROOT / 'ml/reports/model_selection_report.json'
    original = json.loads(source_path.read_text())
    candidate = json.loads((ROOT / 'ml/manifests/candidate_v1.json').read_text())
    artifact = ROOT / candidate['artifact_path']
    validate_model_package(candidate, artifact)
    train, val = split('train'), split('val')
    x_train, x_val = normalize_features_df(train, FEATURES), normalize_features_df(val, FEATURES)
    y_train, y_val = train[TARGET_COLUMN].to_numpy(), val[TARGET_COLUMN].to_numpy()
    mlflow.set_tracking_uri(os.getenv('MLFLOW_TRACKING_URI', 'http://mlflow:5000'))
    mlflow.set_experiment('credimarket-riesgo-v1')
    mapping = {'created_at': datetime.now(timezone.utc).isoformat(), 'source_report_sha256': sha256_file(source_path),
        'frozen_artifact_sha256': sha256_file(artifact), 'runs': {},
        'scope': 'Actual train/validation reproduction; test metrics imported from original report, not recomputed'}
    prior = {row['run_name']: row for row in original['runs']}
    for spec in get_candidate_specifications():
        old = prior[spec['run_name']]
        pipe = build_candidate_pipeline(spec)
        with mlflow.start_run(run_name='reproduced_' + spec['run_name']) as run:
            selected = old['run_id'] == candidate['run_id']
            mlflow.set_tags({'source_run_id': old['run_id'], 'phase': '12', 'reproduction': 'true',
                'selected_candidate': str(selected).lower(), 'test_metrics_origin': 'original_frozen_report'})
            mlflow.log_params({'algorithm': spec['algorithm'], 'source_run_id': old['run_id'],
                               'test_set_read': False, **spec['params']})
            pipe.fit(x_train, y_train)
            train_probs, val_probs = pipe.predict_proba(x_train)[:, 1], pipe.predict_proba(x_val)[:, 1]
            metrics = {}
            for name, labels, probs in [('train', y_train, train_probs), ('val', y_val, val_probs)]:
                actual = compute_classification_metrics(labels, probs)
                for metric in ('average_precision', 'roc_auc', 'brier_score'):
                    assert abs(actual[metric] - old[name + '_metrics'][metric]) <= 1e-6
                metrics.update({name + '_' + k: v for k, v in actual.items() if isinstance(v, (int, float))})
            mlflow.log_metrics(metrics)
            mlflow.log_dict(compute_classification_metrics(y_val, val_probs)['confusion_matrix'], 'confusion_matrix_val.json')
            mlflow.log_dict(compute_calibration_data(y_val, val_probs), 'calibration_curve_val.json')
            with tempfile.TemporaryDirectory() as temporary:
                saved = Path(temporary) / 'reproduced_pipeline.joblib'
                joblib.dump(pipe, saved)
                mlflow.log_artifact(str(saved))
            if selected:
                frozen = joblib.load(artifact)
                assert np.max(np.abs(frozen.predict_proba(x_val)[:, 1] - val_probs)) <= 1e-12
                mlflow.log_artifact(str(artifact))
                mlflow.log_dict(optimize_threshold_on_validation(y_val, val_probs), 'threshold_cost_curve.json')
                mlflow.log_dict({'origin': 'Original frozen evaluation; no test reevaluation in phase 12',
                    'source_report_sha256': mapping['source_report_sha256'],
                    'evaluation': original['final_test_evaluation']}, 'test_evaluation.json')
                mlflow.log_metrics({'imported_test_' + key: value for key, value in
                    original['final_test_evaluation']['metrics_at_optimal_threshold'].items()
                    if isinstance(value, (int, float))})
            mapping['runs'][old['run_id']] = run.info.run_id
    atomic_json(ROOT / 'ml/manifests/mlflow_reproduction.json', mapping)
    print(json.dumps(mapping))


if __name__ == '__main__':
    main()
