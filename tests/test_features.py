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
