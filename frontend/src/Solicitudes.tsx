import { FormEvent, useEffect, useRef, useState } from 'react';
import { api, ApiError, errorText, IdempotencyKeys } from './api';
import { cancellableStates, loanStates, motiveText, pendingStates, type LoanState } from './labels';
import type { Session } from './session';
import { Feedback, formatDate, formatMoney, Modal, Pagination, shortId, usePolling, useProductNames, type Page } from './ui';

export type Loan = {
  id: string; cliente_id: string; producto_id: string; cantidad: number; plazo_meses: number;
  estado: LoanState; motivo: string | null;
  precio_unitario_cop: string | null; version_producto: number | null; monto_cop: string | null; cuota_cop: string | null;
  riesgo: { probabilidad_incumplimiento: number; decision_riesgo: 'FAVORABLE' | 'DESFAVORABLE'; umbral: number; model_version: string; run_id: string } | null;
  reserva_id: string | null; vence_en: string | null; reserva_utilizable: boolean;
  created_at: string; updated_at: string;
};

const PAGE = 15;
const keys = new IdempotencyKeys();

export function Solicitudes({ session, navigate }: { session: Session; navigate: (to: string) => void }) {
  const [loans, setLoans] = useState<Loan[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [detail, setDetail] = useState<Loan | null>(null);
  const [cancelling, setCancelling] = useState<Loan | null>(null);
  const [delivering, setDelivering] = useState<Loan | null>(null);
  const known = useRef(new Map<string, LoanState>());
  const isAdmin = session.role === 'administrador';
  const token = session.access_token;
  const productName = useProductNames(loans.map(l => l.producto_id), token);

  async function fetchPage() {
    const page = await api<Page<Loan>>('prestamos', `/prestamos?limit=${PAGE}&offset=${offset}`, { token });
    const changes = page.items.filter(l => known.current.has(l.id) && known.current.get(l.id) !== l.estado);
    if (changes.length) setNotice(changes.map(l => `Solicitud ${shortId(l.id)}: ${loanStates[l.estado].label}.`).join(' '));
    known.current = new Map(page.items.map(l => [l.id, l.estado]));
    setLoans(page.items); setTotal(page.total); setUpdatedAt(new Date());
    setDetail(current => current && (page.items.find(l => l.id === current.id) ?? current));
  }

  async function reload() {
    setLoading(true); setError('');
    try { await fetchPage(); } catch (err) { setError(errorText(err)); } finally { setLoading(false); }
  }
  useEffect(() => { known.current.clear(); void reload(); }, [offset]);

  const hasPending = loans.some(l => pendingStates.includes(l.estado));
  const hasReserved = loans.some(l => l.estado === 'APROBADA');
  // Pendientes: cada 2 s. Aprobadas con reserva que puede vencer: cada 10 s.
  const failures = usePolling(fetchPage, !loading && (hasPending || hasReserved), hasPending ? 2000 : 10000);

  async function act(loan: Loan, kind: 'cancelacion' | 'entrega', body: object | undefined, success: string) {
    const scope = `${kind}:${loan.id}`;
    setBusy(true); setError(''); setNotice('');
    try {
      const updated = await api<Loan>('prestamos', `/prestamos/${loan.id}/${kind}`, { method: 'POST', token, body, idempotencyKey: keys.keyFor(scope, body) });
      keys.settle(scope);
      known.current.set(updated.id, updated.estado);
      setLoans(current => current.map(l => l.id === updated.id ? updated : l));
      setNotice(success);
      return true;
    } catch (err) {
      if (!(err instanceof ApiError) || !err.retryable) keys.settle(scope);
      setError(errorText(err) + (err instanceof ApiError && err.retryable ? ' Puedes reintentar: se reutiliza la misma operación.' : ''));
      if (err instanceof ApiError && (err.status === 409 || err.status === 404)) await reload();
      return false;
    } finally { setBusy(false); }
  }

  async function cancel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const motivo = String(new FormData(event.currentTarget).get('motivo')).trim();
    if (!motivo) { setError('Escribe el motivo de la cancelación.'); return; }
    if (await act(cancelling!, 'cancelacion', { motivo }, 'Cancelación aceptada. La solicitud seguirá en «Cancelando» hasta que Inventario libere la reserva.')) setCancelling(null);
  }

  async function deliver() {
    if (await act(delivering!, 'entrega', undefined, 'Entrega solicitada. Quedará «Entregando» hasta que Inventario confirme la salida.')) setDelivering(null);
  }

  return <section>
    <div className="module-heading">
      <div><p className="eyebrow">Créditos</p><h1>{isAdmin ? 'Todas las solicitudes' : 'Mis solicitudes'}</h1></div>
      <div className="actions">
        <button type="button" onClick={() => void reload()} disabled={loading}>{loading ? 'Cargando…' : 'Actualizar'}</button>
        {!isAdmin && <button type="button" className="primary" onClick={() => navigate('/catalogo')}>Nueva solicitud</button>}
      </div>
    </div>
    <p className="live" aria-live="polite">
      {failures > 0 ? <span className="bad-text">Sin conexión con Préstamos; reintentando automáticamente…</span>
        : hasPending ? 'Hay solicitudes en proceso: se actualizan automáticamente cada 2 s.'
        : updatedAt ? `Actualizado a las ${updatedAt.toLocaleTimeString('es-CO')}.` : ''}
    </p>
    <Feedback error={error} notice={notice} onClose={() => { setError(''); setNotice(''); }} />

    {loading && !loans.length ? <p className="loading" role="status">Cargando solicitudes…</p>
      : !loans.length ? <div className="empty">
          <p>{isAdmin ? 'Aún no hay solicitudes de crédito.' : 'Todavía no tienes solicitudes.'}</p>
          {!isAdmin && <button className="primary" onClick={() => navigate('/catalogo')}>Explorar el catálogo</button>}
        </div>
      : <div className="table-scroll"><table className="responsive">
          <thead><tr><th>Solicitud</th><th>Producto</th>{isAdmin && <th>Cliente</th>}<th>Monto</th><th>Cuota</th><th>Estado</th><th>Acciones</th></tr></thead>
          <tbody>{loans.map(loan => {
            const state = loanStates[loan.estado];
            return <tr key={loan.id}>
              <td data-label="Solicitud"><code>{shortId(loan.id)}</code><small>{formatDate(loan.created_at)}</small></td>
              <td data-label="Producto">{productName(loan.producto_id) ?? <code>{shortId(loan.producto_id)}</code>}<small>{loan.cantidad} u. · {loan.plazo_meses} meses</small></td>
              {isAdmin && <td data-label="Cliente"><code>{shortId(loan.cliente_id)}</code></td>}
              <td data-label="Monto">{formatMoney(loan.monto_cop)}</td>
              <td data-label="Cuota">{formatMoney(loan.cuota_cop)}</td>
              <td data-label="Estado"><span className={`state-pill ${state.tone}`} title={state.help}>{state.label}</span>
                {loan.motivo && <small>{motiveText(loan.motivo)}</small>}
                {loan.estado === 'APROBADA' && loan.vence_en && <small>Reserva vence en <Countdown until={loan.vence_en} /></small>}</td>
              <td data-label="Acciones"><div className="actions compact">
                <button type="button" onClick={() => setDetail(loan)}>Detalle</button>
                {cancellableStates.includes(loan.estado) && <button type="button" className="danger" disabled={busy} onClick={() => setCancelling(loan)}>Cancelar</button>}
                {isAdmin && loan.estado === 'APROBADA' && loan.reserva_utilizable && <button type="button" className="primary" disabled={busy} onClick={() => setDelivering(loan)}>Entregar</button>}
              </div></td>
            </tr>;
          })}</tbody>
        </table></div>}
    <Pagination offset={offset} limit={PAGE} total={total} busy={loading} onChange={setOffset} label="solicitudes" />

    {detail && <Modal title={`Solicitud ${shortId(detail.id)}`} onClose={() => setDetail(null)} wide>
      <p className={`state-pill ${loanStates[detail.estado].tone}`}>{loanStates[detail.estado].label}</p>
      <p>{detail.motivo ? motiveText(detail.motivo) : loanStates[detail.estado].help}</p>
      <dl className="facts">
        <dt>Identificador</dt><dd><code>{detail.id}</code></dd>
        <dt>Producto</dt><dd>{productName(detail.producto_id) ?? detail.producto_id} × {detail.cantidad}</dd>
        <dt>Precio cotizado</dt><dd>{formatMoney(detail.precio_unitario_cop)} (versión de producto {detail.version_producto ?? '—'})</dd>
        <dt>Monto</dt><dd>{formatMoney(detail.monto_cop)}</dd>
        <dt>Cuota</dt><dd>{formatMoney(detail.cuota_cop)} × {detail.plazo_meses} meses</dd>
        <dt>Reserva</dt><dd>{detail.reserva_id ? <><code>{shortId(detail.reserva_id)}</code> · {detail.reserva_utilizable ? 'activa' : 'no utilizable'}{detail.vence_en && <> · vence {formatDate(detail.vence_en)}</>}</> : 'Sin reserva'}</dd>
        <dt>Creada</dt><dd>{formatDate(detail.created_at)} · actualizada {formatDate(detail.updated_at)}</dd>
      </dl>
      {detail.riesgo ? <><h3>Evaluación de riesgo</h3><dl className="facts">
        <dt>Decisión</dt><dd className={detail.riesgo.decision_riesgo === 'FAVORABLE' ? 'ok-text' : 'bad-text'}>{detail.riesgo.decision_riesgo === 'FAVORABLE' ? 'Favorable' : 'Desfavorable'}</dd>
        <dt>Probabilidad de incumplimiento</dt><dd>{(detail.riesgo.probabilidad_incumplimiento * 100).toFixed(2)} % (umbral {(detail.riesgo.umbral * 100).toFixed(0)} %)</dd>
        <dt>Modelo</dt><dd>{detail.riesgo.model_version} · run <code>{shortId(detail.riesgo.run_id)}</code></dd>
      </dl>{detail.riesgo.decision_riesgo === 'FAVORABLE' && detail.estado !== 'APROBADA' && detail.estado !== 'COMPLETADA' &&
        <p className="note">Una evaluación favorable no equivale a aprobación: el crédito se aprueba cuando Inventario confirma la reserva.</p>}</>
        : <p className="note">Sin evaluación del modelo: la solicitud se resolvió antes por las reglas de política.</p>}
      <div className="actions"><button onClick={() => setDetail(null)}>Cerrar</button></div>
    </Modal>}

    {cancelling && <Modal title="Cancelar solicitud" onClose={() => { if (!busy) setCancelling(null); }}>
      <form onSubmit={cancel} className="stack">
        <p>Se liberará la reserva de {productName(cancelling.producto_id) ?? 'el producto'}. La cancelación queda pendiente hasta que Inventario lo confirme.</p>
        <label>Motivo<input name="motivo" required maxLength={250} placeholder="Ej.: ya no necesito el producto" /></label>
        <div className="actions"><button className="danger-solid" disabled={busy}>{busy ? 'Enviando…' : 'Confirmar cancelación'}</button><button type="button" disabled={busy} onClick={() => setCancelling(null)}>Volver</button></div>
      </form>
    </Modal>}

    {delivering && <Modal title="Confirmar entrega" onClose={() => { if (!busy) setDelivering(null); }}>
      <p>Inventario descontará {delivering.cantidad} unidad(es) de {productName(delivering.producto_id) ?? 'el producto'} del stock físico y reservado.</p>
      <dl className="facts"><dt>Solicitud</dt><dd><code>{delivering.id}</code></dd><dt>Monto</dt><dd>{formatMoney(delivering.monto_cop)}</dd></dl>
      <div className="actions"><button className="primary" disabled={busy} onClick={() => void deliver()}>{busy ? 'Enviando…' : 'Confirmar entrega'}</button><button disabled={busy} onClick={() => setDelivering(null)}>Volver</button></div>
    </Modal>}
  </section>;
}

function Countdown({ until }: { until: string }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  const seconds = Math.max(0, Math.round((new Date(until).getTime() - now) / 1000));
  return <>{Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, '0')}</>;
}
