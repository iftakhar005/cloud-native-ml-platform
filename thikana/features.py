"""Per-token features for the CRF. Shared by training AND serving.

A CRF only sees the features we expose, so this file IS the model's view of an
address. It lives outside thikana/training/ because the API imports it too:
one code path means training and serving cannot silently drift apart.
"""

from __future__ import annotations

from thikana.text import Token

SEPARATORS = {",", ";"}

# Optional gazetteer membership features: {"district": {...}, "division": {...},
# "upazila": {...}} of lowercase single tokens. None disables them.
Vocab = dict[str, frozenset[str]]


def shape(text: str) -> str:
    """Collapse a word to its character classes: 'Dhaka' -> 'Xx', '1229' -> 'd'."""
    out: list[str] = []
    for ch in text:
        if "ঀ" <= ch <= "৿":
            cls = "b"
        elif ch.isdigit():
            cls = "d"
        elif ch.isupper():
            cls = "X"
        elif ch.islower():
            cls = "x"
        else:
            cls = ch
        if not out or out[-1] != cls:
            out.append(cls)
    return "".join(out)


def sentence_features(tokens: list[Token], vocab: Vocab | None = None) -> list[dict]:
    words = [t.text.lower() for t in tokens]
    shapes = [shape(t.text) for t in tokens]
    total_separators = sum(w in SEPARATORS for w in words)
    n = len(tokens)

    features, seen, separators_so_far = [], set(), 0
    for i, token in enumerate(tokens):
        w, raw = words[i], token.text
        is_word = any(c.isalpha() or "ঀ" <= c <= "৿" for c in raw)
        if w in SEPARATORS:
            separators_so_far += 1

        f: dict = {
            "bias": 1.0, "w": w, "shape": shapes[i], "len": min(len(w), 8),
            "p2": w[:2], "p3": w[:3], "s2": w[-2:], "s3": w[-3:],
            "sep_before": min(separators_so_far, 4),
            "sep_after": min(total_separators - separators_so_far, 4),
        }
        if raw.isdigit():
            f["digits"] = len(raw)
        if is_word and raw.isupper() and len(raw) > 1:
            f["upper"] = 1.0
        if is_word and raw.istitle():
            f["title"] = 1.0
        if is_word and w in seen:
            f["seen_before"] = 1.0  # decision D1: the 2nd "Dhaka" is the DIVISION
        if i == 0:
            f["bos"] = 1.0
        if i == n - 1:
            f["eos"] = 1.0

        for offset in (-2, -1, 1, 2):
            j = i + offset
            if 0 <= j < n:
                f[f"w{offset:+d}"] = words[j]
                f[f"shape{offset:+d}"] = shapes[j]
        if i > 0:
            f["w-1|w"] = f"{words[i - 1]}|{w}"
        if i < n - 1:
            f["w|w+1"] = f"{w}|{words[i + 1]}"

        if vocab:
            for kind, names in vocab.items():
                if w in names:
                    f[f"gaz_{kind}"] = 1.0

        if is_word:
            seen.add(w)
        features.append(f)
    return features
