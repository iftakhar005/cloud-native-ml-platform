import pytest

from thikana.schema import ENTITY_TYPES
from thikana.text import bio_to_spans, normalize_digits, tokenize, to_bio
import unicodedata

from thikana.training.gazetteer import load_all
from thikana.training.handwritten import Item, audit, load, parse_markup, path_for


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


def test_a_literal_backslash_n_becomes_a_real_line_break():
    example = parse_markup(r"{HOUSE|House 8}\n{ROAD|Road 2}\n{AREA|Banani}")
    assert example.text == "House 8\nRoad 2\nBanani"
    assert example.surface("ROAD") == ["Road 2"]
    tokens = tokenize(example.text)
    assert [t.text for t in tokens] == ["House", "8", "Road", "2", "Banani"]


# ---- v2: written after the generator was widened, scored once -------------

def test_v2_loads_audits_clean_and_is_tagged_targeted_or_fresh():
    items, variants = load(path_for("v2"))
    assert len(items) >= 70
    assert audit(items, variants) == []
    assert {i.style[:2] for i in items} == {"T-", "F-"}
    assert {s.label for i in items for s in i.example.spans} == set(ENTITY_TYPES)


def test_v2_shares_no_address_with_the_spent_v1_set():
    v1 = {i.example.text for i in load()[0]}
    v2 = {i.example.text for i in load(path_for("v2"))[0]}
    assert v1.isdisjoint(v2)


def test_v2_unicode_items_use_nfc_while_the_gazetteer_does_not():
    items, _ = load(path_for("v2"))
    unicode_items = [i for i in items if i.style == "F-unicode"]
    assert len(unicode_items) == 3
    for item in unicode_items:
        assert unicodedata.normalize("NFC", item.example.text) == item.example.text
    # the whole problem: the gazetteer stores the precomposed, non-NFC form
    names = [n.strip() for n in load_all()["upazilas"]["bn_name"]]
    assert sum(unicodedata.normalize("NFC", n) != n for n in names) > 100


def test_every_v2_gold_span_lands_on_token_boundaries():
    items, _ = load(path_for("v2"))
    for item in items:
        tokens = tokenize(normalize_digits(item.example.text))
        tags = to_bio(tokens, item.example.spans)
        assert bio_to_spans(tokens, tags) == list(item.example.spans), item.example.text


# ---- v3: written after the three fixes and the final retrain, scored once -----

def test_v3_loads_audits_clean_and_has_all_three_groups():
    items, variants = load(path_for("v3"))
    assert len(items) >= 65
    assert audit(items, variants) == []
    assert {i.style[:2] for i in items} == {"T-", "R-", "F-"}
    assert {s.label for i in items for s in i.example.spans} == set(ENTITY_TYPES)


def test_v3_shares_no_address_with_the_spent_v1_and_v2_sets():
    earlier = {i.example.text for v in ("v1", "v2") for i in load(path_for(v))[0]}
    v3 = {i.example.text for i in load(path_for("v3"))[0]}
    assert earlier.isdisjoint(v3)


def test_v3_unicode_items_really_exercise_the_nfc_fix():
    items, _ = load(path_for("v3"))
    unicode_items = [i for i in items if i.style == "T-unicode"]
    assert len(unicode_items) == 8
    for item in unicode_items:
        assert unicodedata.normalize("NFC", item.example.text) == item.example.text
        # য় ড় ঢ় are two codepoints in NFC: at least one such name per item
        assert any(pair in item.example.text for pair in
                   ("\u09af\u09bc", "\u09a1\u09bc", "\u09a2\u09bc")), item.example.text


def test_v3_upazila_first_items_really_start_with_an_upazila():
    items, _ = load(path_for("v3"))
    firsts = [i.example.spans[0].label for i in items if i.style == "T-upazila"]
    assert sum(label == "UPAZILA" for label in firsts) >= 9


def test_every_v3_gold_span_lands_on_token_boundaries():
    items, _ = load(path_for("v3"))
    for item in items:
        tokens = tokenize(normalize_digits(item.example.text))
        tags = to_bio(tokens, item.example.spans)
        assert bio_to_spans(tokens, tags) == list(item.example.spans), item.example.text
