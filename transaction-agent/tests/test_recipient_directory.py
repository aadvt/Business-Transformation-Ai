from transaction_agent import recipient_directory as rd


def test_register_and_exact_match(tmp_path):
    path = str(tmp_path / "recipients.sqlite")
    rid = rd.register("ABC Logistics Pvt Ltd", aliases=["ABC Logistics"], path=path)

    result = rd.resolve("ABC Logistics", path=path)
    assert result.status == "auto"
    assert result.recipient_id == rid


def test_ambiguous_close_candidates(tmp_path):
    path = str(tmp_path / "recipients.sqlite")
    rd.register("Ravi Transport Services", path=path)
    rd.register("Ravi Traders", path=path)

    result = rd.resolve("Ravi Trans", path=path)
    assert result.status == "ambiguous"
    assert len(result.candidates) == 2


def test_no_match_on_empty_directory(tmp_path):
    path = str(tmp_path / "recipients.sqlite")
    result = rd.resolve("Anyone At All", path=path)
    assert result.status == "none"
    assert result.candidates == []


def test_no_match_below_candidate_threshold(tmp_path):
    path = str(tmp_path / "recipients.sqlite")
    rd.register("Completely Unrelated Name", path=path)
    result = rd.resolve("Xyzzy Corp", path=path)
    assert result.status == "none"


def test_list_all_reflects_registrations(tmp_path):
    path = str(tmp_path / "recipients.sqlite")
    rd.register("A", path=path)
    rd.register("B", path=path)
    names = {row["name"] for row in rd.list_all(path=path)}
    assert names == {"A", "B"}
