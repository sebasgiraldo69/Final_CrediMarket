import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError, errorText, IdempotencyKeys } from './api';
import { estimateInstallment, loanStates, motiveText, POLICY } from './labels';
import type { Session } from './session';
import type { Loan } from './Solicitudes';
import { Feedback, formatMoney, loadAllProducts, Modal, Pagination, type Product } from './ui';

const PAGE = 12;

export function Catalogo({ session, navigate }: { session: Session | null; navigate: (to: string) => void }) {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');
  const [offset, setOffset] = useState(0);
  const [includeInactive, setIncludeInactive] = useState(false);
  const [financesMissing, setFinancesMissing] = useState(false);
  const [editing, setEditing] = useState<Product | 'nuevo' | null>(null);
  const [deactivating, setDeactivating] = useState<Product | null>(null);
  const [requesting, setRequesting] = useState<Product | null>(null);
  const isAdmin = session?.role === 'administrador';
  const token = session?.access_token;

  async function reload() {
    if (!token) return;
    setLoading(true); setError('');
    try { setProducts(await loadAllProducts(token, isAdmin && includeInactive)); }
    catch (err) { setError(errorText(err)); }
    finally { setLoading(false); }
  }
  useEffect(() => { void reload(); }, [token, includeInactive]);

  useEffect(() => {
    if (session?.role !== 'cliente' || !session.cliente_id) return;
    api<{ finanzas: unknown }>('clientes', `/clientes/${session.cliente_id}`, { token })
      .then(profile => setFinancesMissing(!profile.finanzas)).catch(() => undefined);
  }, [token]);

  const categories = useMemo(() => Array.from(new Set(products.map(p => p.categoria))).sort(), [products]);
  const filtered = products.filter(p => (!category || p.categoria === category)
    && (!search || `${p.nombre} ${p.categoria}`.toLowerCase().includes(search.trim().toLowerCase())));
  const visible = filtered.slice(offset, offset + PAGE);

  async function mutate(work: () => Promise<void>, success: string) {
    setBusy(true); setError(''); setNotice('');
    try { await work(); setNotice(success); await reload(); return true; }
    catch (err) {
      setError(errorText(err));
      if (err instanceof ApiError && err.status === 409) await reload();
      return false;
    } finally { setBusy(false); }
  }

  async function saveProduct(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const values = {
      nombre: String(form.get('nombre')).trim(),
      categoria: String(form.get('categoria')).trim(),
      precio_cop: Number(form.get('precio_cop')).toFixed(2),
    };
    const current = editing;
    const ok = current === 'nuevo'
      ? await mutate(() => api('productos', '/productos', { method: 'POST', token, body: values }), `Producto «${values.nombre}» creado.`)
      : await mutate(async () => {
          const changes: Record<string, unknown> = { version_esperada: current!.version };
          for (const [field, value] of Object.entries(values)) if (value !== current![field as keyof Product]) changes[field] = value;
          await api('productos', `/productos/${current!.id}`, { method: 'PATCH', token, body: changes });
        }, 'Producto actualizado. La cotización en caché se invalidó.');
    if (ok) setEditing(null);
  }

  async function deactivate() {
    const product = deactivating!;
    const ok = await mutate(() => api('productos', `/productos/${product.id}/desactivar`, { method: 'POST', token, body: { version_esperada: product.version } }),
      `«${product.nombre}» desactivado; los clientes ya no lo ven.`);
    if (ok) setDeactivating(null);
  }

  if (!session) return <section className="panel narrow">
    <p className="eyebrow">Catálogo</p>
    <h1>Explora nuestra tecnología</h1>
    <p className="intro">Inicia sesión para ver los precios vigentes y solicitar financiación.</p>
    <button className="primary" onClick={() => navigate('/acceso')}>Ingresar o registrarse</button>
  </section>;

  return <section>
    <div className="module-heading">
      <div><p className="eyebrow">Catálogo</p><h1>{isAdmin ? 'Administrar productos' : 'Productos disponibles'}</h1></div>
      {isAdmin && <button className="primary" disabled={busy} onClick={() => setEditing('nuevo')}>Nuevo producto</button>}
    </div>
    {financesMissing && <p className="warning" role="status">Tu perfil financiero aún no está completo. Las solicitudes se rechazarán por información incompleta hasta que un administrador lo complete.</p>}
    <Feedback error={error} notice={notice} onClose={() => { setError(''); setNotice(''); }} />

    <div className="toolbar">
      <label>Buscar<input type="search" value={search} placeholder="Nombre o categoría" onChange={e => { setSearch(e.target.value); setOffset(0); }} /></label>
      <label>Categoría<select value={category} onChange={e => { setCategory(e.target.value); setOffset(0); }}>
        <option value="">Todas</option>{categories.map(c => <option key={c}>{c}</option>)}
      </select></label>
      {isAdmin && <label className="check"><input type="checkbox" checked={includeInactive} onChange={e => { setIncludeInactive(e.target.checked); setOffset(0); }} />Incluir inactivos</label>}
      <button type="button" onClick={() => void reload()} disabled={loading}>{loading ? 'Cargando…' : 'Actualizar'}</button>
    </div>

    {loading && !products.length ? <p role="status" className="loading">Cargando catálogo…</p>
      : !visible.length ? <p className="empty">{products.length ? 'Ningún producto coincide con la búsqueda.' : 'Todavía no hay productos en el catálogo.'}</p>
      : <div className="product-grid">{visible.map(product => <article key={product.id} className={`product${product.activo ? '' : ' inactive'}`}>
          <p className="eyebrow">{product.categoria}</p>
          <h3>{product.nombre}</h3>
          <p className="price">{formatMoney(product.precio_cop)}</p>
          <p className="note">Desde {formatMoney(estimateInstallment(Number(product.precio_cop), 36))}/mes a 36 meses</p>
          {isAdmin && <p className="meta"><code>{product.id}</code> · Versión {product.version} · {product.activo ? 'Activo' : 'Inactivo'}</p>}
          <div className="actions">
            {isAdmin ? <>
              <button type="button" disabled={busy} onClick={() => setEditing(product)}>Editar</button>
              {product.activo && <button type="button" className="danger" disabled={busy} onClick={() => setDeactivating(product)}>Desactivar</button>}
            </> : <button type="button" className="primary" onClick={() => setRequesting(product)}>Solicitar a crédito</button>}
          </div>
        </article>)}</div>}
    <Pagination offset={offset} limit={PAGE} total={filtered.length} onChange={setOffset} label="productos" />

    {editing && <Modal title={editing === 'nuevo' ? 'Nuevo producto' : `Editar «${editing.nombre}»`} onClose={() => setEditing(null)}>
      <form onSubmit={saveProduct} className="stack">
        {editing !== 'nuevo' && <p className="note">Versión {editing.version}. Si otra persona lo modifica antes, verás un conflicto y los datos se recargarán.</p>}
        <label>Nombre<input name="nombre" required minLength={1} maxLength={250} defaultValue={editing === 'nuevo' ? '' : editing.nombre} /></label>
        <label>Categoría<input name="categoria" required minLength={1} maxLength={250} list="categorias" defaultValue={editing === 'nuevo' ? '' : editing.categoria} /></label>
        <datalist id="categorias">{categories.map(c => <option key={c} value={c} />)}</datalist>
        <label>Precio (COP)<input name="precio_cop" type="number" required min="0.01" step="0.01" defaultValue={editing === 'nuevo' ? '' : editing.precio_cop} /></label>
        <div className="actions"><button className="primary" disabled={busy}>{busy ? 'Guardando…' : 'Guardar'}</button><button type="button" onClick={() => setEditing(null)}>Cancelar</button></div>
      </form>
    </Modal>}

    {deactivating && <Modal title="Desactivar producto" onClose={() => setDeactivating(null)}>
      <p>«{deactivating.nombre}» dejará de aparecer para los clientes y no podrá solicitarse. Las solicitudes existentes no cambian.</p>
      <div className="actions"><button className="danger-solid" disabled={busy} onClick={() => void deactivate()}>{busy ? 'Desactivando…' : 'Desactivar'}</button><button onClick={() => setDeactivating(null)}>Cancelar</button></div>
    </Modal>}

    {requesting && session.role === 'cliente' && <SolicitudCredito product={requesting} session={session} onClose={() => setRequesting(null)} onTrack={() => navigate('/solicitudes')} />}
  </section>;
}

