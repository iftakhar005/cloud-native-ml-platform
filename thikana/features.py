"""Per-token features for the CRF. Shared by training AND serving.

A CRF only sees the features we expose, so this file IS the model's view of an
address. It lives outside thikana/training/ because the API imports it too:
one code path means training and serving cannot silently drift apart.
"""

from __future__ import annotations

from thikana.text import Token, normalize_token

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


def sentence_features(tokens: list[Token], vocab: Vocab | None = None,
                      memory: bool = False) -> list[dict]:
    """Features per token.

    memory=True adds RELATIONAL district features (a district name earlier or
    later in the address). A linear-chain CRF sees one label back, so it cannot
    know that a district occurred two entities ago (`Bagerhat-9300, Khulna`);
    decision D1 (the second district-like name is the DIVISION) needs exactly that.
    """
    if memory and not (vocab and "district" in vocab):
        raise ValueError("memory features need a vocab with a 'district' entry")
    texts = [normalize_token(t.text) for t in tokens]  # NFC, so both keyboard forms match
    words = [t.lower() for t in texts]
    shapes = [shape(t) for t in texts]
    total_separators = sum(w in SEPARATORS for w in words)
    n = len(tokens)
    in_district = [memory and w in vocab["district"] for w in words]

    features, seen, separators_so_far = [], set(), 0
    for i in range(n):
        w, raw = words[i], texts[i]
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

        if memory:
            f["district_before"] = min(sum(in_district[:i]), 2)
            f["district_after"] = min(sum(in_district[i + 1:]), 2)
            if i > 0 and in_district[i - 1]:
                f["district_prev"] = 1.0
            if i < n - 1 and in_district[i + 1]:
                f["district_next"] = 1.0

        if is_word:
            seen.add(w)
        features.append(f)
    return features
