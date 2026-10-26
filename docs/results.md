# Results log

Every number here comes with what it does and does not mean. Reproduce with
`python -m thikana.training.train` (split-trained models, synthetic dev),
`python -m thikana.training.train_all` (production models, every record), then
`python -m thikana.training.evaluate_handwritten v1|v2|v3|v4`.
All values are entity-level micro F1 (start, end and label must all match).

## Current state (2026-10-26)

| Evaluation set | Rule baseline | CRF v1 | CRF v2 (+gazetteer) | CRF district_memory |
|---|---|---|---|---|
| Synthetic dev, final generator (600) | 0.872 | 0.959 | 0.961 | 0.963 |
| Hand-written v1 (70) - SPENT, scored by much older models | 0.852 | 0.932 | 0.946 | n/a |
| Hand-written v2 (74) - SPENT, scored by older models | 0.861 | 0.917 | 0.910 | n/a |
| Hand-written v3 (69) - SPENT, split-trained models | 0.851 | 0.897 | 0.901 | 0.910 |

### Hand-written v4 (65 addresses, 199 entities) - scored once, DEPLOYMENT setting

Here the rule baseline and the "all" models know every gazetteer record. The
split-trained models are controls, so the effect of full coverage is measured.

| System | Trained on | Micro F1 |
|---|---|---|
| rule baseline | (full gazetteer vocabulary) | **0.918** |
| crf_v1_surface_context | 70% of records | 0.862 |
| crf_district_memory | 70% of records | 0.872 |
| crf_all_v1_surface_context | every record | 0.885 |
| **crf_all_district_memory (the ADOPTED production model)** | every record | **0.897** |
| crf_all_gazetteer (full-table vocabulary features) | every record | 0.947 |

### How to read this

- **Synthetic dev** is produced by the same code as the training data. It
  measures how well a model learned the generator, not addresses, and changes
  whenever the generator does, so it is never comparable across rounds.
- **The hand-written sets are NOT real data.** An AI assistant wrote them from
  general knowledge of Bangladeshi addresses (`data/handwritten/README.md`). The
  same author wrote the generator, so every gap is probably a LOWER BOUND on the
  real synthetic-to-real gap. `data/real/` is still empty.
- v1, v2 and v3 are SPENT (their errors drove fixes). v4 was written after the
  production models were trained and scored once; it is now spent too.
- 65 addresses, group cells of 1-19 items: group numbers are directional only.
- The "gap" column printed by the scorer is NOT meaningful for the rule baseline
  on v4: its synthetic score used split-trained vocabulary, its v4 score used the
  full gazetteer. Different systems.

### v4 comparisons (paired bootstrap, 95% interval, micro F1)

PRE-REGISTERED (four, fixed before scoring):

| Comparison | Result | Prediction | Held? |
|---|---|---|---|
| adopted model minus rule baseline | -0.022 [-0.094, +0.044] | -0.02 to +0.05, includes 0 | yes |
| adopted model minus crf_all_v1 (district memory, full data) | +0.013 [-0.005, +0.035] | 0 to +0.03 | yes |
| adopted model minus the SAME model on 70% (full-data effect) | +0.025 [-0.006, +0.058] | +0.03 to +0.08, above 0 | **no** |
| crf_all_v1 minus crf_v1 (full-data effect, no memory) | +0.022 [-0.012, +0.055] | n/a | not established |

EXPLORATORY (post hoc: chosen after seeing v4, so NOT evidence for a decision):

| Comparison | Result |
|---|---|
| crf_all_gazetteer minus the adopted model | +0.051 [+0.015, +0.091] |
| crf_all_gazetteer minus crf_all_v1 | +0.063 [+0.032, +0.098] |
| crf_all_gazetteer minus the rule baseline | +0.029 [-0.034, +0.084] (not distinguishable) |

### By group (v4)

| Group | n | Baseline | v1 (70%) | memory (70%) | all_v1 | **all_memory** | all_gazetteer |
|---|---|---|---|---|---|---|---|
| T-vocab (upazila names unseen by the 70% models) | 19 | 1.000 | 0.660 | 0.660 | 0.809 | **0.809** | 0.957 |
| T-d1 (lone district; district + division) | 12 | 1.000 | 1.000 | 1.000 | 0.972 | **1.000** | 1.000 |
| **targeted overall** | 31 | 1.000 | 0.807 | 0.807 | 0.880 | **0.892** | 0.976 |
| **regression guards (R-)** | 13 | 0.911 | 0.978 | 0.978 | 0.978 | **0.978** | 1.000 |
| F-novel (invented names; right answer is AREA) | 8 | 1.000 | 0.917 | 0.958 | 0.857 | **0.857** | 0.958 |
| F-punct (`/`, `\|`, brackets) - unfixed | 4 | 0.933 | 0.600 | 0.600 | 0.600 | **0.600** | 0.667 |
| **fresh overall** | 21 | 0.828 | 0.853 | 0.881 | 0.833 | **0.853** | 0.881 |