const keys = new IdempotencyKeys();

function SolicitudCredito({ product, session, onClose, onTrack }: { product: Product; session: Session; onClose: () => void; onTrack: () => void }) {
  const [quantity, setQuantity] = useState(1);
  const [term, setTerm] = useState(12);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [result, setResult] = useState<Loan | null>(null);
  const submitting = useRef(false);
  const amount = Number(product.precio_cop) * quantity;
  const outOfPolicy = amount < POLICY.minAmount || amount > POLICY.maxAmount;
  const scope = `solicitud:${product.id}`;

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    if (submitting.current || outOfPolicy) return;
    submitting.current = true; setBusy(true); setError(null);
    const body = { producto_id: product.id, cantidad: quantity, plazo_meses: term };
    try {
      const loan = await api<Loan>('prestamos', '/prestamos', { method: 'POST', token: session.access_token, body, idempotencyKey: keys.keyFor(scope, body) });
      keys.settle(scope);
      setResult(loan);
    } catch (err) {
      // 409 por la misma clave con otro cuerpo no se repite; los errores transitorios conservan la clave.
      if (!(err instanceof ApiError) || !err.retryable) keys.settle(scope);
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally { submitting.current = false; setBusy(false); }
  }

  if (result) {
    const state = loanStates[result.estado];
    return <Modal title="Resultado de la solicitud" onClose={onClose}>
      <p className={`state-pill ${state.tone}`}>{state.label}</p>
      <p>{result.estado === 'RECHAZADA' ? motiveText(result.motivo) : state.help}</p>
      <dl className="facts">
        <dt>Producto</dt><dd>{product.nombre} × {result.cantidad}</dd>
        <dt>Precio cotizado</dt><dd>{formatMoney(result.precio_unitario_cop)} (versión {result.version_producto ?? '—'})</dd>
        <dt>Monto</dt><dd>{formatMoney(result.monto_cop)}</dd>
        <dt>Cuota mensual</dt><dd>{formatMoney(result.cuota_cop)} × {result.plazo_meses} meses</dd>
        {result.riesgo && <><dt>Evaluación de riesgo</dt><dd>{result.riesgo.decision_riesgo === 'FAVORABLE' ? 'Favorable' : 'Desfavorable'} · probabilidad {(result.riesgo.probabilidad_incumplimiento * 100).toFixed(1)} % · modelo {result.riesgo.model_version}</dd></>}
      </dl>
      <div className="actions"><button className="primary" onClick={onTrack}>Ver mis solicitudes</button><button onClick={onClose}>Cerrar</button></div>
    </Modal>;
  }

  const retryable = error instanceof ApiError && error.retryable;
  return <Modal title={`Solicitar «${product.nombre}» a crédito`} onClose={() => { if (!busy) onClose(); }}>
    <form onSubmit={submit} className="stack">
      <div className="form-grid">
        <label>Cantidad<input type="number" min={1} max={POLICY.maxQuantity} required value={quantity} disabled={busy}
          onChange={e => setQuantity(Math.min(POLICY.maxQuantity, Math.max(1, Math.trunc(Number(e.target.value)) || 1)))} /></label>
        <label>Plazo<select value={term} disabled={busy} onChange={e => setTerm(Number(e.target.value))}>
          {POLICY.terms.map(t => <option key={t} value={t}>{t} meses</option>)}</select></label>
      </div>
      <dl className="facts">
        <dt>Precio unitario</dt><dd>{formatMoney(product.precio_cop)}</dd>
        <dt>Monto total</dt><dd>{formatMoney(amount)}</dd>
        <dt>Cuota estimada</dt><dd><strong>{formatMoney(estimateInstallment(amount, term))}</strong> /mes · tasa fija 1,8 % mensual</dd>
      </dl>
      {outOfPolicy && <p className="warning" role="alert">El monto debe estar entre {formatMoney(POLICY.minAmount)} y {formatMoney(POLICY.maxAmount)}. Ajusta la cantidad.</p>}
      <p className="note">El precio se vuelve a cotizar al enviar; el resultado muestra el valor definitivo.</p>
      {error && <div className="error" role="alert">{errorText(error)}{retryable && ' Al reintentar se reutiliza la misma solicitud, sin duplicarla.'}</div>}
      <div className="actions">
        <button className="primary" disabled={busy || outOfPolicy}>{busy ? 'Evaluando…' : retryable ? 'Reintentar envío' : 'Enviar solicitud'}</button>
        <button type="button" onClick={onClose} disabled={busy}>Cancelar</button>
      </div>
    </form>
  </Modal>;
}
