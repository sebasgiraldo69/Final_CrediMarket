from decimal import Decimal
from typing import Annotated, Optional, List
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Text = Annotated[str, Field(min_length=1, max_length=250)]
Money = Annotated[str, Field(pattern=r'^(0|[1-9][0-9]{0,15})\.[0-9]{2}$')]


class Closed(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ProductoCrear(Closed):
    nombre: Text
    categoria: Text
    precio_cop: Money

    @field_validator('precio_cop')
    @classmethod
    def positive_price(cls, v: str) -> str:
        if Decimal(v) <= 0:
            raise ValueError('El precio debe ser estrictamente positivo (mayor a 0.00)')
        return v


class ProductoEditar(Closed):
    version_esperada: Annotated[int, Field(ge=1, strict=True)]
    nombre: Optional[Text] = None
    categoria: Optional[Text] = None
    precio_cop: Optional[Money] = None

    @field_validator('precio_cop')
    @classmethod
    def positive_price(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and Decimal(v) <= 0:
            raise ValueError('El precio debe ser estrictamente positivo (mayor a 0.00)')
        return v

    @model_validator(mode='after')
    def check_at_least_one_field(self):
        fields = self.model_fields_set - {'version_esperada'}
        if not fields or any(getattr(self, f) is None for f in fields):
            raise ValueError('Debes proporcionar al menos un campo no nulo para actualizar (nombre, categoria o precio_cop)')
        return self


class VersionEsperada(Closed):
    version_esperada: Annotated[int, Field(ge=1, strict=True)]


class Producto(Closed):
    id: str
    nombre: str
    categoria: str
    precio_cop: str
    activo: bool
    version: int
    created_at: str
    updated_at: str


class Productos(Closed):
    items: List[Producto]
    total: int
    limit: int
    offset: int


class Cotizacion(Closed):
    producto_id: str
    precio_unitario_cop: Money
    version_producto: int
    activo: bool
    cotizado_en: str
