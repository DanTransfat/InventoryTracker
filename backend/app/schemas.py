"""Request schemas. Pydantic does shape/format validation; business rules
(sign of a quantity vs. its type, stock never negative) live in the service layer."""
from __future__ import annotations

from typing import Any, Literal, Type, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError, field_validator

from .errors import BadRequest, ValidationFailed

TransactionType = Literal["received", "shipped", "adjustment", "returned"]
SKU_PATTERN = r"^[A-Z0-9][A-Z0-9._-]{0,63}$"


class _Base(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class ItemCreate(_Base):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    unit: str = Field(min_length=1, max_length=32)
    reorder_threshold: StrictInt = Field(ge=0, le=1_000_000_000)
    # Optional opening balance. It is recorded as a 'received' ledger entry,
    # never written directly to the stock column (see README, open question 1).
    initial_stock: StrictInt = Field(default=0, ge=0, le=1_000_000_000)
    created_by: str = Field(default="system", min_length=1, max_length=100)

    @field_validator("sku", mode="before")
    @classmethod
    def normalise_sku(cls, v: Any) -> Any:
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("sku")
    @classmethod
    def check_sku(cls, v: str) -> str:
        import re

        if not re.match(SKU_PATTERN, v):
            raise ValueError("SKU may contain only letters, digits, '.', '_' and '-' and must start with a letter or digit")
        return v


class ItemUpdate(_Base):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    reorder_threshold: StrictInt | None = Field(default=None, ge=0, le=1_000_000_000)
    is_archived: StrictBool | None = None


class TransactionCreate(_Base):
    type: TransactionType
    # Signed ledger value: +N for received/returned, -N for shipped, either for adjustment.
    quantity_change: StrictInt = Field(ge=-1_000_000_000, le=1_000_000_000)
    note: str | None = Field(default=None, max_length=500)
    created_by: str = Field(min_length=1, max_length=100)


class AlertAcknowledge(_Base):
    acknowledged_by: str | None = Field(default=None, max_length=100)


M = TypeVar("M", bound=BaseModel)


def parse_body(model: Type[M], data: Any) -> M:
    """Validate a JSON body, converting Pydantic errors into a 422 with per-field messages."""
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise BadRequest("Request body must be a JSON object.", code="INVALID_JSON")
    if model is ItemUpdate and "sku" in data:
        raise ValidationFailed("SKU cannot be changed after an item is created.",
                               code="SKU_IMMUTABLE", fields={"sku": "SKU is immutable."})
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        fields: dict[str, str] = {}
        for err in exc.errors():
            field = ".".join(str(p) for p in err["loc"]) or "body"
            msg = err["msg"].removeprefix("Value error, ")
            if err["type"] == "extra_forbidden":
                msg = "Unknown field."
            elif err["type"] in ("int_type", "int_parsing"):
                msg = "Must be a whole number."
            fields.setdefault(field, msg)
        raise ValidationFailed("Some fields are invalid.", fields=fields) from None
