"""Operator-only inspection and DLQ replay. Uses each service's own credentials."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def docker(*args, stdin=None):
    result = subprocess.run(['docker', 'compose', *args], cwd=ROOT, input=stdin,
        text=True, encoding='utf-8', capture_output=True, timeout=60)
    if result.returncode:
        raise SystemExit('Operation failed: ' + result.stderr[-1000:])
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['status', 'lag', 'replay', 'requeue'])
    parser.add_argument('--service', choices=['prestamos', 'inventario'], default='inventario')
    parser.add_argument('--failure-id', type=str)
    parser.add_argument('--replacement', type=Path,
                        help='Corrected event JSON with a NEW event_id, if original bytes were invalid')
    args = parser.parse_args()
    if args.action == 'lag':
        print(docker('exec', '-T', 'kafka', '/opt/kafka/bin/kafka-consumer-groups.sh',
            '--bootstrap-server', 'kafka:9092', '--command-config', '/run/secrets/kafka_admin.properties',
            '--describe', '--group', args.service + '-v1'))
        return
    if args.action == 'status':
        print(docker('exec', '-T', args.service, 'python', '-m', 'shared.messaging_cli', 'status'))
        return
    if not args.failure_id:
        parser.error('--failure-id is required')
    from uuid import UUID
    failure_id = str(UUID(args.failure_id))
    source = '''
import json
from sqlalchemy import create_engine, select
from shared.runtime import database_url
from shared.messaging_models import failures
with create_engine(database_url()).connect() as c:
    body=c.execute(select(failures.c.envelope).where(failures.c.envelope['failure_id'].astext == FAILURE_ID)).scalar_one()
print(json.dumps(body))
'''.replace('FAILURE_ID', repr(failure_id))
    envelope = json.loads(docker('exec', '-T', args.service, 'python', '-', stdin=source))
    body = json.loads(args.replacement.read_text(encoding='utf-8')) if args.replacement else json.loads(
        base64.b64decode(envelope['original_value_base64']))
    if args.replacement and body['event_id'] == envelope['event_id']:
        parser.error('Corrections require a new event_id; retain correlation_id for traceability')
    owner = 'prestamos' if envelope['original_topic'].endswith('comandos.v1') else 'inventario'
    print(docker('exec', '-T', owner, 'python', '-m', 'shared.messaging_cli',
                 args.action, stdin=json.dumps(body)))


if __name__ == '__main__':
    main()
