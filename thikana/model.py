"""Serving-side wrapper around a trained CRF model file.

The model file is plain data (crfsuite's native format), not a Python pickle:
loading a pickle executes code, so a pickle would be a trust boundary.
"""

from __future__ import annotations

from pathlib import Path

import pycrfsuite

from thikana.features import Vocab, sentence_features
from thikana.schema import Span
from thikana.text import bio_to_spans, normalize_digits, tokenize


class AddressParser:
    def __init__(self, model_path: str | Path, vocab: Vocab | None = None) -> None:
        self._tagger = pycrfsuite.Tagger()
        self._tagger.open(str(model_path))
        self.vocab = vocab

    def predict(self, text: str) -> list[Span]:
        tokens = tokenize(normalize_digits(text))
        if not tokens:
            return []
        tags = self._tagger.tag(sentence_features(tokens, self.vocab))
        return bio_to_spans(tokens, tags)
