import { FormEvent, useEffect, useState } from 'react';
import type { Session } from './Clientes';

export type Product = {
  id: string;
  nombre: string;
  categoria: string;
  precio_cop: string;
  activo: boolean;
  version: number;
  created_at: string;
  updated_at: string;
};

interface CatalogoProps {
  session: Session | null;
  onNavigateToClients?: () => void;
}

export function Catalogo({ session, onNavigateToClients }: CatalogoProps) {
  const [products, setProducts] = useState<Product[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [limit] = useState(12);
  const [incluirInactivos, setIncluirInactivos] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  // Estados de administración
  const [editingProduct, setEditingProduct] = useState<Product | null>(null);
  const [creating, setCreating] = useState(false);

  const isAdmin = session?.role === 'administrador';

  async function api(path: string, options: RequestInit = {}) {
    const headers = new Headers(options.headers);
    if (session?.access_token) {
      headers.set('Authorization', `Bearer ${session.access_token}`);
    }
    if (options.body && !(options.body instanceof FormData)) {
      headers.set('Content-Type', 'application/json');
    }
    const response = await fetch(`/api/productos${path}`, { ...options, headers });
    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error('El servicio de productos no está disponible.');
    }
    if (!response.ok) {
      const details = data.details?.map((d: { field: string; message: string }) => `${d.field}: ${d.message}`).join(' · ');
      throw new Error([data.message || 'Error en la solicitud', details].filter(Boolean).join(' · '));
    }
    return data;
  }

  async function loadProducts() {
    if (!session) return;
    setBusy(true);
    setError('');
    try {
      const query = new URLSearchParams({
        limit: String(limit),
        offset: String(offset),
        incluir_inactivos: String(isAdmin && incluirInactivos)
      });
      const data = await api(`/productos?${query.toString()}`);
      setProducts(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error cargando catálogo');
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void loadProducts();
  }, [session, offset, incluirInactivos]);

  async function handleCreate(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const nombre = String(form.get('nombre') || '').trim();
    const categoria = String(form.get('categoria') || '').trim();
    const precioRaw = String(form.get('precio_cop') || '').trim();
    const precio = Number(precioRaw).toFixed(2);

    setBusy(true);
    setError('');
    setNotice('');
    try {
      await api('/productos', {
        method: 'POST',
        body: JSON.stringify({ nombre, categoria, precio_cop: precio })
      });
      setCreating(false);
      setNotice('Producto creado exitosamente en el catálogo.');
      await loadProducts();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error creando producto');
    } finally {
      setBusy(false);
    }
  }

  async function handleEdit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!editingProduct) return;
    const form = new FormData(e.currentTarget);
    const nombre = String(form.get('nombre') || '').trim();
    const categoria = String(form.get('categoria') || '').trim();
    const precioRaw = String(form.get('precio_cop') || '').trim();

    const payload: Record<string, unknown> = {
      version_esperada: editingProduct.version
    };
    if (nombre && nombre !== editingProduct.nombre) payload.nombre = nombre;
    if (categoria && categoria !== editingProduct.categoria) payload.categoria = categoria;
    if (precioRaw) {
      const precio = Number(precioRaw).toFixed(2);
      if (precio !== editingProduct.precio_cop) payload.precio_cop = precio;
    }

    setBusy(true);
    setError('');
    setNotice('');
    try {
      await api(`/productos/${editingProduct.id}`, {
        method: 'PATCH',
        body: JSON.stringify(payload)
      });
      setEditingProduct(null);
      setNotice('Producto y precio actualizados. Caché Redis invalidada.');
      await loadProducts();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error actualizando producto');
    } finally {
      setBusy(false);
    }
  }

  async function handleDeactivate(product: Product) {
    if (!confirm(`¿Estás seguro de desactivar "${product.nombre}"?`)) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await api(`/productos/${product.id}/desactivar`, {
        method: 'POST',
        body: JSON.stringify({ version_esperada: product.version })
      });
      setNotice('Producto desactivado. Ya no será visible para clientes.');
      await loadProducts();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error desactivando producto');
    } finally {
      setBusy(false);
    }
  }

  function formatMoney(amount: string | number) {
    return new Intl.NumberFormat('es-CO', {
      style: 'currency',
      currency: 'COP',
      maximumFractionDigits: 0
    }).format(Number(amount));
  }

  if (!session) {
    return (
      <section className="panel">
        <p className="eyebrow">Catálogo de Productos</p>
        <h1>Explora nuestra tecnología</h1>
        <p className="intro">
          Para consultar los precios vigentes, características de los productos o solicitar financiación a crédito,
          inicia sesión con tu cuenta de cliente o administrador.
        </p>
        {onNavigateToClients && (
          <button className="back" onClick={onNavigateToClients}>
            Ir a Clientes e Iniciar Sesión
          </button>
        )}
      </section>
    );
  }

  const categories = Array.from(new Set(products.map(p => p.categoria)));
  const filteredProducts = categoryFilter
    ? products.filter(p => p.categoria === categoryFilter)
    : products;

  return (
    <section className="client-module">
      <div className="module-heading">
        <div>
          <p className="eyebrow">Catálogo y Precios · Cache Redis</p>
          <h1>Productos Disponibles</h1>
        </div>
        {isAdmin && !creating && !editingProduct && (
          <button onClick={() => setCreating(true)} disabled={busy} style={{ background: '#163d30', color: 'white' }}>
            + Nuevo Producto
          </button>
        )}
      </div>

      {notice && <p className="success" role="status">{notice}</p>}
      {error && <p className="error" role="alert">{error}</p>}

      {creating && (
        <form onSubmit={handleCreate} className="panel" style={{ marginTop: 20 }}>
          <h2>Crear Nuevo Producto</h2>
          <div className="form-grid">
            <label>
              Nombre del Producto
              <input name="nombre" required minLength={2} maxLength={250} placeholder="Ej: Portátil Dell Core i7" />
            </label>
            <label>
              Categoría
              <input name="categoria" required minLength={2} maxLength={250} placeholder="Ej: Portátiles" />
            </label>
            <label>
              Precio (COP)
              <input name="precio_cop" type="number" step="0.01" min="1000" required placeholder="Ej: 3200000.00" />
            </label>
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
            <button type="submit" disabled={busy} style={{ background: '#163d30', color: 'white' }}>
              {busy ? 'Guardando...' : 'Crear Producto'}
            </button>
            <button type="button" onClick={() => setCreating(false)} disabled={busy}>
              Cancelar
            </button>
          </div>
        </form>
      )}

      {editingProduct && (
        <form onSubmit={handleEdit} className="panel" style={{ marginTop: 20 }}>
          <h2>Editar Producto: {editingProduct.nombre}</h2>
          <p className="note" style={{ marginBottom: 16 }}>
            Versión actual: {editingProduct.version}. Al guardar, la versión aumentará y se invalidará la clave en Redis.
          </p>
          <div className="form-grid">
            <label>
              Nombre
              <input name="nombre" defaultValue={editingProduct.nombre} required minLength={2} maxLength={250} />
            </label>
            <label>
              Categoría
              <input name="categoria" defaultValue={editingProduct.categoria} required minLength={2} maxLength={250} />
            </label>
            <label>
              Precio (COP)
              <input name="precio_cop" type="number" step="0.01" min="1000" defaultValue={editingProduct.precio_cop} required />
            </label>
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
            <button type="submit" disabled={busy} style={{ background: '#163d30', color: 'white' }}>
              {busy ? 'Actualizando...' : 'Guardar Cambios'}
            </button>
            <button type="button" onClick={() => setEditingProduct(null)} disabled={busy}>
              Cancelar
            </button>
          </div>
        </form>
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 20, flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <label style={{ fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}>
            Filtrar por categoría:
            <select value={categoryFilter} onChange={e => setCategoryFilter(e.target.value)} style={{ padding: '6px 12px' }}>
              <option value="">Todas las categorías</option>
              {categories.map(c => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>
        </div>

        {isAdmin && (
          <label className="check" style={{ margin: 0, fontSize: 13 }}>
            <input
              type="checkbox"
              checked={incluirInactivos}
              onChange={e => {
                setIncluirInactivos(e.target.checked);
                setOffset(0);
              }}
            />
            Incluir productos inactivos
          </label>
        )}
      </div>

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Producto</th>
              <th>Categoría</th>
              <th>Precio COP</th>
              <th>Versión</th>
              <th>Estado</th>
              {isAdmin && <th>Acciones</th>}
            </tr>
          </thead>
          <tbody>
            {filteredProducts.length === 0 ? (
              <tr>
                <td colSpan={isAdmin ? 6 : 5} style={{ textAlign: 'center', padding: 24 }}>
                  No se encontraron productos en este catálogo.
                </td>
              </tr>
            ) : (
              filteredProducts.map(product => (
                <tr key={product.id} style={{ opacity: product.activo ? 1 : 0.6 }}>
                  <td>
                    <strong>{product.nombre}</strong>
                    <div style={{ fontSize: 11, color: '#6a7d73' }}>ID: {product.id}</div>
                  </td>
                  <td>{product.categoria}</td>
                  <td style={{ fontWeight: 600, color: '#163d30' }}>{formatMoney(product.precio_cop)}</td>
                  <td>v{product.version}</td>
                  <td>
                    <span style={{
                      padding: '4px 8px',
                      borderRadius: 12,
                      fontSize: 11,
                      fontWeight: 600,
                      background: product.activo ? '#e9f5e8' : '#f0f0f0',
                      color: product.activo ? '#28502c' : '#777'
                    }}>
                      {product.activo ? 'Activo' : 'Inactivo'}
                    </span>
                  </td>
                  {isAdmin && (
                    <td>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button
                          type="button"
                          onClick={() => {
                            setEditingProduct(product);
                            setCreating(false);
                          }}
                          disabled={busy}
                          style={{ padding: '4px 10px', fontSize: 12 }}
                        >
                          Editar
                        </button>
                        {product.activo && (
                          <button
                            type="button"
                            onClick={() => handleDeactivate(product)}
                            disabled={busy}
                            style={{ padding: '4px 10px', fontSize: 12, color: '#a33', borderColor: '#dcc' }}
                          >
                            Desactivar
                          </button>
                        )}
                      </div>
                    </td>
                  )}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="pagination">
        <span>Mostrando {filteredProducts.length} de {total} productos</span>
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
    </section>
  );
}
