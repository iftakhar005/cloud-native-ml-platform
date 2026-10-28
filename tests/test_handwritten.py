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


# ---- v4: scored once, in the deployment setting (full-data models) ---------

def test_v4_loads_audits_clean_and_has_all_three_groups():
    items, variants = load(path_for("v4"))
    assert len(items) >= 60
    assert audit(items, variants) == []
    assert {i.style[:2] for i in items} == {"T-", "R-", "F-"}
    assert {s.label for i in items for s in i.example.spans} == set(ENTITY_TYPES)


def test_v4_shares_no_address_with_any_spent_set():
    earlier = {i.example.text for v in ("v1", "v2", "v3") for i in load(path_for(v))[0]}
    v4 = {i.example.text for i in load(path_for("v4"))[0]}
    assert earlier.isdisjoint(v4)


def test_v4_novel_names_appear_in_no_gazetteer_file():
    # F-novel guards against "any leading name is an upazila"; it only works if
    # the names really are unknown to every reference file
    f = load_all()
    nfc = lambda s: unicodedata.normalize("NFC", s.strip()).lower()
    known = set()
    for frame, columns in ((f["districts"], ("name", "bn_name")), (f["divisions"], ("name", "bn_name")),
                           (f["upazilas"], ("name", "bn_name")), (f["postcodes"], ("upazila", "postOffice"))):
        for column in columns:
            known |= {nfc(x) for x in frame[column]}
    items, _ = load(path_for("v4"))
    novel = [nfc(i.example.text[s.start:s.end]) for i in items if i.style == "F-novel"
             for s in i.example.spans if s.label == "AREA"]
    assert len(novel) >= 7
    assert not [n for n in novel if n in known]


def test_v4_vocab_names_were_unseen_by_the_split_trained_models():
    # T-vocab only measures the full-data effect if the split models never saw these
    # names as upazilas
    from thikana.training.synth import build_places, split_places

    nfc = lambda s: unicodedata.normalize("NFC", s.strip()).lower()
    train = split_places(build_places())["train"]
    seen = {nfc(n) for p in train if p.upazila_admin for n in (p.upazila, p.upazila_bn) if n}
    items, _ = load(path_for("v4"))
    names = [nfc(i.example.text[s.start:s.end]) for i in items if i.style == "T-vocab"
             for s in i.example.spans if s.label == "UPAZILA"]
    assert len(names) >= 18
    assert not [n for n in names if n in seen]


def test_every_v4_gold_span_lands_on_token_boundaries():
    items, _ = load(path_for("v4"))
    for item in items:
        tokens = tokenize(normalize_digits(item.example.text))
        tags = to_bio(tokens, item.example.spans)
        assert bio_to_spans(tokens, tags) == list(item.example.spans), item.example.text


# ---- v5 (diagnostic) and v6 (fresh), for decision D12 ------------------------

def _known_names():
    f = load_all()
    nfc = lambda s: unicodedata.normalize("NFC", s.strip()).lower()
    known = set()
    for frame, columns in ((f["districts"], ("name", "bn_name")), (f["divisions"], ("name", "bn_name")),
                           (f["upazilas"], ("name", "bn_name")), (f["postcodes"], ("upazila", "postOffice"))):
        for column in columns:
            known |= {nfc(x) for x in frame[column]}
    return nfc, known


@pytest.mark.parametrize("version", ["v5", "v6", "v7"])
def test_village_sets_load_audit_clean_and_cover_targets_and_guards(version):
    items, variants = load(path_for(version))
    assert len(items) >= 35
    assert audit(items, variants) == []
    assert {i.style[:2] for i in items} == {"T-", "R-", "F-"}
    upazilas = [s for i in items if i.style.startswith("R-upazila") for s in i.example.spans
                if s.label == "UPAZILA"]
    assert len(upazilas) >= 6 or version == "v5"          # v6 guards real upazilas from being swallowed


def test_v6_and_v7_share_no_address_with_any_earlier_set_and_v5_only_repeats_its_regression_guards():
    earlier = {i.example.text for v in ("v1", "v2", "v3", "v4") for i in load(path_for(v))[0]}
    v5_items = load(path_for("v5"))[0]
    v5 = {i.example.text for i in v5_items}
    v6 = {i.example.text for i in load(path_for("v6"))[0]}
    v7 = {i.example.text for i in load(path_for("v7"))[0]}
    assert v6.isdisjoint(earlier | v5)                      # the fresh sets are fully fresh
    assert v7.isdisjoint(earlier | v5 | v6)
    # v5 was a diagnostic; a regression guard ("R-") may reuse a string that already existed
    assert all(i.style.startswith("R-") for i in v5_items if i.example.text in earlier)


@pytest.mark.parametrize("version", ["v5", "v6", "v7"])
def test_the_invented_village_names_are_in_no_gazetteer_file(version):
    nfc, known = _known_names()
    items, _ = load(path_for(version))
    novel = [nfc(i.example.text[s.start:s.end]) for i in items if i.style.startswith("T-")
             for s in i.example.spans if s.label == "AREA"]
    assert len(novel) >= 20
    assert not [n for n in novel if n in known]


@pytest.mark.parametrize("version", ["v6", "v7"])
def test_fresh_village_names_are_ones_the_generator_can_never_write(version):
    # v6 and v7 only measure generalisation if their names were not in the training data
    from thikana.training import synth

    nfc = lambda s: unicodedata.normalize("NFC", s.strip()).lower()
    composed = {nfc(stem + suffix) for stem in synth.BN_VILLAGE_STEMS for suffix in synth.BN_VILLAGE_SUFFIXES}
    composed |= {nfc(prefix + " " + name) for prefix in synth.BN_VILLAGE_PREFIXES for name in composed}
    items, _ = load(path_for(version))
    names = [nfc(i.example.text[s.start:s.end]) for i in items for s in i.example.spans if s.label == "AREA"]
    assert len(names) >= 30
    assert not [n for n in names if n in composed]


@pytest.mark.parametrize("version", ["v5", "v6", "v7"])
def test_every_village_set_gold_span_lands_on_token_boundaries(version):
    items, _ = load(path_for(version))
    for item in items:
        tokens = tokenize(normalize_digits(item.example.text))
        tags = to_bio(tokens, item.example.spans)
        assert bio_to_spans(tokens, tags) == list(item.example.spans), item.example.text
