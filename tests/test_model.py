import pytest

from thikana.model import AddressParser
from thikana.training.synth import build_places, generate, split_places
from thikana.training.train import build_vocab, train_model


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
