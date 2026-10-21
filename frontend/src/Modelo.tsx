import { Fragment, useEffect, useState } from 'react';
import { api, errorText } from './api';
import { modelVariables } from './labels';
import type { Session } from './session';
import { Feedback, formatDate } from './ui';

type ModelInfo = {
  model_version: string; run_id: string; variables: string[]; clase_positiva: 1; umbral: number; artifact_sha256: string;
  algoritmo: string | null; experimento: string | null; exportado_en: string | null; metricas_prueba: Record<string, number> | null;
};

// URL pública de MLflow (sin secretos); se fija al construir la imagen. 127.0.0.1 y no localhost:
// Docker publica el puerto solo en IPv4 y en macOS localhost:5000 puede resolver a AirPlay.
export const MLFLOW_URL = import.meta.env.VITE_MLFLOW_URL || 'http://127.0.0.1:5000';

const metrics: [string, string, (v: number) => string][] = [
  ['average_precision', 'Precisión promedio (AP)', v => v.toFixed(3)],
  ['roc_auc', 'ROC AUC', v => v.toFixed(3)],
  ['brier_score', 'Brier score', v => v.toFixed(3)],
  ['precision_pos', 'Precisión (incumplidores)', v => `${(v * 100).toFixed(1)} %`],
  ['recall_pos', 'Sensibilidad (incumplidores)', v => `${(v * 100).toFixed(1)} %`],
  ['approval_rate', 'Tasa de aprobación', v => `${(v * 100).toFixed(1)} %`],
  ['approved_default_rate', 'Incumplimiento entre aprobados', v => `${(v * 100).toFixed(1)} %`],
  ['business_cost_per_loan', 'Costo de negocio por solicitud', v => v.toFixed(3)],
];

export function Modelo({ session }: { session: Session }) {
  const [info, setInfo] = useState<ModelInfo | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true); setError('');
    try { setInfo(await api<ModelInfo>('prestamos', '/modelo/info', { token: session.access_token })); }
    catch (err) { setInfo(null); setError(errorText(err)); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);

  return <section>
    <div className="module-heading">
      <div><p className="eyebrow">Riesgo crediticio</p><h1>Ficha del modelo</h1></div>
      <button type="button" onClick={() => void load()} disabled={loading}>{loading ? 'Cargando…' : 'Actualizar'}</button>
    </div>
    <Feedback error={error} />
    {loading && !info && <p className="loading" role="status">Consultando el modelo activo…</p>}
    {info && <>
      <div className="stats">
        <div><strong>{info.model_version}</strong><span>Versión activa</span></div>
        <div><strong>{(info.umbral * 100).toFixed(0)} %</strong><span>Umbral de decisión</span></div>
        <div><strong>{info.variables.length}</strong><span>Variables</span></div>
        {info.algoritmo && <div><strong>{info.algoritmo}</strong><span>Algoritmo</span></div>}
      </div>
      <div className="two-col">
        <div className="panel">
          <h2>Cómo decide</h2>
          <p>El modelo estima la probabilidad de que el cliente incumpla (clase positiva = {info.clase_positiva}). Si la probabilidad es <strong>menor a {info.umbral}</strong>, la evaluación es favorable y se solicita la reserva de inventario; si no, la solicitud se rechaza con motivo de riesgo desfavorable.</p>
          <p className="note">Una evaluación favorable no aprueba el crédito por sí sola: la aprobación llega cuando Inventario confirma la reserva.</p>
          <h3>Trazabilidad</h3>
          <dl className="facts">
            {info.experimento && <><dt>Experimento MLflow</dt><dd>{info.experimento}</dd></>}
            <dt>Run de MLflow</dt><dd><code>{info.run_id}</code></dd>
            <dt>SHA-256 del artefacto</dt><dd><code className="wrap">{info.artifact_sha256}</code></dd>
            {info.exportado_en && <><dt>Exportado</dt><dd>{formatDate(info.exportado_en)}</dd></>}
          </dl>
          <p><a className="button primary" href={MLFLOW_URL} target="_blank" rel="noreferrer">Abrir MLflow</a></p>
          <p className="note">MLflow solo escucha en este equipo ({MLFLOW_URL}). Busca el experimento {info.experimento ?? ''} y filtra por el run indicado para ver parámetros, métricas y artefactos.</p>
        </div>
        <div className="panel">
          <h2>Métricas en prueba</h2>
          {info.metricas_prueba ? <dl className="facts">
            {metrics.filter(([key]) => key in info.metricas_prueba!).map(([key, label, format]) => <Fragment key={key}><dt>{label}</dt><dd>{format(info.metricas_prueba![key])}</dd></Fragment>)}
          </dl> : <p className="note">El manifiesto de esta versión no incluye métricas; consúltalas en MLflow.</p>}
          <p className="note">Medidas sobre el conjunto de prueba al umbral operativo.</p>
          <h3>Variables de entrada</h3>
          <ul className="chips">{info.variables.map(v => <li key={v} title={v}>{modelVariables[v] ?? v}</li>)}</ul>
        </div>
      </div>
    </>}
  </section>;
}
