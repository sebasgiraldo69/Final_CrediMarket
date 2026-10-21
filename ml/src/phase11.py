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
