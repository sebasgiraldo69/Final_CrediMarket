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
