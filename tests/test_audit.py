from transaction_agent import audit


def test_append_entries_writes_new_entries(tmp_path):
    path = str(tmp_path / "audit.json")
    entries = [
        {"entry_id": "a", "transaction_id": "t1", "from_status": None, "to_status": "Created"},
        {"entry_id": "b", "transaction_id": "t1", "from_status": "Created", "to_status": "PendingApproval"},
    ]
    written = audit.append_entries(entries, path=path)
    assert written == entries
    assert audit.read_all(path) == entries


def test_append_entries_dedupes_by_entry_id(tmp_path):
    path = str(tmp_path / "audit.json")
    entry = {"entry_id": "a", "transaction_id": "t1", "from_status": None, "to_status": "Created"}

    audit.append_entries([entry], path=path)
    written_again = audit.append_entries([entry], path=path)

    assert written_again == []
    assert audit.read_all(path) == [entry]


def test_append_entries_mixed_new_and_duplicate(tmp_path):
    path = str(tmp_path / "audit.json")
    entry_a = {"entry_id": "a", "transaction_id": "t1", "from_status": None, "to_status": "Created"}
    entry_b = {"entry_id": "b", "transaction_id": "t1", "from_status": "Created", "to_status": "PendingApproval"}

    audit.append_entries([entry_a], path=path)
    written = audit.append_entries([entry_a, entry_b], path=path)

    assert written == [entry_b]
    assert audit.read_all(path) == [entry_a, entry_b]


def test_append_entries_empty_list_is_noop(tmp_path):
    path = str(tmp_path / "audit.json")
    assert audit.append_entries([], path=path) == []
    assert audit.read_all(path) == []
