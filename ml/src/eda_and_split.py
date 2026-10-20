"""Validación de datos, EDA reproducible, diccionario de datos y particionado 60/20/20 estratificado."""
import json
from pathlib import Path
from typing import Any, Dict
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from .contract import (
    EXPECTED_HASHES,
    FEATURES,
    ID_COLUMNS,
    EXCLUDED_CONSTANT_COLUMNS,
    TARGET_COLUMN,
    RANDOM_SEED,
    sha256_file,
    validate_dataset,
)

ROOT = Path(__file__).resolve().parents[2]
ML_DIR = ROOT / "ml"
SPLITS_DIR = ML_DIR / "data" / "splits"
MANIFESTS_DIR = ML_DIR / "manifests"
REPORTS_DIR = ML_DIR / "reports"


def build_data_dictionary(hist_df: pd.DataFrame, nuevas_df: pd.DataFrame) -> Dict[str, Any]:
    """Construye el diccionario de datos distinguiendo unidades observadas y reglas del dominio."""
    columns_spec = [
        {
            "name": "solicitud_id",
            "role": "identifier",
            "included_in_model": False,
            "type": "string",
            "unit": "ID alfanumérico (SOL-XXXXXXX)",
            "nullable": False,
            "observed_historical": f"{hist_df['solicitud_id'].iloc[0]} .. {hist_df['solicitud_id'].iloc[-1]} (12000 únicos)",
            "observed_new": f"{nuevas_df['solicitud_id'].iloc[0]} .. {nuevas_df['solicitud_id'].iloc[-1]} (200 únicos)",
            "domain_rule": "Identificador único de solicitud; excluido estrictamente de los predictores para evitar memorización/fuga.",
        },
        {
            "name": "cliente_id",
            "role": "identifier",
            "included_in_model": False,
            "type": "string",
            "unit": "ID alfanumérico (CLI-XXXXXXX) / UUID en servicio",
            "nullable": False,
            "observed_historical": "12000 clientes distintos (1 por fila)",
            "observed_new": "200 clientes distintos sin intersección con histórico",
            "domain_rule": "Clave externa de cliente; excluida del estimador.",
        },
        {
            "name": "ingresos_mensuales_cop",
            "role": "predictor",
            "included_in_model": True,
            "type": "number",
            "unit": "COP / mes",
            "nullable": False,
            "observed_historical": f"[{hist_df['ingresos_mensuales_cop'].min():.0f}, {hist_df['ingresos_mensuales_cop'].max():.0f}]",
            "observed_new": f"[{nuevas_df['ingresos_mensuales_cop'].min():.0f}, {nuevas_df['ingresos_mensuales_cop'].max():.0f}]",
            "domain_rule": "Estrictamente positivo (> 0). En pipeline: imputación mediana de respaldo y escalado en modelos lineales.",
        },
        {
            "name": "obligaciones_mensuales_cop",
            "role": "predictor",
            "included_in_model": True,
            "type": "number",
            "unit": "COP / mes",
            "nullable": False,
            "observed_historical": f"[{hist_df['obligaciones_mensuales_cop'].min():.0f}, {hist_df['obligaciones_mensuales_cop'].max():.0f}]",
            "observed_new": f"[{nuevas_df['obligaciones_mensuales_cop'].min():.0f}, {nuevas_df['obligaciones_mensuales_cop'].max():.0f}]",
            "domain_rule": "No negativo (>= 0). Representa egresos financieros mensuales vigentes del solicitante.",
        },
        {
            "name": "tipo_empleo",
            "role": "predictor",
            "included_in_model": True,
            "type": "categorical",
            "unit": "Categoría laboral",
            "nullable": True,
            "observed_historical": "dependiente, independiente, temporal, null (93 faltantes)",
            "observed_new": "dependiente, independiente, temporal, null (2 faltantes)",
            "domain_rule": "Valores admitidos: {'dependiente', 'independiente', 'temporal', null}. En pipeline: imputación a categoría explícita 'faltante' + One-Hot Encoding.",
        },
        {
            "name": "antiguedad_laboral_meses",
            "role": "predictor",
            "included_in_model": True,
            "type": "integer",
            "unit": "meses",
            "nullable": True,
            "observed_historical": f"[{hist_df['antiguedad_laboral_meses'].min():.0f}, {hist_df['antiguedad_laboral_meses'].max():.0f}] (91 faltantes)",
            "observed_new": f"[{nuevas_df['antiguedad_laboral_meses'].min():.0f}, {nuevas_df['antiguedad_laboral_meses'].max():.0f}] (1 faltante)",
            "domain_rule": "Entero >= 0 o null. En pipeline: imputación por mediana de train + indicador binario de faltante.",
        },
        {
            "name": "meses_historial_crediticio",
            "role": "predictor",
            "included_in_model": True,
            "type": "integer",
            "unit": "meses",
            "nullable": True,
            "observed_historical": f"[{hist_df['meses_historial_crediticio'].min():.0f}, {hist_df['meses_historial_crediticio'].max():.0f}] (97 faltantes)",
            "observed_new": f"[{nuevas_df['meses_historial_crediticio'].min():.0f}, {nuevas_df['meses_historial_crediticio'].max():.0f}] (1 faltante)",
            "domain_rule": "Entero >= 0 o null. En pipeline: imputación por mediana de train + indicador binario de faltante.",
        },
        {
            "name": "creditos_previos",
            "role": "predictor",
            "included_in_model": True,
            "type": "integer",
            "unit": "conteo de créditos",
            "nullable": False,
            "observed_historical": f"[{hist_df['creditos_previos'].min():.0f}, {hist_df['creditos_previos'].max():.0f}]",
            "observed_new": f"[{nuevas_df['creditos_previos'].min():.0f}, {nuevas_df['creditos_previos'].max():.0f}]",
            "domain_rule": "Entero >= 0 sin nulos. Cuando vale 0, porcentaje_pago_puntual debe ser null.",
        },
        {
            "name": "atrasos_previos_30d",
            "role": "predictor",
            "included_in_model": True,
            "type": "integer",
            "unit": "conteo de moras >30 días",
            "nullable": False,
            "observed_historical": f"[{hist_df['atrasos_previos_30d'].min():.0f}, {hist_df['atrasos_previos_30d'].max():.0f}]",
            "observed_new": f"[{nuevas_df['atrasos_previos_30d'].min():.0f}, {nuevas_df['atrasos_previos_30d'].max():.0f}]",
            "domain_rule": "Entero >= 0 sin nulos.",
        },
        {
            "name": "porcentaje_pago_puntual",
            "role": "predictor",
            "included_in_model": True,
            "type": "number",
            "unit": "porcentaje [0, 100]",
            "nullable": True,
            "observed_historical": f"[{hist_df['porcentaje_pago_puntual'].min():.2f}, {hist_df['porcentaje_pago_puntual'].max():.2f}] (2473 nulos cuando creditos_previos=0)",
            "observed_new": f"[{nuevas_df['porcentaje_pago_puntual'].min():.2f}, {nuevas_df['porcentaje_pago_puntual'].max():.2f}] (43 nulos cuando creditos_previos=0)",
            "domain_rule": "Null si y solo si creditos_previos == 0; de lo contrario en [0, 100]. Nunca imputar como 0: se imputa con la mediana de train acompañada de bandera binaria add_indicator=True.",
        },
        {
            "name": "monto_solicitado_cop",
            "role": "predictor",
            "included_in_model": True,
            "type": "number",
            "unit": "COP",
            "nullable": False,
            "observed_historical": f"[{hist_df['monto_solicitado_cop'].min():.0f}, {hist_df['monto_solicitado_cop'].max():.0f}]",
            "observed_new": f"[{nuevas_df['monto_solicitado_cop'].min():.0f}, {nuevas_df['monto_solicitado_cop'].max():.0f}]",
            "domain_rule": "Política financiera v1: [500000, 15000000] COP.",
        },
        {
            "name": "plazo_meses",
            "role": "predictor",
            "included_in_model": True,
            "type": "integer",
            "unit": "meses",
            "nullable": False,
            "observed_historical": "Conjunto discreto {6, 12, 18, 24, 36}",
            "observed_new": "Conjunto discreto {6, 12, 18, 24, 36}",
            "domain_rule": "Plazo de amortización en {6, 12, 18, 24, 36}.",
        },
        {
            "name": "tasa_mensual_simulada",
            "role": "constant_parameter",
            "included_in_model": False,
            "type": "number",
            "unit": "proporción mensual (0.018 = 1.8% MV)",
            "nullable": False,
            "observed_historical": "Constante 0.0180 en las 12000 filas",
            "observed_new": "Constante 0.0180 en las 200 filas",
            "domain_rule": "Varianza cero; se excluye del estimador pero se conserva como parámetro financiero para el cálculo de cuota.",
        },
        {
            "name": "cuota_estimada_cop",
            "role": "predictor",
            "included_in_model": True,
            "type": "number",
            "unit": "COP / mes",
            "nullable": False,
            "observed_historical": f"[{hist_df['cuota_estimada_cop'].min():.2f}, {hist_df['cuota_estimada_cop'].max():.2f}]",
            "observed_new": f"[{nuevas_df['cuota_estimada_cop'].min():.2f}, {nuevas_df['cuota_estimada_cop'].max():.2f}]",
            "domain_rule": "Derivada por fórmula de anualidad sobre monto y plazo. Aunque es función no lineal de monto y plazo, se conserva porque aporta relación lineal directa frente al ingreso mensual en modelos lineales.",
        },
        {
            "name": "incumplimiento_90d",
            "role": "target",
            "included_in_model": False,
            "type": "integer (binary)",
            "unit": "0 = cumplido, 1 = incumplimiento >= 90 días",
            "nullable": False,
            "observed_historical": "1: 3667 (30.56%), 0: 8333 (69.44%)",
            "observed_new": "Ausente (lote sin etiqueta para inferencia batch)",
            "domain_rule": "Variable objetivo en entrenamiento/validación/prueba. Clase positiva = 1.",
        },
    ]
    return {
        "version": "1.0.0",
        "total_columns_historical": 15,
        "total_columns_new": 14,
        "model_features_count": len(FEATURES),
        "model_features": FEATURES,
        "excluded_columns": ID_COLUMNS + EXCLUDED_CONSTANT_COLUMNS + [TARGET_COLUMN],
        "columns": columns_spec,
    }


