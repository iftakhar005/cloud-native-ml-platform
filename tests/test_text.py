import pytest

from thikana.schema import Example, Span
from thikana.text import bio_to_spans, normalize_digits, tokenize, to_bio


def span_of(text, piece, label):
    start = text.index(piece)
    return Span(start, start + len(piece), label)


def test_bangla_word_with_vowel_signs_stays_one_token():
    # regression: Python's \w alone splits this into ['ঢ', 'া', 'ক', 'া']
    assert [t.text for t in tokenize("ঢাকা 1229")] == ["ঢাকা", "1229"]


def test_digit_normalisation_keeps_length_and_maps_values():
    assert normalize_digits("বাসা ১২, রোড ৫") == "বাসা 12, রোড 5"
    assert len(normalize_digits("১২৩")) == 3


def test_token_offsets_point_back_into_the_original_text():
    text = "H#12/5, রোড-৩, Block C"
    for t in tokenize(text):
        assert text[t.start:t.end] == t.text


def test_bio_tags_for_a_mixed_address():
    text = "H#12/5, Road 3, Mirpur"
    spans = [span_of(text, "H#12/5", "HOUSE"), span_of(text, "Road 3", "ROAD"),
             span_of(text, "Mirpur", "AREA")]
    tags = to_bio(tokenize(text), spans)
    assert tags == ["B-HOUSE", "I-HOUSE", "I-HOUSE", "I-HOUSE", "I-HOUSE", "O",
                    "B-ROAD", "I-ROAD", "O", "B-AREA"]


def test_spans_survive_a_round_trip_through_bio():
    text = "বাসা 12, রোড 5, বসুন্ধরা, ঢাকা 1229"
    spans = [span_of(text, "বাসা 12", "HOUSE"), span_of(text, "রোড 5", "ROAD"),
             span_of(text, "বসুন্ধরা", "AREA"), span_of(text, "ঢাকা", "DISTRICT"),
             span_of(text, "1229", "POSTCODE")]
    tokens = tokenize(text)
    assert bio_to_spans(tokens, to_bio(tokens, spans)) == spans


def test_decision_d9_a_numbered_area_is_one_span_including_hyphen_and_number():
    text = "Mirpur-10, Dhaka-1216"
    spans = [span_of(text, "Mirpur-10", "AREA"), span_of(text, "Dhaka", "DISTRICT"),
             span_of(text, "1216", "POSTCODE")]
    # Mirpur - 10 , Dhaka - 1216: the hyphen inside the area is part of it,
    # the hyphen before the postcode is not.
    assert to_bio(tokenize(text), spans) == [
        "B-AREA", "I-AREA", "I-AREA", "O", "B-DISTRICT", "O", "B-POSTCODE"]


def test_a_token_straddling_a_span_boundary_is_an_error():
    text = "Block C12"
    with pytest.raises(ValueError, match="straddles"):
        to_bio(tokenize(text), [Span(0, 7, "BLOCK")])  # cuts "C12" in half


def test_overlapping_spans_are_rejected_at_construction():
    with pytest.raises(ValueError, match="overlapping"):
        Example("Dhaka 1229", (Span(0, 5, "DISTRICT"), Span(3, 8, "AREA")))


def test_unknown_label_is_rejected():
    with pytest.raises(ValueError, match="unknown label"):
        Span(0, 3, "CITY")  # CITY was dropped in decision D1
