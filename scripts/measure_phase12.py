"""Controlled local cache microbenchmark and Docker resource samples (not a capacity test)."""
from datetime import datetime, timezone
import json
import subprocess
import threading
import time
from phase12_support import ROOT, api, docker, inside, fixtures, evidence, wait_for


def main():
    fixture = fixtures()
    product = fixture['product']['id']
    token = fixture['tokens']['admin']
    resource_samples = []
    stop = threading.Event()

    def resources():
        while not stop.is_set():
            result = subprocess.run(['docker', 'stats', '--no-stream', '--format', '{{json .}}'],
                cwd=ROOT, text=True, capture_output=True, timeout=30)
            if result.returncode == 0:
                resource_samples.append({'at': datetime.now(timezone.utc).isoformat(),
                    'containers': [json.loads(line) for line in result.stdout.splitlines() if line.strip()]})
            stop.wait(2)

    thread = threading.Thread(target=resources, daemon=True)
    thread.start()
    source = '''
import time, urllib.request
from app.cache import get_redis_client
mode=MODE
url='http://127.0.0.1:8000/productos/'+PRODUCT
token=TOKEN
times=[]; cache_counts={}
cache=get_redis_client() if mode!='offline' else None
if mode=='warm':
    with urllib.request.urlopen(urllib.request.Request(url,headers={'Authorization':'Bearer '+token})) as r: r.read()
for index in range(60):
    if mode=='cold': cache.delete('producto:'+PRODUCT)
    began=time.perf_counter()
    with urllib.request.urlopen(urllib.request.Request(url,headers={'Authorization':'Bearer '+token})) as r:
        body=json.loads(r.read()); outcome=r.headers['X-Cache']
    times.append((time.perf_counter()-began)*1000)
    assert body['id']==PRODUCT
    cache_counts[outcome]=cache_counts.get(outcome,0)+1
values=sorted(times)
def percentile(p):
    x=(len(values)-1)*p; lo=int(x)
    return round(values[lo]+(values[min(lo+1,len(values)-1)]-values[lo])*(x-lo),3)
print(json.dumps({'samples':len(times),'p50_ms':percentile(.5),'p95_ms':percentile(.95),
    'cache_outcomes':cache_counts,'hit_rate':cache_counts.get('HIT',0)/len(times),
    'measurement':'HTTP loopback inside Productos; preparation excluded; serial identical product requests'}))
'''.replace('PRODUCT', repr(product)).replace('TOKEN', repr(token))

    def bench(mode):
        return json.loads(inside('productos', source.replace('MODE', repr(mode))))

    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'product_id': product,
        'limits': 'Local sequential diagnostic workload (60 requests per mode); not production SLA or maximum capacity'}
    try:
        report['initial_dns_bound'] = json.loads(inside('productos', '''
import time
from unittest.mock import patch
from app import cache
def slow_dns(host):
    time.sleep(2)
    raise OSError('simulated DNS outage')
with patch.object(cache.socket,'gethostbyname',slow_dns):
    began=time.perf_counter()
    try: cache.redis_address()
    except cache.RedisError: pass
    else: raise AssertionError('Expected unavailable DNS')
    elapsed=time.perf_counter()-began
    assert elapsed < .5
    print(json.dumps({'simulated_blocked_dns':True,'caller_wait_seconds':round(elapsed,3)}))
'''))
        report['cold'] = bench('cold')
        report['warm'] = bench('warm')
        assert report['cold']['cache_outcomes'] == {'MISS': 60}
        assert report['warm']['cache_outcomes'] == {'HIT': 60}
        ttl = json.loads(inside('productos', '''
import time
from app.cache import get_redis_client
with get_redis_client() as cache:
    key='producto:'+PRODUCT
    initial=cache.ttl(key)
    assert 0 < initial <= 60
    began=time.monotonic()
    while cache.exists(key):
        assert time.monotonic()-began < 66
        time.sleep(.2)
    print(json.dumps({'initial_ttl_seconds': initial, 'observed_wait_seconds': round(time.monotonic()-began,2),
                     'expired_without_forcing_ttl': True}))
'''.replace('PRODUCT', repr(product))))
        report['expiration'] = ttl
        status, _ = api('productos/productos/'+product, token=token)
        assert status == 200
        status, updated = api('productos/productos/'+product, 'PATCH',
            {'version_esperada': 1, 'precio_cop': '2600000.00'}, token)
        assert status == 200 and updated['version'] == 2
        exists = inside('productos', "from app.cache import get_redis_client; print(get_redis_client().exists('producto:'+"+repr(product)+"))")
        assert exists == '0'
        status, fresh = api('productos/productos/'+product, token=token)
        assert status == 200 and fresh['precio_cop'] == '2600000.00'
        report['invalidation'] = {'key_removed_after_update': True, 'new_price_read': True}
        try:
            docker('stop', 'redis')
            status, changed = api('productos/productos/'+product, 'PATCH',
                {'version_esperada': 2, 'precio_cop': '2700000.00'}, token)
            assert status == 200 and changed['version'] == 3
            pending = inside('productos', '''
from app.models import invalidaciones_cache
with engine.connect() as c:
    print(c.execute(select(func.count()).select_from(invalidaciones_cache).where(
        invalidaciones_cache.c.producto_id == PRODUCT, invalidaciones_cache.c.procesado == False)).scalar())
'''.replace('PRODUCT', repr(product)))
            assert int(pending) >= 1
            report['invalidation_during_outage'] = {'write_committed': True, 'pending_record_durable': True}
            report['fallback'] = bench('offline')
            assert report['fallback']['cache_outcomes'] == {'BYPASS': 60}
            assert report['fallback']['p95_ms'] < 2000, 'Unexpected hidden retry/backoff during cache outage'
            status, ready = api('productos/ready')
            assert status == 200 and ready['dependencies']['redis'] == 'degraded'
        finally:
            docker('restart', '--no-deps', 'redis')
        wait_for(lambda: api('productos/ready')[1]['dependencies']['redis'] == 'ok')
        status, recovered = api('productos/productos/'+product, token=token)
        assert status == 200 and recovered['precio_cop'] == '2700000.00'
        report['p50_warm_to_cold_ratio'] = report['warm']['p50_ms'] / report['cold']['p50_ms']
        evidence('redis_metrics.json', report)
        print(json.dumps(report), flush=True)
    finally:
        stop.set()
        thread.join(timeout=35)
        info = subprocess.run(['docker', 'info', '--format',
            '{"cpus":{{.NCPU}},"memory_bytes":{{.MemTotal}},"server_version":"{{.ServerVersion}}"}'],
            cwd=ROOT, text=True, capture_output=True, timeout=20)
        assert resource_samples and info.returncode == 0, 'Docker resource samples missing'
        peaks = {}
        for sample in resource_samples:
            for container in sample['containers']:
                name = container.get('Name', container.get('Container'))
                row = peaks.setdefault(name, {'max_observed_cpu_percent': 0, 'max_observed_memory_percent': 0})
                row['max_observed_cpu_percent'] = max(row['max_observed_cpu_percent'], float(container['CPUPerc'].rstrip('%')))
                row['max_observed_memory_percent'] = max(row['max_observed_memory_percent'], float(container['MemPerc'].rstrip('%')))
        evidence('resources.json', {'docker_vm': json.loads(info.stdout), 'sample_count': len(resource_samples),
            'sampled_peaks': peaks,
            'samples': resource_samples, 'scope': 'Docker VM allocation and samples during this microbenchmark; not physical host totals'})
    print('PASS measured hit/miss, actual TTL expiration, invalidation, fallback and resource samples', flush=True)


if __name__ == '__main__':
    main()
