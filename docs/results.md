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
   **Changed 2026-10-28**, on the owner's request to improve the village result: production is now
   district memory plus the full-table vocabulary features (`crf_all_district_memory_vocab`); the
   evidence is in "Making it better" above.
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

## The village / union fix (decision D12, 2026-10-28)

**Trigger.** A person typed `বুধড়া, গুনবতী` (a village and a union, no cue words) into the live
page; both came back UPAZILA. Decision D12 in `docs/label-schema.md` has the cause (the
generator wrote every rural area in Latin script, so the model only ever saw Bangla
upazilas) and exactly what the generator now does.

**What was measured, in order.** v5 (a diagnostic, written first, 37 addresses) put the
size of the gap at 0.775 micro F1 for the production model. The generator was changed, the
production model retrained, then a fresh v6 (47 addresses, names the generator provably
cannot write) was scored. Micro F1, production model `crf_all_district_memory`:

| Set | Before the fix | After (shipped) | After, with upazila-vocabulary features (adopted next, with district memory: see below) |
|---|---|---|---|
| v1 (70) | 0.983 | 0.990 | 0.983 |
| v2 (74) | 0.928 | 0.952 | 0.942 |
| v3 (69) | 0.919 | 0.910 | 0.933 |
| v4 (65) | 0.897 | 0.915 | 0.942 |
| v5 (37), diagnostic | 0.775 | 0.874 | 0.955 |
| **v6 (47), fresh** | **0.758** | **0.871** | 0.992 |

v6 paired bootstrap, 95% interval: after minus before **+0.114 [+0.051, +0.175]** (excludes
zero); vocabulary-feature model minus the shipped one **+0.121 [+0.067, +0.177]**.

By group on v6 (before, shipped, vocabulary-feature model):

| Group | n | Before | Shipped | Vocabulary features |
|---|---|---|---|---|
| T-bnvillage (bare Bangla village or union, with a district) | 10 | 0.591 | 0.773 | 0.955 |
| T-bnpair (village and union, then upazila and district) | 10 | 0.639 | 0.861 | 1.000 |
| T-bnmixed (Bangla village among English) | 5 | 0.667 | 0.867 | 1.000 |
| R-upazila-bn (real Bangla upazilas, must stay UPAZILA) | 8 | 1.000 | 0.947 | 1.000 |
| R-upazila-en (real English upazilas, must stay UPAZILA) | 7 | 0.941 | 0.882 | 1.000 |

**What this says.**
1. The fix helped, and the interval excludes zero on the fresh set. It did not finish the job:
   `বুধড়া, গুনবতী` now comes out `[AREA] [UPAZILA]` (one of two right), and
   `রামপুর, কাজীপাড়া, বগুড়া` still comes out UPAZILA, UPAZILA, DISTRICT.
2. **It cost something.** A few real upazilas (Kaharole, Dohar, Raninagar, Hatibandha) are now
   sometimes called AREA. Data alone cannot separate "an unseen real upazila" from "an
   unknown village": both are unfamiliar words in the same place. Giving the model more
   examples moves the balance between the two errors; it does not remove the trade-off.
3. **A name list does remove it.** `crf_all_gazetteer` (a "this token is a known upazila name"
   feature) gets both of the user's examples right and scores 0.955 / 0.992 on v5 / v6 with
   no loss on v1-v4. This is the same candidate v4 pointed to (+0.051 there). It was
   adopted in the next step, in combination with district memory ("Making it better").
4. **Read the baseline column with care.** The rule baseline scores 0.973 on v5 and 0.992 on
   v6, because these sets turn on "is this name in the gazetteer?", which a dictionary
   answers exactly. Real villages that share a name with an upazila elsewhere would not be
   so easy for it. Both sets were written by the same author as the generator.

**Seed noise, measured, and what it changed.** Three training seeds, final generator,
micro F1 (`train_all` uses seed 1):

