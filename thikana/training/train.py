"""Train CRF variants and score them against the rule baseline on the SAME dev split.

Run:  python -m thikana.training.train

The test split is deliberately not touched here: it is for one final report,
after every choice (features, regularisation) has been made on dev.

Variants (each changes ONE thing relative to the previous idea):
  crf_v1_surface_context  words, affixes, shapes, context, seen-before, separators
  crf_v2_plus_gazetteer   v1 + "this token is a district / division / upazila name"
  crf_district_memory     v1 + "a district name appears before / after this token"
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pycrfsuite

from thikana.features import Vocab, sentence_features
from thikana.model import AddressParser
from thikana.schema import ENTITY_TYPES
from thikana.text import normalize_digits, normalize_token, tokenize, to_bio
from thikana.training.baseline import Baseline
from thikana.training.evaluate import REPORTS, paired_bootstrap, score
from thikana.training.gazetteer import load_all
from thikana.training.synth import DATASET_SEEDS, DATASET_SIZES, build_datasets

MODELS = Path(__file__).resolve().parents[2] / "models"
HYPERPARAMS = {"c1": 0.1, "c2": 0.05, "max_iterations": 150,
               "feature.possible_transitions": True}


def build_vocab(places) -> Vocab:
    """Single NFC-lowercase tokens of district / division / administrative-upazila names."""
    names: dict[str, set[str]] = {"district": set(), "division": set(), "upazila": set()}
    for p in places:
        names["district"] |= {p.district, p.district_bn}
        names["division"] |= {p.division, p.division_bn}
        if p.upazila_admin:  # decision D8
            names["upazila"] |= {p.upazila, p.upazila_bn}
    return {kind: frozenset(normalize_token(t.text).lower()
                            for name in group if name for t in tokenize(name))
            for kind, group in names.items()}


def build_vocab_full(frames: dict | None = None) -> Vocab:
    """The vocabulary straight from the full reference TABLES (all 64 districts, 8
    divisions and 494 upazilas), not from whichever records a split happened to
    contain. What a deployed model would know."""
    f = frames or load_all()

    def tokens(*columns):
        return frozenset(normalize_token(t.text).lower() for column in columns
                         for name in column if name for t in tokenize(name.strip()))

    return {"district": tokens(f["districts"]["name"], f["districts"]["bn_name"]),
            "division": tokens(f["divisions"]["name"], f["divisions"]["bn_name"]),
            "upazila": tokens(f["upazilas"]["name"], f["upazilas"]["bn_name"])}


def train_model(examples, path: Path, vocab: Vocab | None = None,
                memory: bool = False) -> float:
    """Train one model; the vocabulary and flags it needs are saved beside it."""
    trainer = pycrfsuite.Trainer(verbose=False)
    for example in examples:
        tokens = tokenize(normalize_digits(example.text))
        trainer.append(sentence_features(tokens, vocab, memory), to_bio(tokens, example.spans))
    trainer.set_params(HYPERPARAMS)
    path.parent.mkdir(exist_ok=True)
    started = time.perf_counter()
    trainer.train(str(path))
    elapsed = time.perf_counter() - started
    path.with_suffix(".json").write_text(json.dumps({
        "memory": memory,
        "vocab": {k: sorted(v) for k, v in vocab.items()} if vocab else None,
    }, ensure_ascii=False), encoding="utf-8")
    return elapsed


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    splits, data = build_datasets()
    dev = data["dev"]
    vocab = build_vocab(splits["train"])

    base_pred = [Baseline(splits["train"]).predict(e.text) for e in dev]
    results = {"rule_baseline": score(dev, base_pred)}
    predictions = {"rule_baseline": base_pred}
    meta = {}
    for name, v, memory in (("crf_v1_surface_context", None, False),
                            ("crf_v2_plus_gazetteer", vocab, False),
                            ("crf_district_memory", {"district": vocab["district"]}, True)):
        path = MODELS / f"{name}.crfsuite"
        seconds = train_model(data["train"], path, v, memory)
        parser = AddressParser.load(path)
        predictions[name] = [parser.predict(e.text) for e in dev]
        results[name] = score(dev, predictions[name])
        meta[name] = {"train_seconds": round(seconds, 1), "model_bytes": path.stat().st_size}

    names = list(results)
    print("entity-level F1 on SYNTHETIC dev (not real addresses)")
    print(f"{'label':10s}" + "".join(f"{n:>24s}" for n in names))
    for label in ENTITY_TYPES:
        print(f"{label:10s}" + "".join(f"{results[n]['per_label'][label]['f1']:24.3f}" for n in names))
    print(f"{'MICRO':10s}" + "".join(f"{results[n]['micro']['f1']:24.3f}" for n in names))
    print(f"{'MACRO':10s}" + "".join(f"{results[n]['macro_f1']:24.3f}" for n in names))
    for name, info in meta.items():
        print(f"{name}: trained in {info['train_seconds']}s, model file {info['model_bytes'] / 1024:.0f} KB")

    comparisons = {}
    for a, b in (("rule_baseline", "crf_v1_surface_context"),
                 ("crf_v1_surface_context", "crf_v2_plus_gazetteer"),
                 ("crf_v1_surface_context", "crf_district_memory")):
        ci = paired_bootstrap(dev, predictions[a], predictions[b])
        comparisons[f"{b} minus {a}"] = ci
        print(f"\nmicro F1, {b} minus {a}: {ci['mean']:+.3f}   "
              f"95% interval [{ci['low']:+.3f}, {ci['high']:+.3f}]")

    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / "crf_vs_baseline_synthetic_dev.json"
    out.write_text(json.dumps({
        "what": "SYNTHETIC dev only; says nothing about real addresses",
        "dataset_sizes": DATASET_SIZES, "dataset_seeds": DATASET_SEEDS,
        "hyperparams": HYPERPARAMS, "models": meta, "scores": results,
        "paired_bootstrap_micro_f1": comparisons,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {out.relative_to(REPORTS.parent)}")


if __name__ == "__main__":
    main()
