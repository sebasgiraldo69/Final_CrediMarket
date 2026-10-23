# Fase 7: Preparar datos y entrenar el modelo

Implementación del pipeline reproducible de preparación de datos, análisis exploratorio (EDA), particionado estratificado 60/20/20 sin fuga de datos, entrenamiento de baseline y 6 candidatos en MLflow (`credimarket-riesgo-v1`), selección por validación, optimización de umbral bajo costos asimétricos de negocio y evaluación única en el conjunto de prueba (`test`).

## Ejecutar o verificar la fase

Con el stack de Docker Compose activo (`mlflow` en `http://localhost:5000`):

```powershell
# Re-ejecutar EDA, particiones y entrenamiento en MLflow (opcional; los artefactos ya están versionados)
python scripts/run_phase7_training.py

# Ejecutar la suite de validación e integridad de la Fase 7
python scripts/check_phase7.py
```

También se pueden inspeccionar las 7 ejecuciones, métricas comparativas y artefactos directamente en la interfaz web de MLflow: http://localhost:5000 (experimento `credimarket-riesgo-v1`).

## Código y entregables

- [`ml/src/contract.py`](../ml/src/contract.py): contrato de las 11 variables predictoras (`FEATURES`), validación semántica e invariantes de negocio, fórmula de anualidad con redondeo `ROUND_HALF_UP`, y construcción del `ColumnTransformer` + `Pipeline` de `scikit-learn`.
- [`ml/src/eda_and_split.py`](../ml/src/eda_and_split.py): verificación SHA-256 de los CSV originales, generación del diccionario de datos y reporte de EDA, y partición estratificada `60 / 20 / 20` con `random_state = 42`.
- [`ml/src/train_and_select.py`](../ml/src/train_and_select.py): estudio de redundancia de `cuota_estimada_cop` sobre validación, entrenamiento de 1 baseline + 6 candidatos en MLflow, regla de selección, optimización del umbral de decisión (`FN = 5`, `FP = 1`) sobre validación y evaluación única en `test`.
- [`docs/diccionario_datos.md`](diccionario_datos.md) y [`ml/reports/data_dictionary.json`](../ml/reports/data_dictionary.json): diccionario de las 15 columnas históricas y 14 de solicitudes nuevas, separando unidades, rangos observados y reglas del dominio.
- [`ml/reports/eda_report.json`](../ml/reports/eda_report.json): estadísticas descriptivas, tasas de mora por segmento y análisis de valores faltantes.
- [`ml/manifests/split_manifest.json`](../ml/manifests/split_manifest.json): hashes SHA-256, tamaños y estratificación de `train.csv` (7,200), `val.csv` (2,400) y `test.csv` (2,400).
- [`ml/manifests/candidate_v1.json`](../ml/manifests/candidate_v1.json) y `ml/artifacts/candidate_v1/pipeline.joblib`: manifiesto y artefacto serializado del modelo ganador (`02_logreg_c1`) listo para promoción en la Fase 8.
- [`ml/reports/model_selection_report.json`](../ml/reports/model_selection_report.json): reporte comparativo de las 7 corridas, curva de costos por umbral y evaluación en `test`.
- [`scripts/check_phase7.py`](../scripts/check_phase7.py): prueba automatizada de extremo a extremo.


---

## Decisiones de datos, EDA y prevención de fuga

1. **Inmutabilidad de fuentes originales:**
   - `prestamos_entrenamiento.csv` (`12,000` filas, 15 columnas, SHA-256 `c6cdc437c3aecc9116bc8b978df421d5a7600634c1ad7d6f82e58222a2446ecd`).
   - `solicitudes_nuevas.csv` (`200` filas, 14 columnas sin `incumplimiento_90d`, SHA-256 `1430d7b34e924d5e4170c4fb9d9a412c1000af17c062af513ef15e44a1a7f1f7`).
   - Cero clientes o solicitudes compartidas entre ambos archivos (`shared_clients_between_files = 0`).
