"""Brittleness probes: addresses written BY HAND in styles the generator never makes.

These are invented by the author. They are NOT real addresses, NOT a test set,
and prove nothing about accuracy. They exist to show where the model breaks
once an address stops looking like the synthetic training data.

Run:  python -m thikana.training.probe
"""

from __future__ import annotations

import sys

from thikana.model import AddressParser
from thikana.training.synth import build_places, split_places
from thikana.training.train import MODELS, build_vocab

PROBES = [
    "Flat-4B, House-12, Road-3, Block-D, Mirpur-10, Dhaka-1216",
    "Vill: Rampur, P.O: Kalikapur, Thana: Savar, Dist: Dhaka",
    "Dhaka 1207, Road 5, House 12, Dhanmondi",
    "mirpur 10 dhaka",
    "House#8, Road#4, Sector-11, Uttara, Dhaka-1230, Bangladesh",
    "বাসা ৮, রোড ৪, সেক্টর ১১, উত্তরা, ঢাকা-১২৩০",
    "Opposite of City College, Dhanmondi 27, Dhaka",
    "Shop 12, Level 3, Bashundhara City Shopping Complex, Panthapath, Dhaka",
    "Ward 5, Union Parishad Office, Savar, Dhaka",
    "45 Zigatola, Dhaka 1209",
]


def mark(text: str, spans) -> str:
    out, pos = [], 0
    for s in spans:
        out += [text[pos:s.start], f"[{s.label}: {text[s.start:s.end]}]"]
        pos = s.end
    return "".join(out + [text[pos:]])


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    train_places = split_places(build_places())["train"]
    parser = AddressParser(MODELS / "crf_v2_plus_gazetteer.crfsuite", build_vocab(train_places))
    for text in PROBES:
        print(text)
        print("   ->", mark(text, parser.predict(text)), "\n")


if __name__ == "__main__":
    main()
