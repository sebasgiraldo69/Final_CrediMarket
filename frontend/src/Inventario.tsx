import { FormEvent, useEffect, useRef, useState } from 'react';
import { api, ApiError, errorText, IdempotencyKeys } from './api';
import type { Session } from './session';
import { Feedback, formatDate, loadAllProducts, Modal, Pagination, shortId, usePolling, type Page, type Product } from './ui';

type Existencia = { producto_id: string; fisico: number; reservado: number; disponible: number };
type Movimiento = { id: string; producto_id: string; prestamo_id: string | null; tipo: 'ENTRADA' | 'RESERVA' | 'LIBERACION' | 'SALIDA' | 'VENCIMIENTO'; cantidad: number; motivo: string; created_at: string };
type Reserva = { reserva_id: string; prestamo_id: string; producto_id: string | null; cantidad: number | null; estado_reserva: 'ACTIVA' | 'SIN_STOCK' | 'CANCELADA' | 'VENCIDA' | 'ENTREGADA'; revision_reserva: number; vence_en: string | null };
type Tab = 'existencias' | 'reservas' | 'movimientos';

const PAGE = 20;
const tabs: [Tab, string, string][] = [
  ['existencias', 'Existencias', '/inventario'],
  ['reservas', 'Reservas', '/inventario/reservas'],
  ['movimientos', 'Movimientos', '/inventario/movimientos'],
];
const movementTone: Record<Movimiento['tipo'], string> = { ENTRADA: 'ok', RESERVA: 'pending', LIBERACION: 'neutral', SALIDA: 'done', VENCIMIENTO: 'bad' };
const reserveTone: Record<Reserva['estado_reserva'], string> = { ACTIVA: 'ok', ENTREGADA: 'done', SIN_STOCK: 'pending', CANCELADA: 'bad', VENCIDA: 'bad' };
const keys = new IdempotencyKeys();

