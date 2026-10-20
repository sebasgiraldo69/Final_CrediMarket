# Entrenamiento offline y MLOps (CrediMarket)

Este directorio contiene la preparación reproducible de datos, el análisis exploratorio (EDA), las particiones estratificadas 60/20/20, el entrenamiento de los 7 experimentos (1 baseline + 6 candidatos) con registro en MLflow y el artefacto candidato seleccionado en la Fase 7.

## Estructura

- `src/contract.py`: Contrato de 11 variables predictoras, reglas de validación semántica, cálculo de anualidad y construcción del `Pipeline` (`ColumnTransformer` + clasificador) sin fuga de datos.
- `src/eda_and_split.py`: Verificación de hashes SHA-256 de los CSV originales, diccionario de datos, reporte EDA y partición estratificada 60/20/20 (`semilla = 42`).
- `src/train_and_select.py`: Ejecución de los 7 modelos en MLflow (`credimarket-riesgo-v1`), estudio de redundancia de `cuota_estimada_cop` en validación, optimización de umbral por costos (5:1) y evaluación única sobre el conjunto de prueba (`test`).
- `data/splits/`: Particiones reproducibles (`train.csv` con 7.200 filas, `val.csv` con 2.400 filas, `test.csv` con 2.400 filas).
- `manifests/split_manifest.json`: Hashes SHA-256 y distribución de clases de cada partición.
- `manifests/candidate_v1.json`: Manifiesto del modelo ganador (`02_logreg_c1`), umbral congelado (`0.26`), métricas y versiones exactas de dependencias.
- `reports/data_dictionary.json`: Diccionario de datos estructurado.
- `reports/eda_report.json`: Estadísticas descriptivas, percentiles, tasas de incumplimiento por segmento y correlaciones.
- `reports/model_selection_report.json`: Comparativa de las 7 ejecuciones, curva de costos de umbral y evaluación final en prueba.
- `artifacts/candidate_v1/pipeline.joblib`: Pipeline serializado completo listo para promoción y servicio en Fase 8.

## Reproducir entrenamiento y verificar

Con el stack Docker en ejecución:

```powershell
python scripts/run_phase7_training.py
python scripts/check_phase7.py
```

El experimento `infrastructure-smoke`, si aparece al ejecutar las pruebas de fase 2, es exclusivamente una prueba de persistencia de infraestructura. El experimento real de modelado es **`credimarket-riesgo-v1`** en http://localhost:5000.
