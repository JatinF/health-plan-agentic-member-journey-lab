"""Dollar amounts from FHIR money elements. Floats are not used for the result."""

from decimal import Decimal

from membercare.errors import LabError

ADJUDICATION = "http://terminology.hl7.org/CodeSystem/adjudication"
CARIN_ADJUDICATION = "http://hl7.org/fhir/us/carin-bb/CodeSystem/C4BBAdjudication"

KNOWN_CODES = {
    (ADJUDICATION, "submitted"),
    (ADJUDICATION, "eligible"),
    (ADJUDICATION, "copay"),
    (ADJUDICATION, "deductible"),
    (ADJUDICATION, "benefit"),
    (CARIN_ADJUDICATION, "coinsurance"),
    (CARIN_ADJUDICATION, "noncovered"),
}

REQUIRED_CODES = ("submitted", "eligible", "benefit", "copay", "deductible", "coinsurance")
MEMBER_CODES = ("copay", "deductible", "coinsurance")


def cents_from_money(amount: dict) -> int:
    if amount.get("currency") != "USD":
        raise LabError("inconsistent", "money currency is not USD")
    dec = Decimal(str(amount["value"]))
    quantized = dec.quantize(Decimal("0.01"))
    if quantized != dec:
        raise LabError("inconsistent", "money has more than two decimal places")
    return int(quantized * 100)


def format_usd(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    whole, rem = divmod(abs(cents), 100)
    if rem == 0:
        return f"{sign}${whole}"
    return f"{sign}${whole}.{rem:02d}"


def _coding(row: dict) -> tuple[str, str]:
    try:
        coding = row["category"]["coding"][0]
        return coding["system"], coding["code"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LabError("inconsistent", "adjudication coding is missing") from exc


def amount_map(adjudications: list[dict]) -> dict[str, int]:
    found: dict[str, int] = {}
    for row in adjudications:
        system, code = _coding(row)
        if (system, code) not in KNOWN_CODES:
            raise LabError("inconsistent", f"unknown adjudication code {code}")
        found[code] = found.get(code, 0) + cents_from_money(row["amount"])
    return found


def member_owes_cents(amounts: dict[str, int]) -> int:
    return sum(amounts.get(code, 0) for code in MEMBER_CODES)


def require_identity(amounts: dict[str, int]) -> dict[str, int]:
    missing = [code for code in REQUIRED_CODES if code not in amounts]
    if missing:
        raise LabError("inconsistent", "adjudication is missing " + ", ".join(missing))
    noncovered = amounts.get("noncovered", 0)
    member = member_owes_cents(amounts)
    expected_eligible = amounts["benefit"] + member + noncovered
    if amounts["eligible"] != expected_eligible:
        raise LabError(
            "inconsistent",
            "eligible amount does not equal benefit plus member cost share",
        )
    amounts = dict(amounts)
    amounts["member_owes"] = member
    return amounts


def explanation_amounts(resource: dict) -> dict[str, int]:
    """Sum item adjudications, require EOB totals to match, then check the identity."""
    items = resource.get("item") or []
    if not items:
        raise LabError("inconsistent", "explanation of benefit has no items")
    combined: dict[str, int] = {}
    for item in items:
        for code, cents in amount_map(item.get("adjudication") or []).items():
            combined[code] = combined.get(code, 0) + cents
    totals = amount_map(resource.get("total") or [])
    codes = set(combined) | set(totals)
    for code in codes:
        if combined.get(code, 0) != totals.get(code, 0):
            raise LabError("inconsistent", f"item sum does not match total for {code}")
    return require_identity(combined)
