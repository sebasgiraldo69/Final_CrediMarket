"""Render the acceptance report only from a fully passed evidence ledger."""
import json
from pathlib import Path
import shutil
import hashlib
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    latest = json.loads((ROOT / 'docs/evidencias/phase12_latest.json').read_text(encoding='utf-8'))
    assert latest.get('all_suites_passed'), 'Acceptance is incomplete; retain FAIL/NOT_RUN statuses'
    assert all(row['status'] == 'PASS' for row in latest['acceptance'].values())
    folder = ROOT / latest['directory'].replace('\\', '/')
    redis = json.loads((folder / 'redis_metrics.json').read_text(encoding='utf-8'))
    resources = json.loads((folder / 'resources.json').read_text(encoding='utf-8'))
    base = folder.relative_to(ROOT / 'docs').as_posix()
    sources = subprocess.check_output(['rg', '--files', 'services', 'shared', 'scripts', 'ml/src',
        'frontend/src', 'infra', 'contracts'], cwd=ROOT, text=True).splitlines()
    sources += ['compose.yaml', 'requirements-acceptance.txt', 'requirements-contracts.txt',
        'requirements-e2e.txt', 'models/active_model.json', 'models/riesgo-v1/manifest.json',
        'models/riesgo-v1/pipeline.joblib', 'models/riesgo-v2/manifest.json', 'models/riesgo-v2/pipeline.joblib',
        'prestamos_entrenamiento.csv', 'solicitudes_nuevas.csv']
    hashes = {name.replace('\\','/'): hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
              for name in sources}
    (folder / 'workspace_hashes.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
    for source in ['ml/reports/phase11_validation.json', 'ml/manifests/mlflow_reproduction.json']:
        shutil.copyfile(ROOT / source, folder / Path(source).name)
    lines = ['# Verificación de fase 12', '',
        'Estado: **16 casos de aceptación aprobados** y todas las suites requeridas terminadas con código 0.', '',
        f"Ejecución: `{latest['run_id']}`. Finalizada: `{latest['finished_at']}`. Commit base: `{latest['commit']}`.", '',
        'Se probó el código de trabajo del repositorio, incluidas las correcciones locales; los logs conservan el hash del script ejecutado. Los datos sintéticos se conservan y los servicios se restauraron.', '',
        f'[Resultados estructurados]({base}/results.json) y [huellas del código, contratos, modelos y fuentes al cierre]({base}/workspace_hashes.json). Cada caso exige todas las suites enlazadas:', '',
        '| Caso | Resultado | Evidencia |', '|---|---|---|']
    for case, value in latest['acceptance'].items():
        links = ', '.join(f'[{name}]({base}/{name}.log)' for name in value['required_suites'])
        lines.append(f"| {case} | {value['status']} | {links} |")
    lines += ['', '## Redis: medición observada', '',
        '60 consultas HTTP secuenciales por escenario, por loopback dentro de Productos. La preparación de caché se excluye del tiempo. Los encabezados X-Cache identifican el origen.', '',
        '| Escenario | p50 (ms) | p95 (ms) | HIT | MISS | BYPASS |', '|---|---:|---:|---:|---:|---:|']
    for key, label in [('cold','Miss forzado'),('warm','Caché caliente'),('fallback','Redis detenido')]:
        row = redis[key]
        outcomes = row['cache_outcomes']
        lines.append(f"| {label} | {row['p50_ms']} | {row['p95_ms']} | {outcomes.get('HIT',0)} | {outcomes.get('MISS',0)} | {outcomes.get('BYPASS',0)} |")
    lines += ['', f"TTL inicial observado: {redis['expiration']['initial_ttl_seconds']} s; espera hasta expiración: {redis['expiration']['observed_wait_seconds']} s, sin forzar ni reducir TTL.", '',
        'En esta carga local pequeña la caché caliente no resultó más rápida que el miss. No se demuestra una mejora de latencia con este ensayo; no se oculta ese resultado ni se extrapola a otras cargas.', '',
        'Se verificaron invalidación al editar precio, escritura con Redis detenido y registro durable de invalidación pendiente. Tras recuperarlo se leyó el precio nuevo.', '',
        f'[Mediciones completas]({base}/redis_metrics.json). No se extrapolan a capacidad máxima, concurrencia de producción ni SLA.', '',
        '## Recursos del entorno', '',
        f"VM Docker: {resources['docker_vm']['cpus']} CPU, {resources['docker_vm']['memory_bytes']} bytes de memoria asignada, Docker {resources['docker_vm']['server_version']}. Muestras: {resources['sample_count']}.", '',
        '| Contenedor | Máximo CPU observado (%) | Máximo memoria observado (%) |', '|---|---:|---:|']
    for name, row in sorted(resources['sampled_peaks'].items()):
        lines.append(f"| {name} | {row['max_observed_cpu_percent']} | {row['max_observed_memory_percent']} |")
    lines += ['', f'[Muestras originales]({base}/resources.json). Son máximos de muestras durante el microbenchmark, no máximos continuos ni memoria física total del equipo.', '',
        '## Fallos y navegador', '',
        f'[Caídas en fronteras de commit]({base}/crash_boundaries.json): trabajadores aislados terminaron después del ACK de Kafka y antes de confirmar outbox, y después del commit de Inventario y antes de confirmar offset. Se comprobó recuperación y un solo movimiento de reserva.', '',
        f'[Pendiente y recuperación reales]({base}/pending_ui.json): Inventario detenido, aprobación por polling al recuperarlo, formulario inválido sin envío, JWT vencido y Productos realmente detenido.', '',
        f'![Solicitud pendiente]({base}/AC15-pending.png)', '',
        f'![Solicitud recuperada]({base}/AC15-recovered.png)', '',
        f'![Error por API detenida]({base}/AC16-api-down.png)', '',
        '## Correcciones y procedencia de MLflow', '',
        'Se detectó que el volumen local de MLflow no contenía las ejecuciones v1 incorporadas por Git en otro equipo. Se reprodujeron los siete modelos sobre train/validación y se verificó coincidencia con el reporte original. El conjunto test no se reevaluó; sus métricas se importaron con procedencia explícita y prefijo imported_test_.', '',
        f'[Mapa de ejecuciones originales a reproducciones locales]({base}/mlflow_reproduction.json). Se mantuvieron el artefacto, run de origen y evaluación histórica de los préstamos.', '',
        'Se añadieron X-Cache para medir HIT/MISS/BYPASS y logs de asignación/revocación de particiones. No se agregaron interruptores de fallo a producción.', '',
        'El primer ensayo Redis detectó bloqueo por DNS; el segundo confirmó esperas adicionales por los tres reintentos internos del cliente. Se corrigieron resolución asíncrona y política de cero reintentos para la caché opcional. Se repitieron Productos y Redis antes del cierre; los intentos fallidos se conservan como logs de intentos en la misma carpeta.', '',
        '## Límites', '',
        'Kafka es un broker único sin alta disponibilidad. El benchmark es local y secuencial; los fallos no cubren todas las particiones de red o condiciones del sistema operativo. Las invalidaciones fallidas se registran, pero no hay un trabajador automático de reintentos de esa tabla. Las cotizaciones internas usan PostgreSQL. La entrega desde un clon limpio y la sustentación corresponden a fase 13.', '']
    (ROOT / 'docs/validacion-fase-12.md').write_text('\n'.join(lines), encoding='utf-8')
    print('Generated docs/validacion-fase-12.md from passed execution ' + latest['run_id'])


if __name__ == '__main__':
    main()
