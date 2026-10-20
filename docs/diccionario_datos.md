# Diccionario de Datos y Contrato de Características

Este documento especifica las variables observadas en los archivos originales (`prestamos_entrenamiento.csv` con 12.000 filas y `solicitudes_nuevas.csv` con 200 filas), distinguiendo entre **rangos empíricos observados**, **reglas del dominio** y **tratamiento dentro del pipeline de Machine Learning**.

## 1. Hashes SHA-256 de archivos fuente (Inmutables)

| Archivo | Filas | Columnas | SHA-256 | Uso permitido |
|---|---:|---:|---|---|
| `prestamos_entrenamiento.csv` | 12.000 | 15 | `c6cdc437c3aecc9116bc8b978df421d5a7600634c1ad7d6f82e58222a2446ecd` | Partición estratificada 60/20/20 (`train`/`val`/`test`) con semilla `42` |
| `solicitudes_nuevas.csv` | 200 | 14 | `1430d7b34e924d5e4170c4fb9d9a412c1000af17c062af513ef15e44a1a7f1f7` | Inferencia batch sin etiqueta y pruebas de paridad offline/API (Fase 8) |

---

## 2. Especificación por columna

| # | Columna | Rol | ¿Entra al modelo? | Tipo y unidad | ¿Permite nulos? | Rango / Valores observados (Histórico) | Regla de dominio y tratamiento en el Pipeline |
|---:|---|---|---|---|---|---|---|
| 1 | `solicitud_id` | Identificador | **No** | `string` (`SOL-XXXXXXX`) | No | `SOL-0000001` .. `SOL-0012000` (12.000 únicos) | Identificador único de solicitud; se excluye para impedir memorización o fuga de datos. |
| 2 | `cliente_id` | Identificador | **No** | `string` (`CLI-XXXXXXX` / UUID) | No | `CLI-0000001` .. `CLI-0012000` (12.000 únicos, 0 compartidos con nuevas) | Identificador de cliente; se excluye del estimador. |
| 3 | `ingresos_mensuales_cop` | Predictor (1/11) | **Sí** | `number` (COP/mes) | No (0 faltantes) | `1.400.000` – `28.000.000` (mediana `3.905.000`) | Regla: `> 0`. Pipeline: `SimpleImputer(strategy='median')` + `StandardScaler` en modelos lineales. |
| 4 | `obligaciones_mensuales_cop` | Predictor (2/11) | **Sí** | `number` (COP/mes) | No (0 faltantes) | `11.000` – `16.485.000` (mediana `972.000`) | Regla: `>= 0`. Pipeline: `SimpleImputer(strategy='median')` + `StandardScaler` en modelos lineales. |
| 5 | `tipo_empleo` | Predictor (3/11) | **Sí** | `categorical` | Sí (93 hist / 2 nuevas) | `'dependiente'` (56,4%), `'independiente'` (28,8%), `'temporal'` (14,0%), `null` (0,8%) | Regla: en `{'dependiente', 'independiente', 'temporal', null}`. Pipeline: `SimpleImputer(strategy='constant', fill_value='faltante')` + `OneHotEncoder`. |
| 6 | `antiguedad_laboral_meses` | Predictor (4/11) | **Sí** | `integer` (meses) | Sí (91 hist / 1 nueva) | `0` – `240` meses (mediana `31`) | Regla: entero `>= 0` o `null`. Pipeline: `SimpleImputer(strategy='median', add_indicator=True)`. |
| 7 | `meses_historial_crediticio` | Predictor (5/11) | **Sí** | `integer` (meses) | Sí (97 hist / 1 nueva) | `0` – `300` meses (mediana `48`) | Regla: entero `>= 0` o `null`. Pipeline: `SimpleImputer(strategy='median', add_indicator=True)`. |
| 8 | `creditos_previos` | Predictor (6/11) | **Sí** | `integer` (conteo) | No (0 faltantes) | `0` – `19` créditos (mediana `2`) | Regla: entero `>= 0`. Invariante estructural: `creditos_previos == 0` $\iff$ `porcentaje_pago_puntual is null`. |
| 9 | `atrasos_previos_30d` | Predictor (7/11) | **Sí** | `integer` (conteo) | No (0 faltantes) | `0` – `12` atrasos (mediana `0`) | Regla: entero `>= 0`. Es el predictor individual con mayor correlación positiva con incumplimiento (`+0.2176`). |
| 10 | `porcentaje_pago_puntual` | Predictor (8/11) | **Sí** | `number` (`%` en `[0, 100]`) | Sí (2.473 hist / 43 nuevas) | `12,68%` – `99,97%` cuando `creditos_previos > 0` (mediana `86,09%`) | Regla: `null` si `creditos_previos == 0`; en `[0, 100]` si `creditos_previos > 0`. **Prohibido imputar como 0**: se imputa con mediana de `train` + bandera `add_indicator=True`. |
| 11 | `monto_solicitado_cop` | Predictor (9/11) | **Sí** | `number` (COP) | No (0 faltantes) | `500.000` – `15.000.000` (mediana `3.200.000`) | Regla de política financiera v1: `[500.000, 15.000.000]` COP inclusive. |
| 12 | `plazo_meses` | Predictor (10/11) | **Sí** | `integer` (meses) | No (0 faltantes) | `{6, 12, 18, 24, 36}` | Regla de política v1: pertenece exactamente a `{6, 12, 18, 24, 36}`. |
| 13 | `tasa_mensual_simulada` | Parámetro constante | **No** | `number` (proporción MV) | No (0 faltantes) | `0.0180` constante en todas las filas | Varianza nula (`std = 0`). Se excluye del estimador pero se conserva como constante financiera ($r = 0.018$) para el cálculo determinista de la cuota. |
| 14 | `cuota_estimada_cop` | Predictor (11/11) | **Sí** | `number` (COP/mes) | No (0 faltantes) | `18.991,92` – `2.659.841,03` (mediana `214.888,96`) | Calculada por anualidad: $\text{monto} \cdot \frac{r}{1-(1+r)^{-n}}$ (diferencia máxima observada $< 0,005$ COP). Se conserva porque mejora AP y Brier en validación. |
| 15 | `incumplimiento_90d` | Variable objetivo ($y$) | **No** | `integer` (`{0, 1}`) | No en histórico / Ausente en nuevas | `1`: `3.667` (`30,56%`), `0`: `8.333` (`69,44%`) | Objetivo binario de supervisión. Clase positiva = `1` (incumplimiento $\ge 90$ días). |

