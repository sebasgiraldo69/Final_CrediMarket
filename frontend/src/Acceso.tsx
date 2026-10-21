import { FormEvent, useState } from 'react';
import { api, errorText } from './api';
import { Feedback } from './ui';
import { tokenExpiry, type Role, type Session } from './session';

type Login = { access_token: string; expires_in: number; role: Role; cliente_id: string | null };

export function Acceso({ onLogin, reason }: { onLogin: (session: Session) => void; reason?: string }) {
  const [register, setRegister] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function login(email: string, password: string) {
    const data = await api<Login>('clientes', '/auth/login', { method: 'POST', body: { email, password } });
    onLogin({ access_token: data.access_token, role: data.role, cliente_id: data.cliente_id, email, expires_at: tokenExpiry(data.access_token, data.expires_in) });
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = String(form.get('email')).trim();
    const password = String(form.get('password'));
    if (register && password !== String(form.get('confirmacion'))) { setError('Las contraseñas no coinciden.'); return; }
    setBusy(true); setError('');
    try {
      if (register) await api('clientes', '/clientes', { method: 'POST', body: { nombre: String(form.get('nombre')).trim(), email, password } });
      await login(email, password);
    } catch (err) { setError(errorText(err)); }
    finally { setBusy(false); }
  }

  return <section className="panel narrow" aria-labelledby="acceso-titulo">
    <p className="eyebrow">{register ? 'Nueva cuenta de cliente' : 'Acceso'}</p>
    <h1 id="acceso-titulo">{register ? 'Crea tu cuenta' : 'Inicia sesión'}</h1>
    {reason && <p className="note">{reason}</p>}
    <Feedback error={error} />
    <form onSubmit={submit} className="stack" key={String(register)}>
      {register && <label>Nombre completo<input name="nombre" required maxLength={250} autoComplete="name" /></label>}
      <label>Correo<input name="email" type="email" required maxLength={254} autoComplete="username" /></label>
      <label>Contraseña<input name="password" type="password" required minLength={register ? 12 : 1} maxLength={128} autoComplete={register ? 'new-password' : 'current-password'} />
        {register && <small>Mínimo 12 caracteres.</small>}</label>
      {register && <label>Confirmar contraseña<input name="confirmacion" type="password" required minLength={12} maxLength={128} autoComplete="new-password" /></label>}
      <button className="primary" disabled={busy}>{busy ? 'Procesando…' : register ? 'Crear cuenta e ingresar' : 'Ingresar'}</button>
    </form>
    <p className="note">{register ? '¿Ya tienes cuenta?' : '¿Aún no tienes cuenta?'}{' '}
      <button type="button" className="link" disabled={busy} onClick={() => { setRegister(!register); setError(''); }}>{register ? 'Inicia sesión' : 'Regístrate como cliente'}</button></p>
    {register && <p className="note">Tu perfil financiero lo completa un administrador; sin él, las solicitudes se rechazan por información incompleta.</p>}
  </section>;
}
