from agent.redact import redact_record, redact_text


def test_redact_text_masks_email_and_phone():
    text, count = redact_text("Call Sam at 312-555-0199 or sam@lakeshoretravel.example.com")
    assert "[PHONE]" in text and "[EMAIL]" in text
    assert "312-555-0199" not in text and "sam@lakeshoretravel.example.com" not in text
    assert count == 2


def test_redact_text_masks_first_names_but_not_words_that_look_like_names():
    text, count = redact_text("Emily at Emily Travel quoted this in April")
    assert text.count("[NAME]") == 2  # both "Emily"s are a first name
    assert "April" in text  # April is also a month, kept on the course's exclusion list
    assert count == 2


def test_redact_text_leaves_plain_text_alone():
    text, count = redact_text("Includes one checked bag")
    assert text == "Includes one checked bag"
    assert count == 0


def test_redact_record_only_touches_note_fields():
    record = {"carrier": "Lakeshore Air", "seller_note": "Ask for Emily at 312-555-0199"}
    out, count = redact_record(record)
    assert out["carrier"] == "Lakeshore Air"  # structured fields are untouched
    assert "[NAME]" in out["seller_note"] and "[PHONE]" in out["seller_note"]
    assert count == 2


def test_redact_record_handles_missing_or_empty_note():
    record = {"carrier": "Lakeshore Air", "seller_note": None}
    out, count = redact_record(record)
    assert out["seller_note"] is None
    assert count == 0
