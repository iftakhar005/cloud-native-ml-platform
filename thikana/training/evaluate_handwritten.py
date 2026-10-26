"""Score the baseline and CRF models on the HAND-WRITTEN set, beside synthetic dev.

The set is NOT real data and not independent of the generator (same author), so
the gap printed here is probably a lower bound on the real synthetic-to-real gap.

Run:  python -m thikana.training.evaluate_handwritten
Needs trained models: run  python -m thikana.training.train  first.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict

from thikana.model import AddressParser
from thikana.schema import ENTITY_TYPES
from thikana.training.baseline import Baseline
from thikana.training.evaluate import REPORTS, paired_bootstrap, score
from thikana.training.handwritten import audit, load, path_for
from thikana.training.probe import mark
from thikana.training.synth import build_places, split_places
from thikana.training.train import MODELS

CHOSEN = "crf_v1_surface_context"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    version = sys.argv[1] if len(sys.argv) > 1 else "v1"
    items, variants = load(path_for(version))
    problems = audit(items, variants)
    if problems:
        sys.exit("fix the gold labels first:\n  " + "\n  ".join(problems))
    gold = [i.example for i in items]

    train_places = split_places(build_places())["train"]
    systems = {"rule_baseline": Baseline(train_places).predict}
    for name in ("crf_v1_surface_context", "crf_v2_plus_gazetteer", "crf_district_memory"):
        path = MODELS / f"{name}.crfsuite"
        if not path.exists():
            sys.exit(f"{path} is missing: run  python -m thikana.training.train  first")
        systems[name] = AddressParser.load(path).predict

    preds = {n: [f(e.text) for e in gold] for n, f in systems.items()}
    scores = {n: score(gold, p) for n, p in preds.items()}
    synthetic = json.loads((REPORTS / "crf_vs_baseline_synthetic_dev.json")
                           .read_text(encoding="utf-8"))["scores"]

    print(f"HAND-WRITTEN set {version} (NOT real data): {len(gold)} addresses, "
          f"{sum(len(e.spans) for e in gold)} gold entities\n")
    print(f"{'system':26s} {'synthetic dev':>14s} {'hand-written':>13s} {'gap':>8s}")
    for n in systems:
        s, h = synthetic[n]["micro"]["f1"], scores[n]["micro"]["f1"]
        print(f"{n:26s} {s:14.3f} {h:13.3f} {s - h:+8.3f}   (micro F1)")

    print(f"\nper-label F1 on the hand-written set   (n = gold entities; small n is noisy)")
    print(f"{'label':10s}" + "".join(f"{n:>24s}" for n in systems) + f"{'n':>6s}")
    for label in ENTITY_TYPES:
        row = "".join(f"{scores[n]['per_label'][label]['f1']:24.3f}" for n in systems)
        print(f"{label:10s}{row}{scores[CHOSEN]['per_label'][label]['support']:6d}")

    comparisons = {}
    for a, b in (("rule_baseline", "crf_v1_surface_context"),
                 ("crf_v1_surface_context", "crf_v2_plus_gazetteer"),
                 ("crf_v1_surface_context", "crf_district_memory")):
        ci = paired_bootstrap(gold, preds[a], preds[b])
        comparisons[f"{b} minus {a}"] = ci
        print(f"\nmicro F1 {b} minus {a}: {ci['mean']:+.3f}  "
              f"95% interval [{ci['low']:+.3f}, {ci['high']:+.3f}]")

    by_style = defaultdict(list)
    for i, item in enumerate(items):
        by_style[item.style].append(i)
    print(f"\nmicro F1 by address style (each cell is a handful of addresses)")
    print(f"{'style':10s}{'n':>4s}" + "".join(f"{n:>24s}" for n in systems))
    style_scores = {}
    for style, idx in by_style.items():
        row = {}
        for n in systems:
            row[n] = score([gold[i] for i in idx], [preds[n][i] for i in idx])["micro"]["f1"]
        style_scores[style] = {"n": len(idx), **row}
        print(f"{style:10s}{len(idx):4d}" + "".join(f"{row[n]:24.3f}" for n in systems))

    group_scores = {}
    names = {"T": "targeted", "R": "regression", "F": "fresh"}
    groups = {k: [i for i, it in enumerate(items) if it.style.startswith(k + "-")] for k in names}
    if groups["T"] and groups["F"]:
        print("\nTARGETED (T-) = this round's fixes; REGRESSION (R-) = last round's fixes, "
              "new instances; FRESH (F-) = deliberately NOT trained for")
        print(f"{'group':11s}{'n':>4s}" + "".join(f"{n:>24s}" for n in systems))
        for key, name in names.items():
            idx = groups[key]
            if not idx:
                continue
            row = {n: score([gold[i] for i in idx], [preds[n][i] for i in idx])["micro"]["f1"]
                   for n in systems}
            group_scores[name] = {"n": len(idx), **row}
            print(f"{name:11s}{len(idx):4d}" + "".join(f"{row[n]:24.3f}" for n in systems))

    wrong = [i for i, e in enumerate(gold)
             if {(s.start, s.end, s.label) for s in e.spans}
             != {(s.start, s.end, s.label) for s in preds[CHOSEN][i]}]
    print(f"\n{CHOSEN}: {len(wrong)} of {len(gold)} addresses not exactly right")
    for i in wrong:
        e = gold[i]
        print(f"\n#{items[i].id} [{items[i].style}]\n  gold: {mark(e.text, e.spans)}"
              f"\n  got : {mark(e.text, preds[CHOSEN][i])}")

    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / ("handwritten_scores.json" if version == "v1"
                     else f"handwritten_{version}_scores.json")
    out.write_text(json.dumps({
        "WARNING": "HAND-WRITTEN by an AI assistant, NOT real addresses; same author as the "
                   "generator, so the gap is probably a lower bound on the real one",
        "addresses": len(gold), "scores": scores, "synthetic_dev_scores": {
            n: synthetic[n]["micro"]["f1"] for n in systems},
        "paired_bootstrap_micro_f1": comparisons, "by_style": style_scores,
        "by_group": group_scores, "version": version,
        "wrong_addresses_for_chosen_model": [items[i].id for i in wrong],
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {out.relative_to(REPORTS.parent)}")


if __name__ == "__main__":
    main()
