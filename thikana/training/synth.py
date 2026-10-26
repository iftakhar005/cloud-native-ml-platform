"""Synthetic labelled addresses built from the gazetteer.

Labels are correct by construction: text is assembled from labelled pieces and
noise is applied to the pieces BEFORE joining, so character spans never drift.

Limits to remember: neighbourhood names come from a small hand-written list,
ordering is almost always small-to-large, and every kind of mess here is one a
human thought of. Real addresses will contain mess that is not. That gap is
what the hand-labelled real test set measures.
"""

from __future__ import annotations

import random
import re
import sys
from collections import defaultdict
from dataclasses import dataclass

from thikana.schema import Example, Span
from thikana.text import normalize_digits, tokenize, to_bio
from thikana.training.gazetteer import load_all

BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
BN_LETTERS = dict(zip("ABCDEFGH", ["এ", "বি", "সি", "ডি", "ই", "এফ", "জি", "এইচ"]))

# Hand-written, NOT authoritative: (english, bangla, gazetteer district name).
URBAN_AREAS = [
    ("Mirpur", "মিরপুর", "Dhaka"), ("Uttara", "উত্তরা", "Dhaka"),
    ("Dhanmondi", "ধানমন্ডি", "Dhaka"), ("Gulshan", "গুলশান", "Dhaka"),
    ("Banani", "বনানী", "Dhaka"), ("Bashundhara R/A", "বসুন্ধরা আ/এ", "Dhaka"),
    ("Mohammadpur", "মোহাম্মদপুর", "Dhaka"), ("Motijheel", "মতিঝিল", "Dhaka"),
    ("Khilgaon", "খিলগাঁও", "Dhaka"), ("Agrabad", "আগ্রাবাদ", "Chattogram"),
    ("Nasirabad", "নাসিরাবাদ", "Chattogram"), ("Zindabazar", "জিন্দাবাজার", "Sylhet"),
    ("Upashahar", "উপশহর", "Sylhet"), ("Sonadanga", "সোনাডাঙ্গা", "Khulna"),
    ("Shaheb Bazar", "সাহেব বাজার", "Rajshahi"),
]
LANDMARKS = [
    ("Jamuna Future Park", "যমুনা ফিউচার পার্ক"), ("Central Mosque", "কেন্দ্রীয় মসজিদ"),
    ("City Hospital", "সিটি হাসপাতাল"), ("Bus Stand", "বাস স্ট্যান্ড"),
    ("Railway Station", "রেলওয়ে স্টেশন"),
]
LANDMARK_WORDS = ("near", "beside", "opposite", "behind")

# Hand-written, NOT authoritative: area names that carry a number, with the
# highest number used (decision D9). Mirpur has sections 1-14, Dhanmondi 1-32,
# Gulshan 1-2.
NUMBERED_AREAS = {"Mirpur": 14, "Dhanmondi": 32, "Gulshan": 2}

# A deliberate augmentation, NOT observed data: a few rural post-office names
# also get a number. Without it the model could learn the shortcut "Mirpur /
# Dhanmondi / Gulshan + digits" instead of the structure "a name followed by a
# 1-2 digit number is part of the name".
RURAL_NUMBERED_RATE = 0.04

# Spellings people really write that differ from the gazetteer's.
SPELLING_VARIANTS = {
    "Chattogram": ["Chittagong", "Chattagram"], "Cumilla": ["Comilla"],
    "Barishal": ["Barisal"], "Bogura": ["Bogra"], "Jashore": ["Jessore"],
    "Mymensingh": ["Mymensing"], "Sylhet": ["Sylet"],
}


@dataclass(frozen=True)
class Place:
    """One internally consistent real tuple from a postcode record."""
    area: str
    upazila: str
    upazila_bn: str | None
    upazila_admin: bool  # decision D8: UPAZILA only for names in the upazilas table
    district: str
    district_bn: str
    division: str
    division_bn: str
    postcode: str


def _clean_upazila(name: str) -> str:
    return re.sub(r"\s+U\.?P\.?O\b\.?", "", name).strip()


def build_places(frames: dict | None = None) -> list[Place]:
    f = frames or load_all()
    districts = f["districts"].set_index("id")
    divisions = f["divisions"].set_index("id")
    upazila_bn = {
        (r.district_id, r.name.strip().lower()): r.bn_name.strip()
        for r in f["upazilas"].itertuples()
    }
    places = []
    for r in f["postcodes"].itertuples():
        d = districts.loc[r.district_id]
        v = divisions.loc[d["division_id"]]
        upazila = _clean_upazila(r.upazila)
        key = (r.district_id, upazila.lower())
        places.append(Place(
            area=r.postOffice.strip(), upazila=upazila,
            upazila_bn=upazila_bn.get(key), upazila_admin=key in upazila_bn,
            district=d["name"].strip(), district_bn=d["bn_name"].strip(),
            division=v["name"].strip(), division_bn=v["bn_name"].strip(),
            postcode=r.postCode,
        ))
    return places


