"""Smoke checks against the running phase-2 stack; safe to rerun.

Run from the host with Docker access. Does not remove containers or volumes.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ["productos", "clientes", "prestamos", "inventario"]


def docker(*args, stdin=None):
    result = subprocess.run(["docker", "compose", *args], cwd=ROOT, input=stdin,
                            text=True, capture_output=True, encoding="utf-8")
    if result.returncode:
        # Never dump subprocess output indiscriminately: credentials may be in environment errors.
        raise RuntimeError(f"Docker operation failed: {' '.join(args[:4])}; exit={result.returncode}")
    return result.stdout.strip()


def http(url):
    request = urllib.request.Request(url, headers={"X-Correlation-ID": "11111111-1111-4111-8111-111111111111"})
    try:
        response = urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    return response.status, response.headers, response.read().decode()


def verify_kafka_marker(marker):
    # The diagnostic topic has one partition. Assign it directly: a random consumer
    # group can spend the whole timeout rebalancing despite the record being durable.
    result = subprocess.run(["docker", "compose", "exec", "-T", "kafka", "/opt/kafka/bin/kafka-console-consumer.sh",
        "--bootstrap-server", "kafka:9092", "--consumer.config", "/run/secrets/kafka_admin.properties",
        "--topic", "credimarket.infra.smoke.v1", "--partition", "0", "--offset", "earliest",
        "--timeout-ms", "15000"], cwd=ROOT, text=True, capture_output=True, timeout=60)
    # The console tool exits nonzero when idle after delivering all existing records.
    assert marker in result.stdout.splitlines(), "Kafka persistence marker not found"
    print("PASS Kafka record persistence")


def verify():
    env = dict(line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines() if "=" in line and not line.startswith("#"))
    base = f"http://localhost:{env.get('FRONTEND_PORT', '8080')}"
    code, _, body = http(base)
    assert code == 200 and 'id="root"' in body, "Frontend unavailable"
    print("PASS frontend and proxy")
    snapshots = {}
    for service in SERVICES:
        code, headers, body = http(f"{base}/api/{service}/health")
        assert code == 200 and json.loads(body)["service"] == service
        assert headers["X-Correlation-ID"] == "11111111-1111-4111-8111-111111111111"
        code, _, body = http(f"{base}/api/{service}/ready")
        ready = json.loads(body)
        assert code == (503 if service == "prestamos" else 200), (service, ready)
        assert ready["dependencies"]["database"] == "ok", (service, ready)
        if service == "prestamos":
            assert ready["dependencies"]["model"] == "unavailable"
        if service in ["prestamos", "inventario"]:
            assert ready["dependencies"]["kafka"] == "ok", (service, ready)
        if service == "productos":
            assert ready["dependencies"]["redis"] == "ok", ready
        code, _, _ = http(f"{base}/api/{service}/openapi.json")
        assert code == 200
        script = '''
import json
from sqlalchemy import create_engine, text
from shared.runtime import database_url
url = database_url()
with create_engine(url).connect() as c:
    row = c.execute(text("SELECT service, created_at::text FROM infrastructure_metadata WHERE id=1")).one()
    revision = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == ('0002' if row[0] in ('clientes', 'productos') else '0001')
    own = c.execute(text("SELECT current_database(), current_user")).one()
    assert own[0] == row[0] + '_db' and own[1] == row[0] + '_app'
    role = c.execute(text("SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user")).one()
    assert not any(role)
    for other in ['productos', 'clientes', 'prestamos', 'inventario', 'mlflow']:
        allowed = c.execute(text("SELECT has_database_privilege(current_user, :db, 'CONNECT')"), {'db': other+'_db'}).scalar_one()
        assert bool(allowed) == (other == row[0]), 'Cross-database permission'
for other in ['productos', 'clientes', 'prestamos', 'inventario', 'mlflow']:
    if other == row[0]: continue
    try:
        with create_engine(url.set(database=other+'_db'), connect_args={'connect_timeout': 2}).connect():
            raise AssertionError('Cross-database connection succeeded')
    except AssertionError: raise
    except Exception: pass
print(json.dumps({'service': row[0], 'created_at': row[1], 'revision': revision}))
'''
        snapshots[service] = json.loads(docker("exec", "-T", service, "python", "-", stdin=script))
        print(f"PASS {service}: health, readiness, migration, identity and isolation")
        if service in ["prestamos", "inventario"]:
            script = '''
import os
from confluent_kafka import KafkaException, KafkaError
from confluent_kafka.admin import AdminClient, NewTopic
client = AdminClient({'bootstrap.servers': 'kafka:9092', 'security.protocol': 'SASL_PLAINTEXT',
    'sasl.mechanism': 'PLAIN', 'sasl.username': SERVICE, 'sasl.password': os.environ['KAFKA_PASSWORD'], 'log_level': 0})
topic = 'credimarket.infra.forbidden.' + SERVICE
try:
    client.create_topics([NewTopic(topic, num_partitions=1, replication_factor=1)], request_timeout=10)[topic].result()
except KafkaException as exc:
    assert exc.args[0].code() in (KafkaError.TOPIC_AUTHORIZATION_FAILED, KafkaError.CLUSTER_AUTHORIZATION_FAILED), 'Unexpected error'
else:
    raise AssertionError('Service unexpectedly authorized to create arbitrary topics')
print('PASS service Kafka ACL denies arbitrary topic creation')
'''.replace("SERVICE", repr(service))
            print(docker("exec", "-T", service, "python", "-", stdin=script))
    code, _, _ = http(f"http://localhost:{env.get('MLFLOW_PORT', '5000')}/health")
    assert code == 200
    topics = docker("exec", "-T", "kafka", "/opt/kafka/bin/kafka-topics.sh", "--bootstrap-server", "kafka:9092",
                    "--command-config", "/run/secrets/kafka_admin.properties", "--describe")
    for topic in ["credimarket.inventario.comandos.v1", "credimarket.inventario.eventos.v1"]:
        assert topic in topics and topic + ".dlq" in topics
    assert "PartitionCount: 3" in topics
    print("PASS MLflow and Kafka topics")
    return snapshots


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--restart", action="store_true", help="Restart this project's durable services and verify persistence")
    args = parser.parse_args()
    before = verify()
    if args.restart:
        # Store a real tracking run and artifact. It is explicitly NOT an ML candidate experiment.
        marker = str(uuid4())
        script = '''
import json, tempfile
from pathlib import Path
import mlflow
mlflow.set_tracking_uri('http://localhost:5000')
mlflow.set_experiment('infrastructure-smoke')
with mlflow.start_run(run_name='phase-2-persistence') as run:
    mlflow.set_tag('purpose', 'infrastructure-only-not-model-training')
    mlflow.log_param('phase', '2')
    with tempfile.TemporaryDirectory() as folder:
        file = Path(folder) / 'probe.txt'
        file.write_text(MARKER)
        mlflow.log_artifact(str(file))
print(json.dumps({'run_id': run.info.run_id}))
'''.replace("MARKER", repr(marker))
        tracking = json.loads(docker("exec", "-T", "mlflow", "python", "-", stdin=script).splitlines()[-1])
        docker("exec", "-T", "kafka", "/opt/kafka/bin/kafka-topics.sh", "--bootstrap-server", "kafka:9092",
               "--command-config", "/run/secrets/kafka_admin.properties", "--create", "--if-not-exists",
               "--topic", "credimarket.infra.smoke.v1", "--partitions", "1", "--replication-factor", "1")
        docker("exec", "-T", "kafka", "/opt/kafka/bin/kafka-console-producer.sh", "--bootstrap-server", "kafka:9092",
               "--producer.config", "/run/secrets/kafka_admin.properties", "--topic", "credimarket.infra.smoke.v1", stdin=marker + "\n")
        print("Restarting project containers; volumes are preserved.", flush=True)
        docker("restart", "postgres", "kafka", "mlflow", *SERVICES)
        deadline = time.monotonic() + 180
        while True:
            try:
                after = verify()
                break
            except (AssertionError, RuntimeError, OSError):
                if time.monotonic() > deadline:
                    raise
                time.sleep(5)
        assert before == after, "Migration baseline changed across restart"
        script = '''
from pathlib import Path
import mlflow
mlflow.set_tracking_uri('http://localhost:5000')
client = mlflow.MlflowClient()
run = client.get_run(RUN_ID)
assert run.data.params['phase'] == '2'
path = client.download_artifacts(RUN_ID, 'probe.txt')
assert Path(path).read_text() == MARKER
print('PASS MLflow metadata and artifact persistence')
'''.replace("RUN_ID", repr(tracking["run_id"])).replace("MARKER", repr(marker))
        print(docker("exec", "-T", "mlflow", "python", "-", stdin=script))
        verify_kafka_marker(marker)
        print("PASS PostgreSQL, Kafka and MLflow survive restart")
    print("Phase 2 infrastructure checks passed. Business acceptance tests remain pending.")
