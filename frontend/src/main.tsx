import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import { Clientes, type Session } from './Clientes';
import { Catalogo } from './Catalogo';

const sections = ['Inicio', 'Catálogo', 'Mis solicitudes', 'Clientes', 'Inventario', 'Modelo'];
const services = ['productos', 'clientes', 'prestamos', 'inventario'];

function App() {
  const [active, setActive] = useState('Inicio');
  const [session, setSession] = useState<Session | null>(null);
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

  return (
    <div className="layout">
      <header>
        <a href="#" onClick={() => setActive('Inicio')} className="brand">
          CrediMarket<span>Financiación de tecnología</span>
        </a>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {session && (
            <span style={{ fontSize: 13, color: '#4a7663' }}>
              Conectado como: <strong>{session.email}</strong> ({session.role})
            </span>
          )}
          <span className="badge">Fase 4: Catálogo y Redis</span>
        </div>
      </header>

      <nav aria-label="Navegación principal">
        {sections.map(section => (
          <button
            key={section}
            aria-current={active === section ? 'page' : undefined}
            onClick={() => setActive(section)}
          >
            {section}
          </button>
        ))}
      </nav>

      <main>
        {active === 'Inicio' ? (
          <>
            <p className="eyebrow">Proyecto académico · Fase 4</p>
            <h1>Catálogo de tecnología<br />y caché Redis en marcha.</h1>
            <p className="intro">
              El servicio de Productos ya cuenta con catálogo tecnológico, cotización interna para Préstamos
              y caché Redis con patrón Cache-Aside. Puedes registrarte en Clientes y explorar el Catálogo.
            </p>
            <section className="panel" aria-label="Conectividad de servicios">
              <h2>Conexión con los servicios</h2>
              <div className="grid">
                {services.map(service => (
                  <article key={service}>
                    <h3>{service}</h3>
                    <p aria-live="polite">{status[service] || 'Comprobando…'}</p>
                  </article>
                ))}
              </div>
              <p className="note">
                Clientes y Productos están completamente operativos. Los módulos de Préstamos, Inventario y Modelo se integrarán en las siguientes fases.
              </p>
            </section>
          </>
        ) : active === 'Clientes' || active === 'Catálogo' ? null : (
          <section className="panel">
            <p className="eyebrow">Próxima etapa</p>
            <h1>{active}</h1>
            <p>Este módulo todavía no está implementado. Aquí aparecerán las operaciones conectadas a los servicios reales.</p>
            <button className="back" onClick={() => setActive('Inicio')}>Volver al inicio</button>
          </section>
        )}

        <div hidden={active !== 'Catálogo'}>
          <Catalogo session={session} onNavigateToClients={() => setActive('Clientes')} />
        </div>

        <div hidden={active !== 'Clientes'}>
          <Clientes session={session} setSession={setSession} />
        </div>
      </main>

      <footer>Datos y operaciones ficticios para aprendizaje.</footer>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
