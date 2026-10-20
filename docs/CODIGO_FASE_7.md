# Código de Fase 7 para estudiar

Este documento reúne los módulos principales implementados en la **Fase 7: Preparar datos y entrenar el modelo**, diseñados para garantizar cero fuga de datos (`data leakage`), trazabilidad completa en MLflow y reproducibilidad exacta de principio a fin.

---

## 1. Contrato de variables, validación semántica y pipelines (`ml/src/contract.py`)

Define las 11 variables predictoras que coinciden con el contrato OpenAPI de Préstamos (`#/components/schemas/Features`), verifica los hashes SHA-256 de los archivos CSV originales, valida las reglas semánticas del dominio (incluyendo que `porcentaje_pago_puntual` es nulo si y solo si `creditos_previos == 0`) y construye el `ColumnTransformer` + `Pipeline` de `scikit-learn`.

```python
"""Contrato de datos, validación semántica y construcción de pipelines sin fuga de datos."""
from decimal import Decimal, ROUND_HALF_UP
import hashlib
from pathlib import Path
from typing import Any, Dict, List
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier

# Hashes SHA-256 esperados de los archivos fuente originales
EXPECTED_HASHES = {
    "prestamos_entrenamiento.csv": "c6cdc437c3aecc9116bc8b978df421d5a7600634c1ad7d6f82e58222a2446ecd",
    "solicitudes_nuevas.csv": "1430d7b34e924d5e4170c4fb9d9a412c1000af17c062af513ef15e44a1a7f1f7",
}

RANDOM_SEED = 42
TASA_MENSUAL_FIJA = Decimal("0.018")
PLAZOS_VALIDOS = (6, 12, 18, 24, 36)
TIPOS_EMPLEO_VALIDOS = ("dependiente", "independiente", "temporal")
MONTO_MIN_COP = Decimal("500000.00")
MONTO_MAX_COP = Decimal("15000000.00")

ID_COLUMNS = ["solicitud_id", "cliente_id"]
EXCLUDED_CONSTANT_COLUMNS = ["tasa_mensual_simulada"]
TARGET_COLUMN = "incumplimiento_90d"
POSITIVE_CLASS = 1

# Exactamente las 11 variables predictoras del contrato OpenAPI (#/components/schemas/Features)
FEATURES = [
    "ingresos_mensuales_cop",
    "obligaciones_mensuales_cop",
    "tipo_empleo",
    "antiguedad_laboral_meses",
    "meses_historial_crediticio",
    "creditos_previos",
    "atrasos_previos_30d",
    "porcentaje_pago_puntual",
    "monto_solicitado_cop",
    "plazo_meses",
    "cuota_estimada_cop",
]

NUMERIC_COMPLETE = [
    "ingresos_mensuales_cop",
    "obligaciones_mensuales_cop",
    "creditos_previos",
    "atrasos_previos_30d",
    "monto_solicitado_cop",
    "plazo_meses",
    "cuota_estimada_cop",
]

NUMERIC_WITH_MISSING = [
    "antiguedad_laboral_meses",
    "meses_historial_crediticio",
    "porcentaje_pago_puntual",
]

CATEGORICAL_FEATURES = ["tipo_empleo"]

# Costos ficticios de negocio para optimización de umbral sobre validación
COST_FN_APROBAR_INCUMPLIDOR = 5.0
COST_FP_RECHAZAR_PAGADOR = 1.0
AP_TIE_TOLERANCE = 0.005


def build_preprocessor(scale_numeric: bool = True, feature_subset: List[str] | None = None) -> ColumnTransformer:
    """Construye el ColumnTransformer que aprende parámetros únicamente de entrenamiento.

    - Numéricas completas: imputación mediana (seguridad ante producción) + escalado opcional.
    - Numéricas con faltantes estructurales/permitidos: imputación mediana + indicador binario
      de dato faltante (`add_indicator=True`), preservando la señal de ausencia de historial
      crediticio cuando `porcentaje_pago_puntual` es nulo (`creditos_previos == 0`).
    - Categórica `tipo_empleo`: imputación con categoría explícita `'faltante'` + One-Hot Encoding.
    """
    active_features = feature_subset or FEATURES
    num_complete = [c for c in NUMERIC_COMPLETE if c in active_features]
    num_missing = [c for c in NUMERIC_WITH_MISSING if c in active_features]
    cat_cols = [c for c in CATEGORICAL_FEATURES if c in active_features]

    num_complete_steps = [("imputer", SimpleImputer(strategy="median"))]
    num_missing_steps = [("imputer", SimpleImputer(strategy="median", add_indicator=True))]
    if scale_numeric:
        num_complete_steps.append(("scaler", StandardScaler()))
        num_missing_steps.append(("scaler", StandardScaler()))

    cat_steps = [
        ("imputer", SimpleImputer(strategy="constant", fill_value="faltante")),
        (
            "onehot",
            OneHotEncoder(
                categories=[["dependiente", "independiente", "temporal", "faltante"]],
                handle_unknown="ignore",
                sparse_output=False,
            ),
        ),
    ]

    return ColumnTransformer(
        transformers=[
            ("num_complete", Pipeline(num_complete_steps), num_complete),
            ("num_missing", Pipeline(num_missing_steps), num_missing),
            ("cat", Pipeline(cat_steps), cat_cols),
        ],
        remainder="drop",
    )
```

