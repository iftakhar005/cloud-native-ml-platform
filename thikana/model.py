"""Serving-side wrapper around a trained CRF model file.

The model file is plain data (crfsuite's native format), not a Python pickle:
loading a pickle executes code, so a pickle would be a trust boundary. The
vocabulary and feature flags a model was trained with travel beside it in a
small JSON file, and load() reads them together so they cannot be mismatched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pycrfsuite

from thikana.features import Vocab, sentence_features
from thikana.schema import Span
from thikana.text import bio_to_spans, normalize_digits, tokenize


class AddressParser:
    def __init__(self, model_path: str | Path, vocab: Vocab | None = None,
                 memory: bool = False) -> None:
        self._tagger = pycrfsuite.Tagger()
        self._tagger.open(str(model_path))
        self.vocab = vocab
        self.memory = memory

    @classmethod
    def load(cls, model_path: str | Path) -> "AddressParser":
        """Load a model with the vocabulary and feature flags saved beside it."""
        path = Path(model_path)
        meta_path = path.with_suffix(".json")
        vocab, memory = None, False
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("vocab"):
                vocab = {kind: frozenset(names) for kind, names in meta["vocab"].items()}
            memory = bool(meta.get("memory"))
        return cls(path, vocab, memory)

    def predict(self, text: str) -> list[Span]:
        tokens = tokenize(normalize_digits(text))
        if not tokens:
            return []
        tags = self._tagger.tag(sentence_features(tokens, self.vocab, self.memory))
        return bio_to_spans(tokens, tags)
