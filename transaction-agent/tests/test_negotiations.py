from transaction_agent import negotiations


def test_record_accepted_outcome(tmp_path):
    path = str(tmp_path / "negotiations.sqlite")
    entry_id = negotiations.record_outcome(
        "call_1",
        "ABC Traders",
        "accepted",
        contact_person="Suresh Kumar",
        agreed_amount=4500.0,
        purpose="raw materials",
        path=path,
    )
    assert entry_id.startswith("neg_")

    rows = negotiations.list_outcomes(path=path)
    assert len(rows) == 1
    assert rows[0]["outcome"] == "accepted"
    assert rows[0]["agreed_amount"] == 4500.0
    assert rows[0]["vendor_name"] == "ABC Traders"
    assert rows[0]["contact_person"] == "Suresh Kumar"


def test_contact_person_defaults_to_none(tmp_path):
    path = str(tmp_path / "negotiations.sqlite")
    negotiations.record_outcome("call_1b", "ABC Traders", "declined", path=path)
    rows = negotiations.list_outcomes(path=path)
    assert rows[0]["contact_person"] is None


def test_record_declined_outcome_has_no_amount(tmp_path):
    path = str(tmp_path / "negotiations.sqlite")
    negotiations.record_outcome("call_2", "XYZ Corp", "declined", notes="price too high", path=path)

    rows = negotiations.list_outcomes(path=path)
    assert rows[0]["outcome"] == "declined"
    assert rows[0]["agreed_amount"] is None
    assert rows[0]["notes"] == "price too high"


def test_invalid_outcome_rejected(tmp_path):
    path = str(tmp_path / "negotiations.sqlite")
    try:
        negotiations.record_outcome("call_3", "Someone", "maybe", path=path)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_multiple_outcomes_ordered_by_time(tmp_path):
    path = str(tmp_path / "negotiations.sqlite")
    negotiations.record_outcome("call_a", "A", "accepted", agreed_amount=100, path=path)
    negotiations.record_outcome("call_b", "B", "declined", path=path)
    rows = negotiations.list_outcomes(path=path)
    assert [r["call_sid"] for r in rows] == ["call_a", "call_b"]
