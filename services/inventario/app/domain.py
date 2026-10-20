from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4
from typing import Optional
from sqlalchemy import select, update, insert
from .models import existencias, reservas, movimientos


def format_reserva(row) -> dict:
    return {
        'reserva_id': str(row['id']),
        'prestamo_id': str(row['prestamo_id']),
        'producto_id': str(row['producto_id']) if row['producto_id'] is not None else None,
        'cantidad': row['cantidad'],
        'estado_reserva': row['estado'],
        'revision_reserva': int(row['revision']),
        'vence_en': row['vence_en'].isoformat() if row['vence_en'] is not None else None
    }


def format_movimiento(row) -> dict:
    return {
        'id': str(row['id']),
        'producto_id': str(row['producto_id']),
        'prestamo_id': str(row['prestamo_id']) if row['prestamo_id'] is not None else None,
        'tipo': row['tipo'],
        'cantidad': int(row['cantidad']),
        'motivo': row['motivo'],
        'created_at': row['created_at'].isoformat()
    }


def format_existencia(row) -> dict:
    return {
        'producto_id': str(row['producto_id']),
        'fisico': int(row['fisico']),
        'reservado': int(row['reservado']),
        'disponible': int(row['disponible'])
    }


def get_reserva_by_prestamo(conn, prestamo_id: UUID) -> Optional[dict]:
    query = select(reservas).where(reservas.c.prestamo_id == prestamo_id)
    row = conn.execute(query).mappings().first()
    if not row:
        return None
    return format_reserva(row)


def reservar(conn, prestamo_id: UUID, producto_id: UUID, cantidad: int, ttl_seconds: int = 600) -> dict:
    now = datetime.now(timezone.utc)
    
    # 1. Lock existing reservation for this prestamo_id
    res_query = select(reservas).where(reservas.c.prestamo_id == prestamo_id).with_for_update()
    res_row = conn.execute(res_query).mappings().first()
    
    if res_row:
        # Consistency check: if product and quantity already defined, ensure they match
        if res_row['producto_id'] is not None and (res_row['producto_id'] != producto_id or res_row['cantidad'] != cantidad):
            raise ValueError("Conflicto de integridad: producto o cantidad no coinciden con la reserva existente")
        
        # If pre-cancelled or already terminal
        if res_row['estado'] in ('CANCELADA', 'SIN_STOCK', 'ENTREGADA'):
            return format_reserva(res_row)
        
        if res_row['estado'] == 'VENCIDA':
            return format_reserva(res_row)
        
        if res_row['estado'] == 'ACTIVA':
            # Check if expired
            if res_row['vence_en'] and res_row['vence_en'] < now:
                # Expired while active: release stock and transition to VENCIDA
                ex_query = select(existencias).where(existencias.c.producto_id == res_row['producto_id']).with_for_update()
                ex_row = conn.execute(ex_query).mappings().first()
                if ex_row:
                    conn.execute(
                        update(existencias)
                        .where(existencias.c.producto_id == res_row['producto_id'])
                        .values(
                            disponible=ex_row['disponible'] + res_row['cantidad'],
                            reservado=ex_row['reservado'] - res_row['cantidad'],
                            updated_at=now
                        )
                    )
                new_rev = res_row['revision'] + 1
                conn.execute(
                    update(reservas)
                    .where(reservas.c.id == res_row['id'])
                    .values(estado='VENCIDA', revision=new_rev, updated_at=now)
                )
                conn.execute(
                    insert(movimientos).values(
                        id=uuid4(),
                        producto_id=res_row['producto_id'],
                        prestamo_id=prestamo_id,
                        tipo='VENCIMIENTO',
                        cantidad=res_row['cantidad'],
                        motivo=f"Vencimiento automático de reserva {res_row['id']}",
                        created_at=now
                    )
                )
                updated_res = dict(res_row)
                updated_res['estado'] = 'VENCIDA'
                updated_res['revision'] = new_rev
                return format_reserva(updated_res)
            
            # Still active and matches
            return format_reserva(res_row)
    
    # 2. No existing reservation (SIN_RESERVA) -> evaluate stock atomically
    ex_query = select(existencias).where(existencias.c.producto_id == producto_id).with_for_update()
    ex_row = conn.execute(ex_query).mappings().first()
    
    if not ex_row or ex_row['disponible'] < cantidad:
        # Insufficient stock: insert SIN_STOCK mark
        res_id = uuid4()
        conn.execute(
            insert(reservas).values(
                id=res_id,
                prestamo_id=prestamo_id,
                producto_id=producto_id,
                cantidad=cantidad,
                estado='SIN_STOCK',
                revision=1,
                vence_en=None,
                created_at=now,
                updated_at=now
            )
        )
        return {
            'reserva_id': str(res_id),
            'prestamo_id': str(prestamo_id),
            'producto_id': str(producto_id),
            'cantidad': cantidad,
            'estado_reserva': 'SIN_STOCK',
            'revision_reserva': 1,
            'vence_en': None
        }
    
    # Sufficient stock: atomically discount disponible and increment reservado
    conn.execute(
        update(existencias)
        .where(existencias.c.producto_id == producto_id)
        .values(
            disponible=ex_row['disponible'] - cantidad,
            reservado=ex_row['reservado'] + cantidad,
            updated_at=now
        )
    )
    
    vence_en = now + timedelta(seconds=ttl_seconds)
    res_id = uuid4()
    conn.execute(
        insert(reservas).values(
            id=res_id,
            prestamo_id=prestamo_id,
            producto_id=producto_id,
            cantidad=cantidad,
            estado='ACTIVA',
            revision=1,
            vence_en=vence_en,
            created_at=now,
            updated_at=now
        )
    )
    
    conn.execute(
        insert(movimientos).values(
            id=uuid4(),
            producto_id=producto_id,
            prestamo_id=prestamo_id,
            tipo='RESERVA',
            cantidad=cantidad,
            motivo=f"Reserva préstamo {prestamo_id}",
            created_at=now
        )
    )
    
    return {
        'reserva_id': str(res_id),
        'prestamo_id': str(prestamo_id),
        'producto_id': str(producto_id),
        'cantidad': cantidad,
        'estado_reserva': 'ACTIVA',
        'revision_reserva': 1,
        'vence_en': vence_en.isoformat()
    }


