"""Synthetic labelled addresses built from the gazetteer.

Labels are correct by construction: text is assembled from labelled pieces and
noise is applied to the pieces BEFORE joining, so character spans never drift.

Limits to remember: neighbourhood names come from a small hand-written list,
and every kind of mess here is one a human thought of. Real addresses will
contain mess that is not. That gap is what hand-written and, eventually, real
evaluation sets measure.
"""

from __future__ import annotations

import random
import re
import sys
import unicodedata
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
    # more cities, so a lone trailing district is not mostly "Dhaka" (decision D1)
    ("Amberkhana", "আম্বরখানা", "Sylhet"), ("Subid Bazar", "সুবিদবাজার", "Sylhet"),
    ("Khulshi", "খুলশী", "Chattogram"), ("Halishahar", "হালিশহর", "Chattogram"),
    ("Panchlaish", "পাঁচলাইশ", "Chattogram"), ("Rupatoli", "রূপাতলী", "Barishal"),
    ("Nathullabad", "নথুল্লাবাদ", "Barishal"), ("Kandirpar", "কান্দিরপাড়", "Cumilla"),
    ("Ganginarpar", "গাঙ্গিনারপাড়", "Mymensingh"), ("Kazla", "কাজলা", "Rajshahi"),
    ("Khalishpur", "খালিশপুর", "Khulna"),
]

# Fixed landmark names; most landmarks are composed (see _landmark).
LANDMARKS = [
    ("Jamuna Future Park", "যমুনা ফিউচার পার্ক"), ("Central Mosque", "কেন্দ্রীয় মসজিদ"),
    ("City Hospital", "সিটি হাসপাতাল"), ("Bus Stand", "বাস স্ট্যান্ড"),
    ("Railway Station", "রেলওয়ে স্টেশন"),
]
FACILITIES = [
    ("Lake", "লেক"), ("Metro Rail Station", "মেট্রো রেল স্টেশন"), ("Graveyard", "কবরস্থান"),
    ("Market", "মার্কেট"), ("Central Mosque", "কেন্দ্রীয় মসজিদ"), ("Hospital", "হাসপাতাল"),
    ("Medical College", "মেডিকেল কলেজ"), ("School", "স্কুল"), ("College", "কলেজ"),
    ("University", "বিশ্ববিদ্যালয়"), ("Bus Stand", "বাস স্ট্যান্ড"),
    ("Railway Station", "রেলওয়ে স্টেশন"), ("Park", "পার্ক"), ("Bridge", "ব্রিজ"),
    ("Bazar", "বাজার"), ("Eidgah", "ঈদগাহ"), ("Petrol Pump", "পেট্রোল পাম্প"),
    ("Madrasa", "মাদ্রাসা"), ("Shopping Mall", "শপিং মল"),
]
LANDMARK_LEADS = ("near", "beside", "opposite", "opposite of", "behind",
                  "adjacent to", "next to", "in front of", "close to")
LANDMARK_PARTICLES_BN = ("পাশে", "সামনে", "কাছে", "পেছনে")

# Spellings people really write that differ from the gazetteer's.
SPELLING_VARIANTS = {
    "Chattogram": ["Chittagong", "Chattagram"], "Cumilla": ["Comilla"],
    "Barishal": ["Barisal"], "Bogura": ["Bogra"], "Jashore": ["Jessore"],
    "Mymensingh": ["Mymensing"], "Sylhet": ["Sylet"],
}

# Hand-written, NOT authoritative: area names that carry a number, with the
# highest number used (decision D9).
NUMBERED_AREAS = {"Mirpur": 14, "Dhanmondi": 32, "Gulshan": 2}

# A deliberate augmentation, NOT observed data: a few rural post-office names
# also get a number, so the model learns the structure, not three names.
RURAL_NUMBERED_RATE = 0.04

# Keyword vocabularies. HOUSE / ROAD / BLOCK keywords are PART of the span.
HOUSE_KW_EN = ("House", "House", "Hse", "H", "H.No", "Holding", "Flat", "Apartment",
               "Apt", "Plot", "Plot No")
HOUSE_KW_BN = ("বাসা", "বাড়ি", "হোল্ডিং", "ফ্ল্যাট", "প্লট")
ROAD_KW_EN = ("Road", "Road", "Rd", "Rd.", "R", "Lane", "Ln", "Street", "Avenue")
ROAD_KW_BN = ("রোড", "লেন")
BLOCK_KW_EN = ("Block", "Blk", "Sector", "Section", "Phase")
BLOCK_KW_BN = ("ব্লক", "সেক্টর", "সেকশন")
CONNECTORS_EN = (" ", " ", "-", "#", " No. ", " No-", " No ")
CONNECTORS_NO_EN = (" ", "-", ". ")  # for keywords that already end in "No"
CONNECTORS_BN = (" ", " ", "-", " নং ", " নং-")
CONNECTORS_BLOCK = (" ", " ", "-", "#")

