"""Loader and gold-label audit for the hand-written evaluation set.

The set is NOT real data: see data/handwritten/README.md. Annotations are
inline, {LABEL|surface}, so spans are derived from the markup and cannot
disagree with the text the way hand-typed character offsets can.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from thikana.schema import Example, Span
from thikana.text import normalize_digits
from thikana.training.gazetteer import load_all

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "handwritten"
PATH = DATA_DIR / "addresses_v1.txt"


def path_for(version: str) -> Path:
    return DATA_DIR / f"addresses_{version}.txt"
_MARKUP = re.compile(r"\{([A-Z]+)\|([^{}|]+)\}")
SEPARATOR = " ::: "


@dataclass(frozen=True)
class Item:
    id: int
    style: str
    example: Example


def parse_markup(annotated: str) -> Example:
    annotated = annotated.replace("\\n", "\n")  # a literal \n in the file is a line break
    text, spans, last = "", [], 0
    for m in _MARKUP.finditer(annotated):
        text += annotated[last:m.start()]
        surface = m.group(2)
        spans.append(Span(len(text), len(text) + len(surface), m.group(1)))
        text += surface
        last = m.end()
    text += annotated[last:]
    if "{" in text or "}" in text:
        raise ValueError(f"unparsed markup in {annotated!r}")
    return Example(text, tuple(spans))


def load(path: Path = PATH) -> tuple[list[Item], set[str]]:
    """Return (items, deliberately-declared spelling variants)."""
    items: list[Item] = []
    variants: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if line.startswith("#variants:"):
            variants |= {v.strip().lower() for v in line[len("#variants:"):].split(",") if v.strip()}
        elif line and not line.startswith("#"):
            style, sep, annotated = line.partition(SEPARATOR)
            if not sep:
                raise ValueError(f"line {number}: expected 'style{SEPARATOR}annotated'")
            items.append(Item(len(items) + 1, style.strip(), parse_markup(annotated)))
    return items, variants


def audit(items: list[Item], variants: set[str]) -> list[str]:
    """Problems with the GOLD labels. Fix the data, not the model."""
    f = load_all()
    district = {n.strip().lower() for n in (*f["districts"]["name"], *f["districts"]["bn_name"])}
    division = {n.strip().lower() for n in (*f["divisions"]["name"], *f["divisions"]["bn_name"])}
    upazila = {n.strip().lower() for n in (*f["upazilas"]["name"], *f["upazilas"]["bn_name"])}
    allowed = {"DISTRICT": district, "DIVISION": division, "UPAZILA": upazila}

    problems = []
    for item in items:
        e = item.example
        for s in e.spans:
            surface = normalize_digits(e.text[s.start:s.end]).strip().lower()
            if s.label == "POSTCODE" and not re.fullmatch(r"\d{4}", surface):
                problems.append(f"#{item.id} POSTCODE {surface!r} is not 4 digits")
            if s.label in allowed and surface not in allowed[s.label] and surface not in variants:
                problems.append(f"#{item.id} {s.label} {surface!r} is not in the gazetteer "
                                "(declare it under #variants if deliberate)")
        if e.surface("DIVISION") and not e.surface("DISTRICT"):
            problems.append(f"#{item.id} DIVISION without a DISTRICT contradicts decision D1")
    return problems


def main() -> None:
    import sys
    from collections import Counter

    sys.stdout.reconfigure(encoding="utf-8")
    for path in sorted(DATA_DIR.glob("addresses_v*.txt")):
        items, variants = load(path)
        labels = Counter(s.label for i in items for s in i.example.spans)
        styles = Counter(i.style for i in items)
        print(f"== {path.name}: {len(items)} addresses, {sum(labels.values())} gold entities")
        print("by label:", dict(sorted(labels.items())))
        print("by style:", dict(styles))
        problems = audit(items, variants)
        print(f"gold-label audit: {len(problems)} problem(s)")
        for problem in problems:
            print("  -", problem)
        print()


if __name__ == "__main__":
    main()