def liberar(conn, prestamo_id: UUID) -> dict:
    now = datetime.now(timezone.utc)
    res_query = select(reservas).where(reservas.c.prestamo_id == prestamo_id).with_for_update()
    res_row = conn.execute(res_query).mappings().first()
    
    if not res_row:
        # Pre-cancellation mark: no prior reservation exists yet.
        # Create durable CANCELADA mark to block any later reservation.
        res_id = uuid4()
        conn.execute(
            insert(reservas).values(
                id=res_id,
                prestamo_id=prestamo_id,
                producto_id=None,
                cantidad=None,
                estado='CANCELADA',
                revision=1,
                vence_en=None,
                created_at=now,
                updated_at=now
            )
        )
        return {
            'reserva_id': str(res_id),
            'prestamo_id': str(prestamo_id),
            'producto_id': None,
            'cantidad': None,
            'estado_reserva': 'CANCELADA',
            'revision_reserva': 1,
            'vence_en': None
        }
    
    # Row exists
    if res_row['estado'] in ('CANCELADA', 'SIN_STOCK', 'VENCIDA'):
        # Idempotent no-op: does not alter stock
        return format_reserva(res_row)
    
    if res_row['estado'] == 'ENTREGADA':
        raise ValueError("YA_ENTREGADA: no es posible liberar una reserva ya entregada")
    
    if res_row['estado'] == 'ACTIVA':
        # Check if already expired
        if res_row['vence_en'] and res_row['vence_en'] < now:
            # Expired: transition to VENCIDA, restore stock
            ex_query = select(existencias).where(existencias.c.producto_id == res_row['producto_id']).with_for_update()
            ex_row = conn.execute(ex_query).mappings().first()
            if ex_row:
                conn.execute(
                    update(existencias)
                    .where(existencias.c.producto_id == res_row['producto_id'])
                    .values(
                        disponible=ex_row['disponible'] + res_row['cantidad'],
                        reservado=ex_row['reservado'] - res_row['cantidad'],
                        updated_at=now
                    )
                )
            new_rev = res_row['revision'] + 1
            conn.execute(
                update(reservas)
                .where(reservas.c.id == res_row['id'])
                .values(estado='VENCIDA', revision=new_rev, updated_at=now)
            )
            conn.execute(
                insert(movimientos).values(
                    id=uuid4(),
                    producto_id=res_row['producto_id'],
                    prestamo_id=prestamo_id,
                    tipo='VENCIMIENTO',
                    cantidad=res_row['cantidad'],
                    motivo=f"Vencimiento automático de reserva {res_row['id']}",
                    created_at=now
                )
            )
            updated_res = dict(res_row)
            updated_res['estado'] = 'VENCIDA'
            updated_res['revision'] = new_rev
            return format_reserva(updated_res)
        
        # Valid active reservation: restore available stock
        ex_query = select(existencias).where(existencias.c.producto_id == res_row['producto_id']).with_for_update()
        ex_row = conn.execute(ex_query).mappings().first()
        if ex_row:
            conn.execute(
                update(existencias)
                .where(existencias.c.producto_id == res_row['producto_id'])
                .values(
                    disponible=ex_row['disponible'] + res_row['cantidad'],
                    reservado=ex_row['reservado'] - res_row['cantidad'],
                    updated_at=now
                )
            )
        
        new_rev = res_row['revision'] + 1
        conn.execute(
            update(reservas)
            .where(reservas.c.id == res_row['id'])
            .values(estado='CANCELADA', revision=new_rev, updated_at=now)
        )
        conn.execute(
            insert(movimientos).values(
                id=uuid4(),
                producto_id=res_row['producto_id'],
                prestamo_id=prestamo_id,
                tipo='LIBERACION',
                cantidad=res_row['cantidad'],
                motivo=f"Liberación de reserva préstamo {prestamo_id}",
                created_at=now
            )
        )
        updated_res = dict(res_row)
        updated_res['estado'] = 'CANCELADA'
        updated_res['revision'] = new_rev
        return format_reserva(updated_res)

    raise ValueError(f"Estado de reserva desconocido: {res_row['estado']}")


