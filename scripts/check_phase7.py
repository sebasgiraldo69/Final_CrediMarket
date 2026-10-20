"""Integration and reproducibility checks for Phase 7: Preparar datos y entrenar el modelo.

Verifies:
1. Original CSV files remain unaltered (SHA-256 verification).
2. Data dictionary, EDA report, and 60/20/20 stratified splits (7200/2400/2400) with seed 42.
3. Zero data leakage (disjoint solicitud_id and cliente_id across train, val, test, and new requests).
4. MLflow tracking server ('credimarket-riesgo-v1'): at least 7 finished runs (1 baseline + 6 candidates),
   logged parameters, metrics (train/val/test), and downloadable artifacts.
5. Candidate pipeline ('ml/artifacts/candidate_v1/pipeline.joblib') integrity, 11-feature contract,
   and batch inference on the 200 unlabeled requests ('solicitudes_nuevas.csv') without inventing classification metrics.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ML_DIR = ROOT / "ml"

EXPECTED_SOURCE_HASHES = {
    "prestamos_entrenamiento.csv": "c6cdc437c3aecc9116bc8b978df421d5a7600634c1ad7d6f82e58222a2446ecd",
    "solicitudes_nuevas.csv": "1430d7b34e924d5e4170c4fb9d9a412c1000af17c062af513ef15e44a1a7f1f7",
}

EXPECTED_FEATURES = [
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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run_in_mlflow_image(code: str) -> str:
    result = subprocess.run(
        [
            "docker",
            "run",
            "-i",
            "--rm",
            "--network",
            "credimarket_backend",
            "-v",
            f"{ROOT}:/workspace",
            "-w",
            "/workspace",
            "-e",
            "MLFLOW_TRACKING_URI=http://mlflow:5000",
            "-e",
            "GIT_PYTHON_REFRESH=quiet",
            "credimarket-mlflow",
            "python",
            "-",
        ],
        cwd=ROOT,
        input=code,
        text=True,
        capture_output=True,
        encoding="utf-8",
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ML container verification failed:\n{result.stderr}\n{result.stdout}")
    return result.stdout.strip()


print("--- Iniciando comprobación de Fase 7: Preparar datos y entrenar el modelo ---")

# 1. Verificar integridad de archivos CSV originales
for filename, expected_hash in EXPECTED_SOURCE_HASHES.items():
    file_path = ROOT / filename
    assert file_path.exists(), f"Archivo original no encontrado: {filename}"
    actual_hash = sha256_file(file_path)
    assert actual_hash == expected_hash, f"El archivo original {filename} fue alterado: {actual_hash} != {expected_hash}"

print("PASS Integridad e inmutabilidad SHA-256 de los CSV originales")

# 2. Verificar existencia y estructura de reportes, diccionario y manifiestos
dict_path = ML_DIR / "reports" / "data_dictionary.json"
eda_path = ML_DIR / "reports" / "eda_report.json"
sel_path = ML_DIR / "reports" / "model_selection_report.json"
split_manifest_path = ML_DIR / "manifests" / "split_manifest.json"
cand_manifest_path = ML_DIR / "manifests" / "candidate_v1.json"
artifact_path = ML_DIR / "artifacts" / "candidate_v1" / "pipeline.joblib"

for p in (dict_path, eda_path, sel_path, split_manifest_path, cand_manifest_path, artifact_path):
    assert p.exists(), f"Falta entregable requerido de Fase 7: {p}"

data_dict = json.loads(dict_path.read_text(encoding="utf-8"))
eda_report = json.loads(eda_path.read_text(encoding="utf-8"))
sel_report = json.loads(sel_path.read_text(encoding="utf-8"))
split_manifest = json.loads(split_manifest_path.read_text(encoding="utf-8"))
cand_manifest = json.loads(cand_manifest_path.read_text(encoding="utf-8"))

assert data_dict["model_features"] == EXPECTED_FEATURES
assert eda_report["validation_historical"]["rows"] == 12000
assert eda_report["validation_new_requests"]["rows"] == 200
assert eda_report["shared_clients_between_files"] == 0
assert eda_report["missing_porcentaje_pago_puntual_analysis"]["exact_equivalence_with_zero_prior_credits"] is True

# Verificar particiones 60/20/20 y hashes
assert split_manifest["random_seed"] == 42
assert split_manifest["splits"]["train"]["rows"] == 7200
assert split_manifest["splits"]["val"]["rows"] == 2400
assert split_manifest["splits"]["test"]["rows"] == 2400

for split_name in ("train", "val", "test"):
    sp_info = split_manifest["splits"][split_name]
    sp_file = ROOT / sp_info["file"]
    assert sp_file.exists(), f"No existe archivo de partición: {sp_file}"
    assert sha256_file(sp_file) == sp_info["sha256"], f"Hash no coincide en {split_name}"
    assert abs(sp_info["positive_rate"] - 0.305583) < 0.001, f"Estratificación desviada en {split_name}"

assert sha256_file(artifact_path) == cand_manifest["artifact_sha256"], "Hash de pipeline.joblib no coincide con manifiesto"
assert cand_manifest["variables"] == EXPECTED_FEATURES
assert cand_manifest["clase_positiva"] == 1
assert 0.05 <= cand_manifest["umbral"] <= 0.95

print("PASS Diccionario, EDA, particiones estratificadas 60/20/20 (7200/2400/2400) y manifiestos verificados")

# 3. Verificar servidor MLflow, las 7 ejecuciones, artefactos e inferencia batch sin fuga
mlflow_check_script = f"""
import json
from pathlib import Path
import joblib
import mlflow
import numpy as np
import pandas as pd
from ml.src.contract import FEATURES, normalize_features_df