# Introducer words (decision D7): labelled O, the value after them is labelled.
INTRODUCERS = {
    "village": (("Vill", "Village", "Gram"), ("গ্রাম",)),
    "post": (("P.O", "PO", "Post", "Post Office"), ("ডাকঘর", "পোস্ট")),
    "thana": (("Thana", "P.S", "PS", "Upazila", "Upazilla", "Police Station"),
              ("থানা", "উপজেলা")),
    "district": (("Dist", "District", "Zila"), ("জেলা",)),
}
INTRO_CONNECTORS = (": ", "- ", ":", "-", ". ", " ")

# Rates. FORM_STYLE: rural addresses written like a paper form (every level has
# an introducer). DIVISION_RATE is high on purpose: decision D1 needs plenty of
# "district, division" pairs with no postcode in between.
INTRO_RATE = 0.10
FORM_STYLE_RATE = 0.20
REVERSED_RATE = 0.10
SHOP_LEVEL_RATE = 0.07   # decision D10: Shop / Level are O
WARD_RATE = 0.06         # decision D10: Ward is AREA
DIVISION_RATE = 0.30


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


def _keyboard_form(text: str, rng: random.Random) -> str:
    """Half the time, the form a different keyboard would type.

    The gazetteer stores য় ড় ঢ় as single precomposed codepoints; NFC splits
    them in two. Both look identical. Spans are computed from the finished
    pieces, so a change of length here cannot shift them.
    """
    return unicodedata.normalize("NFC", text) if rng.random() < 0.5 else text


def _digits(text: str, bangla: bool, rng: random.Random) -> str:
    return text.translate(BN_DIGITS) if bangla and rng.random() < 0.7 else text


# ---- units: house / road / block / shop / level / ward -------------------

def _connector(keyword: str, bn: bool, rng: random.Random, pool=None) -> str:
    if bn:
        return rng.choice(CONNECTORS_BN)
    if pool is not None:
        return rng.choice(pool)
    return rng.choice(CONNECTORS_NO_EN if keyword.endswith("No") else CONNECTORS_EN)


def _house(rng, bn):
    # Real holding numbers can have 4 digits. Keep those keyword-led so they are
    # not confused with a postcode; otherwise "4 digits" becomes a shortcut.
    big = rng.random() < 0.06
    n = rng.randint(1000, 2999) if big else rng.randint(1, 150)
    if not big and rng.random() < 0.12:  # a bare number at the start of an address
        return _digits(rng.choice((f"{n}", f"{n}/{rng.randint(1, 12)}")), bn, rng)
    keyword = rng.choice(HOUSE_KW_BN if bn else HOUSE_KW_EN)
    number = rng.choice((f"{n}", f"{n}", f"{n}/{rng.randint(1, 12)}",
                         f"{n}{rng.choice('ABCD')}"))
    return _digits(keyword + _connector(keyword, bn, rng) + number, bn, rng)


def _road(rng, bn):
    keyword = rng.choice(ROAD_KW_BN if bn else ROAD_KW_EN)
    return _digits(f"{keyword}{_connector(keyword, bn, rng)}{rng.randint(1, 40)}", bn, rng)


def _block(rng, bn):
    keyword = rng.choice(BLOCK_KW_BN if bn else BLOCK_KW_EN)
    connector = rng.choice(CONNECTORS_BLOCK)
    if keyword in ("Block", "Blk", "ব্লক"):
        letter = rng.choice("ABCDEFGH")
        return keyword + connector + (BN_LETTERS[letter] if bn else letter)
    return _digits(f"{keyword}{connector}{rng.randint(1, 14)}", bn, rng)


def _shop_level(rng, bn):
    """Decision D10: Shop / Level are NOT entities. The caller labels this O."""
    if rng.random() < 0.6:
        n = rng.randint(1, 40)
        forms = ([f"দোকান {n}", f"দোকান নং {n}"] if bn else
                 [f"Shop {n}", f"Shop-{n}", f"Shop No-{n}", f"Shop No. {n}", f"Shop#{n}"])
    else:
        n = rng.randint(1, 9)
        forms = [f"লেভেল {n}"] if bn else [f"Level {n}", f"Level-{n}", f"Level#{n}"]
    return _digits(rng.choice(forms), bn, rng)