def entregar(conn, prestamo_id: UUID) -> dict:
    now = datetime.now(timezone.utc)
    res_query = select(reservas).where(reservas.c.prestamo_id == prestamo_id).with_for_update()
    res_row = conn.execute(res_query).mappings().first()
    
    if not res_row:
        return {
            'reserva_id': None,
            'prestamo_id': str(prestamo_id),
            'producto_id': None,
            'cantidad': None,
            'estado_reserva': 'SIN_RESERVA',
            'revision_reserva': 0,
            'vence_en': None
        }
    
    if res_row['estado'] == 'ENTREGADA':
        # Idempotent: confirmed effect, no second salida
        return format_reserva(res_row)
    
    if res_row['estado'] in ('CANCELADA', 'SIN_STOCK', 'VENCIDA'):
        raise ValueError(f"Entrega rechazada: la reserva está en estado terminal {res_row['estado']}")
    
    if res_row['estado'] == 'ACTIVA':
        # Check expiration
        if res_row['vence_en'] and res_row['vence_en'] < now:
            # Expired: transition to VENCIDA, restore stock
            ex_query = select(existencias).where(existencias.c.producto_id == res_row['producto_id']).with_for_update()
            ex_row = conn.execute(ex_query).mappings().first()
            if ex_row:
                conn.execute(
                    update(existencias)
                    .where(existencias.c.producto_id == res_row['producto_id'])
                    .values(
                        disponible=ex_row['disponible'] + res_row['cantidad'],
                        reservado=ex_row['reservado'] - res_row['cantidad'],
                        updated_at=now
                    )
                )
            new_rev = res_row['revision'] + 1
            conn.execute(
                update(reservas)
                .where(reservas.c.id == res_row['id'])
                .values(estado='VENCIDA', revision=new_rev, updated_at=now)
            )
            conn.execute(
                insert(movimientos).values(
                    id=uuid4(),
                    producto_id=res_row['producto_id'],
                    prestamo_id=prestamo_id,
                    tipo='VENCIMIENTO',
                    cantidad=res_row['cantidad'],
                    motivo=f"Vencimiento automático de reserva {res_row['id']}",
                    created_at=now
                )
            )
            raise ValueError("RESERVA_VENCIDA: la reserva expiró antes de la entrega")
        
        # Deliver: discount fisico and reservado
        ex_query = select(existencias).where(existencias.c.producto_id == res_row['producto_id']).with_for_update()
        ex_row = conn.execute(ex_query).mappings().first()
        if not ex_row:
            raise ValueError("Existencias no encontradas para el producto")
        
        conn.execute(
            update(existencias)
            .where(existencias.c.producto_id == res_row['producto_id'])
            .values(
                fisico=ex_row['fisico'] - res_row['cantidad'],
                reservado=ex_row['reservado'] - res_row['cantidad'],
                updated_at=now
            )
        )
        
        new_rev = res_row['revision'] + 1
        conn.execute(
            update(reservas)
            .where(reservas.c.id == res_row['id'])
            .values(estado='ENTREGADA', revision=new_rev, updated_at=now)
        )
        conn.execute(
            insert(movimientos).values(
                id=uuid4(),
                producto_id=res_row['producto_id'],
                prestamo_id=prestamo_id,
                tipo='SALIDA',
                cantidad=res_row['cantidad'],
                motivo=f"Entrega definitiva préstamo {prestamo_id}",
                created_at=now
            )
        )
        updated_res = dict(res_row)
        updated_res['estado'] = 'ENTREGADA'
        updated_res['revision'] = new_rev
        return format_reserva(updated_res)

    raise ValueError(f"Estado de reserva desconocido: {res_row['estado']}")


