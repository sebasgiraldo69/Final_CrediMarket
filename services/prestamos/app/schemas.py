"""Esquemas Pydantic de validación estricta para el servicio de Préstamos y modelo de riesgo (Fase 8)."""
from decimal import Decimal, ROUND_HALF_UP
import math
from typing import Any, List, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TASA_MENSUAL_FIJA = Decimal("0.018")
PLAZOS_VALIDOS = (6, 12, 18, 24, 36)
TIPOS_EMPLEO_VALIDOS = ("dependiente", "independiente", "temporal")


def calcular_cuota_anualidad(monto_cop: float | Decimal, plazo_meses: int) -> Decimal:
    """Calcula la cuota mensual con tasa fija 0.018 redondeada a 2 decimales (ROUND_HALF_UP)."""
    monto = Decimal(str(monto_cop))
    r = TASA_MENSUAL_FIJA
    n = int(plazo_meses)
    factor = Decimal("1") - (Decimal("1") + r) ** Decimal(-n)
    cuota = (monto * r) / factor
    return cuota.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _ensure_finite_number(val: Any, field_name: str) -> float:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ValueError(f"{field_name} debe ser un número finito")
    fval = float(val)
    if not math.isfinite(fval):
        raise ValueError(f"{field_name} no admite NaN ni Infinity")
    return fval


def _ensure_strict_int(val: Any, field_name: str) -> int:
    if isinstance(val, bool):
        raise ValueError(f"{field_name} debe ser un número entero")
    if isinstance(val, int):
        return val
    if isinstance(val, float) and math.isfinite(val) and val.is_integer():
        return int(val)
    raise ValueError(f"{field_name} debe ser un número entero sin parte fraccionaria")


class Features(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingresos_mensuales_cop: float
    obligaciones_mensuales_cop: float
    tipo_empleo: Literal["dependiente", "independiente", "temporal"] | None
    antiguedad_laboral_meses: int | None
    meses_historial_crediticio: int | None
    creditos_previos: int
    atrasos_previos_30d: int
    porcentaje_pago_puntual: float | None
    monto_solicitado_cop: float
    plazo_meses: Literal[6, 12, 18, 24, 36]
    cuota_estimada_cop: float

    @field_validator("ingresos_mensuales_cop", mode="before")
    @classmethod
    def validate_ingresos(cls, v: Any) -> float:
        f = _ensure_finite_number(v, "ingresos_mensuales_cop")
        if f <= 0:
            raise ValueError("ingresos_mensuales_cop debe ser estrictamente positivo (> 0)")
        return f

    @field_validator("obligaciones_mensuales_cop", mode="before")
    @classmethod
    def validate_obligaciones(cls, v: Any) -> float:
        f = _ensure_finite_number(v, "obligaciones_mensuales_cop")
        if f < 0:
            raise ValueError("obligaciones_mensuales_cop no puede ser negativo")
        return f

    @field_validator("antiguedad_laboral_meses", "meses_historial_crediticio", mode="before")
    @classmethod
    def validate_nullable_months(cls, v: Any, info) -> int | None:
        if v is None:
            return None
        ival = _ensure_strict_int(v, info.field_name)
        if ival < 0:
            raise ValueError(f"{info.field_name} debe ser >= 0")
        return ival

    @field_validator("creditos_previos", "atrasos_previos_30d", mode="before")
    @classmethod
    def validate_non_negative_counts(cls, v: Any, info) -> int:
        if v is None:
            raise ValueError(f"{info.field_name} no puede ser nulo")
        ival = _ensure_strict_int(v, info.field_name)
        if ival < 0:
            raise ValueError(f"{info.field_name} debe ser >= 0")
        return ival

    @field_validator("porcentaje_pago_puntual", mode="before")
    @classmethod
    def validate_porcentaje(cls, v: Any) -> float | None:
        if v is None:
            return None
        f = _ensure_finite_number(v, "porcentaje_pago_puntual")
        if f < 0.0 or f > 100.0:
            raise ValueError("porcentaje_pago_puntual debe estar entre 0 y 100")
        return f

    @field_validator("monto_solicitado_cop", mode="before")
    @classmethod
    def validate_monto(cls, v: Any) -> float:
        f = _ensure_finite_number(v, "monto_solicitado_cop")
        if f < 500000.0 or f > 15000000.0:
            raise ValueError("monto_solicitado_cop debe estar dentro de la política [500000, 15000000] COP")
        return f

    @field_validator("plazo_meses", mode="before")
    @classmethod
    def validate_plazo(cls, v: Any) -> int:
        ival = _ensure_strict_int(v, "plazo_meses")
        if ival not in PLAZOS_VALIDOS:
            raise ValueError("plazo_meses debe pertenecer a {6, 12, 18, 24, 36}")
        return ival

    @field_validator("cuota_estimada_cop", mode="before")
    @classmethod
    def validate_cuota_positiva(cls, v: Any) -> float:
        f = _ensure_finite_number(v, "cuota_estimada_cop")
        if f <= 0:
            raise ValueError("cuota_estimada_cop debe ser estrictamente positiva (> 0)")
        return f

    @model_validator(mode="after")
    def validate_relational_rules(self) -> "Features":
        if self.creditos_previos == 0 and self.porcentaje_pago_puntual is not None:
            raise ValueError("porcentaje_pago_puntual debe ser null cuando creditos_previos == 0")
        if self.creditos_previos > 0 and self.porcentaje_pago_puntual is None:
            raise ValueError("porcentaje_pago_puntual es obligatorio cuando creditos_previos > 0")

        cuota_esperada = calcular_cuota_anualidad(self.monto_solicitado_cop, self.plazo_meses)
        cuota_recibida = Decimal(str(round(self.cuota_estimada_cop, 4)))
        if abs(cuota_recibida - cuota_esperada) > Decimal("0.01"):
            raise ValueError(
                f"cuota_estimada_cop ({self.cuota_estimada_cop:.2f}) no coincide con la fórmula de anualidad "
                f"a tasa fija 0.018 ({cuota_esperada}) dentro de +/- 0.01 COP"
            )
        return self


class Riesgo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    probabilidad_incumplimiento: float = Field(..., ge=0.0, le=1.0)
    decision_riesgo: Literal["FAVORABLE", "DESFAVORABLE"]
    umbral: float = Field(..., ge=0.0, le=1.0)
    model_version: str = Field(..., min_length=1, max_length=250)
    run_id: str = Field(..., min_length=1, max_length=250)


class ModeloInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_version: str = Field(..., min_length=1, max_length=250)
    run_id: str = Field(..., min_length=1, max_length=250)
    variables: List[str]
    clase_positiva: Literal[1]
    umbral: float = Field(..., ge=0.0, le=1.0)
    artifact_sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")
