"""Which name strings carry more than one label in the generated training data?

Some ambiguity is inherent (decision D1: "Dhaka" is a DISTRICT, then a
DIVISION). A model can use context to resolve some of it, but a string that
really is ambiguous sets a ceiling on achievable accuracy, so measure it.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict

from thikana.text import normalize_digits, normalize_token, tokenize, to_bio
from thikana.training.synth import build_datasets

NAME_LABELS = ("AREA", "UPAZILA", "DISTRICT", "DIVISION")


def hyphen_number_report(examples) -> dict:
    """What label does a number get when it directly follows a hyphen?

    Broken down by the label of the token BEFORE the hyphen and the number's
    digit count. If "a name, a hyphen, then digits" is always a postcode in the
    training data, the model learns that as a rule (it did: "Mirpur-10").
    """
    table: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for example in examples:
        tokens = tokenize(normalize_digits(example.text))
        tags = to_bio(tokens, example.spans)
        for i in range(2, len(tokens)):
            if tokens[i - 1].text == "-" and tokens[i].text.isdigit():
                n = len(tokens[i].text)
                bucket = "1-2 digits" if n <= 2 else "4 digits" if n == 4 else "3 or 5+ digits"
                table[(tags[i - 2][2:] or "O", bucket)][tags[i][2:] or "O"] += 1
    return table


def print_hyphen_report(examples) -> None:
    table = hyphen_number_report(examples)
    print("\nnumber right after 'X-': label of X, digit count -> labels the number received")
    for (before, bucket), counter in sorted(table.items(), key=lambda kv: -sum(kv[1].values())):
        total = sum(counter.values())
        shares = ", ".join(f"{label} {n / total:.0%}" for label, n in counter.most_common())
        print(f"  X={before:9s} {bucket:15s} n={total:5d}  {shares}")
    names = [c for (before, _), c in table.items() if before in ("AREA", "DISTRICT", "UPAZILA")]
    total = sum(sum(c.values()) for c in names)
    postcode = sum(c["POSTCODE"] for c in names)
    if total:
        print(f"when X is a place name: the number is a POSTCODE in {postcode / total:.1%} "
              f"of {total} cases")


def label_sets(examples) -> dict[str, Counter]:
    seen: dict[str, Counter] = defaultdict(Counter)
    for example in examples:
        for span in example.spans:
            if span.label in NAME_LABELS:
                surface = normalize_token(normalize_digits(example.text[span.start:span.end])).lower()
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

    print_hyphen_report(data["train"])


if __name__ == "__main__":
    main()
