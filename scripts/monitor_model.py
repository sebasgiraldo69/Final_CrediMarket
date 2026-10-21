"""Aggregate retained inference logs. Never writes raw financial inputs or tokens."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * fraction
    low = int(index)
    return round(values[low] + (values[min(low + 1, len(values) - 1)] - values[low]) * (index - low), 3)


def summarize(records):
    versions = {}
    http = {'requests': 0, 'errors_4xx': 0, 'errors_5xx': 0, 'latencies_ms': []}
    for record in records:
        if record.get('path') in ('/riesgo/predict', '/prestamos'):
            http['requests'] += 1
            status = record.get('status', 0)
            http['errors_4xx'] += int(400 <= status < 500)
            http['errors_5xx'] += int(status >= 500)
            if isinstance(record.get('duration_ms'), (int, float)):
                http['latencies_ms'].append(record['duration_ms'])
        if record.get('event') not in ('risk_prediction', 'risk_prediction_failed'):
            continue
        version = record.get('model_version') or 'unknown'
        row = versions.setdefault(version, {'predictions': 0, 'inference_errors': 0,
            'favorable': 0, 'unfavorable': 0, 'missing_fields': {}, 'scores': [], 'latencies': []})
        if isinstance(record.get('latency_ms'), (int, float)):
            row['latencies'].append(record['latency_ms'])
        if record['event'] == 'risk_prediction_failed':
            row['inference_errors'] += 1
            continue
        row['predictions'] += 1
        row['favorable'] += int(record.get('decision_riesgo') == 'FAVORABLE')
        row['unfavorable'] += int(record.get('decision_riesgo') == 'DESFAVORABLE')
        score = record.get('probabilidad_incumplimiento')
        if isinstance(score, (int, float)) and math.isfinite(score) and 0 <= score <= 1:
            row['scores'].append(score)
        for field in record.get('missing_fields', []):
            row['missing_fields'][field] = row['missing_fields'].get(field, 0) + 1
    for row in versions.values():
        times, scores = row.pop('latencies'), row.pop('scores')
        row.update({'latency_p50_ms': percentile(times, .5), 'latency_p95_ms': percentile(times, .95),
                    'mean_score': sum(scores) / len(scores) if scores else None,
                    'score_histogram': [sum(min(int(p * 10), 9) == i for p in scores) for i in range(10)]})
        row['missing_rates'] = {f: n / row['predictions'] for f, n in row['missing_fields'].items()} if row['predictions'] else {}
    times = http.pop('latencies_ms')
    http.update({'latency_p50_ms': percentile(times, .5), 'latency_p95_ms': percentile(times, .95)})
    return {'versions': versions, 'http': http}


def collect(since='24h'):
    result = subprocess.run(['docker', 'compose', 'logs', '--no-color', '--no-log-prefix',
        '--since', since, 'prestamos'], cwd=ROOT, text=True, encoding='utf-8', errors='replace',
        capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError('No se pudieron consultar los logs de Préstamos')
    records = []
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            records.append(item)
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'requested_window': since,
        'scope': 'Only logs retained in the current prestamos container; recreation may truncate history',
        'records_read': len(records), **summarize(records),
        'interpretation': 'HTTP validation/authentication errors are separate from inference failures. No accuracy without labels.'}
    destination = ROOT / 'ml/reports/monitoring_report.json'
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--since', default='24h')
    print(json.dumps(collect(parser.parse_args().since), indent=2, ensure_ascii=False))
