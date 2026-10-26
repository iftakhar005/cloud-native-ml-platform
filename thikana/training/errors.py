"""Error analysis: for each gold entity a model got wrong, what did it do instead?

Run:  python -m thikana.training.errors [model_name]     (default crf_v2_plus_gazetteer)
Scores are never improved by staring at totals; read the examples.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict

from thikana.model import AddressParser
from thikana.training.synth import build_datasets
from thikana.training.train import MODELS, build_vocab


def classify(gold, predicted) -> str:
    exact = {(p.start, p.end, p.label) for p in predicted}
    if (gold.start, gold.end, gold.label) in exact:
        return ""
    same_range = [p for p in predicted if (p.start, p.end) == (gold.start, gold.end)]
    if same_range:
        return "labelled " + same_range[0].label
    overlap = [p for p in predicted if p.start < gold.end and gold.start < p.end]
    if overlap:
        return "boundary differs (" + "+".join(sorted({p.label for p in overlap})) + ")"
    return "missed entirely"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    name = sys.argv[1] if len(sys.argv) > 1 else "crf_v2_plus_gazetteer"
    splits, data = build_datasets()
    vocab = build_vocab(splits["train"]) if "gazetteer" in name else None
    parser = AddressParser(MODELS / f"{name}.crfsuite", vocab)

    outcomes: dict[str, Counter] = defaultdict(Counter)
    samples: dict[tuple[str, str], list] = defaultdict(list)
    total = 0
    for example in data["dev"]:
        predicted = parser.predict(example.text)
        for gold in example.spans:
            total += 1
            outcome = classify(gold, predicted)
            if outcome:
                outcomes[gold.label][outcome] += 1
                if len(samples[(gold.label, outcome)]) < 2:
                    samples[(gold.label, outcome)].append(
                        (example.text[gold.start:gold.end], example.text))

    errors = sum(sum(c.values()) for c in outcomes.values())
    print(f"{name}: {errors} of {total} gold entities not exactly right ({errors / total:.1%})")
    for label, counter in sorted(outcomes.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"\n{label}: {sum(counter.values())} errors")
        for outcome, n in counter.most_common(3):
            gold_text, text = samples[(label, outcome)][0]
            print(f"  {n:3d}  {outcome:34s} gold {gold_text!r} in {text!r}")


if __name__ == "__main__":
    main()