| Model and size | Seed | v1 | v2 | v3 | v4 | v5 | v6 |
|---|---|---|---|---|---|---|---|
| district memory, 4,000 | 1 | 0.983 | 0.945 | 0.891 | 0.879 | 0.883 | 0.879 |
| district memory, 4,000 | 2 | 0.980 | 0.931 | 0.905 | 0.889 | 0.901 | 0.864 |
| district memory, 4,000 | 3 | 0.990 | 0.945 | 0.921 | 0.894 | 0.901 | 0.864 |
| district memory, 8,000 | 1 | 0.990 | 0.952 | 0.910 | 0.915 | 0.874 | 0.871 |
| district memory, 8,000 | 2 | 0.983 | 0.949 | 0.901 | 0.915 | 0.910 | 0.848 |
| district memory, 8,000 | 3 | 0.987 | 0.949 | 0.926 | 0.905 | 0.892 | 0.864 |
| vocabulary features, 4,000 | 1 | 0.980 | 0.942 | 0.928 | 0.937 | 0.937 | 0.977 |
| vocabulary features, 4,000 | 2 | 0.970 | 0.916 | 0.917 | 0.920 | 0.946 | 0.970 |
| vocabulary features, 4,000 | 3 | 0.980 | 0.933 | 0.917 | 0.907 | 0.928 | 0.970 |

At 4,000 examples the same recipe scored between 0.891 and 0.921 on v3 depending only on
the seed, so one unlucky run failed the quality gate (v3 0.891, v4 0.879) after a change
that should not have mattered. Production therefore trains on 8,000 examples
(`PRODUCTION_EXAMPLES`): all three seeds clear every floor, and v4 rises from 0.88-0.89 to
0.91. The split-trained models keep 4,000 so earlier experiments stay comparable. A trade
named plainly: this changes the production recipe, and a different size or seed would land
on slightly different numbers than the ones in the table above.

**Process disclosures.**
- v5 was scored before the generator was changed and its errors drove the change, so it
  is spent and says nothing unbiased. v6 was written after the change and before any model
  saw it.
- v6 was scored by earlier versions of the generator while it was being built (0.886, then
  0.879 for the data-only versions) and then once more after a final generator fix that came
  from a unit-test failure, not from v6 errors (no village pair beside a post office named
  like its upazila). The table shows the shipped model only; the move between versions was
  inside the seed noise above.
- A "before" score of 0.586 on v5 was wrong: the backed-up model had been copied without its
  `.json` sidecar (the district vocabulary), so it was a different model. It was caught
  because the same string gave two different answers. Back up a model with BOTH files.
- Two tests that had passed only by luck of the random stream failed after the change and
  were corrected (an area named "Thanar Hat" with a typo, and a reversed address with no
  district). Neither was a model problem.
- Round-robin sampling of places (the "guarantee exposure" next step above) was tried and
  removed: it was no better than uniform draws across three seeds.

**Not done at this point.** Switching production to the vocabulary features (done next, below);
separate Village and Union labels; any evaluation on real addresses.

## Making it better: district memory plus vocabulary features (2026-10-28)

The "combined candidate" of next step 2 above: district memory AND the full-table token
features ("this token is a known district / division / upazila name"), trained on every
gazetteer record. The model file is `crf_all_district_memory_vocab`.

**How it was chosen.** A fresh sealed set, v7 (51 addresses, 154 gold entities), was written
first and not scored against until the choice was made. The choice used v1-v6 over three
training seeds each, with a rule fixed beforehand: the highest mean over v1-v6, no set under
its gate floor. Range over the three seeds, micro F1:

