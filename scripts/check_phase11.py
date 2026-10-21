"""Real API v1 -> v2 -> rollback demonstration. Retains synthetic fixtures.

Restores the original active version in finally. Does not retrain or evaluate test.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request
import urllib.error
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
env = dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines()
           if '=' in line and not line.startswith('#'))
BASE = f"http://127.0.0.1:{env.get('FRONTEND_PORT', '8080')}/api/prestamos"


def docker(*args, stdin=None):
    result = subprocess.run(['docker', 'compose', *args], cwd=ROOT, input=stdin,
        text=True, encoding='utf-8', capture_output=True, timeout=90)
    if result.returncode:
        raise RuntimeError('Docker fixture operation failed (credentials suppressed)')
    return result.stdout.strip()


def inside(service, source):
    prefix = '''
import json
from uuid import UUID, uuid4
from sqlalchemy import create_engine, select
from shared.runtime import database_url
engine = create_engine(database_url(), hide_parameters=True)
'''
    return docker('exec', '-T', service, 'python', '-', stdin=prefix + source)


def api(path, body=None, token=None, key=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if key:
        headers['Idempotency-Key'] = key
    request = urllib.request.Request(BASE + path,
        data=json.dumps(body).encode() if body is not None else None, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=20)
    except urllib.error.HTTPError as exc:
        response = exc
    return response.status, json.load(response)


def activate(version, rollback=False):
    command = [sys.executable, str(ROOT / 'scripts/promote_model.py'), '--version', version,
               '--restart', '--reason', 'Prueba reproducible de fase 11']
    if rollback:
        command.append('--rollback')
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=180)
    if result.returncode:
        raise RuntimeError('Promotion failed: ' + result.stderr[-1500:])


def history():
    return json.loads(inside('prestamos', '''
from app.models import prestamos
with engine.connect() as c:
    rows=c.execute(select(prestamos.c.id, prestamos.c.model_version, prestamos.c.run_id,
        prestamos.c.probabilidad_incumplimiento, prestamos.c.umbral_riesgo)).all()
print(json.dumps({str(row[0]): [str(value) if value is not None else None for value in row[1:]] for row in rows}))
'''))


def main():
    original = json.loads((ROOT / 'models/active_model.json').read_text())
    v1_hash = hashlib.sha256((ROOT / 'models/riesgo-v1/pipeline.joblib').read_bytes()).hexdigest()
    before = history()
    product, client, account = str(uuid4()), str(uuid4()), str(uuid4())
    service_token = inside('clientes', "from shared.auth import issue_service_token; print(issue_service_token('prestamos', ['modelo:read','riesgo:predict']))")
    client_token = inside('clientes', '''
from app.models import clientes, usuarios
from app.security import hasher, issue_token
with engine.begin() as c:
    c.execute(clientes.insert().values(id=UUID(CLIENT), nombre='Prueba fase 11', finanzas={
        'ingresos_mensuales_cop': '10000000.00', 'obligaciones_mensuales_cop': '200000.00',
        'tipo_empleo': 'dependiente', 'antiguedad_laboral_meses': 60,
        'meses_historial_crediticio': 60, 'creditos_previos': 5,
        'atrasos_previos_30d': 0, 'porcentaje_pago_puntual': 100.0}))
    c.execute(usuarios.insert().values(id=UUID(ACCOUNT), cliente_id=UUID(CLIENT),
        email=ACCOUNT+'@example.com', password_hash=hasher.hash(str(uuid4())), rol='cliente'))
print(issue_token(ACCOUNT, role='cliente', cliente_id=CLIENT))
'''.replace('CLIENT', repr(client)).replace('ACCOUNT', repr(account)))
    inside('productos', '''
from app.models import productos
with engine.begin() as c:
    c.execute(productos.insert().values(id=UUID(PRODUCT), nombre='Producto prueba fase 11',
        categoria='Portátiles', precio_cop=3000000))
'''.replace('PRODUCT', repr(product)))
    inside('inventario', '''
from app.domain import agregar_stock
with engine.begin() as c:
    agregar_stock(c, UUID(PRODUCT), 3, 'Fixture fase 11')
'''.replace('PRODUCT', repr(product)))
    sample = dict(ingresos_mensuales_cop=10000000.0, obligaciones_mensuales_cop=200000.0,
        tipo_empleo='dependiente', antiguedad_laboral_meses=60, meses_historial_crediticio=60,
        creditos_previos=5, atrasos_previos_30d=0, porcentaje_pago_puntual=100.0,
        monto_solicitado_cop=3000000.0, plazo_meses=12)
    sample['cuota_estimada_cop'] = float((Decimal('3000000') * Decimal('.018') /
        (1 - Decimal('1.018') ** -12)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))
    observed = []
    loans = []
    try:
        for version, rollback in [('riesgo-v1', False), ('riesgo-v2', False), ('riesgo-v1', True)]:
            activate(version, rollback)
            status, info = api('/modelo/info', token=service_token)
            assert status == 200 and info['model_version'] == version
            status, risk = api('/riesgo/predict', sample, service_token)
            assert status == 200 and risk['model_version'] == version
            status, loan = api('/prestamos', {'producto_id': product, 'cantidad': 1, 'plazo_meses': 12},
                               client_token, str(uuid4()))
            assert status in (201, 202), (status, loan.get('message'))
            assert loan['riesgo']['model_version'] == version
            loans.append({'id': loan['id'], 'model_version': version, 'run_id': loan['riesgo']['run_id']})
            observed.append({'model_version': version, 'run_id': info['run_id'],
                'artifact_sha256': info['artifact_sha256'], 'prediction': risk,
                'loan_id': loan['id'], 'api_verified_at': datetime.now(timezone.utc).isoformat()})
            print('PASS API prediction and persisted loan: ' + version, flush=True)
        assert observed[0]['prediction'] == observed[2]['prediction'], 'Rollback prediction changed'
        assert observed[0]['artifact_sha256'] != observed[1]['artifact_sha256']
        after = history()
        assert all(after.get(identity) == value for identity, value in before.items())
        for loan in loans:
            assert after[loan['id']][:2] == [loan['model_version'], loan['run_id']]
        print('PASS historical model metadata preserved across promotion and rollback', flush=True)
        assert api('/riesgo/predict', sample)[0] == 401
        assert api('/riesgo/predict', {**sample, 'creditos_previos': 0}, service_token)[0] == 422

        # Corruption must be rejected before activation, without touching active pointer.
        active_before = (ROOT / 'models/active_model.json').read_bytes()
        bad_version = 'invalid-phase11-' + uuid4().hex[:8]
        folder = ROOT / 'models' / bad_version
        folder.mkdir()
        try:
            manifest = json.loads((ROOT / 'models/riesgo-v1/manifest.json').read_text())
            manifest['model_version'] = bad_version
            (folder / 'manifest.json').write_text(json.dumps(manifest))
            (folder / 'pipeline.joblib').write_bytes(b'corrupt-test-artifact')
            result = subprocess.run(['docker', 'run', '--rm', '--mount',
                f'type=bind,source={ROOT},target=/workspace', '-w', '/workspace', 'credimarket-mlflow',
                'python', '-c', 'from ml.src.export_and_promote import promote_model_version; promote_model_version(' + repr(bad_version) + ')'],
                cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=60)
            assert result.returncode != 0
            assert (ROOT / 'models/active_model.json').read_bytes() == active_before
        finally:
            (folder / 'pipeline.joblib').unlink()
            (folder / 'manifest.json').unlink()
            folder.rmdir()
        print('PASS corrupt artifact rejected; active pointer unchanged', flush=True)

        inside('prestamos', '''
from unittest.mock import patch, Mock
from app.model_service import ModelRegistry
registry=ModelRegistry()
registry.load()
registry._pipeline=Mock()
registry._pipeline.predict_proba.side_effect=RuntimeError('sensitive-input-do-not-log')
sample=SAMPLE
with patch('app.model_service.logger.error') as log:
    try: registry.predict_one(sample)
    except RuntimeError: pass
    else: raise AssertionError('Expected inference failure')
    payload=json.loads(log.call_args.args[0])
    assert payload['event']=='risk_prediction_failed' and payload['error_type']=='RuntimeError'
    assert 'sensitive-input' not in json.dumps(payload)
    assert not any(key in payload for key in sample)
'''.replace('SAMPLE', repr(sample)))

        from monitor_model import collect, summarize
        synthetic = summarize([{'event': 'risk_prediction_failed', 'model_version': 'fixture', 'latency_ms': 2}])
        assert synthetic['versions']['fixture']['inference_errors'] == 1
        report = collect()
        assert all(v in report['versions'] for v in ('riesgo-v1', 'riesgo-v2'))
        assert report['http']['errors_4xx'] >= 2
        for row in report['versions'].values():
            assert row['latency_p95_ms'] is not None
            assert sum(row['score_histogram']) == row['predictions']
        drift = json.loads((ROOT / 'ml/reports/drift_report.json').read_text())
        simulated = drift['batches']['explicitly_simulated']
        normal = drift['batches']['unlabeled_current']
        assert simulated['simulated'] is True and simulated['features']['ingresos_mensuales_cop']['psi'] > normal['features']['ingresos_mensuales_cop']['psi']
        assert hashlib.sha256((ROOT / 'models/riesgo-v1/pipeline.joblib').read_bytes()).hexdigest() == v1_hash
        comparison = json.loads((ROOT / 'ml/reports/v2_comparison.json').read_text())
        assert not any(key.startswith('test') for key in json.loads(
            (ROOT / 'models/riesgo-v2/manifest.json').read_text())['metrics'])
        result = {'passed': True, 'verified_at': datetime.now(timezone.utc).isoformat(),
            'observed_sequence': observed, 'historical_loans_checked': len(before),
            'historical_metadata_unchanged': True, 'v1_artifact_unchanged': True,
            'v2_run_id': comparison['run_id'], 'monitoring_versions': list(report['versions']),
            'drift_is_simulated': True, 'fixtures_retained': True}
        (ROOT / 'ml/reports/phase11_validation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print('PASS monitoring, explicit simulated drift and immutable v1 artifact', flush=True)
    finally:
        current = json.loads((ROOT / 'models/active_model.json').read_text())['model_version']
        if current != original['model_version']:
            activate(original['model_version'], rollback=True)
    print('Phase 11 verified. Original active version restored.', flush=True)


if __name__ == '__main__':
    main()
