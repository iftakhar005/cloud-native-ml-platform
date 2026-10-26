"""Label vocabulary and the annotated-example data model.

Mirrors docs/label-schema.md. Spans are CHARACTER offsets into the text, so
they survive tokenizer changes and can be shown on the user's original input.
"""

from __future__ import annotations

from dataclasses import dataclass

ENTITY_TYPES = (
    "HOUSE", "ROAD", "BLOCK", "AREA", "UPAZILA",
    "DISTRICT", "DIVISION", "POSTCODE", "LANDMARK",
)
OUTSIDE = "O"
BIO_LABELS = (OUTSIDE, *(f"{p}-{t}" for t in ENTITY_TYPES for p in ("B", "I")))


@dataclass(frozen=True)
class Span:
    start: int
    end: int  # exclusive
    label: str

    def __post_init__(self) -> None:
        if self.label not in ENTITY_TYPES:
            raise ValueError(f"unknown label {self.label!r}")
        if not 0 <= self.start < self.end:
            raise ValueError(f"bad span range {self.start}:{self.end}")


@dataclass(frozen=True)
class Example:
    text: str
    spans: tuple[Span, ...]

    def __post_init__(self) -> None:
        ordered = sorted(self.spans, key=lambda s: s.start)
        for span in ordered:
            if span.end > len(self.text):
                raise ValueError(f"span {span} runs past the end of the text")
        for left, right in zip(ordered, ordered[1:]):
            if right.start < left.end:
                raise ValueError(f"overlapping spans {left} and {right}")
        object.__setattr__(self, "spans", tuple(ordered))

    def surface(self, label: str) -> list[str]:
        """Text of every span with this label, in order."""
        return [self.text[s.start:s.end] for s in self.spans if s.label == label]
