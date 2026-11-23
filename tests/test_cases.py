from membercare.cases import CaseStore
from membercare.catalog import load_catalog
from membercare.errors import LabError


def test_open_is_refused_until_a_reviewer_approves(tmp_path) -> None:
    catalog = load_catalog()
    member = catalog.require_actor("demo-member")
    reviewer = catalog.require_actor("demo-reviewer")
    store = CaseStore(tmp_path / "cases.db")
    case = store.request(member, "DEMO-1048", "Member requested a billing review", "thread-1")
    try:
        store.open_case(reviewer, case["id"])
        raise AssertionError("case opened before approval")
    except LabError as exc:
        assert exc.code == "approval_required"
    try:
        store.approve(member, case["id"])
        raise AssertionError("member approved the case")
    except LabError as exc:
        assert exc.code == "permission_denied"
    approved = store.approve(reviewer, case["id"])
    assert approved["status"] == "approved"
    opened = store.open_case(reviewer, case["id"])
    assert opened["status"] == "open"
    store.close()
