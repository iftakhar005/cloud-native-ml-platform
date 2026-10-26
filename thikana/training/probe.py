"""Brittleness probes: addresses written BY HAND in styles the generator avoids.

These are invented by the author. They are NOT real addresses, NOT a test set,
and prove nothing about accuracy. Two kinds:

  * SCORED probes carry an expected answer written from docs/label-schema.md
    (not from the model's output), so they work as a pass/fail regression
    checklist. Several are CONTRAST pairs that would expose a shortcut in
    either direction (e.g. "Dhaka-1216" vs "Mirpur-10" vs "Holding 1845").
  * LOOK-ONLY probes have no expected answer, because they involve schema
    decisions that are still open (D10) or are simply for reading.

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


D9_PROBES = [
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
]

LOOK_ONLY = [Probe(t) for t in [
    "Flat-4B, House-12, Road-3, Block-D, Mirpur-10, Dhaka-1216",
    "Vill: Rampur, P.O: Kalikapur, Thana: Savar, Dist: Dhaka",
    "Dhaka 1207, Road 5, House 12, Dhanmondi",
    "House#8, Road#4, Sector-11, Uttara, Dhaka-1230, Bangladesh",
    "বাসা ৮, রোড ৪, সেক্টর ১১, উত্তরা, ঢাকা-১২৩০",
    "Opposite of City College, Dhanmondi 27, Dhaka",
    "Shop 12, Level 3, Bashundhara City Shopping Complex, Panthapath, Dhaka",  # D10 open
    "Ward 5, Union Parishad Office, Savar, Dhaka",                              # D10 open
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
    for probe in D9_PROBES:
        got = parser.predict(probe.text)
        ok = surfaces(probe.text, got) == set(probe.expected)
        passed += ok
        print(f"  {'PASS' if ok else 'FAIL'}  {probe.text}")
        if not ok:
            print(f"        got: {mark(probe.text, got)}")
    print(f"\n{passed} of {len(D9_PROBES)} scored probes pass "
          "(hand-written checklist, NOT an accuracy measurement)")

    print("\nLOOK-ONLY probes:")
    for probe in LOOK_ONLY:
        print(f"  {probe.text}\n      -> {mark(probe.text, parser.predict(probe.text))}")


if __name__ == "__main__":
    main()
