import json

import pytest

from thikana.model import AddressParser
from thikana.training.synth import build_places, generate, split_places
from thikana.training.train import build_vocab, build_vocab_full, train_model


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    train_places = split_places(build_places())["train"]
    path = tmp_path_factory.mktemp("model") / "tiny.crfsuite"
    train_model(generate(train_places, 400, seed=1), path)
    return path


def test_a_trained_model_finds_an_obvious_postcode(trained):
    text = "Mazara, Dhaka 1212"
    spans = AddressParser(trained).predict(text)
    assert any(s.label == "POSTCODE" and text[s.start:s.end] == "1212" for s in spans)


def test_empty_input_returns_no_spans(trained):
    parser = AddressParser(trained)
    assert parser.predict("") == []
    assert parser.predict("   ") == []


def test_loading_the_same_file_twice_gives_identical_predictions(trained):
    text = "House 5, Road 3, Mirpur, Dhaka 1216"
    assert AddressParser(trained).predict(text) == AddressParser(trained).predict(text)


def test_spans_index_into_the_original_text_even_with_bangla_digits(trained):
    text = "Mazara, Dhaka ১২১২"
    for span in AddressParser(trained).predict(text):
        assert 0 <= span.start < span.end <= len(text)


def test_vocab_follows_decision_d8():
    vocab = build_vocab(split_places(build_places())["train"])
    assert "dhaka" in vocab["district"] and "dhaka" in vocab["division"]
    assert "gulshan" not in vocab["upazila"]  # a thana, not an administrative upazila


def test_a_model_gives_identical_spans_for_both_bangla_keyboard_forms(trained):
    precomposed = "\u0995\u09be\u0989\u09a8\u09bf\u09df\u09be"
    decomposed = "\u0995\u09be\u0989\u09a8\u09bf\u09af\u09bc\u09be"
    parser = AddressParser(trained)

    def shape_of(text):  # spans, but compared by label and token count, not by offset
        return [(s.label, len(text[s.start:s.end].split())) for s in parser.predict(text)]

    a, b = f"House 5, {precomposed}, Dhaka 1209", f"House 5, {decomposed}, Dhaka 1209"
    assert shape_of(a) == shape_of(b)
    # character offsets differ (the two forms differ in length) but each is valid
    for text in (a, b):
        for span in parser.predict(text):
            assert 0 <= span.start < span.end <= len(text)


def test_load_reads_the_vocab_and_flags_saved_beside_the_model(tmp_path):
    places = split_places(build_places())["train"]
    vocab = {"district": build_vocab(places)["district"]}
    path = tmp_path / "memory.crfsuite"
    train_model(generate(places, 200, seed=2), path, vocab, memory=True)

    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["memory"] is True and "dhaka" in meta["vocab"]["district"]

    parser = AddressParser.load(path)
    assert parser.memory is True and "dhaka" in parser.vocab["district"]
    assert parser.predict("Mazara, Dhaka 1212")  # works end to end


def test_load_without_a_meta_file_means_no_vocab_and_no_memory(trained):
    parser = AddressParser.load(trained)
    assert parser.vocab is None and parser.memory is False


def test_the_full_table_vocabulary_covers_every_district_and_upazila_name():
    from thikana.training.gazetteer import load_all
    from thikana.text import normalize_token as nt, tokenize

    f = load_all()
    vocab = build_vocab_full(f)
    for column in (f["districts"]["name"], f["districts"]["bn_name"]):
        for name in column:
            for t in tokenize(name.strip()):
                assert nt(t.text).lower() in vocab["district"]
    for name in list(f["upazilas"]["name"]) + list(f["upazilas"]["bn_name"]):
        for t in tokenize(name.strip()):
            assert nt(t.text).lower() in vocab["upazila"]
    assert "dhaka" in vocab["district"] and "dhaka" in vocab["division"]


def test_full_table_district_vocab_matches_the_record_built_one():
    # every district has a postcode record, so only the UPAZILA vocabulary differs
    from thikana.training.synth import build_all_places

    assert build_vocab_full()["district"] == build_vocab(build_all_places())["district"]
    assert len(build_vocab_full()["upazila"]) > len(build_vocab(split_places(build_places())["train"])["upazila"])