| Recipe | v1 | v2 | v3 | v4 | v5 | v6 |
|---|---|---|---|---|---|---|
| district memory, 8,000 (the previous step) | .983-.990 | .949-.952 | .901-.926 | .905-.915 | .874-.910 | .848-.871 |
| vocabulary only, 4,000 | .970-.980 | .916-.942 | .917-.928 | .907-.937 | .928-.946 | .970-.977 |
| vocabulary only, 8,000 | .980-.987 | .942-.949 | .926-.933 | .935-.947 | .946-.955 | .977-.992 |
| memory + vocabulary, 4,000 | .987-.997 | .940-.959 | .926-.935 | .947-.952 | .991 | .992-1.000 |
| **memory + vocabulary, 8,000 (adopted)** | .990-.993 | .956-.963 | .933-.935 | .952-.960 | .982-1.000 | .992-1.000 |

Mean over v1-v6 per seed: 0.971, 0.973 and 0.972 for the adopted recipe; 0.965-0.972 at 4,000;
0.952-0.958 vocabulary only; 0.918-0.920 district memory alone. The combined recipes at 4,000
and 8,000 examples are close; 8,000 was kept because production already trains on that and it
had the tightest range on v2.

**The sealed score.** v7, scored once for each system (micro F1):

| System | v7 |
|---|---|
| model before any of this (district memory, 4,000, Latin-only villages) | 0.818 |
| district memory, 8,000, village data only (previous step) | 0.929 |
| vocabulary features only (`crf_all_gazetteer`) | 0.968 |
| **memory + vocabulary (adopted)** | **0.981** |
| rule baseline (full gazetteer lookup) | 0.981 |

Paired bootstrap, 95% interval: adopted minus the model before **+0.163 [+0.104, +0.225]**;
adopted minus the previous step **+0.053 [+0.019, +0.095]**; adopted minus vocabulary only
+0.013 [0.000, +0.032] (not distinguishable); adopted minus the rule baseline 0.000
[-0.019, +0.019] (tied). On v4 the adopted model scores 0.952 against 0.897 before and
against 0.918 for the baseline (+0.034 over the baseline, interval [-0.024, +0.082]: not
established).

The user's own examples now come out right: `বুধড়া, গুনবতী` is `[AREA] [AREA]`,
`বুধড়া, গুনবতী, বগুড়া` adds a DISTRICT, and `রামপুর, কাজীপাড়া, বগুড়া` is AREA, AREA, DISTRICT,
while `কাহালু, বগুড়া` stays UPAZILA, DISTRICT.

**What is still wrong.** 3 of 51 on v7: a real English upazila (`Jhenaigati`) called AREA, and
two typo cases (`Hosue 9` read as an AREA, and the misspelled upazila `Araihazaar`). Typos
inside keywords and names were an open problem before and remain one. The earlier trade-off
(real upazilas swallowed by villages) is mostly gone: the R-upazila groups on v7 are 1.000
(Bangla) and 0.947 (English).

**How to read it.** The rule baseline ties the CRF on v7 and is within 0.01 of it on v6,
because these sets turn on "is this name in the gazetteer?", which a dictionary answers
exactly. The CRF now matches it on that, and its other strengths (typos inside keywords,
number formats, odd order) were shown in earlier rounds. Both sets were written by the same
author as the generator and neither is real. The numbers say the village problem is fixed on
made-up villages; they say nothing about real ones, which will share names with upazilas
elsewhere in ways nobody here wrote down.

**What changed in the repository.** `PRODUCTION_MODEL`, the default `THIKANA_MODEL_PATH`, the
Dockerfile, `.dockerignore`, the CI artifact list and the docs now name
`crf_all_district_memory_vocab`. The gate floors were RAISED (v2 0.920, v4 0.920, v6 0.950;
v1 0.970 and v3 0.900 unchanged), each about 3 points under the lowest of the three seeds.
`train_all` now trains four models (about 30 s each) so earlier comparisons stay
reproducible. The model file is 509 KB. Not checked: that the Linux-trained model predicts
like the Windows-trained one (it did for the previous model); the first CI run is that check.

v7 is now SPENT as well.

## Rules for the next iteration

v4, v5, v6 and v7 are SPENT. Change the generator or training, decide the primary comparison in
advance, then write a fresh `addresses_v8.txt` before reporting a new number.
Real addresses, once collected, supersede all of these.