---

## 2. EDA reproducible y partición estratificada 60/20/20 (`ml/src/eda_and_split.py`)

Valida los dos conjuntos de datos, genera el diccionario y el reporte exploratorio, y divide las 12,000 solicitudes históricas en `train` (7,200), `val` (2,400) y `test` (2,400) preservando la proporción de `incumplimiento_90d` (`~30.56%`) con semilla fija `42`.

```python
    # Partición 60 / 20 / 20 estratificada con semilla fija 42
    train_df, temp_df = train_test_split(
        hist_df,
        test_size=0.40,
        stratify=hist_df[TARGET_COLUMN],
        random_state=RANDOM_SEED,
    )
    val_df, test_df = train_test_split(
        temp_df,
        test_size=0.50,
        stratify=temp_df[TARGET_COLUMN],
        random_state=RANDOM_SEED,
    )

    assert len(train_df) == 7200 and len(val_df) == 2400 and len(test_df) == 2400
    assert set(train_df["solicitud_id"]).isdisjoint(set(val_df["solicitud_id"]))
    assert set(train_df["solicitud_id"]).isdisjoint(set(test_df["solicitud_id"]))
    assert set(val_df["solicitud_id"]).isdisjoint(set(test_df["solicitud_id"]))
```

---

## 3. Entrenamiento en MLflow, selección y umbral óptimo (`ml/src/train_and_select.py`)

Registra las 7 corridas en el experimento `credimarket-riesgo-v1`, aplica la regla de selección sobre validación (`val_average_precision` con desempate en `<= 0.005` por `val_brier_score` y menor complejidad), optimiza el umbral con pesos `5:1` en validación y evalúa el conjunto `test` una única vez tras congelar todas las decisiones:

```python
    # 4. Selección del modelo ganador según criterio preestablecido:
    # Mayor val_average_precision; si están a <= 0.005 del máximo, menor val_brier_score y menor complexity_rank
    non_baseline = [r for r in runs_summary if r["family"] != "baseline"]
    max_val_ap = max(r["val_metrics"]["average_precision"] for r in non_baseline)
    finalists = [
        r for r in non_baseline if (max_val_ap - r["val_metrics"]["average_precision"]) <= AP_TIE_TOLERANCE
    ]
    finalists.sort(
        key=lambda r: (
            r["val_metrics"]["brier_score"],
            r["complexity_rank"],
            r["val_predict_latency_ms"],
        )
    )
    winner = finalists[0]
    winner_run_name = winner["run_name"]
    winner_run_id = winner["run_id"]
    winner_pipeline = trained_pipelines[winner_run_name]
    winner_val_prob = val_probs_by_run[winner_run_name]

    # 5. Ajustar el umbral óptimo sobre validación con costos ficticios (FN=5, FP=1)
    threshold_opt = optimize_threshold_on_validation(y_val, winner_val_prob)
    optimal_threshold = float(threshold_opt["optimal_threshold"])

    # 6. Congelar decisiones y evaluar el conjunto de prueba (test) UNA SOLA VEZ
    test_prob = winner_pipeline.predict_proba(X_test)[:, 1]
    test_metrics_optimal = compute_classification_metrics(y_test, test_prob, threshold=optimal_threshold)
```

---

## 4. Verificación automatizada de la Fase 7 (`scripts/check_phase7.py`)

Comprueba la inmutabilidad SHA-256 de los archivos CSV originales, la existencia y validez de los reportes y particiones 60/20/20, la presencia de las 7 corridas y sus artefactos en el servidor MLflow (`http://mlflow:5000`), y la inferencia por lotes sobre las 200 solicitudes nuevas sin etiqueta.