def _ward(rng, bn):
    """Decision D10: Ward is ONE AREA span, keyword and number included."""
    n = rng.randint(1, 9)
    forms = ([f"ওয়ার্ড {n}", f"ওয়ার্ড নং {n}"] if bn else
             [f"Ward {n}", f"Ward No. {n}", f"Ward-{n}", f"Ward No-{n}"])
    return _digits(rng.choice(forms), bn, rng)


def _numbered(surface: str, number: int, bangla: bool, rng: random.Random) -> str:
    """'Mirpur' -> 'Mirpur-10' / 'Mirpur 10' / 'Mirpur - 10' (D9: one AREA span)."""
    return surface + rng.choice(("-", "-", " ", " - ")) + _digits(str(number), bangla, rng)


def _intro(kind: str, bangla: bool, rng: random.Random) -> str:
    """An introducer word plus connector, e.g. 'P.O: ' (decision D7: labelled O)."""
    words = INTRODUCERS[kind][1 if bangla else 0]
    return rng.choice(words) + rng.choice(INTRO_CONNECTORS)


def _landmark(rng, bn, head_en, head_bn):
    """A landmark built from pieces, so the model learns the pattern, not 5 names."""
    facility_en, facility_bn = rng.choice(FACILITIES)
    if rng.random() < 0.3:
        name_en, name_bn = rng.choice(LANDMARKS)
    else:
        top = NUMBERED_AREAS.get(head_en)
        number = rng.randint(1, top) if top and rng.random() < 0.4 else None
        base_en = f"{head_en}-{number}" if number else head_en
        base_bn = (f"{head_bn}-{_digits(str(number), True, rng)}" if number else head_bn
                   ) if head_bn else None
        name_en = f"{base_en} {facility_en}"
        name_bn = f"{base_bn} {facility_bn}" if base_bn else None
    if bn and name_bn:
        particle = rng.choice(LANDMARK_PARTICLES_BN)
        style = rng.random()
        if style < 0.4:
            return f"{name_bn} এর {particle}"
        if style < 0.6:
            return f"{name_bn}-এর {particle}"
        genitive = "ের" if "ক" <= name_bn[-1] <= "হ" else "র"  # attached form
        return f"{name_bn}{genitive} {particle}"
    return f"{rng.choice(LANDMARK_LEADS)} {name_en}"


# ---- assembling one address ----------------------------------------------

