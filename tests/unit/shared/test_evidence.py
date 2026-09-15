from atlaz.shared.evidence import Evidence


def test_evidence_gap_has_no_locators():
    ev = Evidence.gap()
    assert ev.is_gap
    assert ev.note == "none - flagged gap"


def test_evidence_with_location_is_not_a_gap():
    ev = Evidence(file="a.py", line=10, commit="abc123")
    assert not ev.is_gap
    assert ev.to_dict() == {"file": "a.py", "line": 10, "commit": "abc123", "note": ""}
