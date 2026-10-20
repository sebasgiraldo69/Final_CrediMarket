"""Ejecuta la preparación de datos, particiones 60/20/20 y entrenamiento en MLflow (Fase 7)
usando la imagen bloqueada credimarket-mlflow conectada al servidor MLflow del stack."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    cmd = [
        "docker",
        "run",
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
        "-m",
        "ml.src.train_and_select",
    ]
    result = subprocess.run(cmd, cwd=ROOT)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
