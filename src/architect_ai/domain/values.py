"""Immutable values, exact decimal units and explicit assertion provenance."""

from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer


class DomainModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", validate_default=True, revalidate_instances="always"
    )

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        """Unlike BaseModel.model_copy, every copy/update crosses validation."""
        data = self.model_dump(mode="python")
        data.update(update or {})
        result = type(self).model_validate(data)
        prevent_promotion(self.model_dump(mode="json"), result.model_dump(mode="json"))
        return result


def prevent_promotion(before: Any, after: Any) -> None:
    """Reject silent relabeling of AI assertions during ordinary copy operations."""
    if isinstance(before, dict) and isinstance(after, dict):
        if before.get("source") == "AI_INFERRED" and after.get("source") in {
            "USER_EXPLICIT",
            "USER_REFERENCE",
        }:
            raise ValueError("AI provenance promotion requires an explicit acceptance workflow")
        for key in before.keys() & after.keys():
            prevent_promotion(before[key], after[key])
    elif isinstance(before, (tuple, list)) and isinstance(after, (tuple, list)):
        if all(isinstance(item, dict) and "id" in item for item in (*before, *after)):
            old = {item["id"]: item for item in before}
            for item in after:
                if item["id"] in old:
                    prevent_promotion(old[item["id"]], item)
        else:
            for old_item, new_item in zip(before, after, strict=False):
                prevent_promotion(old_item, new_item)


def exact_decimal(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise ValueError("Use Decimal, integer or decimal string; binary floats are forbidden")
    try:
        result = Decimal(value)
    except ArithmeticError as exc:
        raise ValueError("Invalid decimal") from exc
    if not result.is_finite():
        raise ValueError("Decimal must be finite")
    exponent = result.as_tuple().exponent
    assert isinstance(exponent, int)
    if result.copy_abs() > Decimal("1000000000") or exponent < -6:
        raise ValueError("Decimal exceeds supported magnitude or six fractional digits")
    return result


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return (text.rstrip("0").rstrip(".") if "." in text else text) if value else "0"


Number = Annotated[
    Decimal, BeforeValidator(exact_decimal), PlainSerializer(decimal_text, return_type=str)
]
Positive = Annotated[Number, Field(gt=0)]
NonNegative = Annotated[Number, Field(ge=0)]
Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Angle = Annotated[Number, Field(ge=0, lt=360)]


class Source(StrEnum):
    USER_EXPLICIT = "USER_EXPLICIT"
    USER_REFERENCE = "USER_REFERENCE"
    IMPORTED_GEOMETRY = "IMPORTED_GEOMETRY"
    SYSTEM_DERIVED = "SYSTEM_DERIVED"
    AI_INFERRED = "AI_INFERRED"


class Assertion[T](DomainModel):
    value: T
    source: Source
    source_reference: Text | None = None


class Point2(DomainModel):
    x: Number
    y: Number


class Point3(Point2):
    z: Number


class Dimensions(DomainModel):
    width: Positive
    depth: Positive
    height: Positive


class Clearance(DomainModel):
    front: NonNegative
    back: NonNegative
    left: NonNegative
    right: NonNegative
    above: NonNegative


def to_millimeters(value: Decimal | int | str, unit: Literal["mm", "cm", "m"]) -> Decimal:
    """Convert exactly, independent of the caller's decimal arithmetic context."""
    number = exact_decimal(value)
    powers = {"mm": 0, "cm": 1, "m": 3}
    if unit not in powers:
        raise ValueError("Unsupported input unit")
    parts = number.as_tuple()
    exponent = parts.exponent
    assert isinstance(exponent, int)
    return exact_decimal(Decimal((parts.sign, parts.digits, exponent + powers[unit])))
