// Sesión del navegador: el token vive solo en sessionStorage y se descarta al vencer.
export type Role = 'cliente' | 'administrador';
export type Session = { access_token: string; role: Role; cliente_id: string | null; email: string; expires_at: number };

const STORAGE_KEY = 'credimarket.session';

export function tokenExpiry(token: string, fallbackSeconds: number): number {
  try {
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    if (typeof payload.exp === 'number') return payload.exp * 1000;
  } catch { /* token opaco: usar expires_in */ }
  return Date.now() + fallbackSeconds * 1000;
}

export function loadSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const session = JSON.parse(raw) as Session;
    return session.expires_at > Date.now() ? session : null;
  } catch { return null; }
}

export function storeSession(session: Session | null) {
  try {
    if (session) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch { /* almacenamiento bloqueado: la sesión dura lo que la pestaña */ }
}
