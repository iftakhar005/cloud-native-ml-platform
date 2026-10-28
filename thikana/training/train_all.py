"""Train the PRODUCTION models on EVERY gazetteer record.

Run:  python -m thikana.training.train_all

The split-trained models in train.py hold back 30% of the postcode records so
that evaluation can measure generalisation to names the model never saw. That is
the right setup for measuring, and the wrong one for deploying: a deployed model
has the whole gazetteer. Here nothing is held back.

Data: every postcode record (1349) PLUS a synthetic place for each upazila the
postcode file lacks (230 of the 492), because the generator builds addresses
from places and the postcode file alone can never teach those names. Vocabulary
comes from the full reference tables.

Same hyperparameters as the split models. The number of training examples is NOT
the same any more: the split models keep DATASET_SIZES["train"] (4,000), so earlier
experiments stay comparable, but production trains on PRODUCTION_EXAMPLES (8,000).
Why, measured over three training seeds (docs/results.md, "The village / union fix"):
at 4,000 examples the same recipe landed anywhere from 0.891 to 0.921 on hand-written
v3 depending on the seed alone, so one lucky or unlucky run decided the quality gate;
at 8,000 all three seeds passed every floor and v4 rose from 0.88-0.89 to 0.91.

PRODUCTION_MODEL is the adopted model. It was district memory (adopted after it led v1 on
the fresh v3 set); since 2026-10-28 it is district memory PLUS the full-table vocabulary
features, chosen over three training seeds on v1-v6 with v7 held back (docs/results.md,
"Making it better").
"""

from __future__ import annotations

import json
import sys

from thikana.text import normalize_token
from thikana.training.evaluate import REPORTS
from thikana.training.gazetteer import load_all
from thikana.training.synth import DATASET_SEEDS, build_all_places, build_places, generate
from thikana.training.train import HYPERPARAMS, MODELS, build_vocab_full, train_model

PRODUCTION_MODEL = "crf_all_district_memory_vocab"
PRODUCTION_EXAMPLES = 8000


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    frames = load_all()
    postcode_places = build_places(frames)
    places = build_all_places(frames)
    vocab = build_vocab_full(frames)
    examples = generate(places, PRODUCTION_EXAMPLES, DATASET_SEEDS["train"])

    covered = {(p.district.lower(), p.upazila.lower()) for p in places if p.upazila_admin}
    # A place being IN THE POOL is not the same as appearing in the EXAMPLES: with
    # uniform random draws most places are sampled once or never. Count both.
    known = {normalize_token(n).lower() for p in places if p.upazila_admin
             for n in (p.upazila, p.upazila_bn) if n}
    appearing = {normalize_token(e.text[s.start:s.end]).lower()
                 for e in examples for s in e.spans if s.label == "UPAZILA"} & known
    print(f"places: {len(postcode_places)} postcode records + "
          f"{len(places) - len(postcode_places)} upazila-only = {len(places)}")
    print(f"administrative upazilas IN THE PLACE POOL: {len(covered)} "
          f"(postcode records alone: "
          f"{len({(p.district.lower(), p.upazila.lower()) for p in postcode_places if p.upazila_admin})})")
    print(f"upazila NAME FORMS that actually APPEAR as UPAZILA in the {len(examples)} examples: "
          f"{len(appearing)} of {len(known)}  <- the number that matters")

    meta = {}
    for name, v, memory in (
            ("crf_all_v1_surface_context", None, False),
            ("crf_all_district_memory", {"district": vocab["district"]}, True),
            ("crf_all_district_memory_vocab", vocab, True),
            ("crf_all_gazetteer", vocab, False)):
        path = MODELS / f"{name}.crfsuite"
        seconds = train_model(examples, path, v, memory)
        meta[name] = {"train_seconds": round(seconds, 1), "model_bytes": path.stat().st_size,
                      "memory": memory, "vocab_kinds": sorted(v) if v else []}
        print(f"{name}: trained in {seconds:.1f}s, {path.stat().st_size / 1024:.0f} KB")

    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / "production_models.json"
    out.write_text(json.dumps({
        "what": "models trained on EVERY gazetteer record; no held-out names, so synthetic "
                "dev numbers would be in-sample and are deliberately not reported",
        "production_model": PRODUCTION_MODEL,
        "postcode_records": len(postcode_places),
        "upazila_only_places": len(places) - len(postcode_places),
        "admin_upazilas_in_place_pool": len(covered),
        "upazila_name_forms_appearing_in_examples": len(appearing),
        "upazila_name_forms_possible": len(known),
        "training_examples": len(examples),
        "hyperparams": HYPERPARAMS, "models": meta,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nproduction model: {PRODUCTION_MODEL}\nwrote {out.relative_to(REPORTS.parent)}")


if __name__ == "__main__":
    main()
