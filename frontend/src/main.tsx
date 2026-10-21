import { useCallback, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import { onUnauthorized } from './api';
import { loadSession, storeSession, type Role, type Session } from './session';
import { Acceso } from './Acceso';
import { Catalogo } from './Catalogo';
import { Clientes } from './Clientes';
import { Inventario } from './Inventario';
import { Modelo } from './Modelo';
import { Solicitudes } from './Solicitudes';
import { Feedback } from './ui';

type Audience = Role | 'publico';
type Route = { path: string; label: (role: Audience) => string; audience: Audience[] };

// La navegación oculta lo que el rol no puede usar; los servicios vuelven a validar cada permiso.
const routes: Route[] = [
  { path: '/', label: () => 'Inicio', audience: ['publico', 'cliente', 'administrador'] },
  { path: '/catalogo', label: () => 'Catálogo', audience: ['publico', 'cliente', 'administrador'] },
  { path: '/solicitudes', label: role => role === 'administrador' ? 'Solicitudes' : 'Mis solicitudes', audience: ['cliente', 'administrador'] },
  { path: '/clientes', label: role => role === 'administrador' ? 'Clientes' : 'Mi perfil', audience: ['cliente', 'administrador'] },
  { path: '/inventario', label: () => 'Inventario', audience: ['administrador'] },
  { path: '/modelo', label: () => 'Modelo', audience: ['administrador'] },
  { path: '/acceso', label: () => 'Ingresar', audience: ['publico'] },
];
const services = ['productos', 'clientes', 'prestamos', 'inventario'];

function currentPath() {
  const path = window.location.pathname.replace(/\/+$/, '') || '/';
  return routes.some(route => route.path === path) ? path : '/';
}

function App() {
  const [path, setPath] = useState(currentPath);
  const [session, setSessionState] = useState<Session | null>(loadSession);
  const [sessionNotice, setSessionNotice] = useState('');
  const audience: Audience = session?.role ?? 'publico';

  const navigate = useCallback((to: string) => {
    if (to !== window.location.pathname) window.history.pushState(null, '', to);
    setPath(to);
    window.scrollTo(0, 0);
  }, []);

  const setSession = useCallback((next: Session | null) => { storeSession(next); setSessionState(next); }, []);
  const expire = useCallback(() => {
    setSession(null);
    setSessionNotice('Tu sesión venció. Inicia sesión nuevamente para continuar.');
  }, [setSession]);

  useEffect(() => {
    const onPop = () => setPath(currentPath());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);
  useEffect(() => { onUnauthorized(expire); return () => onUnauthorized(null); }, [expire]);
  useEffect(() => {
    if (!session) return;
    const timer = setTimeout(expire, Math.max(0, session.expires_at - Date.now()));
    return () => clearTimeout(timer);
  }, [session, expire]);

  function login(next: Session) {
    setSession(next); setSessionNotice('');
    if (path === '/acceso') navigate(next.role === 'administrador' ? '/solicitudes' : '/catalogo');
  }

  function logout() { setSession(null); setSessionNotice(''); navigate('/'); }

  const route = routes.find(r => r.path === path)!;
  const visible = routes.filter(r => r.audience.includes(audience));

  function content() {
    if (path === '/') return <Inicio session={session} navigate={navigate} />;
    if (path === '/catalogo') return <Catalogo session={session} navigate={navigate} />;
    if (path === '/acceso') return session ? <Inicio session={session} navigate={navigate} /> : <Acceso onLogin={login} />;
    if (!session) return <Acceso onLogin={login} reason={`Inicia sesión para abrir ${route.label('cliente')}.`} />;
    if (!route.audience.includes(session.role)) return <section className="panel narrow">
      <p className="eyebrow">Permiso insuficiente</p><h1>{route.label(session.role)}</h1>
      <p>Tu cuenta tiene rol <strong>{session.role}</strong>. Este módulo es exclusivo para administradores.</p>
      <button className="primary" onClick={() => navigate('/')}>Volver al inicio</button>
    </section>;
    if (path === '/solicitudes') return <Solicitudes session={session} navigate={navigate} />;
    if (path === '/clientes') return <Clientes session={session} />;
    if (path === '/inventario') return <Inventario session={session} />;
    return <Modelo session={session} />;
  }

  return <div className="layout">
    <header>
      <a href="/" onClick={event => { event.preventDefault(); navigate('/'); }} className="brand">CrediMarket<span>Financiación de tecnología</span></a>
      <div className="session-box">
        {session ? <>
          <span className="session-user"><strong>{session.email}</strong>{session.role === 'administrador' ? 'Administrador' : 'Cliente'}</span>
          <button type="button" onClick={logout}>Cerrar sesión</button>
        </> : path !== '/acceso' && <button type="button" className="primary" onClick={() => navigate('/acceso')}>Ingresar</button>}
      </div>
    </header>
    <nav aria-label="Navegación principal">
      {visible.map(r => <a key={r.path} href={r.path} aria-current={r.path === path ? 'page' : undefined}
        onClick={event => { event.preventDefault(); navigate(r.path); }}>{r.label(audience)}</a>)}
    </nav>
    <main>
      <Feedback notice={sessionNotice} onClose={() => setSessionNotice('')} />
      {content()}
    </main>
    <footer>Proyecto académico · Datos y operaciones ficticios para aprendizaje.</footer>
  </div>;
}

function Inicio({ session, navigate }: { session: Session | null; navigate: (to: string) => void }) {
  const [status, setStatus] = useState<Record<string, string>>({});
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setStatus({});
    Promise.all(services.map(async service => {
      try {
        const response = await fetch(`/api/${service}/ready`, { signal: controller.signal });
        return [service, response.ok ? 'Disponible' : 'No disponible'];
      } catch { return [service, 'Sin conexión']; }
    })).then(entries => { if (!controller.signal.aborted) setStatus(Object.fromEntries(entries)); });
    return () => controller.abort();
  }, [attempt]);

  const actions = !session
    ? [['/catalogo', 'Explorar el catálogo', 'Productos tecnológicos con precio vigente.'], ['/acceso', 'Ingresar o registrarse', 'Crea una cuenta de cliente para solicitar crédito.']]
    : session.role === 'cliente'
      ? [['/catalogo', 'Solicitar un crédito', 'Elige un producto, cantidad y plazo.'], ['/solicitudes', 'Seguir mis solicitudes', 'Estado en vivo, cancelación y entrega.'], ['/clientes', 'Mi perfil', 'Datos de contacto e información financiera.']]
      : [['/solicitudes', 'Solicitudes', 'Supervisar créditos y confirmar entregas.'], ['/catalogo', 'Catálogo', 'Crear, editar precios y desactivar productos.'], ['/clientes', 'Clientes', 'Importar CSV y completar perfiles financieros.'], ['/inventario', 'Inventario', 'Entradas de stock, reservas y movimientos.'], ['/modelo', 'Modelo de riesgo', 'Ficha del modelo activo y acceso a MLflow.']];

  return <>
    <p className="eyebrow">Proyecto académico</p>
    <h1>Financia tecnología con<br />evaluación de riesgo en línea.</h1>
    <p className="intro">Solicita un crédito para un producto del catálogo; el modelo de riesgo evalúa la solicitud y el inventario reserva las unidades sin sobreventa.</p>
    <div className="cards">
      {actions.map(([to, title, text]) => <a key={to} href={to} className="card" onClick={event => { event.preventDefault(); navigate(to); }}><strong>{title}</strong><span>{text}</span></a>)}
    </div>
    <section className="panel" aria-label="Conectividad de servicios">
      <div className="module-heading"><h2>Estado de los servicios</h2><button type="button" onClick={() => setAttempt(a => a + 1)}>Comprobar de nuevo</button></div>
      <div className="grid">
        {services.map(service => <article key={service}><h3>{service}</h3><p aria-live="polite" className={status[service] === 'Disponible' ? 'ok-text' : status[service] ? 'bad-text' : ''}>{status[service] || 'Comprobando…'}</p></article>)}
      </div>
    </section>
  </>;
}

createRoot(document.getElementById('root')!).render(<App />);
