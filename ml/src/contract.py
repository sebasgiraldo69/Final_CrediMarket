"""Contrato de datos, validación semántica y construcción de pipelines sin fuga de datos."""
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple
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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def calcular_cuota_anualidad(monto_cop: float | Decimal, plazo_meses: int, tasa_mensual: Decimal = TASA_MENSUAL_FIJA) -> Decimal:
    """Calcula la cuota mensual con la fórmula de anualidad redondeada a 2 decimales (HALF_UP)."""
    monto = Decimal(str(monto_cop))
    r = Decimal(str(tasa_mensual))
    n = int(plazo_meses)
    factor = Decimal("1") - (Decimal("1") + r) ** Decimal(-n)
    cuota = (monto * r) / factor
    return cuota.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_features_df(df: pd.DataFrame, feature_names: List[str] = FEATURES) -> pd.DataFrame:
    """Normaliza tipos de las variables de entrada para entrenamiento e inferencia sin alterar valores."""
    out = df[feature_names].copy()
    for col in feature_names:
        if col == "tipo_empleo":
            out[col] = out[col].replace({None: np.nan, "": np.nan}).astype(object)
        else:
            out[col] = pd.to_numeric(out[col], errors="coerce").astype("float64")
    return out


def validate_dataset(df: pd.DataFrame, is_training: bool = True) -> Dict[str, Any]:
    """Valida tipos, rangos, nulos permitidos, invariantes semánticos y relación de anualidad."""
    expected_cols = ID_COLUMNS + FEATURES[:10] + EXCLUDED_CONSTANT_COLUMNS + [FEATURES[10]]
    if is_training:
        expected_cols = expected_cols + [TARGET_COLUMN]

    missing_cols = [c for c in expected_cols if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Columnas faltantes en el dataset: {missing_cols}")

    errors: List[str] = []

    # 1. Duplicados de IDs y filas
    dup_rows = int(df.duplicated().sum())
    dup_sol = int(df["solicitud_id"].duplicated().sum())
    dup_cli = int(df["cliente_id"].duplicated().sum())
    if dup_rows > 0 or dup_sol > 0 or dup_cli > 0:
        errors.append(f"Duplicados detectados: filas={dup_rows}, solicitud_id={dup_sol}, cliente_id={dup_cli}")

    # 2. Ingresos y obligaciones
    if (df["ingresos_mensuales_cop"].isna() | (df["ingresos_mensuales_cop"] <= 0)).any():
        errors.append("ingresos_mensuales_cop contiene nulos o valores <= 0")
    if (df["obligaciones_mensuales_cop"].isna() | (df["obligaciones_mensuales_cop"] < 0)).any():
        errors.append("obligaciones_mensuales_cop contiene nulos o valores < 0")

    # 3. Tipo de empleo (permite nulos, valores válidos en catálogo)
    emp_non_null = df["tipo_empleo"].dropna()
    invalid_emp = set(emp_non_null.unique()) - set(TIPOS_EMPLEO_VALIDOS)
    if invalid_emp:
        errors.append(f"Categorías desconocidas en tipo_empleo: {invalid_emp}")

    # 4. Antigüedad laboral y meses de historial (permiten nulos, enteros >= 0)
    for col in ("antiguedad_laboral_meses", "meses_historial_crediticio"):
        s = df[col].dropna()
        if (s < 0).any():
            errors.append(f"{col} contiene valores negativos")
        if ((s % 1) != 0).any():
            errors.append(f"{col} contiene valores con parte fraccionaria no entera")

    # 5. Créditos previos y atrasos previos (sin nulos, enteros >= 0)
    for col in ("creditos_previos", "atrasos_previos_30d"):
        if df[col].isna().any() or (df[col] < 0).any() or ((df[col] % 1) != 0).any():
            errors.append(f"{col} contiene nulos, negativos o no enteros")

    # 6. Regla semántica estricta de porcentaje_pago_puntual:
    # null si y solo si creditos_previos == 0; cuando no es null, en [0, 100]
    zero_cred = df["creditos_previos"] == 0
    null_pct = df["porcentaje_pago_puntual"].isna()
    if not (zero_cred == null_pct).all():
        mismatch = int((zero_cred != null_pct).sum())
        errors.append(f"Incumplimiento de regla semántica creditos_previos==0 <=> porcentaje_pago_puntual is null en {mismatch} filas")
    pct_valid = df.loc[~null_pct, "porcentaje_pago_puntual"]
    if ((pct_valid < 0) | (pct_valid > 100)).any():
        errors.append("porcentaje_pago_puntual fuera de rango [0, 100]")

    # 7. Monto, plazo, tasa y cuota
    if (df["monto_solicitado_cop"].isna() | (df["monto_solicitado_cop"] < float(MONTO_MIN_COP)) | (df["monto_solicitado_cop"] > float(MONTO_MAX_COP))).any():
        errors.append("monto_solicitado_cop fuera de política [500000, 15000000]")
    if (~df["plazo_meses"].isin(PLAZOS_VALIDOS)).any():
        errors.append("plazo_meses contiene valores fuera de {6, 12, 18, 24, 36}")
    if not np.allclose(df["tasa_mensual_simulada"].values, float(TASA_MENSUAL_FIJA), atol=1e-8):
        errors.append("tasa_mensual_simulada no es constante en 0.018")

    # Verificar fórmula de anualidad
    r = float(TASA_MENSUAL_FIJA)
    cuota_teorica = df["monto_solicitado_cop"] * r / (1.0 - np.power(1.0 + r, -df["plazo_meses"]))
    max_diff_cuota = float(np.max(np.abs(df["cuota_estimada_cop"] - cuota_teorica)))
    if max_diff_cuota > 0.01:
        errors.append(f"cuota_estimada_cop difiere de la anualidad teórica en hasta {max_diff_cuota:.4f} COP")

    # 8. Etiqueta objetivo en histórico
    if is_training:
        if (~df[TARGET_COLUMN].isin([0, 1])).any():
            errors.append("incumplimiento_90d contiene valores distintos de {0, 1}")

    if errors:
        raise ValueError("Errores de validación del dataset: " + "; ".join(errors))

    return {
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "distinct_solicitudes": int(df["solicitud_id"].nunique()),
        "distinct_clientes": int(df["cliente_id"].nunique()),
        "duplicate_rows": dup_rows,
        "missing_counts": {col: int(df[col].isna().sum()) for col in df.columns if int(df[col].isna().sum()) > 0},
        "zero_creditos_matches_null_pct": bool((zero_cred == null_pct).all()),
        "tasa_constante": float(TASA_MENSUAL_FIJA),
        "max_cuota_formula_diff_cop": round(max_diff_cuota, 6),
    }


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


def get_candidate_specifications() -> List[Dict[str, Any]]:
    """Define el baseline y los 6 candidatos requeridos en el plan de desarrollo."""
    return [
        {
            "run_name": "00_baseline_dummy_prior",
            "algorithm": "DummyClassifier",
            "family": "baseline",
            "complexity_rank": 0,
            "scale_numeric": False,
            "params": {"strategy": "prior", "random_state": RANDOM_SEED},
            "estimator": DummyClassifier(strategy="prior", random_state=RANDOM_SEED),
        },
        {
            "run_name": "01_logreg_c01",
            "algorithm": "LogisticRegression",
            "family": "logistic_regression",
            "complexity_rank": 1,
            "scale_numeric": True,
            "params": {"C": 0.1, "max_iter": 1000, "solver": "lbfgs", "random_state": RANDOM_SEED},
            "estimator": LogisticRegression(C=0.1, max_iter=1000, solver="lbfgs", random_state=RANDOM_SEED),
        },
        {
            "run_name": "02_logreg_c1",
            "algorithm": "LogisticRegression",
            "family": "logistic_regression",
            "complexity_rank": 2,
            "scale_numeric": True,
            "params": {"C": 1.0, "max_iter": 1000, "solver": "lbfgs", "random_state": RANDOM_SEED},
            "estimator": LogisticRegression(C=1.0, max_iter=1000, solver="lbfgs", random_state=RANDOM_SEED),
        },
        {
            "run_name": "03_tree_depth4_leaf20",
            "algorithm": "DecisionTreeClassifier",
            "family": "decision_tree",
            "complexity_rank": 3,
            "scale_numeric": False,
            "params": {"max_depth": 4, "min_samples_leaf": 20, "random_state": RANDOM_SEED},
            "estimator": DecisionTreeClassifier(max_depth=4, min_samples_leaf=20, random_state=RANDOM_SEED),
        },
        {
            "run_name": "04_tree_depth8_leaf20",
            "algorithm": "DecisionTreeClassifier",
            "family": "decision_tree",
            "complexity_rank": 4,
            "scale_numeric": False,
            "params": {"max_depth": 8, "min_samples_leaf": 20, "random_state": RANDOM_SEED},
            "estimator": DecisionTreeClassifier(max_depth=8, min_samples_leaf=20, random_state=RANDOM_SEED),
        },
        {
            "run_name": "05_rf_200_depth8_leaf5",
            "algorithm": "RandomForestClassifier",
            "family": "random_forest",
            "complexity_rank": 5,
            "scale_numeric": False,
            "params": {"n_estimators": 200, "max_depth": 8, "min_samples_leaf": 5, "random_state": RANDOM_SEED},
            "estimator": RandomForestClassifier(
                n_estimators=200, max_depth=8, min_samples_leaf=5, random_state=RANDOM_SEED, n_jobs=-1
            ),
        },
        {
            "run_name": "06_rf_200_unlim_leaf5",
            "algorithm": "RandomForestClassifier",
            "family": "random_forest",
            "complexity_rank": 6,
            "scale_numeric": False,
            "params": {"n_estimators": 200, "max_depth": None, "min_samples_leaf": 5, "random_state": RANDOM_SEED},
            "estimator": RandomForestClassifier(
                n_estimators=200, max_depth=None, min_samples_leaf=5, random_state=RANDOM_SEED, n_jobs=-1
            ),
        },
    ]


def build_candidate_pipeline(spec: Dict[str, Any], feature_subset: List[str] | None = None) -> Pipeline:
    """Construye el Pipeline completo (preprocesamiento + estimador) para un candidato."""
    preprocessor = build_preprocessor(scale_numeric=spec["scale_numeric"], feature_subset=feature_subset)
    return Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("classifier", spec["estimator"]),
        ]
    )