def vencer(conn, prestamo_id: UUID) -> Optional[dict]:
    now = datetime.now(timezone.utc)
    res_query = select(reservas).where(reservas.c.prestamo_id == prestamo_id).with_for_update()
    res_row = conn.execute(res_query).mappings().first()
    
    if not res_row:
        return None
    
    if res_row['estado'] == 'ACTIVA' and res_row['vence_en'] and res_row['vence_en'] < now:
        ex_query = select(existencias).where(existencias.c.producto_id == res_row['producto_id']).with_for_update()
        ex_row = conn.execute(ex_query).mappings().first()
        if ex_row:
            conn.execute(
                update(existencias)
                .where(existencias.c.producto_id == res_row['producto_id'])
                .values(
                    disponible=ex_row['disponible'] + res_row['cantidad'],
                    reservado=ex_row['reservado'] - res_row['cantidad'],
                    updated_at=now
                )
            )
        new_rev = res_row['revision'] + 1
        conn.execute(
            update(reservas)
            .where(reservas.c.id == res_row['id'])
            .values(estado='VENCIDA', revision=new_rev, updated_at=now)
        )
        conn.execute(
            insert(movimientos).values(
                id=uuid4(),
                producto_id=res_row['producto_id'],
                prestamo_id=prestamo_id,
                tipo='VENCIMIENTO',
                cantidad=res_row['cantidad'],
                motivo=f"Vencimiento automático de reserva {res_row['id']}",
                created_at=now
            )
        )
        updated_res = dict(res_row)
        updated_res['estado'] = 'VENCIDA'
        updated_res['revision'] = new_rev
        return format_reserva(updated_res)
    
    return format_reserva(res_row)


def agregar_stock(conn, producto_id: UUID, cantidad: int, motivo: str) -> dict:
    now = datetime.now(timezone.utc)
    ex_query = select(existencias).where(existencias.c.producto_id == producto_id).with_for_update()
    ex_row = conn.execute(ex_query).mappings().first()
    
    if ex_row:
        conn.execute(
            update(existencias)
            .where(existencias.c.producto_id == producto_id)
            .values(
                fisico=ex_row['fisico'] + cantidad,
                disponible=ex_row['disponible'] + cantidad,
                updated_at=now
            )
        )
    else:
        conn.execute(
            insert(existencias).values(
                producto_id=producto_id,
                fisico=cantidad,
                reservado=0,
                disponible=cantidad,
                updated_at=now
            )
        )
    
    mov_id = uuid4()
    conn.execute(
        insert(movimientos).values(
            id=mov_id,
            producto_id=producto_id,
            prestamo_id=None,
            tipo='ENTRADA',
            cantidad=cantidad,
            motivo=motivo,
            created_at=now
        )
    )
    
    return {
        'id': str(mov_id),
        'producto_id': str(producto_id),
        'prestamo_id': None,
        'tipo': 'ENTRADA',
        'cantidad': cantidad,
        'motivo': motivo,
        'created_at': now.isoformat()
    }