2. **Exclusión de identificadores y constantes:**
   - Se excluyen `solicitud_id` y `cliente_id` para evitar memorización de identificadores.
   - Se excluye `tasa_mensual_simulada` por tener varianza cero (`0.018` constante en las 12,000 filas históricas y en las 200 nuevas).
3. **Semántica de valores faltantes (`porcentaje_pago_puntual`):**
   - En los 2,473 registros históricos (y 43 de `solicitudes_nuevas.csv`) donde `porcentaje_pago_puntual` es nulo, se cumple exactamente la equivalencia `creditos_previos == 0`.
   - La tasa de incumplimiento de solicitantes sin créditos previos es **34.73%**, frente a **29.47%** en quienes sí tienen historial. Imputar con `0` confundiría "sin historial" con "0% de pagos puntuales (moroso crónico)".
   - **Solución en el pipeline:** `SimpleImputer(strategy="median", add_indicator=True)` ajustado exclusivamente sobre `train`, preservando la señal binaria de ausencia de historial crediticio junto con la mediana de entrenamiento.
   - De igual forma, `antiguedad_laboral_meses` (91 nulos) y `meses_historial_crediticio` (97 nulos) usan mediana de `train` + indicador binario, y `tipo_empleo` (93 nulos) se imputa a la categoría explícita `'faltante'` antes de `OneHotEncoder(handle_unknown="ignore")`.
4. **Análisis de redundancia de `cuota_estimada_cop`:**
   - Aunque `cuota_estimada_cop` se calcula mediante la anualidad de `monto_solicitado_cop` y `plazo_meses`, es una función no lineal de ambos. Evaluando en validación con y sin `cuota_estimada_cop`:
     - En `LogisticRegression (C=1.0)`, mantener las 11 variables mejora `val_average_precision` de `0.493702` a **`0.504484`** y `val_roc_auc` de `0.684402` a **`0.693093`**, reduciendo el Brier score de `0.192004` a **`0.190691`**.
   - Por tanto, se conserva dentro de las 11 variables predictoras del contrato OpenAPI (`#/components/schemas/Features`).
5. **Partición estratificada 60 / 20 / 20 (`random_state = 42`):**
   - `train`: 7,200 filas (`2,200` positivas, tasa `30.5556%`).
   - `val`: 2,400 filas (`734` positivas, tasa `30.5833%`).
   - `test`: 2,400 filas (`733` positivas, tasa `30.5417%`).

---

## Comparación de modelos en MLflow (`credimarket-riesgo-v1`)

Todas las corridas entrenan el `Pipeline` completo (`ColumnTransformer` + clasificador) únicamente sobre `train.csv` y se comparan en `val.csv`:

| Run Name | Algoritmo | Hiperparámetros principales | Train AP | Val AP (Principal) | Val ROC-AUC | Val Brier (Calibración) | Val F1 (`t=0.50`) |
|---|---|---|---:|---:|---:|---:|---:|
| `00_baseline_dummy_prior` | `DummyClassifier` | `strategy='prior'` | 0.305556 | 0.305833 | 0.500000 | 0.212299 | 0.000000 |
| `01_logreg_c01` | `LogisticRegression` | `C=0.1, max_iter=1000` | 0.520525 | 0.504181 | 0.692872 | 0.190735 | 0.359699 |
| **`02_logreg_c1` (Ganador)** | **`LogisticRegression`** | **`C=1.0, max_iter=1000`** | **0.520545** | **0.504484** | **0.693093** | **0.190691** | **0.360718** |
| `03_tree_depth4_leaf20` | `DecisionTreeClassifier` | `max_depth=4, min_samples_leaf=20` | 0.464891 | 0.424151 | 0.628735 | 0.201941 | 0.273092 |
| `04_tree_depth8_leaf20` | `DecisionTreeClassifier` | `max_depth=8, min_samples_leaf=20` | 0.576224 | 0.444603 | 0.642110 | 0.208189 | 0.371212 |
| `05_rf_200_depth8_leaf5` | `RandomForestClassifier` | `n_estimators=200, max_depth=8, min_samples_leaf=5` | 0.674415 | 0.485607 | 0.674030 | 0.194458 | 0.299578 |
| `06_rf_200_unlim_leaf5` | `RandomForestClassifier` | `n_estimators=200, max_depth=None, min_samples_leaf=5` | 0.961116 | 0.492038 | 0.676177 | 0.193199 | 0.340164 |