export function Inventario({ session }: { session: Session }) {
  const token = session.access_token;
  const [tab, setTab] = useState<Tab>('existencias');
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<any> | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [entry, setEntry] = useState<string | null>(null);
  const [entryError, setEntryError] = useState<ApiError | null>(null);
  const name = (id: string | null) => (id && products.find(p => p.id === id)?.nombre) || shortId(id);

  const view = useRef({ tab, offset });
  view.current = { tab, offset };

  async function fetchTab() {
    const requested = { tab, offset };
    const path = tabs.find(([key]) => key === tab)![2];
    const data = await api<Page<any>>('inventario', `${path}?limit=${PAGE}&offset=${offset}`, { token });
    // Una respuesta tardía de otra pestaña o página no debe reemplazar la vista actual.
    if (view.current.tab === requested.tab && view.current.offset === requested.offset) setPage(data);
  }

  async function reload() {
    setLoading(true); setError('');
    try { await fetchTab(); } catch (err) { setError(errorText(err)); } finally { setLoading(false); }
  }
  useEffect(() => { void reload(); }, [tab, offset]);
  useEffect(() => { loadAllProducts(token, true).then(setProducts).catch(err => setError(errorText(err))); }, [token]);
  // Las reservas cambian por eventos de Kafka: refresco silencioso cada 5 s.
  const failures = usePolling(fetchTab, !loading, 5000);

  async function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body = { producto_id: String(form.get('producto_id')), cantidad: Number(form.get('cantidad')), motivo: String(form.get('motivo')).trim() };
    const scope = 'entrada';
    setBusy(true); setEntryError(null); setNotice('');
    try {
      const movement = await api<Movimiento>('inventario', '/inventario/entradas', { method: 'POST', token, body, idempotencyKey: keys.keyFor(scope, body) });
      keys.settle(scope);
      setEntry(null);
      setNotice(`Entrada registrada: +${movement.cantidad} de ${name(movement.producto_id)}.`);
      if (tab !== 'existencias') { setTab('existencias'); setOffset(0); } else await reload();
    } catch (err) {
      if (!(err instanceof ApiError) || !err.retryable) keys.settle(scope);
      setEntryError(err instanceof ApiError ? err : new ApiError(errorText(err), 0));
    } finally { setBusy(false); }
  }

  const activeProducts = products.filter(p => p.activo);
  return <section>
    <div className="module-heading">
      <div><p className="eyebrow">Administración</p><h1>Inventario</h1></div>
      <button className="primary" onClick={() => { setEntryError(null); setEntry(''); }}>Registrar entrada</button>
    </div>
    <Feedback error={error} notice={notice} onClose={() => { setError(''); setNotice(''); }} />
    <div className="tabs" role="tablist">
      {tabs.map(([key, label]) => <button key={key} role="tab" aria-selected={tab === key} onClick={() => { setTab(key); setOffset(0); setPage(null); }}>{label}</button>)}
    </div>
    <p className="live" aria-live="polite">{failures > 0 ? <span className="bad-text">Sin conexión con Inventario; reintentando…</span> : 'Se actualiza automáticamente cada 5 s.'}</p>

    {!page ? <p className="loading" role="status">Cargando…</p> : !page.items.length ? <p className="empty">Sin registros todavía.</p>
      : <div className="table-scroll"><table className="responsive">
        {tab === 'existencias' && <>
          <thead><tr><th>Producto</th><th>Físico</th><th>Reservado</th><th>Disponible</th><th>Acción</th></tr></thead>
          <tbody>{(page.items as Existencia[]).map(row => <tr key={row.producto_id}>
            <td data-label="Producto"><strong>{name(row.producto_id)}</strong><small><code>{row.producto_id}</code></small></td>
            <td data-label="Físico">{row.fisico}</td>
            <td data-label="Reservado">{row.reservado}</td>
            <td data-label="Disponible" className={row.disponible > 0 ? 'ok-text' : 'bad-text'}><strong>{row.disponible}</strong></td>
            <td data-label="Acción"><button onClick={() => { setEntryError(null); setEntry(row.producto_id); }}>Agregar stock</button></td>
          </tr>)}</tbody>
        </>}
        {tab === 'reservas' && <>
          <thead><tr><th>Reserva</th><th>Préstamo</th><th>Producto</th><th>Cantidad</th><th>Estado</th><th>Vence</th></tr></thead>
          <tbody>{(page.items as Reserva[]).map(row => <tr key={row.reserva_id}>
            <td data-label="Reserva"><code>{shortId(row.reserva_id)}</code><small>revisión {row.revision_reserva}</small></td>
            <td data-label="Préstamo"><code>{shortId(row.prestamo_id)}</code></td>
            <td data-label="Producto">{name(row.producto_id)}</td>
            <td data-label="Cantidad">{row.cantidad ?? '—'}</td>
            <td data-label="Estado"><span className={`state-pill ${reserveTone[row.estado_reserva]}`}>{row.estado_reserva}</span></td>
            <td data-label="Vence">{formatDate(row.vence_en)}</td>
          </tr>)}</tbody>
        </>}
        {tab === 'movimientos' && <>
          <thead><tr><th>Fecha</th><th>Tipo</th><th>Producto</th><th>Cantidad</th><th>Préstamo</th><th>Motivo</th></tr></thead>
          <tbody>{(page.items as Movimiento[]).map(row => <tr key={row.id}>
            <td data-label="Fecha">{formatDate(row.created_at)}</td>
            <td data-label="Tipo"><span className={`state-pill ${movementTone[row.tipo]}`}>{row.tipo}</span></td>
            <td data-label="Producto">{name(row.producto_id)}</td>
            <td data-label="Cantidad">{row.cantidad}</td>
            <td data-label="Préstamo">{row.prestamo_id ? <code>{shortId(row.prestamo_id)}</code> : '—'}</td>
            <td data-label="Motivo">{row.motivo}</td>
          </tr>)}</tbody>
        </>}
      </table></div>}
    {page && <Pagination offset={offset} limit={PAGE} total={page.total} busy={loading} onChange={setOffset} label="registros" />}

    {entry !== null && <Modal title="Registrar entrada de stock" onClose={() => { if (!busy) setEntry(null); }}>
      <form onSubmit={register} className="stack">
        <label>Producto<select name="producto_id" required defaultValue={entry}>
          <option value="" disabled>Selecciona un producto</option>
          {activeProducts.map(p => <option key={p.id} value={p.id}>{p.nombre} · {p.categoria}</option>)}
        </select></label>
        <label>Cantidad<input name="cantidad" type="number" min={1} step={1} required defaultValue={5} /></label>
        <label>Motivo<input name="motivo" required maxLength={250} defaultValue="Reabastecimiento" /></label>
        {entryError && <div className="error" role="alert">{errorText(entryError)}{entryError.retryable && ' Al reintentar se reutiliza la misma entrada, sin duplicarla.'}</div>}
        <div className="actions"><button className="primary" disabled={busy}>{busy ? 'Registrando…' : entryError?.retryable ? 'Reintentar' : 'Registrar'}</button><button type="button" disabled={busy} onClick={() => setEntry(null)}>Cancelar</button></div>
      </form>
    </Modal>}
  </section>;
}
