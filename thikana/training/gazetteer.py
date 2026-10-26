"""Load and integrity-check the pinned Bangladesh administrative gazetteer.

Every consumer goes through load_all(), so the data contract lives in one place.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

GAZETTEER_DIR = Path(__file__).resolve().parents[2] / "data" / "gazetteer"

# table -> (file, key wrapping the record list, expected record count).
# The counts are a CONTRACT: if upstream changes them, the label space changed
# and loading fails on purpose rather than training on shifted data.
FILES = {
    "divisions": ("bd-divisions.json", "divisions", 8),
    "districts": ("bd-districts.json", "districts", 64),
    "upazilas": ("bd-upazilas.json", "upazilas", 494),
    "postcodes": ("bd-postcodes.json", "postcodes", 1349),
}

# 12 postcode records carry a district NAME instead of district_id, and spell it
# differently from the districts file ("Nawabganj"). Explicit and hand-checked,
# not fuzzy matching: a new unknown spelling must fail loudly, not be guessed.
DISTRICT_ALIASES = {"Chapinawabganj": "22"}


def _records(filename: str, key: str) -> list[dict]:
    path = GAZETTEER_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"{path} missing - see data/gazetteer/MANIFEST.md")
    # encoding is explicit: the Windows default (cp1252) cannot read Bangla.
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload[key]


def _resolve_districts(postcodes: pd.DataFrame) -> pd.DataFrame:
    """Fill district_id for the records that only carry a district name."""
    missing = postcodes["district_id"].isna()
    if missing.any():
        resolved = postcodes.loc[missing, "district"].map(DISTRICT_ALIASES)
        unknown = sorted(postcodes.loc[missing, "district"][resolved.isna()].unique())
        if unknown:
            raise ValueError(f"Unmapped district spellings in postcodes: {unknown}")
        postcodes.loc[missing, "district_id"] = resolved
    return postcodes.drop(columns=["district"], errors="ignore")


def load_all() -> dict[str, pd.DataFrame]:
    frames = {}
    for table, (filename, key, expected) in FILES.items():
        frame = pd.DataFrame(_records(filename, key))
        if len(frame) != expected:
            raise ValueError(
                f"{filename}: expected {expected} records, got {len(frame)}. "
                "Upstream changed - investigate before continuing."
            )
        frames[table] = frame

    frames["postcodes"] = _resolve_districts(frames["postcodes"])

    # Referential integrity: every foreign key must point at a real row.
    division_ids = set(frames["divisions"]["id"])
    district_ids = set(frames["districts"]["id"])
    if not set(frames["districts"]["division_id"]) <= division_ids:
        raise ValueError("districts reference a division that does not exist")
    if not set(frames["upazilas"]["district_id"]) <= district_ids:
        raise ValueError("upazilas reference a district that does not exist")
    if not set(frames["postcodes"]["district_id"]) <= district_ids:
        raise ValueError("postcodes reference a district that does not exist")
    if not set(frames["postcodes"]["division_id"]) <= division_ids:
        raise ValueError("postcodes reference a division that does not exist")

    return frames
