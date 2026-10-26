"""Profile the gazetteer. The goal is to find the AMBIGUITIES we must design for."""

import sys

from thikana.training.gazetteer import load_all


def main() -> None:
    # The Windows console defaults to cp1252, which cannot print Bangla.
    sys.stdout.reconfigure(encoding="utf-8")
    f = load_all()
    divisions, districts = f["divisions"], f["districts"]
    upazilas, postcodes = f["upazilas"], f["postcodes"]

    lower = lambda s: s.str.strip().str.lower()  # noqa: E731

    counts = lower(upazilas["name"]).value_counts()
    repeated = counts[counts > 1]
    print(f"upazila names used by more than one upazila: {len(repeated)}")
    print(repeated.head(8).to_string())
    print("  ^ unresolvable from the name alone - needs surrounding context")

    d, u, v = (set(lower(x["name"])) for x in (districts, upazilas, divisions))
    print(f"\nnames that are both a district and an upazila: {len(d & u)}")
    print("  examples:", sorted(d & u)[:8])
    print(f"names that are both a division and a district: {len(v & d)}")
    print("  examples:", sorted(v & d))

    print("\nBangla coverage (missing or empty bn_name):")
    for name, frame in (("divisions", divisions), ("districts", districts), ("upazilas", upazilas)):
        bad = int((frame["bn_name"].isna() | (frame["bn_name"].str.strip() == "")).sum())
        print(f"  {name}: {bad} of {len(frame)}")
    print("  postcodes: no Bangla names exist at all")

    print("\nstray leading/trailing whitespace in names:")
    for name, frame in (("divisions", divisions), ("districts", districts),
                        ("upazilas", upazilas), ("postcodes", postcodes)):
        for column in frame.columns:
            if column in ("lat", "long", "id", "division_id", "district_id"):
                continue
            values = frame[column].astype(str)
            dirty = int((values != values.str.strip()).sum())
            if dirty:
                print(f"  {name}.{column}: {dirty} of {len(frame)}")

    known = set(zip(upazilas["district_id"], lower(upazilas["name"])))
    in_table = [
        (r.district_id, r.upazila.strip().lower()) in known for r in postcodes.itertuples()
    ]
    share = sum(in_table) / len(in_table)
    print(f"\npostcode rows whose upazila name EXACTLY matches the upazilas table: {share:.1%}")
    print(f"  ^ the other {1 - share:.1%} differ: some are spelling variants, some look like "
          "a different administrative unit (measured in Task 1 notes, not assumed)")
    drift = postcodes.loc[[not x for x in in_table], ["upazila", "district_id"]].drop_duplicates()
    print("  examples of non-matching postcode upazila names:")
    print(drift.head(8).to_string(index=False))


if __name__ == "__main__":
    main()
