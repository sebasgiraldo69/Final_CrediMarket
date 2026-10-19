from decimal import Decimal
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictBool, field_validator, model_validator

Text = Annotated[str, Field(min_length=1, max_length=250)]
Count = Annotated[int, Field(ge=0, strict=True)]
Money = Annotated[str, Field(pattern=r'^(0|[1-9][0-9]{0,15})\.[0-9]{2}$')]


class Closed(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Finanzas(Closed):
    ingresos_mensuales_cop: Money
    obligaciones_mensuales_cop: Money
    tipo_empleo: Literal['dependiente', 'independiente', 'temporal'] | None
    antiguedad_laboral_meses: Count | None
    meses_historial_crediticio: Count | None
    creditos_previos: Count
    atrasos_previos_30d: Count
    porcentaje_pago_puntual: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False, strict=True)] | None

    @model_validator(mode='after')
    def coherent(self):
        if Decimal(self.ingresos_mensuales_cop) <= 0:
            raise ValueError('Los ingresos deben ser positivos')
        if (self.creditos_previos == 0) != (self.porcentaje_pago_puntual is None):
            raise ValueError('El porcentaje es nulo únicamente cuando no hay créditos previos')
        return self


class Login(Closed):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=128)]

    @field_validator('email')
    @classmethod
    def normalize_email(cls, value):
        return str(value).lower()


class Registro(Login):
    nombre: Text
    password: Annotated[str, Field(min_length=12, max_length=128)]


class ClienteEditar(Closed):
    version_esperada: Annotated[int, Field(ge=1, strict=True)]
    nombre: Text | None = None
    email: EmailStr | None = None
    activo: StrictBool | None = None
    finanzas: Finanzas | None = None

    @model_validator(mode='after')
    def not_empty(self):
        fields = self.model_fields_set - {'version_esperada'}
        if not fields or any(getattr(self, field) is None for field in fields):
            raise ValueError('Incluye al menos un campo no nulo para editar')
        return self
