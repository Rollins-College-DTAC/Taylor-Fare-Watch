"""Pydantic schemas every expert's output must pass, whichever expert produced it.

Type checks catch malformed output; the business checks catch values that are well-formed
but impossible for this case study (a departure outside April 2027, a negative fare).
Pass the settings as validation context: Quote.model_validate(data, context=settings).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from agent.config import Settings
from agent.reference import CARRIER_CODES, CATEGORIES, ORIGIN_CODES, URGENCY_LEVELS

Carrier = Literal[CARRIER_CODES]
Origin = Literal[ORIGIN_CODES]
Category = Literal[CATEGORIES]
Urgency = Literal[URGENCY_LEVELS]


class QuoteExtraction(BaseModel):
    """Values pulled from one fare quote. Anything the record does not state is None."""

    model_config = ConfigDict(extra="forbid")

    quote_id: str | None
    carrier_code: Carrier | None
    flight_number: str | None = Field(pattern=r"^[A-Z]{2}\d{3,4}$")
    origin: Origin | None
    destination: Literal["CUN"] | None
    depart_date: date | None
    return_date: date | None
    fare_amount: float | None = Field(gt=0)
    fare_currency: Literal["USD", "MXN"] | None
    cabin: Literal["economy", "basic_economy"] | None
    seats_left: int | None = Field(ge=0, le=500)
    nonstop: bool | None
    checked_bag_included: bool | None
    refundable: bool | None
    price_hold_hours: int | None = Field(gt=0, le=168)
    summary: str | None = Field(max_length=200)
    confidence: Literal["high", "low"]

    @model_validator(mode="after")
    def business_rules(self, info: ValidationInfo) -> "QuoteExtraction":
        settings: Settings | None = info.context
        if settings and self.depart_date and (
            (self.depart_date.year, self.depart_date.month)
            != (settings.departure_year, settings.departure_month)
        ):
            raise ValueError(f"depart_date {self.depart_date} is outside the tracked month")
        if self.depart_date and self.return_date and self.return_date <= self.depart_date:
            raise ValueError("return_date must be after depart_date")
        if (self.fare_amount is None) != (self.fare_currency is None):
            raise ValueError("fare_amount and fare_currency must both be set or both be null")
        return self


class QuoteClassification(BaseModel):
    """Answers to the three Jev questions, from Jev or from an expert asking the same questions."""

    model_config = ConfigDict(extra="forbid")

    category: Category
    category_confidence: float = Field(ge=0, le=1)
    category_probs: dict[str, float] | None = None
    urgency: Urgency
    urgency_confidence: float = Field(ge=0, le=1)
    urgency_probs: dict[str, float] | None = None
    injection: bool
    injection_confidence: float = Field(ge=0, le=1)
    injection_prob: float | None = None  # probability that it IS an injection, for the Brier score


def choice_confidence(probs: dict[str, float]) -> float:
    """Course formula for n options: (p_max - 1/n) / (1 - 1/n). 0 = a pure guess, 1 = certain."""
    n = len(probs)
    if n < 2:
        return 1.0
    return max(0.0, (max(probs.values()) - 1 / n) / (1 - 1 / n))
