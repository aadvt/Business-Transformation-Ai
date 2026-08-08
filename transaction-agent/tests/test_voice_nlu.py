from voice import nlu


def test_parse_selection_words_and_ordinals():
    assert nlu.parse_selection("one and three", 3) == [1, 3]
    assert nlu.parse_selection("the first and second one", 3) == [1, 2]
    assert nlu.parse_selection("1, 2 and 3", 3) == [1, 2, 3]


def test_parse_selection_all_and_none():
    assert nlu.parse_selection("all", 3) == [1, 2, 3]
    assert nlu.parse_selection("all of them", 3) == [1, 2, 3]
    assert nlu.parse_selection("none", 3) == []
    assert nlu.parse_selection("nothing", 3) == []


def test_parse_selection_drops_out_of_range_numbers():
    assert nlu.parse_selection("five", 3) == []
    assert nlu.parse_selection("two and five", 3) == [2]


def test_parse_dtmf_selection():
    assert nlu.parse_dtmf_selection("1*3#", 3) == [1, 3]
    assert nlu.parse_dtmf_selection("2#", 3) == [2]
    assert nlu.parse_dtmf_selection("9#", 3) == [1, 2, 3]  # shortcut: all
    assert nlu.parse_dtmf_selection("0#", 3) == []  # shortcut: none
    assert nlu.parse_dtmf_selection("5#", 3) == []  # out of range, dropped


def test_is_affirmative_and_negative():
    assert nlu.is_affirmative("confirm")
    assert nlu.is_affirmative("yes please go ahead")
    assert nlu.is_affirmative("1")
    assert not nlu.is_affirmative("cancel")
    assert not nlu.is_affirmative("maybe")

    assert nlu.is_negative("cancel")
    assert nlu.is_negative("no, wait")
    assert not nlu.is_negative("confirm")


def test_amount_to_words_basic_cases():
    assert nlu.amount_to_words(12000, "INR") == "twelve thousand rupees"
    assert nlu.amount_to_words(8500, "INR") == "eight thousand five hundred rupees"
    assert nlu.amount_to_words(0, "INR") == "zero rupees"
    assert nlu.amount_to_words(105, "INR") == "one hundred and five rupees"


def test_amount_to_words_includes_paise_when_fractional():
    text = nlu.amount_to_words(100.50, "INR")
    assert "fifty paise" in text


def test_format_review_for_voice_lists_each_transaction_and_total():
    transactions = [
        {"recipient": "ABC Logistics", "amount": 12000.0, "currency": "INR", "purpose": None},
        {"recipient": "Ravi Transport", "amount": 8500.0, "currency": "INR", "purpose": "logistics"},
    ]
    text = nlu.format_review_for_voice(transactions)
    assert "First" in text and "Second" in text
    assert "ABC Logistics" in text and "Ravi Transport" in text
    assert "twenty thousand five hundred rupees" in text
    assert "2 payments" in text


def test_format_review_for_voice_singular_wording_for_one_transaction():
    transactions = [{"recipient": "A", "amount": 100.0, "currency": "INR", "purpose": None}]
    text = nlu.format_review_for_voice(transactions)
    assert "1 payment " in text or text.count("payment") >= 1
    assert "1 payments" not in text


def test_format_review_for_voice_handles_empty():
    text = nlu.format_review_for_voice([])
    assert "again" in text.lower()


def test_format_selection_confirmation_names_each_pick_and_total():
    selected = [{"recipient": "A", "amount": 100.0, "currency": "INR"}, {"recipient": "B", "amount": 200.0, "currency": "INR"}]
    text = nlu.format_selection_confirmation(selected, 300.0, "INR")
    assert "A" in text and "B" in text
    assert "three hundred rupees" in text
    assert "confirm" in text.lower()


def test_format_selection_confirmation_empty_selection_still_requires_confirm_word():
    text = nlu.format_selection_confirmation([], 0.0, "INR")
    assert "confirm" in text.lower()
