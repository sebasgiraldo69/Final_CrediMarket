import { ReactNode, useEffect, useId, useRef, useState } from 'react';
import { api } from './api';

export type Product = {
  id: string; nombre: string; categoria: string; precio_cop: string;
  activo: boolean; version: number; created_at: string; updated_at: string;
};
export type Page<T> = { items: T[]; total: number; limit: number; offset: number };

export function formatMoney(amount: string | number | null | undefined) {
  if (amount === null || amount === undefined || amount === '') return '—';
  return new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 }).format(Number(amount));
}

export function formatDate(value: string | null | undefined) {
  if (!value) return '—';
  return new Date(value).toLocaleString('es-CO', { dateStyle: 'medium', timeStyle: 'short' });
}

export function shortId(id: string | null | undefined) { return id ? `${id.slice(0, 8)}…` : '—'; }

export function Feedback({ error, notice, onClose }: { error?: string; notice?: string; onClose?: () => void }) {
  if (!error && !notice) return null;
  return <div className={error ? 'error' : 'success'} role={error ? 'alert' : 'status'}>
    <span>{error || notice}</span>
    {onClose && <button type="button" className="link" onClick={onClose} aria-label="Cerrar mensaje">×</button>}
  </div>;
}

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const titleId = useId();
  const ref = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>('input, select, textarea, button:not(.modal-close)')?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') close.current(); };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); previous?.focus(); };
  }, []);
  return <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div ref={ref} className={`modal${wide ? ' wide' : ''}`} role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <div className="modal-heading"><h2 id={titleId}>{title}</h2><button type="button" className="modal-close link" onClick={onClose} aria-label="Cerrar">×</button></div>
      {children}
    </div>
  </div>;
}

export function Pagination({ offset, limit, total, busy, onChange, label }: { offset: number; limit: number; total: number; busy?: boolean; onChange: (offset: number) => void; label: string }) {
  const pages = Math.max(1, Math.ceil(total / limit));
  return <div className="pagination">
    <button type="button" disabled={busy || offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>Anterior</button>
    <span>{total} {label} · Página {Math.floor(offset / limit) + 1} de {pages}</span>
    <button type="button" disabled={busy || offset + limit >= total} onClick={() => onChange(offset + limit)}>Siguiente</button>
  </div>;
}

// Polling con retroceso exponencial: 2 s mientras responde, hasta 30 s si falla. Se pausa con la pestaña oculta.
export function usePolling(task: () => Promise<void>, active: boolean, baseMs = 2000, maxMs = 30000) {
  const taskRef = useRef(task);
  taskRef.current = task;
  const [failures, setFailures] = useState(0);
  useEffect(() => {
    if (!active) { setFailures(0); return; }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    let fails = 0;
    const schedule = () => { timer = setTimeout(tick, fails ? Math.min(maxMs, baseMs * 2 ** fails) : baseMs); };
    const tick = async () => {
      if (document.hidden) { schedule(); return; }
      try { await taskRef.current(); fails = 0; } catch { fails += 1; }
      if (cancelled) return;
      setFailures(fails);
      schedule();
    };
    schedule();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [active, baseMs, maxMs]);
  return failures;
}

const productNames = new Map<string, string>();

// Nombres de producto para listas que solo traen el identificador; si no se puede leer, se muestra el id.
export function useProductNames(ids: string[], token: string | undefined) {
  const key = Array.from(new Set(ids)).sort().join(',');
  const [, setVersion] = useState(0);
  useEffect(() => {
    const missing = key.split(',').filter(id => id && !productNames.has(id));
    if (!missing.length || !token) return;
    let alive = true;
    Promise.all(missing.map(id => api<Product>('productos', `/productos/${id}`, { token })
      .then(product => { productNames.set(id, product.nombre); })
      .catch(() => undefined)))
      .then(() => { if (alive) setVersion(v => v + 1); });
    return () => { alive = false; };
  }, [key, token]);
  return (id: string) => productNames.get(id);
}

export function rememberProducts(products: Product[]) {
  for (const product of products) productNames.set(product.id, product.nombre);
}

export async function loadAllProducts(token: string, includeInactive: boolean): Promise<Product[]> {
  const products: Product[] = [];
  for (let offset = 0; ; offset += 100) {
    const page = await api<Page<Product>>('productos', `/productos?limit=100&offset=${offset}&incluir_inactivos=${includeInactive}`, { token });
    products.push(...page.items);
    if (offset + 100 >= page.total) break;
  }
  rememberProducts(products);
  return products;
}
