"""CI quality gate: refuse to ship a freshly trained model that has regressed.

Run:  python -m thikana.training.gate        (after  python -m thikana.training.train_all)

CI trains the production model on a Linux runner. The `.crfsuite` file is NOT
byte-identical to the Windows-trained one (checked: different SHA-256, identical
predictions on all 278 hand-written addresses), so a hash cannot be the check. The
check is behaviour: score the model that is about to be baked into the image on the
hand-written sets and fail if any score falls below its floor.

What this is and is not:
  * It is a REGRESSION gate. It catches a broken gazetteer, a feature change that
    wrecks tagging, or an empty or truncated model.
  * It is NOT an evaluation. v1-v4 were each scored once to choose between models and
    are spent for that purpose, and they are not real data. A pass says "this is the
    model we measured", not "this model is good on real addresses".
  * The floors are the observed score minus a margin, not a target. Raising them
    after a real improvement is a deliberate, reviewed edit of this file.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

from thikana.model import AddressParser
from thikana.schema import Span
from thikana.training.evaluate import score
from thikana.training.handwritten import load, path_for
from thikana.training.train_all import PRODUCTION_MODEL
from thikana.training.train import MODELS

# Observed micro F1 for crf_all_district_memory: v1 0.9834, v2 0.9279, v3 0.9192,
# v4 0.8972 (identical for the Windows- and Linux-trained files). Floors sit ~1.5
# points below, enough for a harmless platform difference, not for a real regression.
FLOORS = {"v1": 0.970, "v2": 0.910, "v3": 0.900, "v4": 0.880}


def check(predict: Callable[[str], list[Span]], floors: dict[str, float] = FLOORS) -> tuple[list[str], list[str]]:
    """Return (report lines, failures). A failure is a set scoring under its floor."""
    lines, failures = [], []
    for version, floor in floors.items():
        items, _ = load(path_for(version))
        gold = [i.example for i in items]
        f1 = score(gold, [predict(e.text) for e in gold])["micro"]["f1"]
        verdict = "ok" if f1 >= floor else "BELOW FLOOR"
        lines.append(f"{version}: micro F1 {f1:.4f}  floor {floor:.3f}  ({len(gold)} addresses)  {verdict}")
        if f1 < floor:
            failures.append(f"{version}: {f1:.4f} < {floor:.3f}")
    return lines, failures


def main() -> None:
    path = MODELS / f"{PRODUCTION_MODEL}.crfsuite"
    if not path.exists():
        sys.exit(f"{path} is missing: run  python -m thikana.training.train_all  first")
    print(f"gating {path.name} (hand-written sets; regression check, not an evaluation)")
    lines, failures = check(AddressParser.load(Path(path)).predict)
    print("\n".join(lines))
    if failures:
        sys.exit("QUALITY GATE FAILED: " + "; ".join(failures))
    print("quality gate passed")


if __name__ == "__main__":
    main()
