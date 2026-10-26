import pytest

from thikana.features import sentence_features, shape
from thikana.text import tokenize


def test_shape_collapses_character_classes():
    assert shape("Dhaka") == "Xx"
    assert shape("1229") == "d"
    assert shape("ঢাকা") == "b"
    assert shape("H#12") == "X#d"


def test_one_feature_dict_per_token():
    tokens = tokenize("House 12, Dhaka")
    assert len(sentence_features(tokens)) == len(tokens)


def test_second_occurrence_is_marked_seen_before_for_decision_d1():
    features = sentence_features(tokenize("Dhaka, Dhaka"))  # Dhaka , Dhaka
    assert "seen_before" not in features[0]
    assert features[2]["seen_before"] == 1.0


def test_context_and_position_features():
    features = sentence_features(tokenize("Road 5, Dhaka"))  # Road 5 , Dhaka
    assert features[1]["w-1"] == "road"
    assert features[0]["bos"] == 1.0 and features[-1]["eos"] == 1.0
    assert features[0]["sep_after"] == 1
    assert features[-1]["sep_before"] == 1


def test_gazetteer_features_are_off_unless_a_vocab_is_given():
    tokens = tokenize("Dhaka")
    assert not any(k.startswith("gaz_") for k in sentence_features(tokens)[0])
    vocab = {"district": frozenset({"dhaka"})}
    assert sentence_features(tokens, vocab)[0]["gaz_district"] == 1.0


def test_features_are_deterministic():
    tokens = tokenize("বাসা 12, রোড 5, Mirpur, Dhaka 1216")
    assert sentence_features(tokens) == sentence_features(tokens)


def test_both_bangla_keyboard_forms_give_identical_features():
    precomposed = "\u0995\u09be\u0989\u09a8\u09bf\u09df\u09be"
    decomposed = "\u0995\u09be\u0989\u09a8\u09bf\u09af\u09bc\u09be"
    a = sentence_features(tokenize(f"{precomposed}, Dhaka"))
    b = sentence_features(tokenize(f"{decomposed}, Dhaka"))
    assert a == b


VOCAB = {"district": frozenset({"dhaka", "bagerhat", "khulna"})}


def test_district_memory_features_see_a_district_earlier_or_later():
    tokens = tokenize("Rayenda, Bagerhat, Khulna")  # Rayenda , Bagerhat , Khulna
    f = sentence_features(tokens, VOCAB, memory=True)
    assert f[0]["district_before"] == 0 and f[0]["district_after"] == 2
    assert f[2]["district_before"] == 0 and f[2]["district_after"] == 1
    assert f[4]["district_before"] == 1 and f[4]["district_after"] == 0  # Khulna: a district came first
    assert f[3].get("district_prev") == 1.0  # the "," follows Bagerhat
    assert f[2].get("district_next") is None  # but Bagerhat is followed by ","


def test_a_lone_district_has_no_district_memory():
    f = sentence_features(tokenize("House 5, Mirpur, Dhaka"), VOCAB, memory=True)
    assert f[-1]["district_before"] == 0 and f[-1]["district_after"] == 0


def test_memory_features_are_off_by_default_and_need_a_vocab():
    assert "district_before" not in sentence_features(tokenize("Dhaka"), VOCAB)[0]
    with pytest.raises(ValueError, match="vocab"):
        sentence_features(tokenize("Dhaka"), None, memory=True)
