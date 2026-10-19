import os
from urllib.parse import quote

password = quote(os.environ["MLFLOW_DB_PASSWORD"], safe="")
uri = f"postgresql+psycopg://mlflow_app:{password}@postgres:5432/mlflow_db"
os.environ["MLFLOW_BACKEND_STORE_URI"] = uri
os.execvp("mlflow", ["mlflow", "server", "--host", "0.0.0.0", "--port", "5000",
    "--serve-artifacts", "--artifacts-destination", "/mlartifacts"])
