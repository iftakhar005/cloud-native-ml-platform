import pytest

from thikana.schema import ENTITY_TYPES
from thikana.text import bio_to_spans, normalize_digits, tokenize, to_bio
from thikana.training.handwritten import Item, audit, load, parse_markup


def test_markup_becomes_plain_text_and_character_spans():
    example = parse_markup("{HOUSE|House 12}, {AREA|Mirpur-10}")
    assert example.text == "House 12, Mirpur-10"
    assert example.surface("HOUSE") == ["House 12"]
    assert example.surface("AREA") == ["Mirpur-10"]


def test_stray_or_unknown_markup_is_rejected():
    with pytest.raises(ValueError):
        parse_markup("{HOUSE|House 12, Dhaka")  # unclosed brace
    with pytest.raises(ValueError, match="unknown label"):
        parse_markup("{CITY|Dhaka}")  # CITY was dropped in decision D1


def test_the_set_loads_and_covers_every_label():
    items, _ = load()
    assert len(items) >= 60
    assert {s.label for i in items for s in i.example.spans} == set(ENTITY_TYPES)


def test_gold_labels_pass_the_audit():
    items, variants = load()
    assert audit(items, variants) == []


def test_the_audit_can_actually_fail():
    bad = [
        Item(1, "x", parse_markup("{UPAZILA|Gulshan}, {DISTRICT|Dhaka}-{POSTCODE|121}")),
        Item(2, "x", parse_markup("{DIVISION|Dhaka}, {AREA|Mirpur}")),
    ]
    problems = audit(bad, set())
    assert any("gulshan" in p for p in problems)   # a thana, not an administrative upazila (D8)
    assert any("not 4 digits" in p for p in problems)
    assert any("D1" in p for p in problems)        # a division with no district


def test_every_gold_span_lands_on_token_boundaries():
    items, _ = load()
    for item in items:
        tokens = tokenize(normalize_digits(item.example.text))
        tags = to_bio(tokens, item.example.spans)  # raises if a span cuts a token
        assert bio_to_spans(tokens, tags) == list(item.example.spans), item.example.text


def test_declared_variants_are_the_only_non_gazetteer_names():
    items, variants = load()
    assert variants == {"dhakka", "dacca", "chittagong", "comilla"}
    used = {normalize_digits(i.example.text[s.start:s.end]).lower()
            for i in items for s in i.example.spans if s.label == "DISTRICT"}
    assert variants <= used  # a declared variant that is never used is a stale declaration