def compute_numeric_summary(df: pd.DataFrame, numeric_cols: list[str]) -> Dict[str, Any]:
    summary = {}
    for col in numeric_cols:
        s = pd.to_numeric(df[col], errors="coerce")
        valid = s.dropna()
        summary[col] = {
            "count": int(valid.count()),
            "missing": int(s.isna().sum()),
            "missing_rate": round(float(s.isna().mean()), 6),
            "mean": round(float(valid.mean()), 4),
            "std": round(float(valid.std()), 4),
            "min": round(float(valid.min()), 4),
            "p05": round(float(np.percentile(valid, 5)), 4),
            "p25": round(float(np.percentile(valid, 25)), 4),
            "p50": round(float(np.percentile(valid, 50)), 4),
            "p75": round(float(np.percentile(valid, 75)), 4),
            "p95": round(float(np.percentile(valid, 95)), 4),
            "max": round(float(valid.max()), 4),
        }
    return summary


def run_eda_and_split() -> Dict[str, Any]:
    SPLITS_DIR.mkdir(parents=True, exist_ok=True)
    MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    hist_path = ROOT / "prestamos_entrenamiento.csv"
    nuevas_path = ROOT / "solicitudes_nuevas.csv"

    hist_hash = sha256_file(hist_path)
    nuevas_hash = sha256_file(nuevas_path)

    if hist_hash != EXPECTED_HASHES["prestamos_entrenamiento.csv"]:
        raise ValueError(f"Hash inesperado para prestamos_entrenamiento.csv: {hist_hash}")
    if nuevas_hash != EXPECTED_HASHES["solicitudes_nuevas.csv"]:
        raise ValueError(f"Hash inesperado para solicitudes_nuevas.csv: {nuevas_hash}")

    hist_df = pd.read_csv(hist_path)
    nuevas_df = pd.read_csv(nuevas_path)

    val_hist = validate_dataset(hist_df, is_training=True)
    val_nuevas = validate_dataset(nuevas_df, is_training=False)

    # Verificar disjunción entre histórico y solicitudes nuevas
    shared_clientes = set(hist_df["cliente_id"]).intersection(set(nuevas_df["cliente_id"]))
    shared_solicitudes = set(hist_df["solicitud_id"]).intersection(set(nuevas_df["solicitud_id"]))
    if shared_clientes or shared_solicitudes:
        raise ValueError("Existen identificadores compartidos entre prestamos_entrenamiento.csv y solicitudes_nuevas.csv")

    numeric_cols = [c for c in FEATURES if c != "tipo_empleo"] + ["tasa_mensual_simulada"]

    # Tasas de incumplimiento por segmento en el histórico
    by_empleo = {}
    for emp_val, grp in hist_df.fillna({"tipo_empleo": "faltante"}).groupby("tipo_empleo"):
        by_empleo[str(emp_val)] = {
            "count": int(len(grp)),
            "share": round(float(len(grp) / len(hist_df)), 6),
            "default_rate": round(float(grp[TARGET_COLUMN].mean()), 6),
        }

    by_plazo = {}
    for plazo_val, grp in hist_df.groupby("plazo_meses"):
        by_plazo[str(int(plazo_val))] = {
            "count": int(len(grp)),
            "share": round(float(len(grp) / len(hist_df)), 6),
            "default_rate": round(float(grp[TARGET_COLUMN].mean()), 6),
        }

    no_hist_mask = hist_df["creditos_previos"] == 0
    default_rate_no_prior_credits = round(float(hist_df.loc[no_hist_mask, TARGET_COLUMN].mean()), 6)
    default_rate_with_prior_credits = round(float(hist_df.loc[~no_hist_mask, TARGET_COLUMN].mean()), 6)

    # Correlaciones con el objetivo y redundancia de cuota
    corr_df = hist_df[[c for c in FEATURES if c != "tipo_empleo"] + [TARGET_COLUMN]].corr()
    target_correlations = {
        col: round(float(corr_df.loc[col, TARGET_COLUMN]), 6)
        for col in FEATURES
        if col != "tipo_empleo"
    }
    cuota_correlations = {
        "corr_cuota_monto": round(float(corr_df.loc["cuota_estimada_cop", "monto_solicitado_cop"]), 6),
        "corr_cuota_plazo": round(float(corr_df.loc["cuota_estimada_cop", "plazo_meses"]), 6),
        "corr_cuota_target": round(float(corr_df.loc["cuota_estimada_cop", TARGET_COLUMN]), 6),
    }

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

    train_path = SPLITS_DIR / "train.csv"
    val_path = SPLITS_DIR / "val.csv"
    test_path = SPLITS_DIR / "test.csv"

    train_df.to_csv(train_path, index=False)
    val_df.to_csv(val_path, index=False)
    test_df.to_csv(test_path, index=False)

    def split_stats(part_df: pd.DataFrame, path: Path) -> Dict[str, Any]:
        pos = int((part_df[TARGET_COLUMN] == 1).sum())
        neg = int((part_df[TARGET_COLUMN] == 0).sum())
        return {
            "file": str(path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256_file(path),
            "rows": int(len(part_df)),
            "positive_class_1": pos,
            "negative_class_0": neg,
            "positive_rate": round(pos / len(part_df), 6),
            "first_solicitud_id": str(part_df["solicitud_id"].iloc[0]),
            "last_solicitud_id": str(part_df["solicitud_id"].iloc[-1]),
        }

    split_manifest = {
        "random_seed": RANDOM_SEED,
        "stratify_column": TARGET_COLUMN,
        "proportions": {"train": 0.60, "val": 0.20, "test": 0.20},
        "source_files": {
            "prestamos_entrenamiento.csv": {
                "sha256": hist_hash,
                "rows": int(len(hist_df)),
                "columns": int(len(hist_df.columns)),
            },
            "solicitudes_nuevas.csv": {
                "sha256": nuevas_hash,
                "rows": int(len(nuevas_df)),
                "columns": int(len(nuevas_df.columns)),
                "usage": "Reserved strictly for unlabeled batch inference and API parity checks in Phase 8",
            },
        },
        "splits": {
            "train": split_stats(train_df, train_path),
            "val": split_stats(val_df, val_path),
            "test": split_stats(test_df, test_path),
        },
    }

    eda_report = {
        "source_hashes": EXPECTED_HASHES,
        "validation_historical": val_hist,
        "validation_new_requests": val_nuevas,
        "shared_clients_between_files": 0,
        "class_distribution_historical": {
            "total": int(len(hist_df)),
            "positive_incumplimiento_1": int((hist_df[TARGET_COLUMN] == 1).sum()),
            "negative_cumplimiento_0": int((hist_df[TARGET_COLUMN] == 0).sum()),
            "positive_rate": round(float(hist_df[TARGET_COLUMN].mean()), 6),
            "majority_baseline_accuracy": round(float(1.0 - hist_df[TARGET_COLUMN].mean()), 6),
        },
        "numeric_summary_historical": compute_numeric_summary(hist_df, numeric_cols),
        "numeric_summary_new_requests": compute_numeric_summary(nuevas_df, numeric_cols),
        "default_rate_by_tipo_empleo": by_empleo,
        "default_rate_by_plazo_meses": by_plazo,
        "missing_porcentaje_pago_puntual_analysis": {
            "historical_missing_count": int(no_hist_mask.sum()),
            "new_requests_missing_count": int((nuevas_df["creditos_previos"] == 0).sum()),
            "exact_equivalence_with_zero_prior_credits": True,
            "default_rate_when_creditos_previos_eq_0": default_rate_no_prior_credits,
            "default_rate_when_creditos_previos_gt_0": default_rate_with_prior_credits,
            "decision": "Impute with training median and add missingness indicator (add_indicator=True); never replace with 0.",
        },
        "target_correlations_historical": target_correlations,
        "cuota_redundancy_analysis": cuota_correlations,
    }

    data_dict = build_data_dictionary(hist_df, nuevas_df)

    (REPORTS_DIR / "data_dictionary.json").write_text(json.dumps(data_dict, indent=2, ensure_ascii=False), encoding="utf-8")
    (REPORTS_DIR / "eda_report.json").write_text(json.dumps(eda_report, indent=2, ensure_ascii=False), encoding="utf-8")
    (MANIFESTS_DIR / "split_manifest.json").write_text(json.dumps(split_manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "split_manifest": split_manifest,
        "eda_report": eda_report,
        "data_dictionary": data_dict,
    }


if __name__ == "__main__":
    result = run_eda_and_split()
    print("EDA y particiones 60/20/20 generadas exitosamente:")
    print(json.dumps(result["split_manifest"]["splits"], indent=2))
