"""Rule-based baseline: regexes for structured fields, gazetteer lookup for names.

This is what an engineer would write without ML. The model has to beat it to
justify its complexity.

Fairness: the name vocabulary is built from the TRAINING postcode records only.
The model never sees test-record names, so the baseline must not either.
Known weaknesses are deliberate to leave in: exact-match names (no typo
tolerance), no context for ambiguous names, and landmark/area boundaries that
depend on punctuation.
"""

from __future__ import annotations

import re
from collections import defaultdict

from thikana.schema import Span
from thikana.text import Token, normalize_digits, tokenize

_F = re.IGNORECASE
_NUM = r"\d+[a-z]?(?:/\d+)?"
_BN = r"[ঀ-৿]"

# Priority order: earlier patterns claim text first.
PATTERNS = (
    ("LANDMARK", re.compile(
        r"\b(?:near|beside|opposite|behind)(?:\s+\w+){1,3}|(?:" + _BN + r"+\s+){1,3}এর\s+পাশে", _F)),
    ("HOUSE", re.compile(
        r"\b(?:house|holding|flat|h)\s*[#\-]?\s*" + _NUM
        + r"|(?:বাসা|বাড়ি)(?:\s+নং)?\s*" + _NUM
        + r"|^\s*\d{1,3}(?:/\d+)?(?=\W)", _F)),
    ("ROAD", re.compile(
        r"\b(?:road|rd|lane|r)\s*[#\-]?\s*\d+|(?:রোড|লেন)(?:\s+নং)?\s*\d+", _F)),
    ("BLOCK", re.compile(
        r"\b(?:block|blk|sector)\s*-?\s*(?:[a-h]\b|\d+)|(?:ব্লক|সেক্টর)\s*[\wঀ-৿]+", _F)),
    ("POSTCODE", re.compile(r"(?<!\d)\d{4}(?!\d)")),
)

# Words that introduce a name but are not part of it (decision D7).
STOPWORDS = {"bangladesh", "বাংলাদেশ", "dist", "upazila", "thana", "p", "o", "po",
             "জেলা", "উপজেলা", "থানা"}


def _snap(tokens: list[Token], start: int, end: int, label: str) -> Span | None:
    """Widen a character range to whole tokens."""
    inside = [t for t in tokens if t.start < end and start < t.end]
    return Span(inside[0].start, inside[-1].end, label) if inside else None


def _is_word(token: Token) -> bool:
    return any(c.isalpha() or "ঀ" <= c <= "৿" for c in token.text)


class Baseline:
    def __init__(self, places) -> None:
        self.names: dict[tuple[str, ...], set[str]] = defaultdict(set)
        for p in places:
            for name, label in ((p.district, "DISTRICT"), (p.district_bn, "DISTRICT"),
                                (p.upazila, "UPAZILA"), (p.upazila_bn, "UPAZILA"),
                                (p.division, "DIVISION"), (p.division_bn, "DIVISION")):
                if name:
                    self.names[self._key(tokenize(name))].add(label)
        self.longest = max(len(key) for key in self.names)

    @staticmethod
    def _key(tokens: list[Token]) -> tuple[str, ...]:
        return tuple(t.text.lower() for t in tokens)

    @staticmethod
    def _choose(labels: set[str], district_seen: bool) -> str:
        # Decision D1: a name that is both district and division is the
        # DISTRICT first, and the DIVISION if a district was already found.
        if "DISTRICT" in labels:
            return "DIVISION" if district_seen and "DIVISION" in labels else "DISTRICT"
        return "UPAZILA" if "UPAZILA" in labels else "DIVISION"

    def predict(self, text: str) -> list[Span]:
        text = normalize_digits(text)
        tokens = tokenize(text)
        spans: list[Span] = []
        covered = [False] * len(tokens)

        def claim(span: Span) -> None:
            spans.append(span)
            for i, t in enumerate(tokens):
                if t.start < span.end and span.start < t.end:
                    covered[i] = True

        for label, pattern in PATTERNS:
            for m in pattern.finditer(text):
                span = _snap(tokens, m.start(), m.end(), label)
                taken = span and any(covered[i] for i, t in enumerate(tokens)
                                     if t.start < span.end and span.start < t.end)
                if span and not taken:
                    claim(span)

        i, district_seen = 0, False
        while i < len(tokens):
            if covered[i]:
                i += 1
                continue
            for length in range(min(self.longest, len(tokens) - i), 0, -1):
                window = tokens[i:i + length]
                key = self._key(window)
                if key in self.names and not any(covered[i:i + length]):
                    label = self._choose(self.names[key], district_seen)
                    district_seen |= label == "DISTRICT"
                    claim(Span(window[0].start, window[-1].end, label))
                    i += length
                    break
            else:
                i += 1

        group: list[Token] = []
        for i, token in enumerate([*tokens, None]):
            is_area_word = (token is not None and not covered[i] and _is_word(token)
                            and token.text.lower() not in STOPWORDS)
            if is_area_word:
                group.append(token)
            elif group:
                spans.append(Span(group[0].start, group[-1].end, "AREA"))
                group = []
        return sorted(spans, key=lambda s: s.start)
