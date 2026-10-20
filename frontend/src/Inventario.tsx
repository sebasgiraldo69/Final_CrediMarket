import { FormEvent, useEffect, useState } from 'react';
import type { Session } from './Clientes';

export type Existencia = {
  producto_id: string;
  fisico: number;
  reservado: number;
  disponible: number;
};

export type Movimiento = {
  id: string;
  producto_id: string;
  prestamo_id: string | null;
  tipo: 'ENTRADA' | 'RESERVA' | 'LIBERACION' | 'SALIDA' | 'VENCIMIENTO';
  cantidad: number;
  motivo: string;
  created_at: string;
};

export type Reserva = {
  reserva_id: string;
  prestamo_id: string;
  producto_id: string | null;
  cantidad: number | null;
  estado_reserva: 'ACTIVA' | 'SIN_STOCK' | 'CANCELADA' | 'VENCIDA' | 'ENTREGADA';
  revision_reserva: number;
  vence_en: string | null;
};

interface InventarioProps {
  session: Session | null;
  onNavigateToClients?: () => void;
}

export function Inventario({ session, onNavigateToClients }: InventarioProps) {
  const [tab, setTab] = useState<'existencias' | 'movimientos' | 'reservas'>('existencias');
  const [existencias, setExistencias] = useState<Existencia[]>([]);
  const [movimientos, setMovimientos] = useState<Movimiento[]>([]);
  const [reservas, setReservas] = useState<Reserva[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  // Form registrar entrada
  const [showEntradaForm, setShowEntradaForm] = useState(false);
  const [entradaProductoId, setEntradaProductoId] = useState('');
  const [entradaCantidad, setEntradaCantidad] = useState(5);
  const [entradaMotivo, setEntradaMotivo] = useState('Reabastecimiento regular de inventario');

  const isAdmin = session?.role === 'administrador';

  async function api(path: string, options: RequestInit = {}) {
    const headers = new Headers(options.headers);
    if (session?.access_token) {
      headers.set('Authorization', `Bearer ${session.access_token}`);
    }
    if (options.body && !(options.body instanceof FormData)) {
      headers.set('Content-Type', 'application/json');
    }
    const response = await fetch(`/api/inventario${path}`, { ...options, headers });
    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error('El servicio de inventario no está disponible.');
    }
    if (!response.ok) {
      const details = data.details?.map((d: { field: string; message: string }) => `${d.field}: ${d.message}`).join(' · ');
      throw new Error([data.message || 'Error en la solicitud', details].filter(Boolean).join(' · '));
    }
    return data;
  }

  async function loadData() {
    if (!isAdmin) return;
    setBusy(true);
    setError('');
    try {
      if (tab === 'existencias') {
        const data = await api('/inventario?limit=50&offset=0');
        setExistencias(data.items);
      } else if (tab === 'movimientos') {
        const data = await api('/inventario/movimientos?limit=50&offset=0');
        setMovimientos(data.items);
      } else if (tab === 'reservas') {
        const data = await api('/inventario/reservas?limit=50&offset=0');
        setReservas(data.items);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al cargar datos de inventario.');
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    loadData();
  }, [tab, session]);

  async function handleRegistrarEntrada(e: FormEvent) {
    e.preventDefault();
    if (!entradaProductoId.trim()) {
      setError('Debes ingresar un UUID de producto válido.');
      return;
    }
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const idempotencyKey = `entrada-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
      const result = await api('/inventario/entradas', {
        method: 'POST',
        headers: {
          'Idempotency-Key': idempotencyKey
        },
        body: JSON.stringify({
          producto_id: entradaProductoId.trim(),
          cantidad: Number(entradaCantidad),
          motivo: entradaMotivo.trim()
        })
      });
      setNotice(`Entrada registrada exitosamente: Movimiento ID ${result.id} (+${result.cantidad} unidades).`);
      setShowEntradaForm(false);
      setEntradaProductoId('');
      if (tab === 'existencias') {
        loadData();
      } else {
        setTab('existencias');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al registrar entrada.');
    } finally {
      setBusy(false);
    }
  }

  if (!session) {
    return (
      <section className="panel" aria-label="Inventario protegido">
        <p className="eyebrow">Acceso restringido</p>
        <h1>Control de inventario</h1>
        <p className="intro">
          Debes iniciar sesión con una cuenta de <strong>Administrador</strong> para consultar el stock físico, reservado y disponible,
          así como para registrar entradas de productos y auditar movimientos.
        </p>
        <button type="button" onClick={onNavigateToClients}>
          Ir a Iniciar Sesión
        </button>
      </section>
    );
  }

  if (!isAdmin) {
    return (
      <section className="panel" aria-label="Permiso insuficiente">
        <p className="eyebrow">Permiso insuficiente</p>
        <h1>Módulo de Inventario</h1>
        <p className="intro">
          Tu cuenta actual (<strong>{session.email}</strong>) tiene rol de <strong>{session.role}</strong>.
          Las consultas de existencias, movimientos y registro de entradas están reservadas exclusivamente para administradores.
        </p>
      </section>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <section className="panel" aria-label="Gestión de inventario">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <p className="eyebrow">Fase 5 · Control de Stock y Reservas Atómicas</p>
            <h1 style={{ margin: '4px 0 8px 0' }}>Gestión de Inventario</h1>
            <p style={{ margin: 0, color: '#4a7663' }}>
              Protección de existencias con aislamiento transaccional PostgreSQL (físico, reservado y disponible).
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowEntradaForm(!showEntradaForm)}
            style={{ padding: '8px 16px', fontWeight: 600 }}
          >
            {showEntradaForm ? 'Cerrar Formulario' : '+ Registrar Entrada de Stock'}
          </button>
        </div>

        {error && (
          <div role="alert" style={{ background: '#fdf2f2', border: '1px solid #f8b4b4', padding: '10px 14px', borderRadius: 6, color: '#9b1c1c', marginTop: 16 }}>
            {error}
          </div>
        )}

        {notice && (
          <div role="status" style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', padding: '10px 14px', borderRadius: 6, color: '#166534', marginTop: 16 }}>
            {notice}
          </div>
        )}

        {showEntradaForm && (
          <form onSubmit={handleRegistrarEntrada} style={{ marginTop: 20, padding: 16, background: '#f8faf9', borderRadius: 8, border: '1px solid #e2e8e5' }}>
            <h3 style={{ marginTop: 0, marginBottom: 12 }}>Nueva Entrada de Existencias</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 12 }}>
              <div>
                <label style={{ display: 'block', fontSize: 13, marginBottom: 4, fontWeight: 500 }}>
                  ID Producto (UUID):
                </label>
                <input
                  type="text"
                  required
                  placeholder="10000000-0000-4000-8000-000000000001"
                  value={entradaProductoId}
                  onChange={e => setEntradaProductoId(e.target.value)}
                  style={{ width: '100%', padding: '8px 10px', boxSizing: 'border-box' }}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 13, marginBottom: 4, fontWeight: 500 }}>
                  Cantidad a ingresar:
                </label>
                <input
                  type="number"
                  required
                  min={1}
                  max={1000}
                  value={entradaCantidad}
                  onChange={e => setEntradaCantidad(Number(e.target.value))}
                  style={{ width: '100%', padding: '8px 10px', boxSizing: 'border-box' }}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: 13, marginBottom: 4, fontWeight: 500 }}>
                  Motivo de entrada:
                </label>
                <input
                  type="text"
                  required
                  maxLength={250}
                  value={entradaMotivo}
                  onChange={e => setEntradaMotivo(e.target.value)}
                  style={{ width: '100%', padding: '8px 10px', boxSizing: 'border-box' }}
                />
              </div>
            </div>
            <div style={{ marginTop: 14, display: 'flex', gap: 10 }}>
              <button type="submit" disabled={busy} style={{ padding: '8px 18px', fontWeight: 600 }}>
                {busy ? 'Registrando...' : 'Confirmar Entrada'}
              </button>
              <button type="button" onClick={() => setShowEntradaForm(false)} style={{ background: 'transparent', border: '1px solid #bbb', padding: '8px 14px' }}>
                Cancelar
              </button>
            </div>
          </form>
        )}
      </section>

      {/* Tabs navigation */}
      <div style={{ display: 'flex', gap: 8, borderBottom: '2px solid #e5e7eb' }}>
        <button
          type="button"
          onClick={() => setTab('existencias')}
          style={{
            padding: '10px 20px',
            background: tab === 'existencias' ? '#fff' : '#f3f4f6',
            border: 'none',
            borderBottom: tab === 'existencias' ? '3px solid #2d6a4f' : 'none',
            fontWeight: tab === 'existencias' ? 700 : 500,
            cursor: 'pointer'
          }}
        >
          Existencias ({existencias.length})
        </button>
        <button
          type="button"
          onClick={() => setTab('movimientos')}
          style={{
            padding: '10px 20px',
            background: tab === 'movimientos' ? '#fff' : '#f3f4f6',
            border: 'none',
            borderBottom: tab === 'movimientos' ? '3px solid #2d6a4f' : 'none',
            fontWeight: tab === 'movimientos' ? 700 : 500,
            cursor: 'pointer'
          }}
        >
          Movimientos ({movimientos.length})
        </button>
        <button
          type="button"
          onClick={() => setTab('reservas')}
          style={{
            padding: '10px 20px',
            background: tab === 'reservas' ? '#fff' : '#f3f4f6',
            border: 'none',
            borderBottom: tab === 'reservas' ? '3px solid #2d6a4f' : 'none',
            fontWeight: tab === 'reservas' ? 700 : 500,
            cursor: 'pointer'
          }}
        >
          Reservas ({reservas.length})
        </button>
      </div>

      {busy && <p style={{ color: '#6b7280' }}>Cargando datos de {tab}...</p>}

      {tab === 'existencias' && !busy && (
        <section className="panel" aria-label="Tabla de existencias">
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
            <thead>
              <tr style={{ borderBottom: '2px solid #d1d5db', background: '#f9fafb' }}>
                <th style={{ padding: '10px 12px' }}>Producto ID</th>
                <th style={{ padding: '10px 12px' }}>Stock Físico</th>
                <th style={{ padding: '10px 12px' }}>Reservado</th>
                <th style={{ padding: '10px 12px' }}>Disponible</th>
                <th style={{ padding: '10px 12px' }}>Acción</th>
              </tr>
            </thead>
            <tbody>
              {existencias.map(ex => (
                <tr key={ex.producto_id} style={{ borderBottom: '1px solid #e5e7eb' }}>
                  <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontSize: 13 }}>
                    {ex.producto_id}
                  </td>
                  <td style={{ padding: '10px 12px', fontWeight: 600 }}>{ex.fisico}</td>
                  <td style={{ padding: '10px 12px', color: '#b45309' }}>{ex.reservado}</td>
                  <td style={{ padding: '10px 12px', color: ex.disponible > 0 ? '#15803d' : '#b91c1c', fontWeight: 700 }}>
                    {ex.disponible}
                  </td>
                  <td style={{ padding: '10px 12px' }}>
                    <button
                      type="button"
                      onClick={() => {
                        setEntradaProductoId(ex.producto_id);
                        setShowEntradaForm(true);
                      }}
                      style={{ fontSize: 12, padding: '4px 8px' }}
                    >
                      + Stock
                    </button>
                  </td>
                </tr>
              ))}
              {existencias.length === 0 && (
                <tr>
                  <td colSpan={5} style={{ padding: 24, textAlign: 'center', color: '#6b7280' }}>
                    No hay existencias registradas en la base de datos.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'movimientos' && !busy && (
        <section className="panel" aria-label="Tabla de movimientos">
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
            <thead>
              <tr style={{ borderBottom: '2px solid #d1d5db', background: '#f9fafb' }}>
                <th style={{ padding: '10px 12px' }}>Fecha</th>
                <th style={{ padding: '10px 12px' }}>Tipo</th>
                <th style={{ padding: '10px 12px' }}>Producto ID</th>
                <th style={{ padding: '10px 12px' }}>Préstamo ID</th>
                <th style={{ padding: '10px 12px' }}>Cantidad</th>
                <th style={{ padding: '10px 12px' }}>Motivo</th>
              </tr>
            </thead>
            <tbody>
              {movimientos.map(mov => (
                <tr key={mov.id} style={{ borderBottom: '1px solid #e5e7eb' }}>
                  <td style={{ padding: '10px 12px', fontSize: 12 }}>
                    {new Date(mov.created_at).toLocaleString()}
                  </td>
                  <td style={{ padding: '10px 12px' }}>
                    <span
                      style={{
                        padding: '2px 8px',
                        borderRadius: 4,
                        fontSize: 12,
                        fontWeight: 600,
                        background:
                          mov.tipo === 'ENTRADA' ? '#dcfce7' :
                          mov.tipo === 'RESERVA' ? '#fef3c7' :
                          mov.tipo === 'LIBERACION' ? '#e0e7ff' :
                          mov.tipo === 'SALIDA' ? '#dbeafe' : '#fee2e2',
                        color:
                          mov.tipo === 'ENTRADA' ? '#166534' :
                          mov.tipo === 'RESERVA' ? '#92400e' :
                          mov.tipo === 'LIBERACION' ? '#3730a3' :
                          mov.tipo === 'SALIDA' ? '#1e40af' : '#991b1b'
                      }}
                    >
                      {mov.tipo}
                    </span>
                  </td>
                  <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontSize: 12 }}>
                    {mov.producto_id}
                  </td>
                  <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontSize: 12 }}>
                    {mov.prestamo_id || '—'}
                  </td>
                  <td style={{ padding: '10px 12px', fontWeight: 600 }}>{mov.cantidad}</td>
                  <td style={{ padding: '10px 12px', fontSize: 13 }}>{mov.motivo}</td>
                </tr>
              ))}
              {movimientos.length === 0 && (
                <tr>
                  <td colSpan={6} style={{ padding: 24, textAlign: 'center', color: '#6b7280' }}>
                    No hay movimientos registrados.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'reservas' && !busy && (
        <section className="panel" aria-label="Tabla de reservas">
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
            <thead>
              <tr style={{ borderBottom: '2px solid #d1d5db', background: '#f9fafb' }}>
                <th style={{ padding: '10px 12px' }}>Reserva ID</th>
                <th style={{ padding: '10px 12px' }}>Préstamo ID</th>
                <th style={{ padding: '10px 12px' }}>Estado</th>
                <th style={{ padding: '10px 12px' }}>Revisión</th>
                <th style={{ padding: '10px 12px' }}>Cantidad</th>
                <th style={{ padding: '10px 12px' }}>Vencimiento</th>
              </tr>
            </thead>
            <tbody>
              {reservas.map(res => (
                <tr key={res.reserva_id} style={{ borderBottom: '1px solid #e5e7eb' }}>
                  <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontSize: 12 }}>
                    {res.reserva_id}
                  </td>
                  <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontSize: 12 }}>
                    {res.prestamo_id}
                  </td>
                  <td style={{ padding: '10px 12px' }}>
                    <span
                      style={{
                        padding: '2px 8px',
                        borderRadius: 4,
                        fontSize: 12,
                        fontWeight: 600,
                        background:
                          res.estado_reserva === 'ACTIVA' ? '#dcfce7' :
                          res.estado_reserva === 'ENTREGADA' ? '#dbeafe' :
                          res.estado_reserva === 'SIN_STOCK' ? '#fef3c7' : '#fee2e2',
                        color:
                          res.estado_reserva === 'ACTIVA' ? '#166534' :
                          res.estado_reserva === 'ENTREGADA' ? '#1e40af' :
                          res.estado_reserva === 'SIN_STOCK' ? '#92400e' : '#991b1b'
                      }}
                    >
                      {res.estado_reserva}
                    </span>
                  </td>
                  <td style={{ padding: '10px 12px', fontWeight: 600 }}>v{res.revision_reserva}</td>
                  <td style={{ padding: '10px 12px' }}>{res.cantidad ?? '—'}</td>
                  <td style={{ padding: '10px 12px', fontSize: 12 }}>
                    {res.vence_en ? new Date(res.vence_en).toLocaleString() : '—'}
                  </td>
                </tr>
              ))}
              {reservas.length === 0 && (
                <tr>
                  <td colSpan={6} style={{ padding: 24, textAlign: 'center', color: '#6b7280' }}>
                    No hay reservas registradas.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