Where each side wins (v4): the rule baseline on vocabulary (T-vocab 1.000),
separators (F-punct 0.93 vs 0.60) and D1; the CRFs on typos inside keywords
(F-typo 1.00 vs 0.50), number formats (F-number 1.00 vs 0.44), abbreviations,
village forms and reversed order (R-village 1.00 vs 0.75, R-order 1.00 vs 0.80).

## What v4 taught us

**1. The adopted configuration did not win.** All-data + district memory scored
0.897, below the full-gazetteer rule baseline (0.918); the difference is not
established (interval includes zero). District memory itself is not hurting: it
is +0.013 over the same data without it, and +0.010 on the 70% models, and it led
v1 by +0.014 on v3. Small, consistent, never negative, never significant on v4.

**2. Training on every record helped, but nowhere near as much as predicted.**
T-vocab went 0.660 -> 0.809, still 8 of 19 wrong, ALL of them names the model
"was trained on". The mechanism, measured: the 8 missed names appeared as an
UPAZILA 0.4 times each in the 4,000 training examples (four appeared ZERO times).

**A correction to an earlier claim.** I said coverage went from 262 to "all 492"
upazilas. That described the POOL of places the generator draws from, not the
training EXAMPLES: with 1,579 places and uniform random draws, only 475 of 958
upazila name forms (English and Bangla) actually appear as an UPAZILA in the
examples. `train_all.py` now prints both numbers.

**3. Vocabulary features did what the data could not.** crf_all_gazetteer (a
"this token is a known upazila name" feature from the full tables) scores 0.957
on T-vocab and 0.947 overall, the best on v4: a feature generalises across all
494 names at once, where a CRF would need many examples of each. NOT adopted: it
was not the pre-registered primary, and choosing it from v4 spends v4.

**4. Over-eagerness is real.** F-novel fell from 0.917 / 0.958 (70% models) to
0.857 (all-data). `নয়াপাড়া, সাভার, ঢাকা` came out as `[UPAZILA: নয়াপাড়া]
[AREA: সাভার]`: roles swapped. Teaching hundreds of upazila names made the
model readier to call an unfamiliar leading name an upazila.

**5. A dictionary is a strong baseline here.** On a set whose names all come from
the gazetteer, lookup is exactly the right tool. The CRF's value is in what a
dictionary cannot do: typos, number formats, abbreviations, odd order.

## Decision log

1. **D11 accepted as written** (a name shared by post office and upazila: once ->
   UPAZILA; twice -> post office then UPAZILA, hierarchy decides in reversed
   order; an introducer or a number marks it AREA).
2. **District memory adopted by the project owner** after it led v1 on v3.
   `PRODUCTION_MODEL = "crf_all_district_memory"` in `train_all.py`. v4 neither
   confirms nor contradicts it (+0.013, not significant). It REMAINS the
   production model until the owner changes it; the evidence now points to a
   better candidate (below), which needs a fresh v5.
3. **Train on every gazetteer record, vocabulary from the full tables.** Done,
   with two augmentations disclosed: 230 synthetic "upazila-only" places for the
   upazilas the postcode file lacks (post office named like the upazila, postcode
   borrowed from a real record of the same district).

## Recommended next steps (untested hypotheses, all need a fresh v5)

1. Guarantee exposure: sample so every place appears at least k times, instead
   of uniform draws that leave half the names unseen.
2. A combined candidate: district memory + full-table token features. Decide the
   primary and the comparisons BEFORE writing v5.
3. Protect the F-novel guard: more invented names, especially Bangla, in
   upazila-like positions, and training examples of novel-name-then-known-upazila.
4. Still open from earlier rounds: separators `/` `|` brackets, nested landmarks,
   typos in keywords for the baseline, the Bangla `পোস্টকোড` introducer.

## Process disclosures

- v4's four comparisons were fixed before scoring; the exploratory ones were
  added after and are labelled. Predictions were written first; roughly half
  held (T-vocab split and baseline, F-novel, regression, three of the four
  comparisons) and half did not (T-vocab for the all-data CRFs, overall level,
  the full-data effect).
- Retraining after the coverage-reporting fix produced byte-identical model
  files (SHA-256 compared), so the v4 scores correspond to the committed code.
- Still undecided, so absent from the generator and every set: `Union Parishad
  Office` and other building / office names, and `Floor`.

## Rules for the next iteration

v4 is SPENT. Change the generator or training, decide the primary comparison in
advance, then write a fresh `addresses_v5.txt` before reporting a new number.
Real addresses, once collected, supersede all of these.
