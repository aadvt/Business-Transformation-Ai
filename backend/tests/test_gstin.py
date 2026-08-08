from app.services.gstin import generate_valid_gstin, validate_gstin


def test_generate_is_valid():
    g = generate_valid_gstin("27", 1)
    check = validate_gstin(g)
    assert check.valid
    assert check.structure_valid
    assert check.checksum_valid


def test_generate_is_deterministic():
    assert generate_valid_gstin("27", 42) == generate_valid_gstin("27", 42)


def test_generate_varies_by_seed():
    assert generate_valid_gstin("27", 1) != generate_valid_gstin("27", 2)


def test_generate_uses_given_state_code():
    g = generate_valid_gstin("33", 7)
    assert g.startswith("33")


def test_generate_rejects_bad_state_code():
    import pytest

    with pytest.raises(ValueError):
        generate_valid_gstin("MH", 1)


def test_validate_rejects_wrong_length():
    check = validate_gstin("27AABCS1429B1Z")
    assert not check.valid
    assert not check.structure_valid


def test_validate_rejects_lowercase_garbage():
    check = validate_gstin("not-a-gstin")
    assert not check.valid


def test_validate_detects_checksum_corruption():
    g = generate_valid_gstin("27", 5)
    corrupted = g[:-1] + ("A" if g[-1] != "A" else "B")
    check = validate_gstin(corrupted)
    assert check.structure_valid
    assert not check.checksum_valid
    assert not check.valid


def test_validate_detects_middle_corruption():
    g = generate_valid_gstin("27", 5)
    # flip one PAN digit — structure still matches, checksum should now fail
    digit_pos = 7
    corrupted_char = "1" if g[digit_pos] != "1" else "2"
    corrupted = g[:digit_pos] + corrupted_char + g[digit_pos + 1 :]
    check = validate_gstin(corrupted)
    assert check.structure_valid
    assert not check.checksum_valid


def test_validate_is_case_insensitive_input():
    g = generate_valid_gstin("27", 9)
    assert validate_gstin(g.lower()).valid
