import hashlib
import re
from pathlib import Path

import pytest

from thikana.training import gazetteer
from thikana.training.gazetteer import FILES, load_all


@pytest.fixture(scope="module")
def frames():
    return load_all()


def test_record_counts_match_the_contract(frames):
    for table, (_, _, expected) in FILES.items():
        assert len(frames[table]) == expected


def test_ids_are_strings_so_joins_do_not_silently_miss(frames):
    assert frames["districts"]["id"].map(type).eq(str).all()
    assert frames["upazilas"]["district_id"].map(type).eq(str).all()
    assert frames["postcodes"]["district_id"].map(type).eq(str).all()


def test_every_postcode_has_a_district_after_alias_resolution(frames):
    assert frames["postcodes"]["district_id"].notna().all()


def test_postcodes_are_four_digits_and_unique(frames):
    codes = frames["postcodes"]["postCode"]
    assert codes.str.fullmatch(r"\d{4}").all()
    assert codes.is_unique


def test_unknown_district_spelling_fails_loudly_instead_of_being_guessed(monkeypatch):
    monkeypatch.setattr(gazetteer, "DISTRICT_ALIASES", {})
    with pytest.raises(ValueError, match="Unmapped district spellings"):
        load_all()


def test_data_files_are_byte_identical_to_the_manifest():
    """Fails if git (or anything else) rewrites line endings in the data."""
    manifest = (gazetteer.GAZETTEER_DIR / "MANIFEST.md").read_text(encoding="utf-8")
    expected = dict(re.findall(r"\| (bd-[a-z]+\.json) \| \d+ \| `([0-9a-f]{64})`", manifest))
    assert len(expected) == len(FILES)
    for filename, digest in expected.items():
        actual = hashlib.sha256((gazetteer.GAZETTEER_DIR / filename).read_bytes()).hexdigest()
        assert actual == digest, f"{filename} bytes changed"
