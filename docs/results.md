# Results log

Every number here comes with what it does and does not mean. Reproduce with
`python -m thikana.training.train`, then `python -m thikana.training.evaluate_handwritten v1|v2|v3`.
All values are entity-level micro F1 (start, end and label must all match).

## Current state (2026-10-26)

| Evaluation set | Rule baseline | CRF v1 | CRF v2 (+gazetteer) | CRF district_memory |
|---|---|---|---|---|
| Synthetic dev, final generator (600 addresses) | 0.872 | 0.959 | 0.961 | 0.963 |
| Hand-written v1 (70) - SPENT, scored by much older models | 0.852 | 0.932 | 0.946 | n/a |
| Hand-written v2 (74) - SPENT, scored by older models | 0.861 | 0.917 | 0.910 | n/a |
| **Hand-written v3 (69 addresses, 215 entities) - scored once** | **0.851** | **0.897** | **0.901** | **0.910** |

### How to read this

- **Synthetic dev** is produced by the same code as the training data: it
  measures how well the model learned the generator, not addresses. It changes
  whenever the generator changes, so it is never comparable across rounds.
- **The hand-written sets are NOT real data.** An AI assistant wrote them from
  general knowledge of Bangladeshi addresses (`data/handwritten/README.md`). The
  same author wrote the generator, so every gap is probably a LOWER BOUND on the
  real synthetic-to-real gap. `data/real/` is still empty.
- v1 and v2 are SPENT (their errors drove fixes); their rows are historical,
  scored by the models of their day. v3 was written after the fixes and the final
  retrain and scored once; it is now spent too.
- 69 addresses, group cells of 1-13 items: per-group numbers are directional only.

### Comparisons (paired bootstrap, 95% interval, micro F1)

| Comparison | Synthetic dev | Hand-written v2 | Hand-written v3 |
|---|---|---|---|
| CRF v1 minus rule baseline | +0.086 [+0.071, +0.101] | +0.056 [-0.006, +0.118] | **+0.046 [-0.017, +0.109]** |
| CRF v2 minus CRF v1 | +0.002 [-0.005, +0.010] | -0.007 [-0.025, +0.007] | +0.005 [-0.012, +0.025] |
| district_memory minus CRF v1 | +0.004 [-0.002, +0.009] | n/a | **+0.014 [+0.002, +0.028]** |

- The CRF's lead over the (fairly upgraded) baseline is established on synthetic
  dev but on neither of the last two fresh hand-written sets: same sign, similar
  size, both intervals include zero. Suggestive, not proven.
- Gazetteer token features (v2) have now tied v1 four times. Dropped as a lead.
- **district_memory beats v1 on v3** with an interval that only just excludes
  zero. Three comparisons were scored on v3, so a borderline "significant" result
  has roughly a 1-in-7 chance of being luck. Supportive, not conclusive.

## What this round fixed (hand-written v3)

T = this round's fixes. R = last round's fixes, new instances (regression guards).
F = constructs deliberately not trained for.

| Group | n | Baseline | v1 | v2 | district_memory |
|---|---|---|---|---|---|
| T-upazila (an upazila with no area before it; D11) | 13 | 0.800 | 0.857 | 0.829 | 0.857 |
| T-d1 (lone district; district + division) | 12 | 1.000 | 0.944 | 0.944 | 0.972 |
| T-unicode (NFC Bangla names) | 8 | 0.821 | 0.900 | 0.900 | 0.950 |
| **targeted overall** | 33 | 0.884 | 0.901 | 0.890 | 0.923 |
| **regression guards overall** | 8 | 0.885 | **1.000** | **1.000** | **1.000** |
| **fresh overall** | 28 | 0.808 | 0.860 | 0.880 | 0.869 |
| F-punct (`/`, `\|`, brackets) - unfixed on purpose | 5 | 0.882 | 0.647 | 0.647 | 0.647 |
| F-landmark (a block / district nested in a landmark) | 2 | 1.000 | 0.556 | 0.588 | 0.588 |

