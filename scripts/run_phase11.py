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
