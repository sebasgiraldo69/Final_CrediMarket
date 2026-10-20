from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SchemaBase(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Entrada(SchemaBase):
    producto_id: UUID
    cantidad: int = Field(..., ge=1)
    motivo: str = Field(..., min_length=1, max_length=250)


class Existencia(SchemaBase):
    producto_id: UUID
    fisico: int = Field(..., ge=0)
    reservado: int = Field(..., ge=0)
    disponible: int = Field(..., ge=0)


class Existencias(SchemaBase):
    items: List[Existencia]
    total: int = Field(..., ge=0)
    limit: int = Field(..., ge=1, le=100)
    offset: int = Field(..., ge=0)


class Movimiento(SchemaBase):
    id: UUID
    producto_id: UUID
    prestamo_id: Optional[UUID] = None
    tipo: Literal['ENTRADA', 'RESERVA', 'LIBERACION', 'SALIDA', 'VENCIMIENTO']
    cantidad: int = Field(..., ge=1)
    motivo: str = Field(..., min_length=1, max_length=250)
    created_at: datetime


class Movimientos(SchemaBase):
    items: List[Movimiento]
    total: int = Field(..., ge=0)
    limit: int = Field(..., ge=1, le=100)
    offset: int = Field(..., ge=0)


class Reserva(SchemaBase):
    reserva_id: UUID
    prestamo_id: UUID
    producto_id: Optional[UUID] = None
    cantidad: Optional[int] = Field(None, ge=1, le=100)
    estado_reserva: Literal['ACTIVA', 'SIN_STOCK', 'CANCELADA', 'VENCIDA', 'ENTREGADA']
    revision_reserva: int = Field(..., ge=1)
    vence_en: Optional[datetime] = None

    @model_validator(mode='after')
    def validate_reserva_state(self):
        if self.estado_reserva in ('ACTIVA', 'VENCIDA', 'ENTREGADA'):
            if self.producto_id is None:
                raise ValueError(f"producto_id es obligatorio cuando estado_reserva es {self.estado_reserva}")
            if self.cantidad is None:
                raise ValueError(f"cantidad es obligatoria cuando estado_reserva es {self.estado_reserva}")
            if self.vence_en is None:
                raise ValueError(f"vence_en es obligatorio cuando estado_reserva es {self.estado_reserva}")
        elif self.estado_reserva == 'SIN_STOCK':
            if self.producto_id is None:
                raise ValueError("producto_id es obligatorio cuando estado_reserva es SIN_STOCK")
            if self.cantidad is None:
                raise ValueError("cantidad es obligatoria cuando estado_reserva es SIN_STOCK")
            if self.vence_en is not None:
                raise ValueError("vence_en debe ser null cuando estado_reserva es SIN_STOCK")
        return self


class Reservas(SchemaBase):
    items: List[Reserva]
    total: int = Field(..., ge=0)
    limit: int = Field(..., ge=1, le=100)
    offset: int = Field(..., ge=0)
