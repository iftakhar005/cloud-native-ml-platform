"""Validation, a thread-safe wrapper around the parser, and model lineage."""

from __future__ import annotations

import hashlib
import re
import threading
from pathlib import Path

from thikana.api.errors import ApiError
from thikana.api.schemas import Entity, ModelInfo, ParseResult
from thikana.model import AddressParser
from thikana.schema import ENTITY_TYPES
from thikana.text import normalize_digits

# Tab, newline and carriage return are fine in a multi-line address; the rest of
# the C0 controls (and DEL) are not text.
_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

LIMITATIONS = [
    "Trained only on synthetic addresses generated from the Bangladesh administrative "
    "gazetteer; no real addresses were used.",
    "Evaluated only on small hand-written sets (65-74 addresses each), never on real "
    "addresses: accuracy on real input is unmeasured.",
    "It labels spans. It does not check that district, upazila and postcode agree, and "
    "it does not geocode.",
    "Bangla and English only. Building and office names and floor numbers are not labelled.",
]


def validate_text(text: str, max_chars: int, where: str = "text") -> None:
    """Raise ApiError if the text is unusable. The message never repeats the text."""
    if not text.strip():
        raise ApiError(422, "empty_text", f"{where} must contain at least one non-space character")
    if len(text) > max_chars:
        raise ApiError(422, "text_too_long",
                       f"{where} is {len(text)} characters; the limit is {max_chars}")
    if _CONTROL.search(text):
        raise ApiError(422, "invalid_characters", f"{where} contains control characters")


def describe_model(parser: AddressParser, model_path: Path, git_sha: str) -> ModelInfo:
    """Identity of the loaded model: a hash of its files, not a name someone typed."""
    digest = hashlib.sha256(model_path.read_bytes())
    sidecar = model_path.with_suffix(".json")
    if sidecar.exists():
        digest.update(sidecar.read_bytes())
    return ModelInfo(
        name=model_path.stem,
        version=digest.hexdigest()[:12],
        size_bytes=model_path.stat().st_size,
        uses_district_memory=parser.memory,
        vocabulary=sorted(parser.vocab) if parser.vocab else [],
        labels=list(ENTITY_TYPES),
        git_sha=git_sha,
        limitations=LIMITATIONS,
    )


def to_result(text: str, spans) -> ParseResult:
    entities = [Entity(label=s.label, text=text[s.start:s.end], start=s.start, end=s.end)
                for s in spans]
    fields: dict[str, list[str]] = {}
    for entity in entities:
        value = entity.text.strip()
        if entity.label == "POSTCODE":
            value = normalize_digits(value)
        fields.setdefault(entity.label.lower(), []).append(value)
    return ParseResult(entities=entities, fields=fields)


class ParserService:
    """One loaded model, safe to call from many threads.

    pycrfsuite.Tagger makes no thread-safety promise and FastAPI runs ordinary
    endpoints in a thread pool, so calls are serialised. Inference takes
    milliseconds; a lock is cheaper than being wrong. (Scaling out means more
    replicas, not more threads.)
    """

    def __init__(self, parser: AddressParser, model_path: Path, git_sha: str = "unknown") -> None:
        self._parser = parser
        self._lock = threading.Lock()
        self.info = describe_model(parser, model_path, git_sha)

    def parse(self, text: str) -> ParseResult:
        with self._lock:
            spans = self._parser.predict(text)
        return to_result(text, spans)
