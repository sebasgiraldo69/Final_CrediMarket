// Textos legibles para estados y motivos que la API devuelve como códigos (docs/estados.md).
export type LoanState =
  | 'EVALUANDO' | 'RECHAZADA' | 'ERROR_TECNICO' | 'PENDIENTE_INVENTARIO' | 'APROBADA'
  | 'CANCELACION_PENDIENTE' | 'ENTREGA_PENDIENTE' | 'VERIFICACION_PENDIENTE'
  | 'CANCELADA_SIN_STOCK' | 'CANCELADA' | 'COMPLETADA';

export const loanStates: Record<LoanState, { label: string; help: string; tone: 'pending' | 'ok' | 'done' | 'bad' }> = {
  EVALUANDO: { label: 'En evaluación', help: 'Estamos evaluando tu solicitud.', tone: 'pending' },
  PENDIENTE_INVENTARIO: { label: 'Reservando producto', help: 'Evaluación favorable. Falta que Inventario confirme la reserva; todavía no está aprobada.', tone: 'pending' },
  APROBADA: { label: 'Aprobada', help: 'Crédito aprobado y producto reservado, listo para entrega.', tone: 'ok' },
  CANCELACION_PENDIENTE: { label: 'Cancelando', help: 'Cancelación aceptada; esperando que Inventario libere la reserva.', tone: 'pending' },
  ENTREGA_PENDIENTE: { label: 'Entregando', help: 'Entrega solicitada; esperando la confirmación de salida de Inventario.', tone: 'pending' },
  VERIFICACION_PENDIENTE: { label: 'Verificando reserva', help: 'La reserva venció o no se pudo confirmar; se está verificando con Inventario.', tone: 'pending' },
  COMPLETADA: { label: 'Entregada', help: 'El producto fue entregado.', tone: 'done' },
  RECHAZADA: { label: 'Rechazada', help: 'La solicitud no cumplió las políticas de crédito.', tone: 'bad' },
  CANCELADA: { label: 'Cancelada', help: 'La solicitud fue cancelada y la reserva liberada.', tone: 'bad' },
  CANCELADA_SIN_STOCK: { label: 'Sin existencias', help: 'Evaluación favorable, pero no había unidades disponibles.', tone: 'bad' },
  ERROR_TECNICO: { label: 'Error técnico', help: 'No se pudo completar la evaluación. Puedes hacer una nueva solicitud.', tone: 'bad' },
};

// Estados que cambian solos y justifican polling.
export const pendingStates: LoanState[] = ['EVALUANDO', 'PENDIENTE_INVENTARIO', 'CANCELACION_PENDIENTE', 'ENTREGA_PENDIENTE', 'VERIFICACION_PENDIENTE'];
export const cancellableStates: LoanState[] = ['PENDIENTE_INVENTARIO', 'APROBADA', 'VERIFICACION_PENDIENTE'];

const motives: Record<string, string> = {
  RIESGO_DESFAVORABLE: 'El modelo de riesgo estimó una probabilidad de incumplimiento superior al umbral.',
  INFORMACION_INCOMPLETA: 'Tu perfil financiero está incompleto. Un administrador debe completarlo.',
  MONTO_FUERA_DE_POLITICA: 'El monto debe estar entre $500.000 y $15.000.000.',
  PRODUCTO_INACTIVO: 'El producto ya no está disponible en el catálogo.',
  CLIENTE_INACTIVO: 'Tu cuenta de cliente está inactiva.',
  STOCK_INSUFICIENTE: 'No había unidades disponibles para reservar.',
  RESERVA_VENCIDA: 'La reserva de inventario venció antes de la entrega.',
  ENTREGA_RECHAZADA_SIN_RESERVA: 'Inventario rechazó la entrega porque la reserva ya no estaba activa.',
  CANCELACION_TARDA: 'La cancelación está tardando más de lo esperado.',
};

export function motiveText(motivo: string | null) {
  if (!motivo) return null;
  return motives[motivo] || motivo;
}

export const modelVariables: Record<string, string> = {
  ingresos_mensuales_cop: 'Ingresos mensuales',
  obligaciones_mensuales_cop: 'Obligaciones mensuales',
  tipo_empleo: 'Tipo de empleo',
  antiguedad_laboral_meses: 'Antigüedad laboral (meses)',
  meses_historial_crediticio: 'Historial crediticio (meses)',
  creditos_previos: 'Créditos previos',
  atrasos_previos_30d: 'Atrasos previos de 30 días',
  porcentaje_pago_puntual: 'Pago puntual (%)',
  monto_solicitado_cop: 'Monto solicitado',
  plazo_meses: 'Plazo (meses)',
  cuota_estimada_cop: 'Cuota estimada',
};

// Reglas de política replicadas solo para guiar el formulario; Préstamos las vuelve a validar.
export const POLICY = { minAmount: 500_000, maxAmount: 15_000_000, monthlyRate: 0.018, terms: [6, 12, 18, 24, 36], maxQuantity: 100 };

export function estimateInstallment(amount: number, months: number) {
  const r = POLICY.monthlyRate;
  return (amount * r) / (1 - Math.pow(1 + r, -months));
}
