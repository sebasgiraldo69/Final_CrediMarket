"""Run acceptance suites sequentially and retain dated evidence. Creates fixtures.

Fault suites temporarily interrupt services. No volume deletion or resets.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
TASKS = {
    'contracts': ('validate_contracts.py', [], []),
    'infrastructure': ('check_infrastructure.py', [], []),
    'clientes': ('check_phase3.py', [], ['AC12', 'AC13', 'AC16']),
    'productos': ('check_phase4.py', [], ['AC08', 'AC09']),
    'inventario': ('check_phase5.py', [], ['AC04', 'AC05', 'AC07']),
    'datos': ('check_phase7.py', [], []),
    'modelo': ('check_phase8.py', [], ['AC10', 'AC16']),
    'prestamos': ('check_phase9.py', [], ['AC01', 'AC02', 'AC03', 'AC04', 'AC05', 'AC07', 'AC09', 'AC13']),
    'frontend': ('check_phase10.py', [], ['AC14', 'AC16']),
    'mlops': ('check_phase11.py', [], ['AC11']),
    'kafka': ('check_phase6.py', ['--faults'], ['AC05', 'AC06']),
    'faults': ('check_phase12_faults.py', [], ['AC05', 'AC06', 'AC07']),
    'redis': ('measure_phase12.py', [], ['AC08']),
    'pending_ui': ('check_phase12_pending.py', [], ['AC15', 'AC16']),
    'final': ('check_infrastructure.py', [], []),
}


def write_json(path, body):
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', nargs='+', choices=list(TASKS))
    parser.add_argument('--resume', type=Path, help='Continue an evidence directory without repeating passed suites')
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    run_id = now.strftime('%Y%m%dT%H%M%S') + '-' + os.urandom(3).hex()
    output = (ROOT / args.resume).resolve() if args.resume else ROOT / 'docs/evidencias' / ('fase12-' + run_id)
    if not output.resolve().is_relative_to((ROOT / 'docs/evidencias').resolve()):
        parser.error('Evidence directory must stay inside docs/evidencias')
    output.mkdir(parents=True, exist_ok=bool(args.resume))
    child_env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1',
        CREDIMARKET_EVIDENCE_DIR=str(output), PLAYWRIGHT_BROWSERS_PATH=str(ROOT / '.local/pw-browsers'))
    child_env['PYTHONPATH'] = os.pathsep.join([str(ROOT / '.local/e2e'), str(ROOT), child_env.get('PYTHONPATH', '')])
    ledger = {'run_id': run_id, 'started_at': now.isoformat(),
        'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'fixtures_retained': True, 'results': {}}
    if args.resume:
        ledger = json.loads((output / 'results.json').read_text(encoding='utf-8'))
    selected = args.only or [name for name in TASKS if ledger['results'].get(name, {}).get('status') != 'PASS']

    def save():
        matrix = {}
        for number in range(1, 17):
            case = f'AC{number:02d}'
            required = [name for name, (_, _, cases) in TASKS.items() if case in cases]
            states = [ledger['results'].get(name, {}).get('status', 'NOT_RUN') for name in required]
            matrix[case] = {'status': 'PASS' if states and all(x == 'PASS' for x in states) else
                'FAIL' if 'FAIL' in states else 'NOT_RUN', 'required_suites': required}
        ledger['acceptance'] = matrix
        write_json(output / 'results.json', ledger)
        write_json(ROOT / 'docs/evidencias/phase12_latest.json', {'directory': output.relative_to(ROOT).as_posix(), **ledger})
    save()
    print('Evidence directory: ' + str(output.relative_to(ROOT)), flush=True)
    for name in selected:
        filename, extra, cases = TASKS[name]
        previous = ledger['results'].get(name)
        if previous and (output / (name + '.log')).exists():
            attempt = previous.get('attempt', 1)
            archived = f'{name}.attempt-{attempt}.log'
            (output / archived).write_bytes((output / (name + '.log')).read_bytes())
            ledger.setdefault('previous_attempts', []).append({**previous, 'suite': name, 'log': archived})
        else:
            attempt = 0
        source_hash = hashlib.sha256((ROOT / 'scripts' / filename).read_bytes()).hexdigest() if (ROOT / 'scripts' / filename).exists() else None
        command = [sys.executable, str(ROOT / 'scripts' / filename), *extra]
        print('START ' + name, flush=True)
        began = time.monotonic()
        try:
            result = subprocess.run(command, cwd=ROOT, env=child_env, text=True,
                encoding='utf-8', errors='replace', stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, timeout=1200)
            code, log = result.returncode, result.stdout
        except subprocess.TimeoutExpired as exc:
            code, log = -1, 'TIMEOUT\n' + str(exc.stdout or '')
        # Redact bearer credentials if a failing fixture happened to print one.
        log = re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[REDACTED_JWT]', log)
        (output / (name + '.log')).write_text(log, encoding='utf-8')
        ledger['results'][name] = {'status': 'PASS' if code == 0 else 'FAIL', 'exit_code': code,
            'duration_seconds': round(time.monotonic() - began, 2), 'cases': cases,
            'source_sha256': source_hash, 'attempt': attempt + 1,
            'log': name + '.log'}
        save()
        print(ledger['results'][name]['status'] + ' ' + name, flush=True)
        if code:
            print(log[-2200:], flush=True)
    ledger['finished_at'] = datetime.now(timezone.utc).isoformat()
    ledger['all_suites_passed'] = all(ledger['results'].get(name, {}).get('status') == 'PASS' for name in TASKS)
    save()
    print('Completed. All suites passed: ' + str(ledger['all_suites_passed']), flush=True)
    raise SystemExit(0 if all(item['status'] == 'PASS' for item in ledger['results'].values()) else 1)


if __name__ == '__main__':
    main()
