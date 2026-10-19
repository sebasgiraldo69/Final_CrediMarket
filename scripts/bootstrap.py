"""Create local credentials once, without printing or overwriting secrets."""
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]
env_path = ROOT / ".env"
template = (ROOT / ".env.example").read_text(encoding="utf-8")
if not env_path.exists():
    lines = []
    for line in template.splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            if key.endswith("PASSWORD"):
                value = secrets.token_hex(24)
            line = f"{key}={value}"
        lines.append(line)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

env = {}
for line in env_path.read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.startswith("#"):
        key, value = line.split("=", 1)
        env[key] = value
for key in ["KAFKA_ADMIN_PASSWORD", "KAFKA_PRESTAMOS_PASSWORD", "KAFKA_INVENTARIO_PASSWORD"]:
    if not env.get(key) or any(c not in "0123456789abcdef" for c in env[key]):
        raise SystemExit(f"{key} must contain generated hexadecimal credentials; no files overwritten.")

secret_dir = ROOT / ".secrets"
secret_dir.mkdir(exist_ok=True)
jaas = '\n'.join([
    'KafkaServer {', '  org.apache.kafka.common.security.plain.PlainLoginModule required',
    '  username="admin"', f'  password="{env["KAFKA_ADMIN_PASSWORD"]}"',
    f'  user_admin="{env["KAFKA_ADMIN_PASSWORD"]}"',
    f'  user_prestamos="{env["KAFKA_PRESTAMOS_PASSWORD"]}"',
    f'  user_inventario="{env["KAFKA_INVENTARIO_PASSWORD"]}";', '};', '',
])
client = '\n'.join([
    'security.protocol=SASL_PLAINTEXT', 'sasl.mechanism=PLAIN',
    'sasl.jaas.config=org.apache.kafka.common.security.plain.PlainLoginModule required '
    f'username="admin" password="{env["KAFKA_ADMIN_PASSWORD"]}";', '',
])
for name, content in [("kafka_server_jaas.conf", jaas), ("kafka_admin.properties", client)]:
    target = secret_dir / name
    if target.exists() and target.read_text(encoding="utf-8") != content:
        raise SystemExit(f"{name} differs from .env. Rotate credentials deliberately; not overwriting.")
    if not target.exists():
        target.write_text(content, encoding="utf-8")
print("Local configuration ready. Credentials not displayed; existing values preserved.")
