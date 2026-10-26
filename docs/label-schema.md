# Address label schema v0.1 (ACCEPTED 2026-10-26: D1-D6 signed off by the project owner)

Each token of an address gets exactly one label. BIO prefixes (B-/I-) are added
at training time, so annotators only choose the entity type.

## Labels

| Label | Means | Examples |
|---|---|---|
| HOUSE | house / holding / flat / plot number | `12`, `H#12`, `বাসা ১২`, `12/A` |
| ROAD | road / lane / avenue identifier | `Road 5`, `rd-5`, `Lane 3` |
| BLOCK | block / sector / phase inside a planned area | `Block C`, `Sector 10` |
| AREA | neighbourhood, village, union, R/A name | `Bashundhara R/A`, `Mirpur DOHS` |
| UPAZILA | upazila / thana | `Vatara`, `Savar`, `Sadar` |
| DISTRICT | district (also used for a bare city name, see D1) | `Dhaka`, `Cumilla` |
| DIVISION | division | `Sylhet` |
| POSTCODE | 4-digit postcode | `1229` |
| LANDMARK | navigation hint, not an administrative unit | `beside Jamuna Future Park` |
| O | everything else: punctuation, filler, "Bangladesh" | `,` `-` |

Recipient names and phone numbers are NOT labels. They are removed before
parsing (privacy) and never reach the model or the logs.

## Decisions

**D1 - A bare "Dhaka" (accepted).** Eight division names are also district names
(measured, below), and "Dhaka" can also mean the city. Rule: one occurrence ->
DISTRICT. If the same name appears twice ("Sylhet, Sylhet"), first is DISTRICT,
second is DIVISION. There is no CITY label in v0.1.
*Why:* annotating city-vs-district intent is subjective, and every extra
label lowers the achievable agreement. Revisit if real data demands it.

**D2 - "12/5" (accepted).** A number, slash, number at the start of an address,
or directly after "house/holding/flat/H#", is HOUSE. A number after
"road/rd/lane" is ROAD. A bare number elsewhere with no keyword is left for
the annotator's judgement and logged as "ambiguous" so it can be counted.

**D3 - Names and phone numbers.** Stripped before labelling. Not a label.

**D4 - A lone "Sadar" (accepted).** Label UPAZILA. The parser later flags the
address as incomplete because the district is missing.

**D5 - Digits (accepted).** Bangla digits (০-৯) are mapped to ASCII (0-9)
before labelling. The mapping is one character to one character, so character
offsets are preserved.

**D6 - Spelling (accepted).** Label what the token IS, not whether it matches
the gazetteer. `Chapai Nawabganj` and `Nawabganj` are both DISTRICT.
Matching to the gazetteer is a separate, later step.

## What the data told us (measured 2026-10-26, pinned gazetteer 4723ee5)

- 12 upazila names are shared by more than one upazila (e.g. `Kaliganj` x4).
  Predicted to be much higher ("Sadar" everywhere); it was not, because the
  table prefixes the district name (`Nawabganj Sadar`).
- All 8 division names are also district names -> D1 is unavoidable.
- 4 names are both a district and an upazila (e.g. `Nawabganj`, `Sherpur`).
- Bangla names: complete for divisions, districts, upazilas. None for postcodes.
- One real district has different spellings across files from the same repo:
  `Nawabganj` (districts) vs `Chapinawabganj` (postcodes). Also `Sirajgonj`.
- Postcode "upazila" vs upazilas table, after stripping `UPO`/`U.P.O`:
  57.9% exact, 22.4% near (similarity >= 0.8, plausibly spelling variants),
  19.7% no close match (look like localities or sub-units, NOT verified).
  The 0.8 cut-off is arbitrary; treat these as rough proportions.

## Worked examples (to be completed from real addresses)

<!-- Five real addresses, every token labelled. Do this by hand. -->

## Clarification added during Task 2 (D7 - awaiting confirmation)

**D7 - Introducer words are O.** Words that merely introduce an administrative
name ("Dist:", "Upazila:", "P.O:", "জেলা:") are labelled O; only the name itself
is the entity. This differs from HOUSE / ROAD / BLOCK, where the keyword is
PART of the span ("Road 5", "বাসা ১২") as in the examples above. The generator
already follows this rule, so confirm it or tell me to change it.

## Decision added during Task 3

**D8 - UPAZILA means an administrative upazila (accepted 2026-10-26).** Only
names in the 494-row upazilas table are UPAZILA. Any other thana or
neighbourhood name is AREA. Motivation: 7 of 15 well-known Dhaka
neighbourhoods are also listed as "upazila" in the postcode file, so one
string carried two labels. Note a name can still legitimately be both:
"Mohammadpur" is a Dhaka neighbourhood AND an upazila of Magura.

## Open questions raised by the brittleness probes (NOT yet decisions)

Hand-written probe addresses (thikana/training/probe.py) showed the model
forcing real-world constructs into the nearest label. These need a schema
decision before more training data is generated:

**D9 - Numbered areas.** "Mirpur-10", "Dhanmondi 27", "Uttara Sector 7".
Proposed: the number is PART of the AREA name, so "Mirpur-10" is one AREA
span. Currently the generator never produces these, and the model labelled the
"10" in "Mirpur-10" as a POSTCODE.

**D10 - Constructs with no label.** "Level 3", "Ward 5", "Shop 12", "Union
Parishad Office". Options: (a) add labels, (b) map to existing ones (Shop -> HOUSE,
Level -> HOUSE, Ward -> AREA), (c) label O and accept the information is
dropped. Needs your call.

## Measured results so far (synthetic dev only; says nothing about real addresses)

- Context-free ceiling for name strings: 90.0% (a pure lookup cannot exceed it).
- Rule baseline micro F1 0.880; CRF v1 0.985; CRF v2 (+gazetteer features) 0.988.
- v1 minus baseline: +0.104, 95% interval [+0.090, +0.118].
- v2 minus v1: +0.003, 95% interval [-0.002, +0.008] -> NOT distinguishable
  from zero; v1 kept (simpler, no extra artifact).
