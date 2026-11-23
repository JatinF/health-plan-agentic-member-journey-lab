"""Shared tool response shape. Money is a two-decimal string, not a float."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from membercare import NOTICE
from membercare.errors import LabError

SCHEMA_VERSION = "1.0"


def usd_string(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    whole, rem = divmod(abs(cents), 100)
    return f"{sign}{whole}.{rem:02d}"


def cents_from_usd_string(value: str) -> int:
    dec = Decimal(value)
    quantized = dec.quantize(Decimal("0.01"))
    if quantized != dec:
        raise LabError("inconsistent", "money string is not exact cents")
    return int(quantized * 100)


def service_year(value: str) -> int:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise LabError("invalid", "date must be YYYY-MM-DD") from exc
    return parsed.year


def envelope(
    tool: str,
    data: dict,
    source: dict,
    *,
    status: str = "success",
    error: str = "",
    message: str = "",
) -> dict:
    return {
        "tool": tool,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "data": data,
        "source": source,
        "error": error,
        "message": message,
        "notice": NOTICE,
    }