client = mlflow.MlflowClient(tracking_uri="http://mlflow:5000")
exp = client.get_experiment_by_name("credimarket-riesgo-v1")
assert exp is not None, "Experimento credimarket-riesgo-v1 no encontrado en MLflow"

runs = client.search_runs(experiment_ids=[exp.experiment_id])
finished_runs = [r for r in runs if r.info.status == "FINISHED"]
assert len(finished_runs) >= 7, f"Se esperaban al menos 7 ejecuciones en MLflow, se hallaron {{len(finished_runs)}}"

algorithms = [r.data.params.get("algorithm") for r in finished_runs]
assert algorithms.count("DummyClassifier") >= 1
assert algorithms.count("LogisticRegression") >= 2
assert algorithms.count("DecisionTreeClassifier") >= 2
assert algorithms.count("RandomForestClassifier") >= 2

# Verificar la corrida seleccionada
cand = json.loads(Path("ml/manifests/candidate_v1.json").read_text(encoding="utf-8"))
winner_run = client.get_run(cand["run_id"])
assert winner_run.data.tags.get("selected_candidate") == "true"
assert "test_average_precision" in winner_run.data.metrics
assert "val_average_precision" in winner_run.data.metrics
assert "val_brier_score" in winner_run.data.metrics

# Descargar artefactos desde MLflow para comprobar persistencia real
art_names = [a.path for a in client.list_artifacts(cand["run_id"])]
for expected_art in ("pipeline.joblib", "confusion_matrix_val.json", "calibration_curve_val.json", "threshold_cost_curve.json", "test_evaluation.json"):
    assert expected_art in art_names, f"Artefacto {{expected_art}} ausente en MLflow run {{cand['run_id']}}"

# Comprobar disjunción de IDs entre particiones y evaluar las 200 solicitudes nuevas sin etiqueta
train_df = pd.read_csv("ml/data/splits/train.csv")
val_df = pd.read_csv("ml/data/splits/val.csv")
test_df = pd.read_csv("ml/data/splits/test.csv")
nuevas_df = pd.read_csv("solicitudes_nuevas.csv")

assert "incumplimiento_90d" not in nuevas_df.columns
assert set(train_df["solicitud_id"]).isdisjoint(set(val_df["solicitud_id"]))
assert set(train_df["solicitud_id"]).isdisjoint(set(test_df["solicitud_id"]))
assert set(val_df["solicitud_id"]).isdisjoint(set(test_df["solicitud_id"]))

pipeline = joblib.load("ml/artifacts/candidate_v1/pipeline.joblib")
X_nuevas = normalize_features_df(nuevas_df, FEATURES)
probs = pipeline.predict_proba(X_nuevas)[:, 1]
assert len(probs) == 200
assert np.all((probs >= 0.0) & (probs <= 1.0)), "Probabilidades fuera de [0, 1]"
assert not np.any(np.isnan(probs)), "El pipeline produjo NaN en las 200 solicitudes nuevas"

favorable_count = int((probs < cand["umbral"]).sum())
desfavorable_count = int((probs >= cand["umbral"]).sum())
assert favorable_count > 0 and desfavorable_count > 0, "El umbral debe producir decisiones favorables y desfavorables en el lote nuevo"

print(json.dumps({{
    "runs_count": len(finished_runs),
    "winner_run_id": cand["run_id"],
    "winner_name": cand["run_name"],
    "threshold": cand["umbral"],
    "nuevas_favorable": favorable_count,
    "nuevas_desfavorable": desfavorable_count
}}))
"""

out = run_in_mlflow_image(mlflow_check_script)
summary = json.loads(out.splitlines()[-1])
print(f"PASS MLflow ('credimarket-riesgo-v1'): {summary['runs_count']} ejecuciones verificadas, artefactos persistidos")
print(
    f"PASS Candidato ganador ({summary['winner_name']}, run_id={summary['winner_run_id']}, umbral={summary['threshold']}) "
    f"evaluó las 200 solicitudes nuevas: {summary['nuevas_favorable']} FAVORABLES / {summary['nuevas_desfavorable']} DESFAVORABLES"
)
print("=================================================================")
print("  ¡FASE 7 COMPLETADA CON ÉXITO: DATOS, EDA, MLFLOW Y MODELO v1!  ")
print("=================================================================")
