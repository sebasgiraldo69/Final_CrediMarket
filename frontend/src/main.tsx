import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

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
      <p className="eyebrow">Proyecto académico · Fase 2</p>
      <h1>La base de CrediMarket<br />ya está en marcha.</h1>
      <p className="intro">Estamos preparando el catálogo y las solicitudes de financiación. Las operaciones de clientes, compras y préstamos se incorporarán en las siguientes etapas.</p>
      <section className="panel" aria-label="Conectividad de servicios"><h2>Conexión con los servicios</h2><div className="grid">{services.map(service => <article key={service}><h3>{service}</h3><p aria-live="polite">{status[service] || 'Comprobando…'}</p></article>)}</div><p className="note">Esta comprobación confirma que los procesos responden. El modelo y las operaciones de negocio aún no están disponibles.</p></section>
    </> : <section className="panel"><p className="eyebrow">Próxima etapa</p><h1>{active}</h1><p>Este módulo todavía no está implementado. Aquí aparecerán las operaciones conectadas a los servicios reales.</p><button className="back" onClick={() => setActive('Inicio')}>Volver al inicio</button></section>}</main>
    <footer>Datos y operaciones ficticios para aprendizaje.</footer>
  </div>;
}

createRoot(document.getElementById('root')!).render(<App />);
