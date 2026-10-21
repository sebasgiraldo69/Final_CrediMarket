import { FormEvent, Fragment, useEffect, useState } from 'react';
import { api, ApiError, errorText } from './api';
import type { Session } from './session';
import { Feedback, formatMoney, Modal, Pagination, shortId, type Page } from './ui';

type Finances = Record<string, string | number | null>;
type Client = { id: string; nombre: string | null; email: string | null; clave_externa: string | null; activo: boolean; version: number; finanzas: Finances | null };
type Report = { id: string; total_filas: number; insertados: number; actualizados: number; sin_cambios: number; rechazados: number; errores: { fila: number; mensaje: string }[] };

const fields: [string, string][] = [
  ['ingresos_mensuales_cop', 'Ingresos mensuales (COP)'],
  ['obligaciones_mensuales_cop', 'Obligaciones mensuales (COP)'],
  ['antiguedad_laboral_meses', 'Antigüedad laboral (meses)'],
  ['meses_historial_crediticio', 'Historial crediticio (meses)'],
  ['creditos_previos', 'Créditos previos'],
  ['atrasos_previos_30d', 'Atrasos previos de 30 días'],
  ['porcentaje_pago_puntual', 'Pago puntual (%)'],
];
const employment: Record<string, string> = { dependiente: 'Dependiente', independiente: 'Independiente', temporal: 'Temporal' };
const PAGE = 20;

