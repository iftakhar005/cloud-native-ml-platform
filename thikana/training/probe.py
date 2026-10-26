"""Brittleness probes: addresses written BY HAND in styles the generator avoids.

These are invented by the author. They are NOT real addresses, NOT a test set,
and prove nothing about accuracy. Two kinds:

  * SCORED probes carry an expected answer written from docs/label-schema.md
    (not from the model's output), so they work as a pass/fail regression
    checklist. Several are CONTRAST pairs that would expose a shortcut in
    either direction (e.g. "Dhaka-1216" vs "Mirpur-10" vs "Holding 1845").
  * LOOK-ONLY probes have no expected answer, because they involve schema
    decisions that are still open (building / office names) or are simply for reading.

Run:  python -m thikana.training.probe [model_name]     (default crf_v1_surface_context)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from thikana.model import AddressParser
from thikana.training.synth import build_places, split_places
from thikana.training.train import MODELS, build_vocab


@dataclass(frozen=True)
class Probe:
    text: str
    expected: tuple[tuple[str, str], ...] | None = None  # (surface, label); None = look only


SCORED_PROBES = [
    # the reported failure and its direct variants
    Probe("Mirpur-10, Dhaka-1216", (("Mirpur-10", "AREA"), ("Dhaka", "DISTRICT"), ("1216", "POSTCODE"))),
    Probe("Mirpur 10, Dhaka 1216", (("Mirpur 10", "AREA"), ("Dhaka", "DISTRICT"), ("1216", "POSTCODE"))),
    Probe("Dhanmondi-27, Dhaka-1209", (("Dhanmondi-27", "AREA"), ("Dhaka", "DISTRICT"), ("1209", "POSTCODE"))),
    Probe("Gulshan - 2, Dhaka - 1212", (("Gulshan - 2", "AREA"), ("Dhaka", "DISTRICT"), ("1212", "POSTCODE"))),
    Probe("House 12, Road 3, Mirpur-14, Dhaka",
          (("House 12", "HOUSE"), ("Road 3", "ROAD"), ("Mirpur-14", "AREA"), ("Dhaka", "DISTRICT"))),
    Probe("মিরপুর-১০, ঢাকা-১২১৬", (("মিরপুর-১০", "AREA"), ("ঢাকা", "DISTRICT"), ("১২১৬", "POSTCODE"))),
    # no punctuation between the parts, and chained hyphens
    Probe("Mirpur-10 Dhaka-1216", (("Mirpur-10", "AREA"), ("Dhaka", "DISTRICT"), ("1216", "POSTCODE"))),
    Probe("Mirpur-10-Dhaka-1216", (("Mirpur-10", "AREA"), ("Dhaka", "DISTRICT"), ("1216", "POSTCODE"))),
    # a numbered name the generator's hand-written list does not contain
    Probe("Rampur-5, Savar, Dhaka", (("Rampur-5", "AREA"), ("Savar", "UPAZILA"), ("Dhaka", "DISTRICT"))),
    # contrasts: 4 digits must not ALWAYS mean postcode, and must still sometimes
    Probe("Holding 1845, Savar, Dhaka-1340",
          (("Holding 1845", "HOUSE"), ("Savar", "UPAZILA"), ("Dhaka", "DISTRICT"), ("1340", "POSTCODE"))),
    Probe("Dhaka-1216", (("Dhaka", "DISTRICT"), ("1216", "POSTCODE"))),
    # the D9 boundary: keyword-introduced units stay BLOCK
    Probe("Uttara Sector 7, Dhaka-1230",
          (("Uttara", "AREA"), ("Sector 7", "BLOCK"), ("Dhaka", "DISTRICT"), ("1230", "POSTCODE"))),
    # lone district with no postcode (decision D1)
    Probe("mirpur 10 dhaka", (("mirpur 10", "AREA"), ("dhaka", "DISTRICT"))),
    # keyword families the generator once never wrote
    Probe("Plot 12, Road No. 4, Section 7, Mirpur, Dhaka",
          (("Plot 12", "HOUSE"), ("Road No. 4", "ROAD"), ("Section 7", "BLOCK"),
           ("Mirpur", "AREA"), ("Dhaka", "DISTRICT"))),
    Probe("Apt 5C, Ln 3, Phase 2, Uttara, Dhaka-1230",
          (("Apt 5C", "HOUSE"), ("Ln 3", "ROAD"), ("Phase 2", "BLOCK"), ("Uttara", "AREA"),
           ("Dhaka", "DISTRICT"), ("1230", "POSTCODE"))),
    # decision D7: introducers are O, the value after them is labelled
    Probe("Vill: Rampur, P.O: Kalikapur, P.S: Savar, Dist: Dhaka",
          (("Rampur", "AREA"), ("Kalikapur", "AREA"), ("Savar", "UPAZILA"), ("Dhaka", "DISTRICT"))),
    Probe("Village- Noapara, Thana- Keraniganj, District- Dhaka",
          (("Noapara", "AREA"), ("Keraniganj", "UPAZILA"), ("Dhaka", "DISTRICT"))),
    Probe("গ্রাম: রামপুর, থানা: সাভার, জেলা: ঢাকা",
          (("রামপুর", "AREA"), ("সাভার", "UPAZILA"), ("ঢাকা", "DISTRICT"))),
    # decision D10: Shop and Level are O, Ward is one AREA span
    Probe("Shop 12, Level 3, Mirpur-10, Dhaka-1216",
          (("Mirpur-10", "AREA"), ("Dhaka", "DISTRICT"), ("1216", "POSTCODE"))),
    Probe("দোকান ১২, লেভেল ৩, মিরপুর-১০, ঢাকা",
          (("মিরপুর-১০", "AREA"), ("ঢাকা", "DISTRICT"))),
    Probe("Ward 5, Savar, Dhaka", (("Ward 5", "AREA"), ("Savar", "UPAZILA"), ("Dhaka", "DISTRICT"))),
    # landmarks, including one named after the address's own area
    Probe("House 4, Banani, near Banani Lake, Dhaka",
          (("House 4", "HOUSE"), ("Banani", "AREA"), ("near Banani Lake", "LANDMARK"),
           ("Dhaka", "DISTRICT"))),
    Probe("যমুনা ফিউচার পার্কের পাশে, বসুন্ধরা, ঢাকা",
          (("যমুনা ফিউচার পার্কের পাশে", "LANDMARK"), ("বসুন্ধরা", "AREA"), ("ঢাকা", "DISTRICT"))),
    # reversed order
    Probe("Dhaka 1207, Road 5, House 12, Dhanmondi",
          (("Dhaka", "DISTRICT"), ("1207", "POSTCODE"), ("Road 5", "ROAD"),
           ("House 12", "HOUSE"), ("Dhanmondi", "AREA"))),
    Probe("1216, Dhaka, Mirpur-10, Road 3, House 5",
          (("1216", "POSTCODE"), ("Dhaka", "DISTRICT"), ("Mirpur-10", "AREA"),
           ("Road 3", "ROAD"), ("House 5", "HOUSE"))),
    # decision D1 in both directions
    Probe("House 9, Road 2, Lalmatia, Dhaka",
          (("House 9", "HOUSE"), ("Road 2", "ROAD"), ("Lalmatia", "AREA"), ("Dhaka", "DISTRICT"))),
    Probe("Rayenda, Bagerhat, Khulna",
          (("Rayenda", "AREA"), ("Bagerhat", "DISTRICT"), ("Khulna", "DIVISION"))),
    Probe("সাহেব বাজার, রাজশাহী", (("সাহেব বাজার", "AREA"), ("রাজশাহী", "DISTRICT"))),
]

LOOK_ONLY = [Probe(t) for t in [
    "Flat-4B, House-12, Road-3, Block-D, Mirpur-10, Dhaka-1216",
    "Vill: Rampur, P.O: Kalikapur, Thana: Savar, Dist: Dhaka",
    "Dhaka 1207, Road 5, House 12, Dhanmondi",
    "House#8, Road#4, Sector-11, Uttara, Dhaka-1230, Bangladesh",
    "বাসা ৮, রোড ৪, সেক্টর ১১, উত্তরা, ঢাকা-১২৩০",
    "Opposite of City College, Dhanmondi 27, Dhaka",
    "Shop 12, Level 3, Bashundhara City Shopping Complex, Panthapath, Dhaka",  # building names: undecided
    "Ward 5, Union Parishad Office, Savar, Dhaka",                              # office names: undecided
    "45 Zigatola, Dhaka 1209",
]]


def surfaces(text: str, spans) -> set[tuple[str, str]]:
    return {(text[s.start:s.end], s.label) for s in spans}


def mark(text: str, spans) -> str:
    out, pos = [], 0
    for s in spans:
        out += [text[pos:s.start], f"[{s.label}: {text[s.start:s.end]}]"]
        pos = s.end
    return "".join(out + [text[pos:]])


def load(name: str) -> AddressParser:
    vocab = build_vocab(split_places(build_places())["train"]) if "gazetteer" in name else None
    return AddressParser(MODELS / f"{name}.crfsuite", vocab)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    name = sys.argv[1] if len(sys.argv) > 1 else "crf_v1_surface_context"
    parser = load(name)

    passed = 0
    print(f"model: {name}\n\nSCORED probes (expected answers written from the schema):")
    for probe in SCORED_PROBES:
        got = parser.predict(probe.text)
        ok = surfaces(probe.text, got) == set(probe.expected)
        passed += ok
        print(f"  {'PASS' if ok else 'FAIL'}  {probe.text}")
        if not ok:
            print(f"        got: {mark(probe.text, got)}")
    print(f"\n{passed} of {len(SCORED_PROBES)} scored probes pass "
          "(hand-written checklist, NOT an accuracy measurement)")

    print("\nLOOK-ONLY probes:")
    for probe in LOOK_ONLY:
        print(f"  {probe.text}\n      -> {mark(probe.text, parser.predict(probe.text))}")


if __name__ == "__main__":
    main()
