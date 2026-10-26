"""The CI quality gate must be able to fail, or it proves nothing."""

import pytest

from thikana.model import AddressParser
from thikana.training.gate import FLOORS, check
from thikana.training.handwritten import load, path_for
from thikana.training.train import MODELS
from thikana.training.train_all import PRODUCTION_MODEL

MODEL = MODELS / f"{PRODUCTION_MODEL}.crfsuite"


def test_a_model_that_finds_nothing_fails_every_set():
    _, failures = check(lambda text: [])
    assert len(failures) == len(FLOORS)


def test_a_model_that_returns_the_gold_labels_passes_every_set():
    gold = {i.example.text: i.example.spans for v in FLOORS for i in load(path_for(v))[0]}
    _, failures = check(lambda text: gold[text])
    assert failures == []


def test_one_regressed_set_is_reported_by_name():
    gold = {i.example.text: i.example.spans for v in FLOORS for i in load(path_for(v))[0]}
    v4_texts = {i.example.text for i in load(path_for("v4"))[0]}
    _, failures = check(lambda text: [] if text in v4_texts else gold[text])
    assert len(failures) == 1 and failures[0].startswith("v4:")


@pytest.mark.skipif(not MODEL.exists(), reason="run python -m thikana.training.train_all first")
def test_the_production_model_on_disk_passes_the_gate():
    lines, failures = check(AddressParser.load(MODEL).predict)
    assert failures == [], "\n".join(lines)
