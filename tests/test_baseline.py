import pytest

from thikana.schema import Example, Span
from thikana.training.baseline import Baseline
from thikana.training.evaluate import score
from thikana.training.synth import build_places, split_places


@pytest.fixture(scope="module")
def baseline():
    return Baseline(split_places(build_places())["train"])


def labelled(baseline, text):
    """{surface text: label} for everything the baseline finds."""
    return {text[s.start:s.end]: s.label for s in baseline.predict(text)}


def test_structured_fields_and_names_on_a_clean_address(baseline):
    got = labelled(baseline, "House 57, Road 36, Blk E, Mazara, Sylhet 3100")
    assert got == {"House 57": "HOUSE", "Road 36": "ROAD", "Blk E": "BLOCK",
                   "Mazara": "AREA", "Sylhet": "DISTRICT", "3100": "POSTCODE"}


def test_decision_d1_second_occurrence_of_a_shared_name_is_the_division(baseline):
    text = "Mazara, Dhaka, Dhaka"
    labels = [s.label for s in baseline.predict(text)]
    assert labels == ["AREA", "DISTRICT", "DIVISION"]


def test_a_lone_shared_name_is_a_district(baseline):
    assert labelled(baseline, "Mazara, Dhaka")["Dhaka"] == "DISTRICT"


def test_bangla_digits_are_handled_and_offsets_point_into_the_raw_text(baseline):
    text = "বাসা ১২, রোড ৫, Mazara"
    got = labelled(baseline, text)
    assert got["বাসা ১২"] == "HOUSE"
    assert got["রোড ৫"] == "ROAD"


def test_decision_d8_baseline_does_not_treat_a_dhaka_thana_as_an_upazila(baseline):
    assert "UPAZILA" not in baseline.names.get(("gulshan",), set())


def test_known_weakness_a_misspelled_district_is_mistaken_for_an_area(baseline):
    # Characterisation test: documents what the baseline gets WRONG, so a model
    # that fixes it is a measured improvement and not a claim.
    assert labelled(baseline, "Mazara, Dhakka 1212")["Dhakka"] == "AREA"


def test_perfect_predictions_score_one():
    gold = [Example("Dhaka 1212", (Span(0, 5, "DISTRICT"), Span(6, 10, "POSTCODE")))]
    result = score(gold, [list(gold[0].spans)])
    assert result["micro"]["f1"] == 1.0
    assert result["per_label"]["DISTRICT"]["f1"] == 1.0


def test_a_wrong_label_costs_both_precision_and_recall():
    gold = [Example("Dhaka", (Span(0, 5, "DISTRICT"),))]
    result = score(gold, [[Span(0, 5, "AREA")]])
    assert result["per_label"]["DISTRICT"]["recall"] == 0.0
    assert result["per_label"]["AREA"]["precision"] == 0.0


def test_scoring_is_strict_about_boundaries():
    gold = [Example("Dhaka Cantt.", (Span(0, 12, "AREA"),))]
    result = score(gold, [[Span(0, 11, "AREA")]])  # one character short
    assert result["micro"]["f1"] == 0.0
