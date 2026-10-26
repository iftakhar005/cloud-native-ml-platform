import re
from collections import Counter

import pytest

from thikana.schema import ENTITY_TYPES
from thikana.text import bio_to_spans, normalize_digits, tokenize, to_bio
from thikana.training.synth import build_places, generate, split_places


@pytest.fixture(scope="module")
def places():
    return build_places()


@pytest.fixture(scope="module")
def splits(places):
    return split_places(places)


def test_every_postcode_record_becomes_a_place(places):
    assert len(places) == 1349
    assert all(p.area and p.district and p.division for p in places)


def test_splits_are_disjoint_and_cover_every_record(splits):
    codes = {name: {p.postcode for p in records} for name, records in splits.items()}
    assert codes["train"].isdisjoint(codes["dev"])
    assert codes["train"].isdisjoint(codes["test"])
    assert codes["dev"].isdisjoint(codes["test"])
    assert sum(len(c) for c in codes.values()) == 1349


def test_generation_is_deterministic_per_seed(splits):
    a = generate(splits["train"], 200, seed=5)
    assert a == generate(splits["train"], 200, seed=5)
    assert a != generate(splits["train"], 200, seed=6)


def test_every_span_lands_on_token_boundaries(splits):
    # to_bio raises if a span cuts a token in half; the round trip proves the
    # spans and the tokenizer agree about where entities start and end.
    for example in generate(splits["train"], 1500, seed=1):
        tokens = tokenize(normalize_digits(example.text))
        tags = to_bio(tokens, example.spans)
        assert bio_to_spans(tokens, tags) == list(example.spans), example.text


def test_all_nine_labels_occur(splits):
    seen = Counter(s.label for e in generate(splits["train"], 3000, seed=1) for s in e.spans)
    assert set(seen) == set(ENTITY_TYPES)


def test_some_addresses_have_no_area(splits):
    # regression: the first version always included an AREA, so the model would
    # never see "House 5, Road 3, Dhaka"
    examples = generate(splits["train"], 3000, seed=1)
    assert any(not e.surface("AREA") for e in examples)
    assert all(e.spans for e in examples)  # but never an empty address


def test_postcode_spans_are_four_digits_once_normalised(splits):
    for example in generate(splits["train"], 1000, seed=2):
        for surface in example.surface("POSTCODE"):
            assert re.fullmatch(r"\d{4}", normalize_digits(surface)), example.text


def test_excluded_strings_never_reappear(splits):
    train = generate(splits["train"], 1000, seed=1)
    train_texts = {e.text for e in train}
    test = generate(splits["test"], 400, seed=3, exclude=train_texts)
    assert train_texts.isdisjoint(e.text for e in test)
    assert len({e.text for e in test}) == len(test)  # unique within the split too
