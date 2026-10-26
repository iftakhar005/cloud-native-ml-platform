# Address label schema v0.1 (DRAFT - decisions marked PROPOSED need owner sign-off)

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

**D1 - A bare "Dhaka" (PROPOSED).** Eight division names are also district names
(measured, below), and "Dhaka" can also mean the city. Rule: one occurrence ->
DISTRICT. If the same name appears twice ("Sylhet, Sylhet"), first is DISTRICT,
second is DIVISION. There is no CITY label in v0.1.
*Why:* annotating city-vs-district intent is subjective, and every extra
label lowers the achievable agreement. Revisit if real data demands it.

**D2 - "12/5" (PROPOSED).** A number, slash, number at the start of an address,
or directly after "house/holding/flat/H#", is HOUSE. A number after
"road/rd/lane" is ROAD. A bare number elsewhere with no keyword is left for
the annotator's judgement and logged as "ambiguous" so it can be counted.

**D3 - Names and phone numbers.** Stripped before labelling. Not a label.

**D4 - A lone "Sadar" (PROPOSED).** Label UPAZILA. The parser later flags the
address as incomplete because the district is missing.

**D5 - Digits (PROPOSED).** Bangla digits (০-৯) are mapped to ASCII (0-9)
before labelling. The mapping is one character to one character, so character
offsets are preserved.

**D6 - Spelling (PROPOSED).** Label what the token IS, not whether it matches
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
