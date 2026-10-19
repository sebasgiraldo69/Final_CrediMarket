"""CSV adapter: financial records never create users or login credentials."""
import csv
import hashlib
import io
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, text, func
from sqlalchemy.dialects.postgresql import insert
from .models import clientes, importaciones
from .schemas import Finanzas

REQUIRED = {'cliente_id', *Finanzas.model_fields}
OPTIONAL = {'solicitud_id', 'monto_solicitado_cop', 'plazo_meses', 'tasa_mensual_simulada',
            'cuota_estimada_cop', 'incumplimiento_90d'}


def financial_row(row):
    value = {}
    for field in Finanzas.model_fields:
        raw = row[field].strip()
        if not raw:
            value[field] = None
        elif field == 'tipo_empleo':
            value[field] = raw
        elif field.endswith('_cop'):
            number = Decimal(raw)
            if not number.is_finite() or number != number.quantize(Decimal('0.01')):
                raise ValueError('Importe inválido o con más de dos decimales')
            value[field] = format(number, '.2f')
        elif field == 'porcentaje_pago_puntual':
            value[field] = float(raw)
        else:
            number = Decimal(raw)
            if not number.is_finite() or number != number.to_integral_value():
                raise ValueError('Meses y conteos deben ser enteros')
            value[field] = int(number)
    return Finanzas.model_validate(value).model_dump(mode='json')


def import_csv(connection, raw):
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, 'El archivo supera 10 MiB')
    try:
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')), strict=True)
        headers = reader.fieldnames or []
        if (len(headers) != len(set(headers)) or not REQUIRED <= set(headers)
                or set(headers) - REQUIRED - OPTIONAL):
            raise HTTPException(422, 'Cabeceras faltantes, repetidas o desconocidas')
        rows = []
        for row in reader:
            rows.append(row)
            if len(rows) > 20000:
                raise HTTPException(413, 'El archivo supera 20.000 filas')
    except (UnicodeDecodeError, csv.Error):
        raise HTTPException(422, 'CSV inválido: usa UTF-8 y separador coma')

    report = {'id': str(uuid4()), 'archivo_sha256': hashlib.sha256(raw).hexdigest(),
        'estado': 'COMPLETADA', 'total_filas': len(rows), 'insertados': 0, 'actualizados': 0,
        'sin_cambios': 0, 'rechazados': 0, 'errores': [],
        'created_at': datetime.now(timezone.utc).isoformat()}
    valid = {}
    seen = set()
    for line, row in enumerate(rows, start=2):
        try:
            if None in row or any(value is None for value in row.values()):
                raise ValueError('Número de columnas incorrecto')
            key = row['cliente_id'].strip()
            if not key or len(key) > 250:
                raise ValueError('cliente_id vacío o demasiado largo')
            if key in seen:
                raise ValueError('cliente_id repetido dentro del archivo')
            seen.add(key)
            valid[key] = financial_row(row)
        except (ValueError, InvalidOperation, OverflowError, ValidationError) as exc:
            field = 'fila'
            message = str(exc) if isinstance(exc, ValueError) else 'Número fuera de rango o inválido'
            if isinstance(exc, ValidationError):
                error = exc.errors()[0]
                field = '.'.join(map(str, error['loc'])) or 'finanzas'
                message = error['msg']
            report['rechazados'] += 1
            report['errores'].append({'fila': line, 'campo': field, 'codigo': 'FILA_INVALIDA',
                'mensaje': message})

    # Serialize imports, including two simultaneous uploads of the same file.
    # External keys cannot be edited through public HTTP endpoints.
    connection.execute(text('SELECT pg_advisory_xact_lock(734201)'))
    existing = {}
    if valid:
        existing = {r.clave_externa: r.finanzas for r in connection.execute(
            select(clientes.c.clave_externa, clientes.c.finanzas).where(
                clientes.c.clave_externa.in_(list(valid))).with_for_update())}
    pending = []
    for key, financial in valid.items():
        if key not in existing:
            report['insertados'] += 1
        elif existing[key] == financial:
            report['sin_cambios'] += 1
            continue
        else:
            report['actualizados'] += 1
        pending.append({'id': uuid4(), 'clave_externa': key, 'finanzas': financial})
    for offset in range(0, len(pending), 500):
        statement = insert(clientes).values(pending[offset:offset + 500])
        statement = statement.on_conflict_do_update(index_elements=['clave_externa'], set_={
            'finanzas': statement.excluded.finanzas, 'version': clientes.c.version + 1,
            'updated_at': func.now()})
        connection.execute(statement)
    connection.execute(importaciones.insert().values(id=report['id'], reporte=report))
    return report
