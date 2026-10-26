"""Which name strings carry more than one label in the generated training data?

Some ambiguity is inherent (decision D1: "Dhaka" is a DISTRICT, then a
DIVISION). A model can use context to resolve some of it, but a string that
really is ambiguous sets a ceiling on achievable accuracy, so measure it.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict

from thikana.text import normalize_digits
from thikana.training.synth import build_datasets

NAME_LABELS = ("AREA", "UPAZILA", "DISTRICT", "DIVISION")


def label_sets(examples) -> dict[str, Counter]:
    seen: dict[str, Counter] = defaultdict(Counter)
    for example in examples:
        for span in example.spans:
            if span.label in NAME_LABELS:
                surface = normalize_digits(example.text[span.start:span.end]).lower()
                seen[surface][span.label] += 1
    return seen


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    _, data = build_datasets()
    seen = label_sets(data["train"])

    ambiguous = {s: c for s, c in seen.items() if len(c) > 1}
    mentions = sum(sum(c.values()) for c in seen.values())
    in_ambiguous = sum(sum(c.values()) for c in ambiguous.values())
    print(f"distinct name strings: {len(seen)}; carrying 2+ labels: {len(ambiguous)}")
    print(f"name mentions in ambiguous strings: {in_ambiguous} of {mentions} "
          f"({in_ambiguous / mentions:.1%})")

    # Best a pure lookup table can do: give every string its single most
    # frequent label. A model must use CONTEXT to exceed this.
    ceiling = sum(max(c.values()) for c in seen.values()) / mentions
    print(f"context-free ceiling (each string -> its most common label): {ceiling:.1%}")

    pairs = Counter(tuple(sorted(c)) for c in ambiguous.values())
    print("\nwhich label pairs collide (strings):")
    for pair, n in pairs.most_common():
        print(f"  {n:4d}  {' / '.join(pair)}")

    print("\nmost frequent ambiguous strings:")
    top = sorted(ambiguous.items(), key=lambda kv: -sum(kv[1].values()))[:10]
    for surface, counter in top:
        print(f"  {surface!r:22s} {dict(counter)}")


if __name__ == "__main__":
    main()
