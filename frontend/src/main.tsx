import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import { Clientes } from './Clientes';

const sections = ['Inicio', 'Catálogo', 'Mis solicitudes', 'Clientes', 'Inventario', 'Modelo'];
const services = ['productos', 'clientes', 'prestamos', 'inventario'];

function App() {
  const [active, setActive] = useState('Inicio');
  const [status, setStatus] = useState<Record<string, string>>({});
  useEffect(() => {
    const controller = new AbortController();
    Promise.all(services.map(async service => {
      try {
        const response = await fetch(`/api/${service}/health`, { signal: controller.signal });
        const data = await response.json();
        return [service, response.ok && data.status === 'ok' ? 'Disponible' : 'Sin conexión'];
      } catch { return [service, 'Sin conexión']; }
    })).then(entries => { if (!controller.signal.aborted) setStatus(Object.fromEntries(entries)); });
    return () => controller.abort();
  }, []);
  return <div className="layout">
    <header><a href="#" onClick={() => setActive('Inicio')} className="brand">CrediMarket<span>Financiación de tecnología</span></a><span className="badge">En desarrollo</span></header>
    <nav aria-label="Navegación principal">{sections.map(section => <button key={section} aria-current={active === section ? 'page' : undefined} onClick={() => setActive(section)}>{section}</button>)}</nav>
    <main>{active === 'Inicio' ? <>
      <p className="eyebrow">Proyecto académico · Fase 3</p>
      <h1>La base de CrediMarket<br />ya está en marcha.</h1>
      <p className="intro">Ya puedes registrarte y administrar tu perfil desde Clientes. El catálogo y las solicitudes de financiación se incorporarán en las siguientes etapas.</p>
      <section className="panel" aria-label="Conectividad de servicios"><h2>Conexión con los servicios</h2><div className="grid">{services.map(service => <article key={service}><h3>{service}</h3><p aria-live="polite">{status[service] || 'Comprobando…'}</p></article>)}</div><p className="note">Clientes ya permite registro y acceso. Los servicios de las siguientes fases siguen en desarrollo.</p></section>
    </> : active === 'Clientes' ? null : <section className="panel"><p className="eyebrow">Próxima etapa</p><h1>{active}</h1><p>Este módulo todavía no está implementado. Aquí aparecerán las operaciones conectadas a los servicios reales.</p><button className="back" onClick={() => setActive('Inicio')}>Volver al inicio</button></section>}<div hidden={active !== 'Clientes'}><Clientes /></div></main>
    <footer>Datos y operaciones ficticios para aprendizaje.</footer>
  </div>;
}

createRoot(document.getElementById('root')!).render(<App />);