---

## 3. Justificación técnica de casos especiales

1. **Ausencia estructural en `porcentaje_pago_puntual` (`creditos_previos == 0`):**
   - En las 2.473 filas históricas (y 43 de solicitudes nuevas) donde `creditos_previos == 0`, el porcentaje de pago puntual está vacío porque el cliente no tiene préstamos anteriores.
   - Su tasa de incumplimiento observada es **27,58%**, inferior al **31,33%** de quienes tienen créditos previos.
   - Imputar `0.0` sería un error metodológico grave que los trataría como morosos crónicos (0% de pagos a tiempo). Por ello el pipeline aplica `SimpleImputer(strategy='median', add_indicator=True)`, asignando la mediana aprendida en `train` (`86,09%`) y activando una columna indicadora binaria que identifica exactamente a los solicitantes sin historial crediticio.

2. **Exclusión de `tasa_mensual_simulada` y retención de `cuota_estimada_cop`:**
   - `tasa_mensual_simulada` vale `0.018` en el 100% de los registros; al tener varianza cero no aporta información discriminante al estimador.
   - `cuota_estimada_cop` es una transformación no lineal de `monto_solicitado_cop` y `plazo_meses`. En el estudio de ablación sobre validación (`val`), conservar `cuota_estimada_cop` elevó el `Average Precision (AP)` en regresión logística de `0.5024` a `0.5045` (y en Random Forest de `0.4802` a `0.4856`), reduciendo además el `Brier score`, ya que permite al modelo comparar linealmente la cuota mensual contra `ingresos_mensuales_cop` y `obligaciones_mensuales_cop`.