def split_places(places, seed=13, fractions=(0.7, 0.15, 0.15)) -> dict[str, list[Place]]:
    """Split RECORDS (not generated strings), so test names are unseen in training."""
    order = list(places)
    random.Random(seed).shuffle(order)
    a = int(len(order) * fractions[0])
    b = a + int(len(order) * fractions[1])
    return {"train": order[:a], "dev": order[a:b], "test": order[b:]}


# ---- noise ---------------------------------------------------------------

def _typo(word: str, rng: random.Random) -> str:
    i = rng.randrange(1, len(word) - 1)
    op = rng.choice(("drop", "double", "swap"))
    if op == "drop":
        return word[:i] + word[i + 1:]
    if op == "double":
        return word[:i] + word[i] + word[i:]
    return word[:i] + word[i + 1] + word[i] + word[i + 2:]


def _latin(name: str, rng: random.Random, typo_rate: float = 0.12) -> str:
    original = name
    if name in SPELLING_VARIANTS and rng.random() < 0.4:
        name = rng.choice(SPELLING_VARIANTS[name])
    if "ganj" in name and rng.random() < 0.2:
        name = name.replace("ganj", "gonj")
    if len(name) >= 5 and rng.random() < typo_rate:
        name = _typo(name, rng)
    return name.strip() or original  # a swap can push a space to the edge


def _pick_script(mode: str, rng: random.Random) -> bool:
    """True -> write this field in Bangla."""
    return mode == "bn" or (mode == "mixed" and rng.random() < 0.5)


def _digits(text: str, bangla: bool, rng: random.Random) -> str:
    return text.translate(BN_DIGITS) if bangla and rng.random() < 0.7 else text


def _house(rng, bn):
    # Real holding numbers can have 4 digits. Keep those keyword-led so they
    # are not confused with a postcode; otherwise "4 digits" becomes a shortcut.
    big = rng.random() < 0.06
    n = rng.randint(1000, 2999) if big else rng.randint(1, 150)
    m = rng.randint(1, 12)
    forms = ([f"বাসা {n}", f"বাড়ি {n}", f"বাসা নং {n}", f"{n}/{m}"] if bn else
             [f"House {n}", f"House-{n}", f"H#{n}", f"H-{n}", f"Holding {n}", f"{n}",
              f"{n}/{m}", f"Flat {n}{rng.choice('ABCD')}"])
    if big:
        forms = [f for f in forms if not f[0].isdigit()]
    return _digits(rng.choice(forms), bn, rng)


def _numbered(surface: str, number: int, bangla: bool, rng: random.Random) -> str:
    """'Mirpur' -> 'Mirpur-10' / 'Mirpur 10' / 'Mirpur - 10' (D9: one AREA span)."""
    return surface + rng.choice(("-", "-", " ", " - ")) + _digits(str(number), bangla, rng)


def _road(rng, bn):
    n = rng.randint(1, 40)
    forms = ([f"রোড {n}", f"রোড নং {n}", f"লেন {n}"] if bn else
             [f"Road {n}", f"Road-{n}", f"Rd {n}", f"R#{n}", f"Lane {n}"])
    return _digits(rng.choice(forms), bn, rng)


def _block(rng, bn):
    letter, n = rng.choice("ABCDEFGH"), rng.randint(1, 12)
    forms = ([f"ব্লক {BN_LETTERS[letter]}", f"সেক্টর {n}"] if bn else
             [f"Block {letter}", f"Block-{letter}", f"Blk {letter}", f"Sector {n}"])
    return _digits(rng.choice(forms), bn, rng)


def _landmark(rng, bn):
    en, bangla = rng.choice(LANDMARKS)
    return f"{bangla} এর পাশে" if bn else f"{rng.choice(LANDMARK_WORDS)} {en}"


# ---- assembling one address ----------------------------------------------

