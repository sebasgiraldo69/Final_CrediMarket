import { FormEvent, useEffect, useState } from 'react';

export type Session = { access_token: string; role: string; cliente_id: string | null; email: string };
type Finances = Record<string, string | number | null>;
type Client = { id: string; nombre: string | null; email: string | null; clave_externa: string | null; activo: boolean; version: number; finanzas: Finances | null };
type Report = { id: string; total_filas: number; insertados: number; actualizados: number; sin_cambios: number; rechazados: number; errores: { fila: number; mensaje: string }[] };
const fields = [
  ['ingresos_mensuales_cop', 'Ingresos mensuales (COP)'],
  ['obligaciones_mensuales_cop', 'Obligaciones mensuales (COP)'],
  ['antiguedad_laboral_meses', 'Antigüedad laboral (meses)'],
  ['meses_historial_crediticio', 'Historial crediticio (meses)'],
  ['creditos_previos', 'Créditos previos'], ['atrasos_previos_30d', 'Atrasos previos de 30 días'],
  ['porcentaje_pago_puntual', 'Pago puntual (%)'],
];

interface ClientesProps {
  session?: Session | null;
  setSession?: (s: Session | null) => void;
}

export function Clientes({ session: propSession, setSession: propSetSession }: ClientesProps = {}) {
  const [localSession, setLocalSession] = useState<Session | null>(null);
  const session = propSession !== undefined ? propSession : localSession;
  const setSession = propSetSession !== undefined ? propSetSession : setLocalSession;
  const [register, setRegister] = useState(false);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [clients, setClients] = useState<Client[]>([]);
  const [selected, setSelected] = useState<Client | null>(null);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [report, setReport] = useState<Report | null>(null);
  const isAdmin = session?.role === 'administrador';

  function logout() {
    setSession(null); setClients([]); setSelected(null); setReport(null); setOffset(0); setTotal(0);
  }

  async function api(path: string, options: RequestInit = {}, token = session?.access_token) {
    const headers = new Headers(options.headers);
    if (token) headers.set('Authorization', `Bearer ${token}`);
    if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
    const response = await fetch(`/api/clientes${path}`, { ...options, headers });
    let data;
    try { data = await response.json(); } catch { throw new Error('El servicio no está disponible. Intenta de nuevo.'); }
    if (!response.ok) {
      if (response.status === 401 && token) logout();
      const details = data.details?.map((d: { field: string; message: string }) => `${d.field}: ${d.message}`).join(' · ');
      throw new Error(response.status === 401 && token ? 'Tu sesión venció. Inicia sesión nuevamente.' : [data.message || 'No se pudo completar la operación', details].filter(Boolean).join(' · '));
    }
    return data;
  }

  async function action(work: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try { await work(); } catch (e) { setError(e instanceof Error ? e.message : 'No se pudo conectar con el servicio.'); }
    finally { setBusy(false); }
  }

  async function reload() {
    if (!session) return;
    if (session.role === 'administrador') {
      const data = await api(`/clientes?limit=20&offset=${offset}`);
      setClients(data.items); setTotal(data.total);
    } else setSelected(await api(`/clientes/${session.cliente_id}`));
  }
  useEffect(() => { if (session) void action(reload); }, [session, offset]);

  async function submitAccess(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await action(async () => {
      const credentials = { email: form.get('email'), password: form.get('password') };
      if (register) {
        await api('/clientes', { method: 'POST', body: JSON.stringify({ ...credentials, nombre: form.get('nombre') }) });
        setRegister(false); setNotice('Cuenta creada. Ahora puedes iniciar sesión.');
      } else {
        const data = await api('/auth/login', { method: 'POST', body: JSON.stringify(credentials) });
        setSession({ ...data, email: String(credentials.email) });
      }
    });
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected) return;
    const form = new FormData(event.currentTarget);
    const payload: Record<string, unknown> = { version_esperada: selected.version };
    for (const field of ['nombre', 'email']) {
      const value = String(form.get(field) || '').trim();
      if (value) payload[field] = value;
    }
    if (isAdmin) {
      payload.activo = form.get('activo') === 'on';
      if (form.get('editar_finanzas') === 'on') {
        const finances: Finances = { tipo_empleo: String(form.get('tipo_empleo') || '') || null };
        for (const [field] of fields) {
          const raw = String(form.get(field) || '').trim();
          finances[field] = raw === '' ? null : field.endsWith('_cop') ? Number(raw).toFixed(2) : Number(raw);
        }
        payload.finanzas = finances;
      }
    }
    await action(async () => {
      setSelected(await api(`/clientes/${selected.id}`, { method: 'PATCH', body: JSON.stringify(payload) }));
      if (isAdmin) await reload();
      setNotice('Datos guardados.');
    });
  }

  return <section className="panel client-module">
    <div className="module-heading"><h1>{session ? (isAdmin ? 'Administrar clientes' : 'Mi perfil') : 'Acceso a CrediMarket'}</h1>{session && <button onClick={logout} disabled={busy}>Cerrar sesión</button>}</div>
    {error && <p role="alert" className="error">{error}</p>}{notice && <p role="status" className="success">{notice}</p>}
    {busy && <p role="status">Procesando…</p>}
    {!session ? <form onSubmit={submitAccess} className="form-grid" key={String(register)}>
      {register && <label>Nombre<input name="nombre" required maxLength={250} autoComplete="name" /></label>}
      <label>Correo de acceso<input name="email" type="email" required autoComplete="username" /></label>
      <label>Contraseña<input name="password" type="password" required minLength={register ? 12 : 1} maxLength={128} autoComplete={register ? 'new-password' : 'current-password'} /></label>
      <button className="back" disabled={busy}>{register ? 'Crear cuenta' : 'Iniciar sesión'}</button>
      <button type="button" disabled={busy} onClick={() => { setRegister(!register); setError(''); }}>{register ? 'Ya tengo cuenta' : 'Registrarme'}</button>
    </form> : <>
      <p>Sesión de {session.email} · {isAdmin ? 'Administrador' : 'Cliente'}</p>
      {isAdmin && <>
        <form className="import-form" onSubmit={event => {
          event.preventDefault(); const form = new FormData(event.currentTarget);
          void action(async () => { setReport(await api('/clientes/importaciones', { method: 'POST', body: form })); await reload(); });
        }}><h2>Importar clientes</h2><label>Archivo CSV<input type="file" name="file" accept=".csv,text/csv" required /></label><button disabled={busy}>Importar</button></form>
        <form className="report-query" onSubmit={event => {
          event.preventDefault(); const id = String(new FormData(event.currentTarget).get('report_id')).trim();
          void action(async () => { setReport(await api(`/clientes/importaciones/${encodeURIComponent(id)}`)); });
        }}><label>Consultar una importación por identificador<input name="report_id" required /></label><button disabled={busy}>Consultar informe</button></form>
        {report && <div className="report"><h2>Resultado de la importación</h2><p>Identificador: {report.id}</p><p>Total: {report.total_filas} · Insertados: {report.insertados} · Actualizados: {report.actualizados} · Sin cambios: {report.sin_cambios} · Rechazados: {report.rechazados}</p>
          {report.errores.length > 0 && <><p>Primeros {Math.min(50, report.errores.length)} errores de {report.errores.length}:</p><ul>{report.errores.slice(0, 50).map((e, index) => <li key={index}>Fila {e.fila}: {e.mensaje}</li>)}</ul></>}</div>}
        <div className="table-scroll"><table><thead><tr><th>Cliente</th><th>Estado</th><th>Acción</th></tr></thead><tbody>{clients.map(client => <tr key={client.id}><td>{client.nombre || client.clave_externa || client.id}</td><td>{client.activo ? 'Activo' : 'Inactivo'}</td><td><button disabled={busy} onClick={() => void action(async () => { setSelected(await api(`/clientes/${client.id}`)); })}>Editar</button></td></tr>)}</tbody></table></div>
        <div className="pagination"><button disabled={busy || offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Anterior</button><span>{total} clientes · Página {Math.floor(offset / 20) + 1}</span><button disabled={busy || offset + 20 >= total} onClick={() => setOffset(offset + 20)}>Siguiente</button></div>
      </>}
      {selected && <form key={`${selected.id}:${selected.version}`} onSubmit={save} className="profile-form"><h2>{isAdmin ? 'Editar cliente' : 'Mis datos'}</h2>
        <p>Versión {selected.version}{selected.clave_externa && ` · Referencia: ${selected.clave_externa}`}</p>
        <div className="form-grid"><label>Nombre<input name="nombre" defaultValue={selected.nombre || ''} maxLength={250} required={!isAdmin} /></label><label>Correo de contacto<input name="email" type="email" defaultValue={selected.email || ''} /></label></div>
        <p className="note">El correo de contacto no cambia tu correo de acceso.</p>
        {isAdmin && <label className="check"><input name="activo" type="checkbox" defaultChecked={selected.activo} />Cliente activo</label>}
        <h3>Información financiera</h3>
        {isAdmin ? <label className="check"><input name="editar_finanzas" type="checkbox" defaultChecked={!!selected.finanzas} />Guardar también la información financiera</label> : <p>Estos datos los administra un responsable de CrediMarket.</p>}
        <fieldset disabled={!isAdmin}><div className="form-grid">
          <label>Tipo de empleo<select name="tipo_empleo" defaultValue={String(selected.finanzas?.tipo_empleo || '')}><option value="">Sin dato</option><option value="dependiente">Dependiente</option><option value="independiente">Independiente</option><option value="temporal">Temporal</option></select></label>
          {fields.map(([field, label]) => <label key={field}>{label}<input name={field} type="number" min="0" max={field === 'porcentaje_pago_puntual' ? 100 : undefined} step={field.endsWith('_cop') || field === 'porcentaje_pago_puntual' ? '0.01' : '1'} defaultValue={selected.finanzas?.[field] ?? ''} /></label>)}
        </div></fieldset><p className="note">Sin créditos previos, el porcentaje de pago puntual debe quedar vacío.</p>
        <button className="back" disabled={busy}>Guardar cambios</button><button type="button" disabled={busy} onClick={() => void action(async () => { setSelected(await api(`/clientes/${selected.id}`)); })}>Recargar datos</button>
      </form>}
    </>}
  </section>;
}
