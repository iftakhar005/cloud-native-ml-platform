# Hand-written evaluation set (NOT real data)

**These are not real addresses.** They were written by an AI assistant from
general knowledge of Bangladeshi address conventions, because no real addresses
had been collected. Any person, house number or postcode here is invented or
incidental. `data/real/` is the place for genuinely collected addresses and is
still empty.

## What this set is for

- Testing the parser on formats and vocabulary the synthetic generator does not
  produce (keyword spellings, unseen neighbourhoods, village forms, reversed
  order, a Bangla landmark with an attached genitive, spelling variants).
- Building and exercising the whole evaluation pipeline, so real addresses can
  be dropped in later with no new code.

## What it is NOT

- Not evidence of how the parser performs on real addresses.
- Not independent: the same author wrote the generator and this set, so the
  author's mental model of an address appears in both. The synthetic-to-
  hand-written gap measured here is probably a LOWER BOUND on the real gap.
- Never describe it as real or collected data (CV, README, interviews).
  Honest wording: "a small hand-written evaluation set".

## Rules

1. Never used for training or tuning. If errors found here drive a generator
   change, this set is spent: write a fresh v2 before claiming a new number.
2. Gold labels follow `docs/label-schema.md` (D1-D9; D7 as implemented). D10
   constructs (Shop, Level, Ward) are deliberately excluded.
3. Annotation conventions: a keyword-led unit is its own span (`Flat 5B` and
   `House 23` are two HOUSE spans); introducer words (`Vill:`, `P.O:`, `Dist:`)
   and `Bangladesh` are O; `Section 6` is BLOCK but `Mirpur-6` is AREA.
4. `python -m thikana.training.handwritten` audits the gold labels against the
   gazetteer before any model is scored.

Format: `style ::: annotated`, with `{LABEL|surface}` markup. Deliberate
spelling variants are declared on a `#variants:` line.

## Status of the sets (2026-10-26)

- `addresses_v1.txt` - SPENT. Its errors drove the first generator widening.
- `addresses_v2.txt` - SPENT. Scored once; its errors drove the second round.
- `addresses_v3.txt` - SPENT. Written after the third round of fixes and scored
  once. Items are tagged T- (this round's fixes), R- (earlier fixes, new
  instances: regression guards) or F- (constructs deliberately not trained for).
  The T-unicode items are generated from the gazetteer and passed through NFC.
- Next: a fresh `addresses_v4.txt` before reporting any new number.