def _one(rng, places, by_district, urban_pool) -> Example:
    mode = rng.choices(("en", "bn", "mixed"), (0.6, 0.15, 0.25))[0]
    urban = bool(urban_pool) and rng.random() < 0.5
    if urban:
        area_en, area_bn, district = rng.choice(urban_pool)
        place = rng.choice(by_district[district])
        p_house, p_road, p_block = 0.75, 0.6, 0.35
    else:
        place = rng.choice(places)
        area_en, area_bn = place.area, None
        p_house, p_road, p_block = 0.15, 0.1, 0.0

    def name(en, bn):
        """Surface form of a name field, in Bangla if possible and chosen."""
        if bn is not None and _pick_script(mode, rng):
            return bn
        return _latin(en, rng)

    chunks: list[list[tuple[str, str | None]]] = []
    for p, label, make in ((p_house, "HOUSE", _house), (p_road, "ROAD", _road),
                           (p_block, "BLOCK", _block)):
        if rng.random() < p:
            chunks.append([(make(rng, _pick_script(mode, rng)), label)])
    if rng.random() < 0.10:
        landmark = [(_landmark(rng, _pick_script(mode, rng)), "LANDMARK")]
        chunks.insert(rng.randint(0, len(chunks)), landmark)

    use_bn = area_bn is not None and _pick_script(mode, rng)
    area = area_bn if use_bn else _latin(area_en, rng)
    top = NUMBERED_AREAS.get(area_en) if urban else None
    if top and rng.random() < 0.6:  # decision D9
        area = _numbered(area, rng.randint(1, top), use_bn, rng)
    elif not urban and rng.random() < RURAL_NUMBERED_RATE:
        area = _numbered(area, rng.randint(1, 9), False, rng)
    area_chunk = [(area, "AREA")]
    if not urban and rng.random() < 0.10:
        area_chunk.insert(0, ("P.O: ", None))
    if rng.random() < 0.92:  # real addresses sometimes have no area at all
        chunks.append(area_chunk)

    if not urban and place.upazila_admin and rng.random() < 0.85:
        upazila = place.upazila
        if upazila.endswith("Sadar") and rng.random() < 0.3:
            upazila = "Sadar"  # decision D4: a lone "Sadar" is still an UPAZILA
        if upazila.lower() != place.area.lower() or rng.random() < 0.5:
            kw = [("Upazila: ", None)] if rng.random() < 0.10 else []
            chunks.append(kw + [(name(upazila, place.upazila_bn), "UPAZILA")])

    district_chunk: list[tuple[str, str | None]] = []
    if rng.random() < 0.93:
        if rng.random() < 0.10:
            district_chunk.append(("জেলা: " if mode == "bn" else "Dist: ", None))
        district_chunk.append((name(place.district, place.district_bn), "DISTRICT"))
    if rng.random() < 0.80:
        glue = rng.choice(("-", " ", ", ", " - ")) if district_chunk else ""
        code = _digits(place.postcode, _pick_script(mode, rng), rng)
        district_chunk += ([(glue, None)] if glue else []) + [(code, "POSTCODE")]
    if district_chunk:
        chunks.append(district_chunk)

    # Decision D1: DISTRICT first, DIVISION after. A lone occurrence of a name
    # that is both is a DISTRICT, so a division is only emitted beside a district.
    has_district = any(label == "DISTRICT" for _, label in district_chunk)
    if has_district and rng.random() < 0.20:
        chunks.append([(name(place.division, place.division_bn), "DIVISION")])
    if rng.random() < 0.10:
        chunks.append([("বাংলাদেশ" if mode == "bn" else "Bangladesh", None)])

    if not chunks:  # never emit an empty address
        chunks.append(area_chunk)

    base_sep = rng.choices((", ", ",", " ", " - ", "; "), (0.55, 0.15, 0.15, 0.08, 0.07))[0]
    vary_sep = rng.random() < 0.25
    case = rng.choices((str, str.lower, str.upper), (0.85, 0.10, 0.05))[0]

    text, spans = "", []
    for i, chunk in enumerate(chunks):
        if i:
            text += rng.choice((", ", " ", " - ")) if vary_sep else base_sep
        for piece, label in chunk:
            piece = case(piece)
            if label:
                spans.append(Span(len(text), len(text) + len(piece), label))
            text += piece
    return Example(text, tuple(spans))


def generate(places, n: int, seed: int, exclude=frozenset()) -> list[Example]:
    """n unique examples; strings in `exclude` are skipped (cross-split leakage)."""
    rng = random.Random(seed)
    by_district = defaultdict(list)
    for p in places:
        by_district[p.district].append(p)
    urban_pool = [a for a in URBAN_AREAS if a[2] in by_district]

    seen, out = set(exclude), []
    for _ in range(50 * n):
        example = _one(rng, places, by_district, urban_pool)
        if example.text not in seen:
            seen.add(example.text)
            out.append(example)
            if len(out) == n:
                return out
    raise RuntimeError(f"could only produce {len(out)} of {n} unique examples")


DATASET_SIZES = {"train": 4000, "dev": 600, "test": 600}
DATASET_SEEDS = {"train": 1, "dev": 2, "test": 3}


def build_datasets(split_seed: int = 13) -> tuple[dict[str, list[Place]], dict[str, list[Example]]]:
    """The one canonical train/dev/test construction. Everything is scored on this.

    dev and test never repeat a string that train contains (nor each other).
    """
    splits = split_places(build_places(), seed=split_seed)
    data, seen = {}, set()
    for name in ("train", "dev", "test"):
        data[name] = generate(splits[name], DATASET_SIZES[name],
                              DATASET_SEEDS[name], exclude=frozenset(seen))
        seen |= {e.text for e in data[name]}
    return splits, data


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    splits = split_places(build_places())
    train = generate(splits["train"], 3000, seed=1)
    print({k: len(v) for k, v in splits.items()}, "<- postcode records per split")

    counts = defaultdict(int)
    for e in train:
        for s in e.spans:
            counts[s.label] += 1
    print("entity counts in 3000 training examples:", dict(sorted(counts.items())))
    bangla = sum(any("ঀ" <= c <= "৿" for c in e.text) for e in train) / len(train)
    print(f"examples containing any Bangla script: {bangla:.0%}\n")

    for e in train[:10]:
        tokens = tokenize(normalize_digits(e.text))
        tags = to_bio(tokens, e.spans)
        print(e.text)
        print("   ", " ".join(f"{t.text}/{g}" for t, g in zip(tokens, tags)))


if __name__ == "__main__":
    main()
