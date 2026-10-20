import { FormEvent, useEffect, useState } from 'react';
import type { Session } from './Clientes';

export type Loan = {
  id: string;
  cliente_id: string;
  producto_id: string;
  cantidad: number;
  plazo_meses: number;
  estado: string;
  motivo: string | null;
  precio_unitario_cop: string | null;
  version_producto: number | null;
  monto_cop: string | null;
  cuota_cop: string | null;
  riesgo: {
    probabilidad_incumplimiento: number;
    decision_riesgo: string;
    umbral: number;
    model_version: string;
    run_id: string;
  } | null;
  reserva_id: string | null;
  vence_en: string | null;
  reserva_utilizable: boolean;
  created_at: string;
  updated_at: string;
};

interface SolicitudesProps {
  session: Session | null;
  onNavigateToCatalog?: () => void;
  onNavigateToClients?: () => void;
}

export function Solicitudes({ session, onNavigateToCatalog, onNavigateToClients }: SolicitudesProps) {
  const [loans, setLoans] = useState<Loan[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [limit] = useState(15);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  // Modales
  const [selectedLoan, setSelectedLoan] = useState<Loan | null>(null);
  const [cancellingLoan, setCancellingLoan] = useState<Loan | null>(null);
  const [deliveringLoan, setDeliveringLoan] = useState<Loan | null>(null);

  const isAdmin = session?.role === 'administrador';

  async function api(path: string, options: RequestInit = {}) {
    const headers = new Headers(options.headers);
    if (session?.access_token) {
      headers.set('Authorization', `Bearer ${session.access_token}`);
    }
    if (options.body && !(options.body instanceof FormData)) {
      headers.set('Content-Type', 'application/json');
    }
    const response = await fetch(`/api/prestamos${path}`, { ...options, headers });
    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error('El servicio de préstamos no está disponible.');
    }
    if (!response.ok) {
      const details = data.details?.map((d: { field: string; message: string }) => `${d.field}: ${d.message}`).join(' · ');
      throw new Error([data.message || 'Error en la solicitud', details].filter(Boolean).join(' · '));
    }
    return data;
  }

  async function loadLoans(silent = false) {
    if (!session) return;
    if (!silent) {
      setBusy(true);
      setError('');
    }
    try {
      const query = new URLSearchParams({
        limit: String(limit),
        offset: String(offset),
      });
      const data = await api(`/prestamos?${query.toString()}`);
      setLoans(data.items);
      setTotal(data.total);
    } catch (err) {
      if (!silent) {
        setError(err instanceof Error ? err.message : 'Error cargando préstamos');
      }
    } finally {
      if (!silent) setBusy(false);
    }
  }

  // Carga inicial y por cambio de página/sesión
  useEffect(() => {
    void loadLoans();
  }, [session, offset]);

  // Polling cada 2.5s si hay solicitudes en estados intermedios
  useEffect(() => {
    if (!session) return;
    const hasPending = loans.some(l =>
      ['PENDIENTE_INVENTARIO', 'CANCELACION_PENDIENTE', 'ENTREGA_PENDIENTE', 'VERIFICACION_PENDIENTE', 'EVALUANDO'].includes(l.estado)
    );
    if (!hasPending) return;

    const interval = setInterval(() => {
      void loadLoans(true);
    }, 2500);

    return () => clearInterval(interval);
  }, [session, loans]);

  async function handleCancel(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!cancellingLoan) return;
    const form = new FormData(e.currentTarget);
    const motivo = String(form.get('motivo') || '').trim();
    if (!motivo) return;

    setBusy(true);
    setError('');
    setNotice('');
    try {
      const idemKey = `canc-${cancellingLoan.id}-${Date.now()}`;
      await api(`/prestamos/${cancellingLoan.id}/cancelacion`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idemKey },
        body: JSON.stringify({ motivo }),
      });
      setCancellingLoan(null);
      setNotice('Cancelación solicitada. Se procesará la liberación de inventario.');
      await loadLoans();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error solicitando cancelación');
    } finally {
      setBusy(false);
    }
  }

  async function handleDeliver(loan: Loan) {
    if (!isAdmin) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const idemKey = `entr-${loan.id}-${Date.now()}`;
      await api(`/prestamos/${loan.id}/entrega`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idemKey },
      });
      setDeliveringLoan(null);
      setNotice('Entrega solicitada. El inventario confirmará la salida física.');
      await loadLoans();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error solicitando entrega');
    } finally {
      setBusy(false);
    }
  }

  function formatMoney(amount: string | null) {
    if (!amount) return '—';
    return `$ ${Number(amount).toLocaleString('es-CO', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function getBadgeStyle(estado: string) {
    switch (estado) {
      case 'APROBADA':
        return { background: '#e9f5e8', color: '#28502c', border: '1px solid #c2e5bf' };
      case 'COMPLETADA':
        return { background: '#e0f2fe', color: '#0369a1', border: '1px solid #bae6fd' };
      case 'PENDIENTE_INVENTARIO':
      case 'CANCELACION_PENDIENTE':
      case 'ENTREGA_PENDIENTE':
      case 'VERIFICACION_PENDIENTE':
      case 'EVALUANDO':
        return { background: '#fef3c7', color: '#92400e', border: '1px solid #fde68a' };
      case 'RECHAZADA':
      case 'CANCELADA':
      case 'CANCELADA_SIN_STOCK':
      case 'ERROR_TECNICO':
      default:
        return { background: '#fee2e2', color: '#991b1b', border: '1px solid #fecaca' };
    }
  }

  if (!session) {
    return (
      <section className="panel">
        <p className="eyebrow">Autenticación requerida</p>
        <h1>Mis solicitudes de crédito</h1>
        <p>Inicia sesión con tu cuenta para ver y gestionar tus solicitudes de préstamo.</p>
        <button onClick={onNavigateToClients} className="button-primary">
          Ir a Iniciar Sesión
        </button>
      </section>
    );
  }

  return (
    <section className="panel" aria-label="Módulo de Préstamos">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 16 }}>
        <div>
          <p className="eyebrow">Gestión de Créditos · Fase 9</p>
          <h1>{isAdmin ? 'Todas las solicitudes de crédito' : 'Mis solicitudes de crédito'}</h1>
          <p className="intro">
            {isAdmin
              ? 'Supervisión integral de préstamos, entregas físicas y estado de reservas de inventario.'
              : 'Historial de tus solicitudes, evaluación de riesgo en vivo y estado de entrega.'}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button type="button" onClick={() => void loadLoans()} disabled={busy}>
            {busy ? 'Cargando…' : 'Actualizar'}
          </button>
          {!isAdmin && onNavigateToCatalog && (
            <button type="button" onClick={onNavigateToCatalog} className="button-primary">
              Solicitar crédito en Catálogo
            </button>
          )}
        </div>
      </div>

      {notice && <div className="feedback success" role="status" style={{ margin: '16px 0' }}>{notice}</div>}
      {error && <div className="feedback error" role="alert" style={{ margin: '16px 0' }}>{error}</div>}

      <div className="table-scroll" style={{ marginTop: 20 }}>
        <table>
          <thead>
            <tr>
              <th>ID Solicitud</th>
              {isAdmin && <th>Cliente ID</th>}
              <th>Cant.</th>
              <th>Plazo</th>
              <th>Monto COP</th>
              <th>Cuota COP</th>
              <th>Estado</th>
              <th>Decisión Riesgo</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody>
            {loans.length === 0 ? (
              <tr>
                <td colSpan={isAdmin ? 9 : 8} style={{ textAlign: 'center', padding: 28, color: '#6a7d73' }}>
                  No tienes solicitudes de préstamo registradas actualmente.
                  {!isAdmin && onNavigateToCatalog && (
                    <div style={{ marginTop: 12 }}>
                      <button type="button" onClick={onNavigateToCatalog} style={{ fontSize: 13 }}>
                        Explorar catálogo de tecnología
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ) : (
              loans.map(loan => (
                <tr key={loan.id}>
                  <td>
                    <code style={{ fontSize: 11, background: '#f5f5f5', padding: '2px 4px', borderRadius: 4 }}>
                      {loan.id.slice(0, 8)}…
                    </code>
                    <div style={{ fontSize: 11, color: '#6a7d73' }}>
                      {new Date(loan.created_at).toLocaleDateString()}
                    </div>
                  </td>
                  {isAdmin && (
                    <td>
                      <code style={{ fontSize: 11 }}>{loan.cliente_id.slice(0, 8)}…</code>
                    </td>
                  )}
                  <td>{loan.cantidad}</td>
                  <td>{loan.plazo_meses} m</td>
                  <td style={{ fontWeight: 600 }}>{formatMoney(loan.monto_cop)}</td>
                  <td style={{ color: '#163d30' }}>{formatMoney(loan.cuota_cop)}</td>
                  <td>
                    <span
                      style={{
                        padding: '4px 8px',
                        borderRadius: 12,
                        fontSize: 11,
                        fontWeight: 600,
                        display: 'inline-block',
                        ...getBadgeStyle(loan.estado),
                      }}
                    >
                      {loan.estado}
                    </span>
                    {loan.motivo && (
                      <div style={{ fontSize: 11, color: '#777', marginTop: 2, maxWidth: 140 }}>
                        {loan.motivo}
                      </div>
                    )}
                  </td>
                  <td>
                    {loan.riesgo ? (
                      <div>
                        <span style={{
                          fontWeight: 600,
                          fontSize: 11,
                          color: loan.riesgo.decision_riesgo === 'FAVORABLE' ? '#28502c' : '#a33'
                        }}>
                          {loan.riesgo.decision_riesgo}
                        </span>
                        <div style={{ fontSize: 11, color: '#6a7d73' }}>
                          P: {(loan.riesgo.probabilidad_incumplimiento * 100).toFixed(1)}%
                        </div>
                      </div>
                    ) : (
                      <span style={{ color: '#999', fontSize: 12 }}>—</span>
                    )}
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      <button
                        type="button"
                        onClick={() => setSelectedLoan(loan)}
                        style={{ padding: '4px 8px', fontSize: 11 }}
                      >
                        Detalles
                      </button>

                      {['PENDIENTE_INVENTARIO', 'APROBADA', 'VERIFICACION_PENDIENTE'].includes(loan.estado) && (
                        <button
                          type="button"
                          onClick={() => setCancellingLoan(loan)}
                          disabled={busy}
                          style={{ padding: '4px 8px', fontSize: 11, color: '#a33', borderColor: '#dcc' }}
                        >
                          Cancelar
                        </button>
                      )}

                      {isAdmin && loan.estado === 'APROBADA' && loan.reserva_utilizable && (
                        <button
                          type="button"
                          onClick={() => setDeliveringLoan(loan)}
                          disabled={busy}
                          style={{ padding: '4px 8px', fontSize: 11, background: '#163d30', color: '#fff' }}
                        >
                          Entregar
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="pagination" style={{ marginTop: 16 }}>
        <span>Mostrando {loans.length} de {total} solicitudes</span>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => setOffset(Math.max(0, offset - limit))}
            disabled={offset === 0 || busy}
          >
            Anterior
          </button>
          <button
            onClick={() => setOffset(offset + limit)}
            disabled={offset + limit >= total || busy}
          >
            Siguiente
          </button>
        </div>
      </div>

      {/* Modal Detalles */}
      {selectedLoan && (
        <div className="modal-backdrop" onClick={() => setSelectedLoan(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 640 }}>
            <h2>Detalles del Préstamo</h2>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, margin: '16px 0', fontSize: 13 }}>
              <div><strong>ID:</strong> <code style={{ fontSize: 11 }}>{selectedLoan.id}</code></div>
              <div><strong>Estado:</strong> <span style={{ fontWeight: 600, ...getBadgeStyle(selectedLoan.estado), padding: '2px 6px', borderRadius: 8 }}>{selectedLoan.estado}</span></div>
              <div><strong>Producto ID:</strong> <code style={{ fontSize: 11 }}>{selectedLoan.producto_id}</code></div>
              <div><strong>Cantidad:</strong> {selectedLoan.cantidad} unidades</div>
              <div><strong>Monto solicitado:</strong> {formatMoney(selectedLoan.monto_cop)}</div>
              <div><strong>Plazo:</strong> {selectedLoan.plazo_meses} meses</div>
              <div><strong>Cuota estimada:</strong> {formatMoney(selectedLoan.cuota_cop)}</div>
              <div><strong>Precio unitario:</strong> {formatMoney(selectedLoan.precio_unitario_cop)}</div>
              <div><strong>Reserva utilizable:</strong> {selectedLoan.reserva_utilizable ? 'Sí' : 'No'}</div>
              <div><strong>Reserva ID:</strong> {selectedLoan.reserva_id ? <code style={{ fontSize: 11 }}>{selectedLoan.reserva_id}</code> : 'Sin reserva'}</div>
              {selectedLoan.vence_en && (
                <div style={{ gridColumn: 'span 2' }}>
                  <strong>Vence en:</strong> {new Date(selectedLoan.vence_en).toLocaleString()}
                </div>
              )}
            </div>

            {selectedLoan.riesgo && (
              <div style={{ background: '#f8faf9', padding: 12, borderRadius: 8, marginBottom: 16, border: '1px solid #e1e7e4' }}>
                <h3 style={{ fontSize: 14, margin: '0 0 8px' }}>Evaluación del Modelo de Riesgo</h3>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 12 }}>
                  <div><strong>Decisión:</strong> <span style={{ color: selectedLoan.riesgo.decision_riesgo === 'FAVORABLE' ? '#28502c' : '#a33', fontWeight: 600 }}>{selectedLoan.riesgo.decision_riesgo}</span></div>
                  <div><strong>Probabilidad incumplimiento:</strong> {(selectedLoan.riesgo.probabilidad_incumplimiento * 100).toFixed(2)}%</div>
                  <div><strong>Umbral activo:</strong> {selectedLoan.riesgo.umbral}</div>
                  <div><strong>Versión modelo:</strong> {selectedLoan.riesgo.model_version}</div>
                  <div style={{ gridColumn: 'span 2' }}><strong>MLflow Run ID:</strong> <code style={{ fontSize: 10 }}>{selectedLoan.riesgo.run_id}</code></div>
                </div>
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button type="button" onClick={() => setSelectedLoan(null)}>Cerrar</button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Cancelación */}
      {cancellingLoan && (
        <div className="modal-backdrop" onClick={() => setCancellingLoan(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 480 }}>
            <h2>Cancelar Solicitud de Préstamo</h2>
            <p style={{ fontSize: 13, color: '#555' }}>
              Esta acción solicitará la liberación inmediata de la reserva de inventario asociada al préstamo.
            </p>
            <form onSubmit={handleCancel}>
              <label>
                <span>Motivo de la cancelación *</span>
                <input
                  type="text"
                  name="motivo"
                  required
                  placeholder="Ej: Ya no requiero el producto, cambio de decisión"
                  maxLength={250}
                  autoFocus
                />
              </label>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
                <button type="button" onClick={() => setCancellingLoan(null)} disabled={busy}>
                  Volver
                </button>
                <button type="submit" disabled={busy} style={{ background: '#a33', color: '#fff', borderColor: '#922' }}>
                  Confirmar Cancelación
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal Entrega (Admin) */}
      {deliveringLoan && (
        <div className="modal-backdrop" onClick={() => setDeliveringLoan(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 480 }}>
            <h2>Confirmar Entrega de Producto</h2>
            <p style={{ fontSize: 13, color: '#555' }}>
              Confirmar que el cliente ha recibido las unidades físicas correspondientes al préstamo.
              Inventario descontará definitivamente el stock físico y reservado.
            </p>
            <div style={{ margin: '16px 0', fontSize: 13, background: '#f5f8f6', padding: 12, borderRadius: 6 }}>
              <div><strong>Préstamo ID:</strong> {deliveringLoan.id}</div>
              <div><strong>Cantidad:</strong> {deliveringLoan.cantidad} unidades</div>
              <div><strong>Monto:</strong> {formatMoney(deliveringLoan.monto_cop)}</div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button type="button" onClick={() => setDeliveringLoan(null)} disabled={busy}>
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => handleDeliver(deliveringLoan)}
                disabled={busy}
                className="button-primary"
              >
                Confirmar Entrega Física
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
