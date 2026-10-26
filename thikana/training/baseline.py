"""Rule-based baseline: regexes for structured fields, gazetteer lookup for names.

This is what an engineer would write without ML. The model has to beat it to
justify its complexity. It is kept honest: when the generator learns a new
keyword family, the regexes learn it too, otherwise the baseline would be a
strawman and the model's gain would look bigger than it is.

Fairness: the name vocabulary is built from the TRAINING postcode records only.
The model never sees test-record names, so the baseline must not either.
Known weaknesses are deliberate to leave in: exact-match names (no typo
tolerance), no context for ambiguous names, and area/landmark boundaries that
depend on punctuation.
"""

from __future__ import annotations

import re
from collections import defaultdict

from thikana.schema import Span
from thikana.text import Token, normalize_digits, normalize_token, tokenize

_F = re.IGNORECASE
_NUM = r"\d+[a-z]?(?:/\d+)?"
_NO = r"(?:\.?\s*no\b\.?)?"      # optional "No" / "No." / ".No" after a keyword
_SEP = r"\s*[#\-]?\s*"
_BN = r"[ঀ-৿]"

# Priority order: earlier patterns claim text first. Label "O" claims text that is
# deliberately NOT an entity (decision D10: Shop / Level).
PATTERNS = (
    ("LANDMARK", re.compile(
        r"\b(?:near|beside|opposite(?: of)?|behind|adjacent to|next to|in front of|close to)"
        r"(?:\s+\w[\w\-]*){1,4}"
        r"|(?:" + _BN + r"[ঀ-৿\-]*\s+){1,4}(?:পাশে|সামনে|কাছে|পেছনে)", _F)),
    ("O", re.compile(
        r"\b(?:shop|level)" + _NO + _SEP + r"\d+|(?:দোকান|লেভেল)(?:\s+নং)?\s*\d+", _F)),
    ("AREA", re.compile(  # decision D10: Ward is one AREA span
        r"\bward" + _NO + _SEP + r"\d+|ওয়ার্ড(?:\s+নং)?\s*\d+", _F)),
    ("HOUSE", re.compile(
        r"\b(?:house|hse|holding|flat|apartment|apt|plot|h)" + _NO + _SEP + _NUM
        + r"|(?:বাসা|বাড়ি|হোল্ডিং|ফ্ল্যাট|প্লট)(?:\s+নং)?[\s\-]*" + _NUM
        + r"|^\s*\d{1,3}(?:/\d+)?(?=\W)", _F)),
    ("ROAD", re.compile(
        r"\b(?:road|rd|lane|ln|street|avenue|r)\.?" + _NO + _SEP + r"\d+"
        + r"|(?:রোড|লেন)(?:\s+নং)?[\s\-]*\d+", _F)),
    ("BLOCK", re.compile(
        r"\b(?:block|blk|sector|section|phase)\s*[#\-]?\s*(?:[a-h]\b|\d+)"
        r"|(?:ব্লক|সেক্টর|সেকশন)[\s#\-]*[\wঀ-৿]+", _F)),
    ("POSTCODE", re.compile(r"(?<!\d)\d{4}(?!\d)")),
)

# Words that introduce a value but are not part of it (decision D7).
STOPWORDS = {
    "bangladesh", "বাংলাদেশ", "dist", "district", "zila", "upazila", "upazilla", "thana",
    "vill", "village", "gram", "post", "office", "police", "station", "p", "o", "po",
    "s", "ps", "জেলা", "উপজেলা", "থানা", "গ্রাম", "ডাকঘর", "পোস্ট",
}


def _snap(tokens: list[Token], start: int, end: int) -> tuple[int, int] | None:
    """Widen a character range to whole tokens."""
    inside = [t for t in tokens if t.start < end and start < t.end]
    return (inside[0].start, inside[-1].end) if inside else None


def _is_word(token: Token) -> bool:
    return any(c.isalpha() or "ঀ" <= c <= "৿" for c in token.text)


class Baseline:
    def __init__(self, places) -> None:
        self.names: dict[tuple[str, ...], set[str]] = defaultdict(set)
        for p in places:
            for name, label in ((p.district, "DISTRICT"), (p.district_bn, "DISTRICT"),
                                (p.upazila, "UPAZILA"), (p.upazila_bn, "UPAZILA"),
                                (p.division, "DIVISION"), (p.division_bn, "DIVISION")):
                if name and (label != "UPAZILA" or p.upazila_admin):  # decision D8
                    self.names[self._key(tokenize(name))].add(label)
        self.longest = max(len(key) for key in self.names)

    @staticmethod
    def _key(tokens: list[Token]) -> tuple[str, ...]:
        return tuple(normalize_token(t.text).lower() for t in tokens)

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

        def mark(start: int, end: int) -> None:
            for i, t in enumerate(tokens):
                if t.start < end and start < t.end:
                    covered[i] = True

        def claim(span: Span) -> None:
            spans.append(span)
            mark(span.start, span.end)

        for label, pattern in PATTERNS:
            for m in pattern.finditer(text):
                snapped = _snap(tokens, m.start(), m.end())
                if not snapped:
                    continue
                start, end = snapped
                if any(covered[i] for i, t in enumerate(tokens) if t.start < end and start < t.end):
                    continue
                if label == "O":  # deliberately not an entity (decision D10): cover, never label
                    mark(start, end)
                else:
                    claim(Span(start, end, label))

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
                            and normalize_token(token.text).lower() not in STOPWORDS)
            if is_area_word:
                group.append(token)
            elif group:
                end = group[-1].end
                # Decision D9: "Mirpur-10" / "Mirpur 10" - a 1-2 digit number
                # right after the name (optionally after a hyphen) is part of it.
                j = i + 1 if token is not None and token.text == "-" else i
                if (j < len(tokens) and not covered[j] and tokens[j].text.isdigit()
                        and len(tokens[j].text) <= 2):
                    end = tokens[j].end
                spans.append(Span(group[0].start, end, "AREA"))
                group = []
        return sorted(spans, key=lambda s: s.start)
