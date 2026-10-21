// Cliente HTTP común: un solo lugar para tokens, errores legibles e Idempotency-Key.
export type Service = 'productos' | 'clientes' | 'prestamos' | 'inventario';
export type ErrorDetail = { field: string; message: string };

const serviceNames: Record<Service, string> = {
  productos: 'Productos', clientes: 'Clientes', prestamos: 'Préstamos', inventario: 'Inventario',
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly details: ErrorDetail[] = [],
    readonly correlationId: string | null = null,
  ) { super(message); }

  // Sin respuesta, 5xx o 503: el mismo envío puede repetirse con la misma clave.
  get retryable() { return this.status === 0 || this.status >= 500; }
}

let unauthorizedHandler: (() => void) | null = null;
// main.tsx lo registra para cerrar la sesión en cualquier módulo que reciba 401.
export function onUnauthorized(handler: (() => void) | null) { unauthorizedHandler = handler; }

type Options = {
  method?: string;
  body?: unknown;
  token?: string | null;
  idempotencyKey?: string;
  signal?: AbortSignal;
};

export async function api<T = any>(service: Service, path: string, options: Options = {}): Promise<T> {
  const headers = new Headers({ Accept: 'application/json' });
  if (options.token) headers.set('Authorization', `Bearer ${options.token}`);
  if (options.idempotencyKey) headers.set('Idempotency-Key', options.idempotencyKey);
  let body: BodyInit | undefined;
  if (options.body instanceof FormData) body = options.body;
  else if (options.body !== undefined) { body = JSON.stringify(options.body); headers.set('Content-Type', 'application/json'); }

  let response: Response;
  try {
    response = await fetch(`/api/${service}${path}`, { method: options.method || 'GET', headers, body, signal: options.signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    throw new ApiError('No hay conexión con el servidor. Revisa tu red; puedes reintentar sin duplicar la operación.', 0);
  }

  let data: any = null;
  try { data = await response.json(); } catch { /* respuestas del proxy sin JSON */ }
  if (response.ok) return data as T;

  const details: ErrorDetail[] = Array.isArray(data?.details) ? data.details : [];
  const serverMessage: string | undefined = data?.message || (typeof data?.detail === 'string' ? data.detail : undefined);
  throw new ApiError(readableMessage(service, response.status, serverMessage, !!options.token), response.status, details, data?.correlation_id ?? null);
}

function readableMessage(service: Service, status: number, serverMessage: string | undefined, authenticated: boolean): string {
  const name = serviceNames[service];
  if (status === 401 && authenticated) {
    unauthorizedHandler?.();
    return 'Tu sesión venció. Inicia sesión nuevamente.';
  }
  switch (status) {
    case 401: return serverMessage || 'Credenciales inválidas.';
    case 403: return `No tienes permiso para esta operación${serverMessage ? `: ${serverMessage}` : '.'}`;
    case 404: return serverMessage || 'El recurso no existe o no te pertenece.';
    case 409: return `${serverMessage || 'Conflicto'}. Los datos cambiaron; recarga y vuelve a intentarlo.`;
    case 413: return 'El archivo supera el tamaño máximo permitido (10 MiB).';
    case 422: return serverMessage && serverMessage !== 'Entrada inválida' ? serverMessage : 'Revisa los datos del formulario.';
    case 502: case 504: return `El servicio de ${name} no responde. Reintenta en unos segundos.`;
    case 503: return `${serverMessage || `El servicio de ${name} no está disponible`}. Reintenta en unos segundos.`;
    default: return serverMessage || `Error inesperado (${status}) en ${name}.`;
  }
}

export function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    const details = err.details.map(d => `${d.field.replace(/^body\./, '')}: ${d.message}`).join(' · ');
    return [err.message, details].filter(Boolean).join(' — ');
  }
  return err instanceof Error ? err.message : 'No se pudo completar la operación.';
}

export function newKey(prefix: string): string {
  const random = typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
  return `${prefix}-${random}`;
}

// Conserva la clave mientras se reintenta el mismo contenido; un contenido distinto recibe otra clave.
export class IdempotencyKeys {
  private pending = new Map<string, { payload: string; key: string }>();

  keyFor(scope: string, payload: unknown): string {
    const serialized = JSON.stringify(payload ?? {});
    const current = this.pending.get(scope);
    if (current && current.payload === serialized) return current.key;
    const key = newKey(scope.split(':')[0]);
    this.pending.set(scope, { payload: serialized, key });
    return key;
  }

  // Solo después de una respuesta definitiva se libera la clave.
  settle(scope: string) { this.pending.delete(scope); }
  has(scope: string) { return this.pending.has(scope); }
}
