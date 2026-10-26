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

(D9 from this list was accepted; see "Decision added during Task 4" below.)

Hand-written probe addresses (thikana/training/probe.py) showed the model
forcing real-world constructs into the nearest label. These need a schema
decision before more training data is generated:

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

## Decision added during Task 4

**D9 - Numbered area names are ONE AREA span (accepted 2026-10-26).** A number
attached directly to an area name, with a hyphen, a spaced hyphen, or a space,
belongs to the name: `Mirpur-10`, `Mirpur 10`, `Mirpur - 10`, `Dhanmondi 27`,
`Gulshan-2`, `মিরপুর-১০`. The span includes the hyphen and the number, so the
tokens `Mirpur` `-` `10` are tagged B-AREA I-AREA I-AREA.

Boundary (my reading, confirm if wrong): keyword-introduced units stay BLOCK.
`Uttara Sector 7` is AREA `Uttara` plus BLOCK `Sector 7`, because BLOCK already
covers "Sector 10". An earlier draft of this note listed `Uttara Sector 7`
under D9; that was inconsistent with BLOCK and is corrected here.

Why it matters: in the original synthetic data a place name followed by a
hyphen and digits was a POSTCODE in 100% of 1,511 cases (measured), and the
model learned that as a rule, labelling the 2-digit "10" in "Mirpur-10" a
POSTCODE. A POSTCODE is always exactly 4 digits.

## D9 measured effect (synthetic data only; 2026-10-26)

Shortcut in the data, before vs after (number directly after "X-" where X is
a place name, training split): POSTCODE in 100% of 1,511 cases -> 87.0% of
1,740 cases. After a name, 4 digits are always POSTCODE (1,514) and 1-2 digits
are always AREA (226); keyword-led 4-digit holding numbers are HOUSE (19).

Controlled comparison on the SAME new dev set (600 addresses, 46 containing a
numbered area, so the slice is small and its uncertainty wide):

| | CRF v1 trained before D9 | CRF v1 retrained with D9 data | rule baseline (+D9 rule) |
|---|---|---|---|
| micro F1, all dev | 0.955 | 0.981 | 0.886 |
| micro F1, numbered-area slice | 0.730 | 0.975 | 0.931 |
| POSTCODE spans not 4 chars long | 9 | 0 | 0 |

Scored hand-written probes (thikana/training/probe.py; my annotations from
this schema, NOT a test set): 3 of 13 before, 12 of 13 after. The one failure
is a lone trailing "Dhaka" labelled DIVISION (decision D1), unrelated to D9.

Method note: the "before" model was trained on the generator as of commit
5cc0434; reproduce it by checking that commit out and running train.py.
Caution: dev sets differ between generator versions, so only same-dev
comparisons like the table above are valid; overall dev F1 fell 0.985 -> 0.981
across retrains because the benchmark got harder, not the model worse.

## Decisions added during Task 5 (accepted 2026-10-26)

**D7 - Introducers are O (accepted; was "awaiting confirmation").** Words that
introduce a value (`Dist:`, `District:`, `Zila`, `P.O:`, `Post:`, `Thana:`,
`P.S`, `Upazila:`, `Vill:`, `Village:`, `Gram`, and Bangla `গ্রাম`, `ডাকঘর`,
`থানা`, `জেলা`) are labelled O, including any `:` / `-` after them. The value
that follows gets its normal entity label.

**D10 - Shop and Level are O; Ward is AREA (accepted).**
- `Shop 12`, `Shop No-12`, `Level 3`, `দোকান ১২`, `লেভেল ৩` are O: the keyword
  AND the number. They are not forced into HOUSE. A new label is added only if
  the product genuinely needs one.
- `Ward 5`, `Ward No. 5`, `Ward-5`, `ওয়ার্ড ৫` are ONE AREA span, keyword and
  number included. (My reading of "Ward can be AREA"; the keyword is part of the
  span, as in `Road 5`.)
- NOT covered by this decision, so deliberately absent from the generator and
  the evaluation sets until decided: `Union Parishad Office` (and similar office
  or building names) and `Floor` (a close cousin of `Level`).

## Decisions added during Task 6

**D11 - A name shared by post office and upazila (PROVISIONAL, awaiting your
confirmation).** 32% of administrative-upazila records (247 of 781) have a post
office named exactly like the upazila (Amtali, Bamna, Betagi, ...), so a lone
`Savar, Dhaka` is genuinely ambiguous. Tie-break within D8:
- once -> the UPAZILA;
- twice -> the first is the post office (AREA), the second the UPAZILA, in the
  usual small-to-large order; in REVERSED order the roles follow the hierarchy
  (the larger unit, the UPAZILA, comes first);
- an introducer (`P.O:`, `Post:`, `ডাকঘর:`) or a number (`Amtali-6`) marks it
  as a post-office name -> AREA.
Easy to revert: one `if` in the generator. The hand-written sets v1 and v2
were annotated with the same lone-name convention.

**Unicode (implementation rule, not a labelling decision).** Bangla `য়` `ড়`
`ঢ়` can be typed as one codepoint (how the gazetteer stores them) or as two
(NFC); about a quarter of the gazetteer's Bangla names are affected (15/64
districts, 123/494 upazilas). Names are now compared in NFC PER TOKEN, after
tokenising, so character offsets into the user's original text never move.