export function Clientes({ session }: { session: Session }) {
  const isAdmin = session.role === 'administrador';
  const token = session.access_token;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [clients, setClients] = useState<Client[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Client | null>(null);
  const [editing, setEditing] = useState(false);
  const [editFinances, setEditFinances] = useState(false);
  const [report, setReport] = useState<Report | null>(null);

  async function run(work: () => Promise<void>, success = '') {
    setBusy(true); setError(''); setNotice('');
    try { await work(); setNotice(success); return true; }
    catch (err) { setError(errorText(err)); return err; }
    finally { setBusy(false); }
  }

  async function loadList() {
    const page = await api<Page<Client>>('clientes', `/clientes?limit=${PAGE}&offset=${offset}`, { token });
    setClients(page.items); setTotal(page.total);
  }
  const loadOne = async (id: string) => setSelected(await api<Client>('clientes', `/clientes/${id}`, { token }));

  useEffect(() => { void run(isAdmin ? loadList : () => loadOne(session.cliente_id!)); }, [offset]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const client = selected!;
    const form = new FormData(event.currentTarget);
    const payload: Record<string, unknown> = { version_esperada: client.version };
    for (const field of ['nombre', 'email']) {
      const value = String(form.get(field) || '').trim();
      if (value && value !== client[field as 'nombre' | 'email']) payload[field] = value;
    }
    if (isAdmin) {
      if ((form.get('activo') === 'on') !== client.activo) payload.activo = form.get('activo') === 'on';
      if (editFinances) {
        const finances: Finances = { tipo_empleo: String(form.get('tipo_empleo') || '') || null };
        for (const [field] of fields) {
          const raw = String(form.get(field) || '').trim();
          finances[field] = raw === '' ? null : field.endsWith('_cop') ? Number(raw).toFixed(2) : Number(raw);
        }
        if (finances.creditos_previos === 0 && finances.porcentaje_pago_puntual !== null) {
          setError('Sin créditos previos, el porcentaje de pago puntual debe quedar vacío.'); return;
        }
        payload.finanzas = finances;
      }
    }
    const result = await run(async () => {
      setSelected(await api<Client>('clientes', `/clientes/${client.id}`, { method: 'PATCH', token, body: payload }));
      if (isAdmin) await loadList();
    }, 'Datos guardados.');
    if (result === true) setEditing(false);
    else if (result instanceof ApiError && result.status === 409) { await loadOne(client.id); setEditing(false); }
  }

  async function importCsv(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const file = (form.elements.namedItem('file') as HTMLInputElement).files?.[0];
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) { setError('El archivo supera 10 MiB.'); return; }
    const body = new FormData(); body.append('file', file);
    await run(async () => {
      setReport(await api<Report>('clientes', '/clientes/importaciones', { method: 'POST', token, body }));
      form.reset(); await loadList();
    }, 'Importación procesada.');
  }

  async function queryReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const id = String(new FormData(event.currentTarget).get('report_id')).trim();
    await run(async () => setReport(await api<Report>('clientes', `/clientes/importaciones/${encodeURIComponent(id)}`, { token })));
  }

  const profile = selected && <ClientProfile client={selected} isAdmin={isAdmin} onEdit={() => { setEditFinances(isAdmin); setEditing(true); }} />;

  return <section>
    <div className="module-heading"><div><p className="eyebrow">{isAdmin ? 'Administración' : 'Cuenta'}</p><h1>{isAdmin ? 'Clientes' : 'Mi perfil'}</h1></div></div>
    <Feedback error={error} notice={notice} onClose={() => { setError(''); setNotice(''); }} />
    {busy && !selected && !clients.length && <p className="loading" role="status">Cargando…</p>}

    {!isAdmin && profile}

    {isAdmin && <>
      <div className="two-col">
        <form className="panel stack" onSubmit={importCsv}>
          <h2>Importar clientes (CSV)</h2>
          <label>Archivo CSV (máx. 10 MiB, 20.000 filas)<input type="file" name="file" accept=".csv,text/csv" required /></label>
          <button className="primary" disabled={busy}>{busy ? 'Procesando…' : 'Importar'}</button>
        </form>
        <form className="panel stack" onSubmit={queryReport}>
          <h2>Consultar una importación</h2>
          <label>Identificador del informe<input name="report_id" required pattern="[0-9a-fA-F-]{36}" title="UUID del informe" /></label>
          <button disabled={busy}>Consultar</button>
        </form>
      </div>
      {report && <div className="panel report">
        <div className="module-heading"><h2>Resultado de la importación</h2><button className="link" onClick={() => setReport(null)} aria-label="Cerrar informe">×</button></div>
        <p>Identificador: <code>{report.id}</code></p>
        <div className="stats">
          {([['Total', report.total_filas], ['Insertados', report.insertados], ['Actualizados', report.actualizados], ['Sin cambios', report.sin_cambios], ['Rechazados', report.rechazados]] as const)
            .map(([label, value]) => <div key={label}><strong>{value}</strong><span>{label}</span></div>)}
        </div>
        {report.errores.length > 0 && <><p>Primeros {Math.min(50, report.errores.length)} errores de {report.errores.length}:</p>
          <ul>{report.errores.slice(0, 50).map((e, i) => <li key={i}>Fila {e.fila}: {e.mensaje}</li>)}</ul></>}
      </div>}

      <div className="table-scroll"><table className="responsive">
        <thead><tr><th>Cliente</th><th>Referencia</th><th>Perfil financiero</th><th>Estado</th><th>Acción</th></tr></thead>
        <tbody>{clients.map(client => <tr key={client.id}>
          <td data-label="Cliente">{client.nombre || <span className="muted">Sin nombre</span>}<small>{client.email || shortId(client.id)}</small></td>
          <td data-label="Referencia">{client.clave_externa || '—'}</td>
          <td data-label="Perfil financiero"><span className={`state-pill ${client.finanzas ? 'ok' : 'pending'}`}>{client.finanzas ? 'Completo' : 'Incompleto'}</span></td>
          <td data-label="Estado">{client.activo ? 'Activo' : 'Inactivo'}</td>
          <td data-label="Acción"><button disabled={busy} onClick={() => void run(() => loadOne(client.id))}>Ver</button></td>
        </tr>)}</tbody>
      </table></div>
      <Pagination offset={offset} limit={PAGE} total={total} busy={busy} onChange={setOffset} label="clientes" />
      {selected && !editing && <Modal title={selected.nombre || 'Cliente'} onClose={() => setSelected(null)} wide>{profile}</Modal>}
    </>}

    {selected && editing && <Modal title={isAdmin ? 'Editar cliente' : 'Editar mis datos'} onClose={() => { if (!busy) setEditing(false); }} wide>
      <form key={`${selected.id}:${selected.version}`} onSubmit={save} className="stack">
        <p className="note">Versión {selected.version}. Si alguien más cambia el perfil antes de guardar, verás un conflicto y se recargarán los datos.</p>
        <div className="form-grid">
          <label>Nombre<input name="nombre" defaultValue={selected.nombre || ''} maxLength={250} required={!isAdmin} /></label>
          <label>Correo de contacto<input name="email" type="email" defaultValue={selected.email || ''} maxLength={254} /><small>No cambia el correo de acceso.</small></label>
        </div>
        {isAdmin && <>
          <label className="check"><input name="activo" type="checkbox" defaultChecked={selected.activo} />Cliente activo</label>
          <label className="check"><input type="checkbox" checked={editFinances} onChange={e => setEditFinances(e.target.checked)} />Guardar información financiera</label>
          <fieldset disabled={!editFinances} className="form-grid">
            <label>Tipo de empleo<select name="tipo_empleo" defaultValue={String(selected.finanzas?.tipo_empleo || '')}><option value="">Sin dato</option>{Object.entries(employment).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
            {fields.map(([field, label]) => <label key={field}>{label}<input name={field} type="number" min="0" max={field === 'porcentaje_pago_puntual' ? 100 : undefined}
              step={field.endsWith('_cop') || field === 'porcentaje_pago_puntual' ? '0.01' : '1'} required={['ingresos_mensuales_cop', 'obligaciones_mensuales_cop', 'creditos_previos', 'atrasos_previos_30d'].includes(field)}
              defaultValue={selected.finanzas?.[field] ?? ''} /></label>)}
          </fieldset>
          <p className="note">Ingresos, obligaciones, créditos previos y atrasos son obligatorios. Sin créditos previos, el pago puntual queda vacío.</p>
        </>}
        <div className="actions"><button className="primary" disabled={busy}>{busy ? 'Guardando…' : 'Guardar cambios'}</button><button type="button" disabled={busy} onClick={() => setEditing(false)}>Cancelar</button></div>
      </form>
    </Modal>}
  </section>;
}

