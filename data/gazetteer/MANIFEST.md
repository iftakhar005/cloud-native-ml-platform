# Gazetteer manifest

- **Source repository:** https://github.com/ifahimreza/bangladesh-geojson
- **Pinned commit:** `4723ee5f9fecaa79af6266a746cf89c39841a02d`
- **Retrieved:** 2026-10-26
- **Pinned on purpose:** a commit SHA is immutable; `master` is not. Upgrading
  the data is a deliberate, reviewed change, never an accident.

| File | Records | SHA-256 |
|---|---|---|
| bd-divisions.json | 8 | `2d1abe211bb26c35446631e408dd2c47bc5778d7e7a1f7b36eb6960449eeba25` |
| bd-districts.json | 64 | `deb62efbfa585264b7342e97774e76273cf8962d035a7632414aebbd9740dfb6` |
| bd-upazilas.json | 494 | `ae7b5360b5ffac5910e4f6a0e0c533bc1825cded31de3f2b9f1122fca474d2b8` |
| bd-postcodes.json | 1349 | `3826669367d905c8ddba1cdf2c6545c504d2c4b6bdd16504939f9f1ffe824a7c` |

## Licence

These four files are the upstream "administrative reference data":
community-contributed, **MIT** (see LICENSE-MIT.txt, saved from the pinned
commit). The upstream ODbL / CC BY 4.0 terms apply to *other* files in that
repository (bazars, major routes, boundary polygons), which this project
does not use.

## Known provenance gap

Upstream does not state where the underlying records (names, postcodes)
originally came from. MIT is the maintainers' claim over a compilation of
public administrative facts. Low risk, but unverified.

## Counts are a contract

Record counts are asserted in thikana/training/gazetteer.py. If upstream
changes them, the label space changed and loading fails on purpose.