### Justificación del modelo ganador

Siguiendo la regla predefinida en el plan:
1. **Métrica principal (`val_average_precision`):** `02_logreg_c1` alcanza el valor más alto (`0.504484`), seguido por `01_logreg_c01` (`0.504181`, dentro de la tolerancia de empate de `0.005`). Los árboles individuales y bosques aleatorios presentan menor generalización en validación y sobreajuste en entrenamiento (`06_rf_200_unlim_leaf5` tiene `Train AP = 0.9611` pero cae a `Val AP = 0.4920`).
2. **Desempate por calibración (`val_brier_score`):** Entre los dos finalistas dentro de `0.005` de AP, `02_logreg_c1` obtiene el menor Brier score (**`0.190691`** vs `0.190735`) y mayor ROC-AUC (**`0.693093`** vs `0.692872`).
3. **Candidato seleccionado:** `02_logreg_c1` (`run_id`: `67e5c9d9db914b4f92ce2aebb6d80a10`).

---

## Optimización del umbral y evaluación única en `test`

### Selección de umbral en validación (`FN = 5`, `FP = 1`)

En crédito al consumo, aprobar a un cliente que incumple (`FN`, costo = `5.0`) es más costoso que rechazar una solicitud cumplida (`FP`, costo = `1.0`).
- **En el umbral por defecto (`t = 0.50`):** El modelo solo detecta el `26.02%` de los incumplimientos en validación (`FN = 543`, `FP = 217`), generando un costo total de **`2,932.0`** (`1.2217` por préstamo).
- **Óptimo operativo (`t = 0.26`):** Sujeto a mantener una viabilidad comercial de aprobación `>= 45%`, el umbral `0.26` minimiza el costo en validación a **`1,751.0`** (`0.7296` por préstamo, reduciendo el costo en **40.3%** respecto a `t = 0.50`), eleva el recall de incumplimiento a **`73.43%`**, maximiza el F1 a **`0.5261`** y reduce la tasa de mora de la cartera aprobada del `30.58%` original a **`17.97%`**.

### Evaluación final en `test` (ejecutada una sola vez)

Congelados el pipeline `02_logreg_c1` y el umbral `0.26`, la evaluación sobre las 2,400 filas de `test.csv` arroja:

- **Average Precision (PR-AUC):** `0.506501` (consistente con `0.504484` en validación)
- **ROC-AUC:** `0.685250`
- **Brier Score:** `0.190870`
- **Recall (clase positiva `incumplimiento_90d = 1`):** `0.720327` (`528` de `733` incumplimientos detectados)
- **Precision (clase positiva):** `0.401521`
- **F1-score (clase positiva):** `0.515625`
- **Tasa de aprobación:** `45.21%` (`1,085` aprobados de `2,400`)
- **Mora en cartera aprobada:** `18.89%` (frente a `30.54%` sin filtro de riesgo)
- **Matriz de confusión en `test` (`t = 0.26`):** `TN = 880`, `FP = 787`, `FN = 205`, `TP = 528`

### Inferencia por lotes sobre `solicitudes_nuevas.csv`

Como `solicitudes_nuevas.csv` (200 filas) carece de la etiqueta `incumplimiento_90d`, **no se usa para entrenar ni para inventar métricas supervisadas**. Al evaluarlo con el candidato congelado (`umbral = 0.26`), produce:
- **87 solicitudes `FAVORABLE`** (`probabilidad_incumplimiento < 0.26`)
- **113 solicitudes `DESFAVORABLE`** (`probabilidad_incumplimiento >= 0.26`)
- Cero valores `NaN` o fuera de `[0, 1]`.
