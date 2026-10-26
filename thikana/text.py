"""Text handling shared by training AND serving.

One tokenizer in one place: if training and the API ever tokenized
differently, the model would silently see input it never trained on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from thikana.schema import OUTSIDE, Span

# Bangla digits -> ASCII, one character to one character, so character
# offsets are identical before and after (decision D5).
_BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

# Python's \w rejects Bangla vowel signs (category Mc), which would shatter
# "ঢাকা" into pieces. The explicit Bangla block U+0980-U+09FF fixes that.
_TOKEN = re.compile(r"[\w\u0980-\u09FF]+|[^\w\s\u0980-\u09FF]")


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int


def normalize_digits(text: str) -> str:
    out = text.translate(_BANGLA_DIGITS)
    assert len(out) == len(text)  # offsets must not move
    return out


def tokenize(text: str) -> list[Token]:
    return [Token(m.group(), m.start(), m.end()) for m in _TOKEN.finditer(text)]


def to_bio(tokens: list[Token], spans: tuple[Span, ...] | list[Span]) -> list[str]:
    """Character spans -> one BIO tag per token."""
    tags = []
    previous_span = None
    for token in tokens:
        owner = None
        for span in spans:
            overlaps = token.start < span.end and span.start < token.end
            if not overlaps:
                continue
            if token.start < span.start or token.end > span.end:
                raise ValueError(
                    f"token {token.text!r} straddles the boundary of {span}"
                )
            owner = span
            break
        if owner is None:
            tags.append(OUTSIDE)
        else:
            tags.append(("I-" if owner is previous_span else "B-") + owner.label)
        previous_span = owner
    return tags


def bio_to_spans(tokens: list[Token], tags: list[str]) -> list[Span]:
    """BIO tags -> character spans. An I- tag with no open entity starts one."""
    spans, label, start, end = [], None, 0, 0
    for token, tag in zip(tokens, tags):
        kind, _, name = tag.partition("-")
        continues = kind == "I" and name == label
        if label is not None and not continues:
            spans.append(Span(start, end, label))
            label = None
        if kind in ("B", "I") and label is None:
            label, start = name, token.start
        if label is not None:
            end = token.end
    if label is not None:
        spans.append(Span(start, end, label))
    return spans