def _one(rng, places, by_district, urban_pool) -> Example:
    mode = rng.choices(("en", "bn", "mixed"), (0.6, 0.15, 0.25))[0]
    urban = bool(urban_pool) and rng.random() < 0.5
    form = (not urban) and rng.random() < FORM_STYLE_RATE
    reverse = rng.random() < REVERSED_RATE
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
            return _keyboard_form(bn, rng)
        return _latin(en, rng)

    def intro(kind, always=False):
        if always or rng.random() < INTRO_RATE:
            return [(_intro(kind, _pick_script(mode, rng), rng), None)]
        return []

    chunks: list[list[tuple[str, str | None]]] = []
    for p, label, make in ((p_house, "HOUSE", _house), (p_road, "ROAD", _road),
                           (p_block, "BLOCK", _block)):
        if rng.random() < p:
            chunks.append([(make(rng, _pick_script(mode, rng)), label)])
    if rng.random() < SHOP_LEVEL_RATE:
        shop = [(_shop_level(rng, _pick_script(mode, rng)), None)]
        chunks.insert(rng.randint(0, min(len(chunks), 2)), shop)
    if rng.random() < 0.14:
        landmark = [(_landmark(rng, _pick_script(mode, rng), area_en, area_bn), "LANDMARK")]
        chunks.insert(rng.randint(0, len(chunks)), landmark)

    if form:  # a village line, as on a paper form: "Vill: X, P.O: Y, ..."
        village = _latin(rng.choice(places).area, rng)
        chunks.append([*intro("village", always=True), (village, "AREA")])
    if not urban and rng.random() < WARD_RATE:
        chunks.append([(_ward(rng, _pick_script(mode, rng)), "AREA")])

    use_bn = area_bn is not None and _pick_script(mode, rng)
    area = _keyboard_form(area_bn, rng) if use_bn else _latin(area_en, rng)
    top = NUMBERED_AREAS.get(area_en) if urban else None
    numbered = False
    if top and rng.random() < 0.6:  # decision D9
        area = _numbered(area, rng.randint(1, top), use_bn, rng)
        numbered = True
    elif not urban and rng.random() < RURAL_NUMBERED_RATE:
        area = _numbered(area, rng.randint(1, 9), False, rng)
        numbered = True
    area_chunk = [*(intro("post", always=form) if not urban else []), (area, "AREA")]
    # Real addresses often have no area: "Savar, Dhaka-1340", "House 5, Road 3,
    # Dhaka". Dropping it is what makes an upazila-FIRST address (0.9% of the old
    # training data) and a district right after a house / road / landmark (4-17
    # cases) common enough to learn.
    if place.upazila_admin and not urban and not form:
        keep_area = 0.55
    else:
        keep_area = 0.85 if (urban or form) else 0.78
    area_index = None
    if rng.random() < keep_area:
        chunks.append(area_chunk)
        area_index = len(chunks) - 1

    upazila_kept = False
    if not urban and place.upazila_admin and rng.random() < (0.95 if form else 0.85):
        upazila = place.upazila
        if upazila.endswith("Sadar") and rng.random() < 0.3:
            upazila = "Sadar"  # decision D4: a lone "Sadar" is still an UPAZILA
        if form or upazila.lower() != place.area.lower() or rng.random() < 0.5:
            chunks.append([*intro("thana", always=form),
                           (name(upazila, place.upazila_bn), "UPAZILA")])
            upazila_kept = True

    # Decision D11 (provisional): when the post office is named exactly like the
    # administrative upazila (32% of them are), a name that appears ONCE is the
    # UPAZILA; if both appear, the first is the post office (AREA) and the second
    # the UPAZILA (as in D1); a "P.O:" introducer or a number marks it as AREA.
    collides = (not urban and place.upazila_admin and not numbered and len(area_chunk) == 1
                and place.area.lower() == place.upazila.lower())
    solo_area = [(area, "UPAZILA")] if collides else area_chunk
    if area_index is not None and not upazila_kept and collides:
        chunks[area_index] = solo_area

    district_pieces: list[tuple[str, str | None]] = []
    if rng.random() < 0.93:
        district_pieces = [*intro("district", always=form),
                           (name(place.district, place.district_bn), "DISTRICT")]
    # Decision D1: DISTRICT first, DIVISION after. A lone occurrence of a name
    # that is both is a DISTRICT, so a division is only emitted beside a district
    # (and never in reversed order, where "first / second" has no meaning).
    division = None
    if district_pieces and not reverse and rng.random() < DIVISION_RATE:
        division = [(name(place.division, place.division_bn), "DIVISION")]
    # With a division the postcode often drops out, so "district, division" sit
    # directly together: the case a postcode between them used to hide.
    district_chunk = district_pieces
    if rng.random() < (0.40 if division else 0.70):
        code = _digits(place.postcode, _pick_script(mode, rng), rng)
        if district_pieces and reverse and rng.random() < 0.4:
            glue = rng.choice((", ", " ", " - "))
            district_chunk = [(code, "POSTCODE"), (glue, None), *district_pieces]
        else:
            glue = rng.choice(("-", " ", ", ", " - ")) if district_pieces else ""
            district_chunk = [*district_pieces, *([(glue, None)] if glue else []),
                              (code, "POSTCODE")]
    if district_chunk:
        chunks.append(district_chunk)
    if division:
        chunks.append(division)
    if rng.random() < 0.10:
        chunks.append([("বাংলাদেশ" if mode == "bn" else "Bangladesh", None)])

    if reverse:
        chunks.reverse()
    if not any(label for chunk in chunks for _, label in chunk):  # never an empty address
        chunks.append(solo_area)  # no upazila chunk exists here, so D11 applies to the lone name

    base_sep = rng.choices((", ", ",", " ", " - ", "; "), (0.55, 0.15, 0.15, 0.08, 0.07))[0]
    vary_sep = rng.random() < 0.25
    case = rng.choices((str, str.lower, str.upper), (0.85, 0.10, 0.05))[0]

    def is_landmark(chunk):
        return any(label == "LANDMARK" for _, label in chunk)

    text, spans = "", []
    for i, chunk in enumerate(chunks):
        if i:
            if is_landmark(chunks[i - 1]) or is_landmark(chunk):
                # a landmark's end is invisible without punctuation: nobody could label it
                text += rng.choice((", ", " - ", "; "))
            else:
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

    for e in train[:12]:
        tokens = tokenize(normalize_digits(e.text))
        tags = to_bio(tokens, e.spans)
        print(e.text)
        print("   ", " ".join(f"{t.text}/{g}" for t, g in zip(tokens, tags)))


if __name__ == "__main__":
    main()