Pre-run predictions: T-unicode >= 0.9 (0.900), T-upazila / T-d1 0.85-0.95 (0.857 /
0.944), regression >= 0.95 (1.000), fresh 0.75-0.85 (0.860, slightly better),
F-punct <= 0.8 (0.647), overall 0.88-0.93 (0.897). district_memory was predicted
to differ from v1 by a small amount that probably includes zero (+0.014, just
excludes it).

## Remaining errors (CRF v1 on v3: 18 of 69 addresses)

| Cause | Addresses | Next step |
|---|---|---|
| An upazila-first name read as AREA - 5 of 6 are names that never appeared as an upazila in the 70% training split | 6 | train on ALL records; build the vocabulary from the full gazetteer |
| Separators `/`, `\|`, brackets glue onto the previous entity | 3 | separator variety |
| Typos INSIDE keywords (`Raod`, `Hause`); an unseen Bangla keyword (`রাস্তা`); the Bangla `পোস্টকোড` | 4 | keyword typos; Bangla postcode introducers |
| A block or district nested inside a landmark | 2 | landmark variety |
| A lone district after a landmark called DIVISION; its reverse | 2 | adopt district_memory (see below) |
| The D11 "twice" case (`Savar, Savar`) read as two UPAZILA | 1 | positional D11 is hard to learn |

The two most informative checks this round:

- **The upazila-first misses are mostly a vocabulary effect.** v3 has 22 UPAZILA
  spans; 15 of the names appear as an upazila in the training split, 7 do not.
  Five of the six upazila-first errors are among the 7 unseen names. The model
  learns upazila identity lexically from training records, and an unseen leading
  name defaults to AREA. Held-out records are the right setup for unseen VILLAGE
  names, but a deployed model would know every gazetteer name, so a production
  model should train on all records. UNTESTED hypothesis: it needs a fresh v4.
- **NFC works as intended.** Both keyboard forms give identical features and
  identical predictions (unit tests, shown to fail with NFC removed). The two
  wrong T-unicode items are role errors (upazila-first), not name-recognition
  errors.

## Decision log for this round

1. **District memory (pre-registered rule): NOT ADOPTED on dev, and that stands.**
   Rule fixed in advance: adopt only if DISTRICT + DIVISION mistakes drop by 40%
   or more AND micro F1 does not regress (interval lower bound >= -0.005). Result
   on the final models: 32 -> 20 mistakes (37.5% fewer) - a near miss - with F1
   +0.004 [-0.002, +0.009]. The specific failure the feature targets (DIVISION
   labelled DISTRICT right after a district) fell from 12 to 2. v1 stays the
   CHOSEN model. v3 now offers independent support for the feature; adopting it
   is a NEW decision made with NEW evidence, which makes v3 spent as selection
   evidence, so any adoption needs a fresh v4 to report a number.
2. **D11 (provisional)** - a name shared by a post office and its upazila: once
   -> UPAZILA; twice -> post office (AREA) then UPAZILA, hierarchy decides in
   reversed order; an introducer or a number marks it AREA. 32% of
   administrative-upazila records have such a post office. Awaiting confirmation.
3. **NFC normalisation** applied PER TOKEN, after tokenising, so character offsets
   into the user's original text never move (NFC changes string length).

## Process disclosures

- The first D11 test failed three times before passing; each failure was the test
  being too narrow (typos defeating exact matching, reversed order, numbered post
  offices) and one exposed a real generator bug (the "never an empty address"
  fallback skipped D11). All fixed with the generator, not by loosening the check.
- One generated v3 item duplicated a v2 item (same gazetteer row); a test caught
  it and the item was replaced BEFORE scoring.
- Models were retrained after the last generator change so they match the final
  code. The adoption rule was evaluated on both the earlier and the final run
  (39.4% and 37.5%): the same outcome.
- Still undecided, so absent from the generator and every set: `Union Parishad
  Office` and other building / office names, and `Floor`.

## Rules for the next iteration

v3 is now SPENT. Before any new number is reported: change the generator or
training, then write a fresh `addresses_v4.txt`. Real addresses, once collected,
supersede all of these.
