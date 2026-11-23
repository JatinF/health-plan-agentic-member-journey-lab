from membercare.errors import LabError
from membercare.explain import dollars_in_text, guard_text
from membercare.money import ADJUDICATION, explanation_amounts, format_usd, require_identity


def test_format_and_guard() -> None:
    assert format_usd(7500) == "$75"
    assert format_usd(1050) == "$10.50"
    assert dollars_in_text("copay is $75 plus $10") == [7500, 1000]
    guard_text("copay is $75", {7500})
    try:
        guard_text("you owe $999", {7500})
    except LabError as exc:
        assert exc.code == "inconsistent"
    else:
        raise AssertionError("invented amount was accepted")


def test_identity_rejects_a_gap() -> None:
    try:
        require_identity(
            {
                "submitted": 10000,
                "eligible": 10000,
                "benefit": 1000,
                "copay": 1000,
                "deductible": 0,
                "coinsurance": 0,
            }
        )
    except LabError as exc:
        assert "eligible" in exc.message
    else:
        raise AssertionError("unbalanced adjudication was accepted")


def test_eob_totals_must_match_items() -> None:
    resource = {
        "item": [
            {
                "adjudication": [
                    {"category": {"coding": [{"system": ADJUDICATION, "code": "submitted"}]}, "amount": {"value": 10, "currency": "USD"}},
                    {"category": {"coding": [{"system": ADJUDICATION, "code": "eligible"}]}, "amount": {"value": 10, "currency": "USD"}},
                    {"category": {"coding": [{"system": ADJUDICATION, "code": "benefit"}]}, "amount": {"value": 10, "currency": "USD"}},
                    {"category": {"coding": [{"system": ADJUDICATION, "code": "copay"}]}, "amount": {"value": 0, "currency": "USD"}},
                    {"category": {"coding": [{"system": ADJUDICATION, "code": "deductible"}]}, "amount": {"value": 0, "currency": "USD"}},
                    {
                        "category": {
                            "coding": [
                                {
                                    "system": "http://hl7.org/fhir/us/carin-bb/CodeSystem/C4BBAdjudication",
                                    "code": "coinsurance",
                                }
                            ]
                        },
                        "amount": {"value": 0, "currency": "USD"},
                    },
                ]
            }
        ],
        "total": [
            {"category": {"coding": [{"system": ADJUDICATION, "code": "submitted"}]}, "amount": {"value": 9, "currency": "USD"}},
            {"category": {"coding": [{"system": ADJUDICATION, "code": "eligible"}]}, "amount": {"value": 10, "currency": "USD"}},
            {"category": {"coding": [{"system": ADJUDICATION, "code": "benefit"}]}, "amount": {"value": 10, "currency": "USD"}},
            {"category": {"coding": [{"system": ADJUDICATION, "code": "copay"}]}, "amount": {"value": 0, "currency": "USD"}},
            {"category": {"coding": [{"system": ADJUDICATION, "code": "deductible"}]}, "amount": {"value": 0, "currency": "USD"}},
            {
                "category": {
                    "coding": [
                        {
                            "system": "http://hl7.org/fhir/us/carin-bb/CodeSystem/C4BBAdjudication",
                            "code": "coinsurance",
                        }
                    ]
                },
                "amount": {"value": 0, "currency": "USD"},
            },
        ],
    }
    try:
        explanation_amounts(resource)
    except LabError as exc:
        assert "submitted" in exc.message
    else:
        raise AssertionError("mismatched totals were accepted")
