"""Entity-level scoring, shared by the baseline and (later) the model.

A predicted entity counts only if its start, end AND label all match a gold
entity. That is stricter than per-token accuracy, which gives partial credit
for getting most of "Dhaka Cantt." right.
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path

from thikana.schema import ENTITY_TYPES, Example, Span
from thikana.training.baseline import Baseline
from thikana.training.synth import DATASET_SEEDS, DATASET_SIZES, build_datasets

REPORTS = Path(__file__).resolve().parents[2] / "reports"


def _prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "support": tp + fn}


def score(gold: list[Example], predicted: list[list[Span]]) -> dict:
    tp, fp, fn = Counter(), Counter(), Counter()
    for example, pred in zip(gold, predicted, strict=True):
        want = {(s.start, s.end, s.label) for s in example.spans}
        got = {(s.start, s.end, s.label) for s in pred}
        for _, _, label in want & got:
            tp[label] += 1
        for _, _, label in got - want:
            fp[label] += 1
        for _, _, label in want - got:
            fn[label] += 1

    per_label = {label: _prf(tp[label], fp[label], fn[label]) for label in ENTITY_TYPES}
    scored = [m["f1"] for m in per_label.values() if m["support"]]
    return {
        "per_label": per_label,
        "micro": _prf(sum(tp.values()), sum(fp.values()), sum(fn.values())),
        "macro_f1": sum(scored) / len(scored) if scored else 0.0,
    }


def _counts(example: Example, pred: list[Span]) -> tuple[int, int, int]:
    want = {(s.start, s.end, s.label) for s in example.spans}
    got = {(s.start, s.end, s.label) for s in pred}
    tp = len(want & got)
    return tp, len(got) - tp, len(want) - tp


def _micro_f1(counts) -> float:
    tp = sum(c[0] for c in counts)
    fp = sum(c[1] for c in counts)
    fn = sum(c[2] for c in counts)
    return 2 * tp / (2 * tp + fp + fn) if tp else 0.0


def paired_bootstrap(gold, pred_a, pred_b, resamples: int = 1000, seed: int = 0) -> dict:
    """95% interval for micro-F1(b) - micro-F1(a), resampling whole ADDRESSES.

    Both systems are scored on the same resampled addresses (paired), so the
    interval reflects the difference itself, not the difficulty of the sample.
    If the interval contains 0, do not claim one system is better.
    """
    a = [_counts(g, p) for g, p in zip(gold, pred_a, strict=True)]
    b = [_counts(g, p) for g, p in zip(gold, pred_b, strict=True)]
    rng = random.Random(seed)
    n = len(gold)
    diffs = []
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        diffs.append(_micro_f1([b[i] for i in idx]) - _micro_f1([a[i] for i in idx]))
    diffs.sort()
    return {"mean": sum(diffs) / resamples, "low": diffs[int(0.025 * resamples)],
            "high": diffs[int(0.975 * resamples) - 1], "resamples": resamples}


def has_bangla(text: str) -> bool:
    return any("ঀ" <= c <= "৿" for c in text)


def format_report(title: str, scores: dict) -> str:
    lines = [title, f"{'label':10s} {'prec':>6s} {'recall':>6s} {'f1':>6s} {'n':>6s}"]
    for label, m in scores["per_label"].items():
        lines.append(f"{label:10s} {m['precision']:6.3f} {m['recall']:6.3f} "
                     f"{m['f1']:6.3f} {m['support']:6d}")
    micro = scores["micro"]
    lines.append(f"{'MICRO':10s} {micro['precision']:6.3f} {micro['recall']:6.3f} "
                 f"{micro['f1']:6.3f} {micro['support']:6d}")
    lines.append(f"macro F1 over labels with support: {scores['macro_f1']:.3f}")
    return "\n".join(lines)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    splits, data = build_datasets()
    baseline = Baseline(splits["train"])

    dev = data["dev"]  # the test split stays sealed until final reporting
    predicted = [baseline.predict(e.text) for e in dev]
    overall = score(dev, predicted)
    print(format_report("RULE BASELINE on SYNTHETIC dev (not real addresses)", overall))

    slices = {}
    for name, keep in (("latin-only", lambda t: not has_bangla(t)),
                       ("contains Bangla", has_bangla)):
        idx = [i for i, e in enumerate(dev) if keep(e.text)]
        slices[name] = score([dev[i] for i in idx], [predicted[i] for i in idx])
        print(f"\n{name}: {len(idx)} addresses, micro F1 {slices[name]['micro']['f1']:.3f}, "
              f"macro F1 {slices[name]['macro_f1']:.3f}")

    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / "baseline_synthetic_dev.json"
    out.write_text(json.dumps({
        "what": "rule baseline scored on SYNTHETIC dev data only; says nothing about real addresses",
        "dataset_sizes": DATASET_SIZES, "dataset_seeds": DATASET_SEEDS,
        "overall": overall, "slices": slices,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {out.relative_to(REPORTS.parent)}")


if __name__ == "__main__":
    main()
