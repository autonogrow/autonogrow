from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictPilotModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModuleAccessUpdate(StrictPilotModel):
    entitled: bool
    active: bool
    module_cost_amount: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )
    module_cost_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def coherent_cost(self):
        if self.active and not self.entitled:
            raise ValueError("Un módulo activo debe estar incluido")
        if (self.module_cost_amount is None) != (self.module_cost_currency is None):
            raise ValueError("El coste y su moneda deben configurarse juntos")
        self.reason = self.reason.strip()
        return self


class PilotBaselineUpdate(StrictPilotModel):
    monthly_bookings: int | None = Field(default=None, ge=0, le=1_000_000)
    average_ticket: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    occupancy_percentage: Decimal | None = Field(default=None, ge=0, le=100)
    recurring_customer_percentage: Decimal | None = Field(default=None, ge=0, le=100)
    cancellation_percentage: Decimal | None = Field(default=None, ge=0, le=100)
    no_show_percentage: Decimal | None = Field(default=None, ge=0, le=100)
    currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    notes: str | None = Field(default=None, max_length=2000)


ProductModule = Literal["essential", "growth", "social"]
