"""Promueve explícitamente una versión de modelo a models/active_model.json y ejecuta la inferencia batch."""
import argparse
import subprocess
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Promover versión de modelo activo y actualizar inferencia batch")
    parser.add_argument("--version", default="riesgo-v1", help="Versión del modelo a promover (por defecto: riesgo-v1)")
    parser.add_argument("--restart", action="store_true", help="Reiniciar el contenedor prestamos tras promover")
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
            f"export_candidate_to_models(version_override=ver) if not (MODELS_DIR / ver / 'manifest.json').exists() else None; "
            f"active = promote_model_version(ver); "
            f"batch = run_batch_inference(); "
            f"print(json.dumps({{'active_model': active, 'batch_summary': batch['summary']}}, indent=2))"
        ),
    ]
    res = subprocess.run(cmd, cwd=ROOT)
    if res.returncode != 0:
        sys.exit(res.returncode)

    if args.restart:
        subprocess.run(["docker", "compose", "restart", "prestamos"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
