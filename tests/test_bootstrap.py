from thikana.schema import Example, Span
from thikana.training.evaluate import paired_bootstrap


def examples(n):
    return [Example("Dhaka 1212", (Span(0, 5, "DISTRICT"), Span(6, 10, "POSTCODE")))
            for _ in range(n)]


def test_identical_systems_have_zero_difference_and_zero_width_interval():
    gold = examples(50)
    pred = [list(e.spans) for e in gold]
    ci = paired_bootstrap(gold, pred, pred, resamples=200)
    assert ci["mean"] == ci["low"] == ci["high"] == 0


def test_a_clearly_better_system_has_an_interval_entirely_above_zero():
    gold = examples(100)
    good = [list(e.spans) for e in gold]
    ci = paired_bootstrap(gold, [[] for _ in gold], good, resamples=200)
    assert ci["low"] > 0


def test_systems_that_differ_only_by_noise_straddle_zero():
    gold = examples(100)
    right = [list(e.spans) for e in gold]
    # A is wrong on even addresses, B on odd ones: equally good overall.
    a = [[] if i % 2 == 0 else right[i] for i in range(100)]
    b = [[] if i % 2 == 1 else right[i] for i in range(100)]
    ci = paired_bootstrap(gold, a, b, resamples=500)
    assert ci["low"] < 0 < ci["high"]
