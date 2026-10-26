# Results log

Every number here comes with what it does and does not mean. Reproduce with
`python -m thikana.training.train`, then `python -m thikana.training.evaluate_handwritten v1|v2`.
All values are entity-level micro F1 (start, end and label must all match).

## Current state (2026-10-26)

| Evaluation set | Rule baseline | CRF v1 | CRF v2 (+gazetteer) |
|---|---|---|---|
| Synthetic dev, widened generator (600 addresses) | 0.869 | 0.965 | 0.966 |
| Hand-written v1 (70) - SPENT, scored by the PRE-widening models | 0.852 | 0.932 | 0.946 |
| **Hand-written v2 (74 addresses, 283 entities) - scored once** | **0.861** | **0.917** | **0.910** |

### How to read this

- **Synthetic dev** is produced by the same code as the training data. It
  measures how well the model learned the generator, not addresses. It also
  changed when the generator was widened, so it is NOT comparable with earlier
  synthetic numbers.
- **The hand-written sets are NOT real data.** An AI assistant wrote them from
  general knowledge of Bangladeshi addresses (`data/handwritten/README.md`). The
  same author wrote the generator, so the gap is probably a LOWER BOUND on the
  real synthetic-to-real gap. `data/real/` is still empty.
- v1 was spent for tuning (its errors drove the generator changes), so the v1
  row is historical: it reflects the models BEFORE the widening and was not
  re-scored. The v2 set was written after the widening and scored once.
- Small samples: 74 addresses, group cells of 2-9 items. Per-group numbers are
  directional only.

### Comparisons (paired bootstrap, 95% interval, micro F1)

| Comparison | Synthetic dev | Hand-written v1 | Hand-written v2 |
|---|---|---|---|
| CRF v1 minus rule baseline | +0.096 [+0.082, +0.111] | +0.081 [+0.038, +0.125] | **+0.056 [-0.006, +0.118]** |
| CRF v2 minus CRF v1 | +0.001 [-0.004, +0.007] | +0.014 [+0.000, +0.029] | -0.007 [-0.025, +0.007] |

On v2 the CRF's lead over the baseline is NOT established (the interval includes
zero). The baseline was deliberately upgraded with the same keyword families,
introducers, landmark patterns and D10 rules the generator learned, so it is not
a strawman. Gazetteer features (v2 model) have now tied with v1 three times;
v1 stays the working model.

## What the widening did (hand-written v2, CRF v1)

TARGETED = new instances of the groups the generator was widened for.
FRESH = constructs deliberately not trained for.

| Group | n | Baseline | CRF v1 |
|---|---|---|---|
| T-keyword (Plot, Apartment, Hse, Ln, Section, Phase, ...) | 8 | 0.918 | 1.000 |
| T-village (Vill / P.O / P.S / Dist introducers) | 8 | 0.806 | 1.000 |
| T-order (postcode or district first) | 6 | 0.964 | 1.000 |
| T-landmark | 7 | 1.000 | 0.828 |
| T-d1 (lone district, district + division) | 9 | 1.000 | 0.885 |
| T-d10 (Shop / Level are O, Ward is AREA) | 8 | 0.920 | 0.920 |
| **targeted overall** | 46 | 0.929 | 0.945 |
| F-punct (newline, `House: 12`, brackets, `/` and `\|` separators) | 8 | 0.754 | 0.754 |
| F-place (Cantonment, DOHS, R/A, C/A) | 6 | 0.653 | 0.955 |
| F-abbrev (Ctg, Dhk) | 2 | 0.571 | 0.857 |
| F-unicode (NFC Bangla) | 3 | 0.556 | 0.778 |
| F-short (very short addresses) | 4 | 1.000 | 0.875 |
| F-other (country first, uppercase, `নম্বর`, a heavier typo) | 5 | 0.857 | 1.000 |
| **fresh overall** | 28 | 0.740 | 0.867 |

Pre-run predictions: targeted 0.93-0.97 (got 0.945), fresh 0.75-0.85 (got 0.867,
slightly better), F-unicode fails some (2 of 3 failed), overall 0.88-0.93 and
beating the baseline (got 0.917, but the margin is not established).

## Remaining errors (CRF v1 on v2: 18 of 74 addresses)

| Cause | Addresses | Next step |
|---|---|---|
| A lone trailing district labelled DIVISION (decision D1), still the top error after targeted work; 2 of 4 follow a landmark, a context with no postcode | 4 | diagnose by context, more data in that shape |
| An upazila with NO area before it labelled AREA (`Savar, Dhaka-1340`); the generator only emits an upazila after an area | 5 | generate upazila-first addresses |
| Separators `/`, `\|` and brackets glue onto the previous entity | 4 | separator variety |
| A BLOCK nested inside a landmark (`next to Uttara Sector-7 Park`) | 1 | landmark variety |
| `Dhk` abbreviation; non-NFC-matching Bangla names | 3 | abbreviations; NFC (below) |

### Unicode normalisation (found while auditing v2)

About a quarter of the gazetteer's Bangla names are stored in a non-NFC form
(15 of 64 districts, 123 of 494 upazilas, 1 of 8 divisions), because `য়` `ড়`
`ঢ়` are single precomposed codepoints there but two codepoints in NFC. A user's
keyboard may produce either, so identical-looking names can arrive as different
strings the model never saw. The tokenizer copes (one token each); the model and
the gazetteer lookups do not. NOT fixed yet, on purpose: fixing it before
scoring would have destroyed the F-unicode measurement. Fix: normalise both sides
to NFC per token, so character offsets never move.

## Process disclosures

- The audit of v2's gold labels found two Bangla names (`ময়মনসিংহ`, `কাউনিয়া`)
  typed differently from the gazetteer. This was before any model saw v2. Their
  lines became a deliberate `F-unicode` category, and two replacement
  `T-` items without those letters keep `T-village` and `T-d1` in Bangla.
- Decisions D7 and D10 arrived while this work was under way and were folded in
  before v2 was scored.
- Not decided, so absent from the generator and both sets: `Union Parishad
  Office` and other building/office names, and `Floor`.

## Rules for the next iteration

v2 is now SPENT for tuning. After the next generator change, write a fresh
`addresses_v3.txt` before reporting a new number. Real addresses, once collected,
supersede all of these.