function ClientProfile({ client, isAdmin, onEdit }: { client: Client; isAdmin: boolean; onEdit: () => void }) {
  const f = client.finanzas;
  const value = (field: string) => {
    const v = f?.[field];
    if (v === null || v === undefined || v === '') return '—';
    return field.endsWith('_cop') ? formatMoney(v) : field === 'porcentaje_pago_puntual' ? `${v} %` : String(v);
  };
  return <div className="panel">
    <dl className="facts">
      <dt>Nombre</dt><dd>{client.nombre || '—'}</dd>
      <dt>Correo de contacto</dt><dd>{client.email || '—'}</dd>
      {client.clave_externa && <><dt>Referencia</dt><dd>{client.clave_externa}</dd></>}
      <dt>Estado</dt><dd>{client.activo ? 'Activo' : 'Inactivo'} · versión {client.version}</dd>
    </dl>
    <h3>Información financiera</h3>
    {f ? <dl className="facts">
      <dt>Tipo de empleo</dt><dd>{employment[String(f.tipo_empleo)] || '—'}</dd>
      {fields.map(([field, label]) => <Fragment key={field}><dt>{label}</dt><dd>{value(field)}</dd></Fragment>)}
    </dl> : <p className="warning">{isAdmin ? 'Perfil financiero incompleto: complétalo para que el cliente pueda solicitar crédito.' : 'Tu perfil financiero está incompleto. Un administrador de CrediMarket debe completarlo antes de que puedas solicitar crédito.'}</p>}
    {!isAdmin && f && <p className="note">Estos datos los administra CrediMarket.</p>}
    <div className="actions"><button className="primary" onClick={onEdit}>{isAdmin ? 'Editar cliente' : 'Editar datos de contacto'}</button></div>
  </div>;
}
